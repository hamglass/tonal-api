#!/usr/bin/env python3
"""
Tonal PKCE Authentication Helper
Handles browser-based OAuth login for Tonal accounts that use email OTP.

Usage:
  python3 tonal_auth_pkce.py start     - Generate login URL
  python3 tonal_auth_pkce.py callback <url_or_code>  - Exchange callback for tokens
"""
import json
import os
import sys
import base64
import hashlib
import secrets
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlparse, parse_qs

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(TOOL_DIR, "tokens.json")
PKCE_STATE_FILE = os.path.join(TOOL_DIR, "pkce_state.json")

AUTH0_DOMAIN = "tonal.auth0.com"
AUTH0_CLIENT_ID = "ERCyexW-xoVG_Yy3RDe-eV4xsOnRHP6L"
REDIRECT_URI = "com.tonal.tonalapp://tonal.auth0.com/ios/com.tonal.tonalapp/callback"
TONAL_API_BASE = "https://api.tonal.com"


def generate_pkce():
    """Generate PKCE code_verifier and code_challenge."""
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def cmd_start():
    """Generate the Tonal login URL."""
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)

    # Save PKCE state for the callback step
    pkce_state = {
        "code_verifier": verifier,
        "state": state,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(PKCE_STATE_FILE, "w") as f:
        json.dump(pkce_state, f, indent=2)
    os.chmod(PKCE_STATE_FILE, 0o600)

    auth_url = (
        f"https://{AUTH0_DOMAIN}/authorize"
        f"?response_type=code"
        f"&client_id={AUTH0_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope=openid+profile+email+offline_access"
        f"&code_challenge={challenge}"
        f"&code_challenge_method=S256"
        f"&state={state}"
    )

    return {
        "status": "ready",
        "login_url": auth_url,
        "instructions": [
            "1. Open this URL in your browser",
            "2. Log in with your Tonal account (email code is fine)",
            "3. After login, you'll be redirected to a URL starting with com.tonal.tonalapp://",
            "4. Copy that full redirect URL",
            "5. Run: python3 tonal_auth_pkce.py callback '<paste_url_here>'",
        ],
    }


def cmd_callback(args):
    """Exchange the callback URL/code for tokens."""
    if not args:
        return {"error": "Provide the redirect URL or authorization code"}

    # Load PKCE state
    if not os.path.exists(PKCE_STATE_FILE):
        return {"error": "No PKCE session found. Run 'start' first."}
    with open(PKCE_STATE_FILE) as f:
        pkce_state = json.load(f)

    # Extract code from URL or use directly
    input_val = args[0]
    if input_val.startswith("http") or input_val.startswith("com.tonal"):
        parsed = urlparse(input_val)
        params = parse_qs(parsed.query or parsed.fragment)
        # Also check if query params are in the fragment
        if not params and "?" in input_val:
            query_part = input_val.split("?", 1)[1]
            params = parse_qs(query_part)
        code = params.get("code", [None])[0]
        if not code:
            return {"error": "Could not extract 'code' from the URL. Make sure you copied the full redirect URL."}
    else:
        code = input_val

    # Exchange code for tokens
    body = json.dumps({
        "grant_type": "authorization_code",
        "client_id": AUTH0_CLIENT_ID,
        "code": code,
        "code_verifier": pkce_state["code_verifier"],
        "redirect_uri": REDIRECT_URI,
    }).encode()

    req = Request(
        f"https://{AUTH0_DOMAIN}/oauth/token",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except HTTPError as e:
        error_body = e.read().decode()
        try:
            error_data = json.loads(error_body)
            return {"error": error_data.get("error_description", f"Token exchange failed: {e.code}")}
        except Exception:
            return {"error": f"Token exchange failed: {e.code} — {error_body[:200]}"}

    id_token = data.get("id_token", "")
    ref_token = data.get("refresh_token", "")

    # Parse JWT expiry
    expires_at = _parse_jwt_expiry(id_token)

    # Get Tonal user ID
    user_id = _fetch_user_id(id_token)

    # Extract email from JWT
    email = _parse_jwt_claim(id_token, "email") or "unknown"

    tokens = {
        "id_token": id_token,
        "refresh_token": ref_token,
        "expires_at": expires_at,
        "user_id": user_id,
        "email": email,
        "authenticated_at": datetime.now(timezone.utc).isoformat(),
        "auth_method": "pkce",
    }

    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    os.chmod(TOKEN_FILE, 0o600)

    # Clean up PKCE state
    if os.path.exists(PKCE_STATE_FILE):
        os.remove(PKCE_STATE_FILE)

    return {
        "status": "authenticated",
        "user_id": user_id,
        "email": email,
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        "message": "Tonal connected! Forge can now access your Tonal data.",
    }


def _parse_jwt_expiry(jwt_token):
    try:
        payload_b64 = jwt_token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.b64decode(payload_b64))
        if "exp" in payload:
            return payload["exp"]
    except Exception:
        pass
    return int(time.time()) + 86400


def _parse_jwt_claim(jwt_token, claim):
    try:
        payload_b64 = jwt_token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.b64decode(payload_b64))
        return payload.get(claim)
    except Exception:
        return None


def _fetch_user_id(token):
    try:
        req = Request(
            f"{TONAL_API_BASE}/v6/users/userinfo",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data.get("id", "")
    except Exception:
        return ""


COMMANDS = {
    "start": lambda args: cmd_start(),
    "callback": cmd_callback,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(json.dumps({
            "error": f"Usage: {sys.argv[0]} <start|callback> [args...]",
        }, indent=2))
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]
    result = COMMANDS[cmd](args)
    print(json.dumps(result, indent=2, default=str))
