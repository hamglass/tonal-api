#!/usr/bin/env python3
"""
FORGE Tonal Fitness Tool v2
Full programmatic access to Tonal smart cable machine.

Usage: python3 tonal_tool.py <command> [args...]

=== AUTH ===
  auth <email> <password>           - Authenticate (tokens stored, not password)
  auth-start <email>                - Send OTP code to email
  auth-verify <code> [email]        - Verify OTP code
  status                            - Token/connection status
  check-health                      - Full diagnostic

=== READINESS & STRENGTH ===
  readiness                         - Muscle readiness 0-100 per group
  strength                          - Current strength scores by region
  strength-history [limit]          - Strength progression (default: 20)
  strength-distribution             - Overall score + percentile

=== WORKOUT HISTORY ===
  history [limit]                   - Recent workout list (default: 10)
  detail <activity_id>              - Full workout: per-set weights, reps, 1RM, power
  performance <activity_id>         - Formatted summary: per-movement totals + names
  exercise-history <search>         - Track an exercise across all workouts (progressive overload)

=== PROGRAMMING ===
  movements [search]                - Search exercise catalog
  create-workout <json>             - Build & push workout to Tonal
  estimate <json>                   - Estimate workout duration
  delete-workout <workout_id>       - Delete a custom workout
  custom-workouts                   - List custom workouts on Tonal

=== PROFILE & DATA ===
  profile                           - User profile
  achievements                      - Badges and milestones
  volume-report [days]              - Training volume summary over N days (default: 30)
"""
import json
import os
import sys
import base64
import time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote

# Paths
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(TOOL_DIR, "tokens.json")
MOVEMENTS_CACHE = os.path.join(TOOL_DIR, "movements_cache.json")

# Tonal API
TONAL_API_BASE = "https://api.tonal.com"
AUTH0_DOMAIN = "tonal.auth0.com"
AUTH0_CLIENT_ID = "ERCyexW-xoVG_Yy3RDe-eV4xsOnRHP6L"

# Timeouts
GET_TIMEOUT = 15
POST_TIMEOUT = 30


# ── Token Management ──────────────────────────────────────────────────

def load_tokens():
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE) as f:
        return json.load(f)

def save_tokens(tokens):
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    os.chmod(TOKEN_FILE, 0o600)

def parse_jwt_expiry(jwt_token):
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

def is_token_expired(tokens):
    if not tokens or "expires_at" not in tokens:
        return True
    return time.time() >= tokens["expires_at"] - 300

def _fetch_user_id(token):
    try:
        data = api_get("/v6/users/userinfo", token=token)
        return data.get("id", "")
    except Exception:
        return ""

def refresh_token():
    tokens = load_tokens()
    if not tokens or "refresh_token" not in tokens:
        return None
    body = json.dumps({
        "grant_type": "refresh_token",
        "client_id": AUTH0_CLIENT_ID,
        "refresh_token": tokens["refresh_token"],
    }).encode()
    req = Request(f"https://{AUTH0_DOMAIN}/oauth/token", data=body,
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=POST_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    tokens["id_token"] = data.get("id_token", tokens["id_token"])
    tokens["refresh_token"] = data.get("refresh_token", tokens["refresh_token"])
    tokens["expires_at"] = parse_jwt_expiry(tokens["id_token"])
    tokens["last_refreshed"] = datetime.now(timezone.utc).isoformat()
    save_tokens(tokens)
    return tokens

def get_user_id():
    tokens = load_tokens()
    if not tokens or "user_id" not in tokens:
        return None
    return tokens["user_id"]


# ── HTTP Client ───────────────────────────────────────────────────────

def api_get(endpoint, token=None, params=None):
    if token is None:
        tokens = load_tokens()
        if not tokens:
            return {"error": "Not authenticated. Run: tonal_tool.py auth <email> <password>"}
        if is_token_expired(tokens):
            tokens = refresh_token()
            if not tokens:
                return {"error": "Token expired and refresh failed. Re-authenticate."}
        token = tokens["id_token"]
    url = f"{TONAL_API_BASE}{endpoint}"
    if params:
        query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
        url += f"?{query}"
    req = Request(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=GET_TIMEOUT) as resp:
            if resp.status == 204:
                return {}
            return json.loads(resp.read())
    except HTTPError as e:
        if e.code == 401:
            new_tokens = refresh_token()
            if new_tokens:
                req = Request(url, headers={"Authorization": f"Bearer {new_tokens['id_token']}",
                                            "Content-Type": "application/json"})
                try:
                    with urlopen(req, timeout=GET_TIMEOUT) as resp:
                        return json.loads(resp.read())
                except HTTPError as e2:
                    return {"error": f"API error after refresh: {e2.code}"}
            return {"error": "Token expired. Re-authenticate."}
        body = e.read().decode()[:200]
        return {"error": f"Tonal API {e.code}: {body}"}
    except URLError as e:
        return {"error": f"Connection error: {e.reason}"}

def api_post(endpoint, body):
    tokens = load_tokens()
    if not tokens:
        return {"error": "Not authenticated."}
    if is_token_expired(tokens):
        tokens = refresh_token()
        if not tokens:
            return {"error": "Token expired and refresh failed."}
    url = f"{TONAL_API_BASE}{endpoint}"
    data = json.dumps(body).encode()
    req = Request(url, data=data, headers={"Authorization": f"Bearer {tokens['id_token']}",
                  "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=POST_TIMEOUT) as resp:
            if resp.status == 204:
                return {"status": "ok"}
            return json.loads(resp.read())
    except HTTPError as e:
        body_text = e.read().decode()[:500]
        return {"error": f"Tonal API {e.code}: {body_text}"}
    except URLError as e:
        return {"error": f"Connection error: {e.reason}"}

def api_delete(endpoint):
    tokens = load_tokens()
    if not tokens:
        return {"error": "Not authenticated."}
    if is_token_expired(tokens):
        tokens = refresh_token()
        if not tokens:
            return {"error": "Token expired and refresh failed."}
    url = f"{TONAL_API_BASE}{endpoint}"
    req = Request(url, headers={"Authorization": f"Bearer {tokens['id_token']}",
                  "Content-Type": "application/json"}, method="DELETE")
    try:
        with urlopen(req, timeout=POST_TIMEOUT) as resp:
            if resp.status == 204:
                return {"status": "deleted"}
            return json.loads(resp.read())
    except HTTPError as e:
        body_text = e.read().decode()[:200]
        return {"error": f"Tonal API {e.code}: {body_text}"}


# ── Movement Catalog ──────────────────────────────────────────────────

def _load_movement_cache():
    if not os.path.exists(MOVEMENTS_CACHE):
        return None
    try:
        with open(MOVEMENTS_CACHE) as f:
            cache = json.load(f)
        if time.time() - cache.get("cached_at", 0) > 86400:
            return None
        return cache.get("movements", [])
    except Exception:
        return None

def _sync_movements():
    data = api_get("/v6/movements")
    if isinstance(data, dict) and "error" in data:
        return data
    movements = data if isinstance(data, list) else data.get("movements", data.get("data", []))
    cache = {"cached_at": time.time(), "count": len(movements), "movements": movements}
    try:
        with open(MOVEMENTS_CACHE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass
    return movements

def _get_movement_map():
    """Return dict of movement_id -> movement data."""
    catalog = _load_movement_cache()
    if not catalog:
        catalog = _sync_movements()
        if isinstance(catalog, dict) and "error" in catalog:
            return {}
    return {m["id"]: m for m in catalog}

def _movement_name(movement_map, mid):
    m = movement_map.get(mid)
    return m.get("name", mid[:8]) if m else mid[:8]


# ── Auth Commands ─────────────────────────────────────────────────────

def cmd_auth(args):
    if len(args) < 2:
        return {"error": "Usage: tonal_tool.py auth <email> <password>"}
    email, password = args[0], args[1]
    body = json.dumps({"grant_type": "password", "username": email, "password": password,
                       "client_id": AUTH0_CLIENT_ID, "scope": "openid profile email offline_access"}).encode()
    req = Request(f"https://{AUTH0_DOMAIN}/oauth/token", data=body,
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=POST_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except HTTPError as e:
        error_body = e.read().decode()
        try:
            return {"error": json.loads(error_body).get("error_description", "Authentication failed")}
        except Exception:
            return {"error": f"Authentication failed: {e.code}"}
    id_token = data.get("id_token", "")
    ref_token = data.get("refresh_token", "")
    expires_at = parse_jwt_expiry(id_token)
    user_id = _fetch_user_id(id_token)
    save_tokens({"id_token": id_token, "refresh_token": ref_token, "expires_at": expires_at,
                 "user_id": user_id, "email": email,
                 "authenticated_at": datetime.now(timezone.utc).isoformat(), "auth_method": "password"})
    return {"status": "authenticated", "user_id": user_id, "email": email,
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()}

def cmd_auth_start(args):
    if len(args) < 1:
        return {"error": "Usage: tonal_tool.py auth-start <email>"}
    email = args[0]
    body = json.dumps({"client_id": AUTH0_CLIENT_ID, "connection": "email",
                       "email": email, "send": "code"}).encode()
    req = Request(f"https://{AUTH0_DOMAIN}/passwordless/start", data=body,
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=POST_TIMEOUT) as resp:
            json.loads(resp.read())
    except HTTPError as e:
        return {"error": f"Failed to send code: {e.code}"}
    pending_file = os.path.join(TOOL_DIR, "pending_auth.json")
    with open(pending_file, "w") as f:
        json.dump({"email": email, "requested_at": datetime.now(timezone.utc).isoformat()}, f)
    return {"status": "code_sent", "email": email}

def cmd_auth_verify(args):
    if len(args) < 1:
        return {"error": "Usage: tonal_tool.py auth-verify <code> [email]"}
    code = args[0]
    if len(args) >= 2:
        email = args[1]
    else:
        pending_file = os.path.join(TOOL_DIR, "pending_auth.json")
        if os.path.exists(pending_file):
            with open(pending_file) as f:
                email = json.load(f).get("email", "")
        else:
            return {"error": "No pending auth. Provide email: auth-verify <code> <email>"}
    body = json.dumps({"grant_type": "http://auth0.com/oauth/grant-type/passwordless/otp",
                       "client_id": AUTH0_CLIENT_ID, "username": email, "otp": code,
                       "realm": "email", "scope": "openid profile email offline_access"}).encode()
    req = Request(f"https://{AUTH0_DOMAIN}/oauth/token", data=body,
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=POST_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except HTTPError as e:
        return {"error": f"Verification failed: {e.code}"}
    id_token = data.get("id_token", "")
    expires_at = parse_jwt_expiry(id_token)
    user_id = _fetch_user_id(id_token)
    save_tokens({"id_token": id_token, "refresh_token": data.get("refresh_token", ""),
                 "expires_at": expires_at, "user_id": user_id, "email": email,
                 "authenticated_at": datetime.now(timezone.utc).isoformat()})
    return {"status": "authenticated", "user_id": user_id, "email": email,
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()}


# ── Status & Health ───────────────────────────────────────────────────

def cmd_status(args):
    tokens = load_tokens()
    if not tokens:
        return {"status": "not_connected"}
    expired = is_token_expired(tokens)
    return {"status": "expired" if expired else "connected",
            "user_id": tokens.get("user_id", "?"), "email": tokens.get("email", "?"),
            "expires_at": datetime.fromtimestamp(tokens.get("expires_at", 0), tz=timezone.utc).isoformat(),
            "last_refreshed": tokens.get("last_refreshed", "never")}

def cmd_check_health(args):
    result = {}
    tokens = load_tokens()
    if not tokens:
        return {"health": "DEAD", "fix": "Ask Dan to re-authenticate."}
    expired = is_token_expired(tokens)
    result["token_status"] = "expired" if expired else "valid"
    result["expires_at"] = datetime.fromtimestamp(tokens.get("expires_at", 0), tz=timezone.utc).isoformat()
    result["last_refreshed"] = tokens.get("last_refreshed", "never")
    status_file = os.path.join(TOOL_DIR, "refresh_status.json")
    if os.path.exists(status_file):
        with open(status_file) as f:
            result["refresh_daemon"] = json.load(f)
    if not expired:
        test = api_get(f"/v6/users/{tokens.get('user_id', '')}")
        result["api_check"] = "FAIL" if "error" in test else "OK"
    else:
        result["api_check"] = "SKIPPED"
    if expired:
        result["health"] = "EXPIRED"
        result["fix"] = "Token expired. Try running any command (auto-refresh). If that fails, Dan must re-auth."
    elif result.get("api_check") == "FAIL":
        result["health"] = "API_FAILING"
    else:
        result["health"] = "HEALTHY"
    return result


# ── Readiness & Strength ─────────────────────────────────────────────

def cmd_readiness(args):
    uid = get_user_id()
    if not uid:
        return {"error": "Not authenticated."}
    data = api_get(f"/v6/users/{uid}/muscle-readiness/current")
    if "error" in data:
        return data
    muscles = {}
    for key in ["Chest", "Shoulders", "Back", "Triceps", "Biceps",
                 "Abs", "Obliques", "Quads", "Glutes", "Hamstrings", "Calves"]:
        if key in data:
            muscles[key] = data[key]
    sorted_muscles = dict(sorted(muscles.items(), key=lambda x: x[1]))
    push_muscles, pull_muscles, leg_muscles = ["Chest", "Triceps", "Shoulders"], ["Back", "Biceps"], ["Quads", "Glutes", "Hamstrings", "Calves"]
    def avg(ml): vals = [muscles.get(m, 50) for m in ml]; return sum(vals) / len(vals) if vals else 50
    push_avg, pull_avg, legs_avg = avg(push_muscles), avg(pull_muscles), avg(leg_muscles)
    best = max([("push", push_avg), ("pull", pull_avg), ("legs", legs_avg)], key=lambda x: x[1])
    return {
        "readiness_scores": sorted_muscles,
        "summary": {
            "fatigued_avoid": [k for k, v in sorted_muscles.items() if v < 40],
            "moderate_light_ok": [k for k, v in sorted_muscles.items() if 40 <= v < 70],
            "ready_to_train": [k for k, v in sorted_muscles.items() if v >= 70],
        },
        "split_readiness": {"push": round(push_avg), "pull": round(pull_avg), "legs": round(legs_avg)},
        "recommendation": f"Best: {best[0]} ({best[1]:.0f}/100)" if best[1] >= 40 else "All fatigued. Rest day.",
    }

def cmd_strength(args):
    uid = get_user_id()
    if not uid:
        return {"error": "Not authenticated."}
    data = api_get(f"/v6/users/{uid}/strength-scores/current")
    if "error" in data:
        return data
    if isinstance(data, list):
        return {"scores": [{"region": s.get("bodyRegionDisplay", s.get("strengthBodyRegion", "")),
                            "score": s.get("score")} for s in data]}
    return data

def cmd_strength_history(args):
    uid = get_user_id()
    if not uid:
        return {"error": "Not authenticated."}
    limit = int(args[0]) if args else 20
    data = api_get(f"/v6/users/{uid}/strength-scores/history", params={"limit": limit})
    if "error" in data:
        return data
    if isinstance(data, list):
        return {"history": [{"date": e.get("activityTime", "")[:10], "overall": e.get("overall"),
                             "upper": e.get("upper"), "lower": e.get("lower"),
                             "core": e.get("core")} for e in data]}
    return data

def cmd_strength_distribution(args):
    uid = get_user_id()
    if not uid:
        return {"error": "Not authenticated."}
    data = api_get(f"/v6/users/{uid}/strength-scores/distribution")
    if "error" in data:
        return data
    return {"overall_score": data.get("overallScore"), "percentile": data.get("percentile")}


# ── Profile ───────────────────────────────────────────────────────────

def cmd_profile(args):
    uid = get_user_id()
    if not uid:
        return {"error": "Not authenticated."}
    data = api_get(f"/v6/users/{uid}")
    if "error" in data:
        return data
    return {"name": f"{data.get('firstName', '')} {data.get('lastName', '')}".strip(),
            "email": data.get("email"), "gender": data.get("gender"),
            "height_inches": data.get("heightInches"), "weight_lbs": data.get("weightPounds"),
            "workouts_per_week": data.get("workoutsPerWeek"),
            "workout_duration_min": data.get("workoutDurationMin"),
            "workout_duration_max": data.get("workoutDurationMax"),
            "member_since": data.get("createdAt")}


# ── Workout History & Detail ──────────────────────────────────────────

def cmd_history(args):
    uid = get_user_id()
    if not uid:
        return {"error": "Not authenticated."}
    limit = int(args[0]) if args else 10
    data = api_get(f"/v6/users/{uid}/activities", params={"limit": limit})
    if "error" in data:
        return data
    activities = data if isinstance(data, list) else data.get("activities", data.get("data", []))
    results = []
    for act in activities:
        p = act.get("workoutPreview", {})
        results.append({
            "activity_id": act.get("activityId"), "date": act.get("activityTime", "")[:10],
            "title": p.get("workoutTitle", "Unknown"), "type": p.get("workoutType", ""),
            "duration_min": round(p.get("totalDuration", 0) / 60) if p.get("totalDuration") else None,
            "total_volume_lbs": p.get("totalVolume"), "coach": p.get("coachName", ""),
            "target_area": p.get("targetArea", ""),
        })
    return {"workouts": results, "count": len(results)}

def cmd_detail(args):
    """Full workout detail with per-set actual weights, reps, 1RM, power, struggling score."""
    if not args:
        return {"error": "Usage: tonal_tool.py detail <activity_id>"}
    uid = get_user_id()
    if not uid:
        return {"error": "Not authenticated."}
    activity_id = args[0]
    data = api_get(f"/v6/users/{uid}/workout-activities/{activity_id}")
    if "error" in data:
        return data

    movement_map = _get_movement_map()

    # Group sets by movement, extracting rich per-set data
    movements = {}
    for s in data.get("workoutSetActivity", []):
        mid = s.get("movementId", "unknown")
        if mid not in movements:
            movements[mid] = {
                "movement_id": mid,
                "name": _movement_name(movement_map, mid),
                "sets": [],
                "warm_up_sets": [],
            }
        set_data = {
            "reps": s.get("repCount", s.get("prescribedReps", 0)),
            "weight_lbs": s.get("baseWeight", s.get("avgWeight", 0)),
            "max_weight_lbs": s.get("maxWeight"),
            "min_weight_lbs": s.get("minWeight"),
            "volume_lbs": s.get("volume", s.get("totalVolume", 0)),
            "one_rep_max": round(s.get("oneRepMax", 0)) if s.get("oneRepMax") else None,
            "max_power_watts": round(s.get("maxConPower", 0)) if s.get("maxConPower") else None,
            "rom_inches": round(s.get("rom", 0), 1) if s.get("rom") else None,
            "struggling_score": round(s.get("strugglingScore", 0), 2) if s.get("strugglingScore") else None,
            "suggested_weight": round(s.get("suggestedWeight", 0), 1) if s.get("suggestedWeight") else None,
            "spotter": s.get("spotterMode", "OFF") != "OFF",
            "eccentric": s.get("eccentric", False),
            "chains": s.get("chains", False),
            "side": s.get("movementSide", "Both"),
            "duration_sec": s.get("duration"),
        }
        if s.get("warmUp"):
            movements[mid]["warm_up_sets"].append(set_data)
        else:
            movements[mid]["sets"].append(set_data)

    # Build per-movement summaries
    movement_summaries = []
    for mid, m in movements.items():
        working_sets = m["sets"]
        if working_sets:
            weights = [s["weight_lbs"] for s in working_sets if s["weight_lbs"]]
            reps = [s["reps"] for s in working_sets if s["reps"]]
            volumes = [s["volume_lbs"] for s in working_sets if s["volume_lbs"]]
            orms = [s["one_rep_max"] for s in working_sets if s["one_rep_max"]]
            powers = [s["max_power_watts"] for s in working_sets if s["max_power_watts"]]
            struggles = [s["struggling_score"] for s in working_sets if s["struggling_score"] is not None]
            summary = {
                "movement_id": mid,
                "name": m["name"],
                "working_sets": len(working_sets),
                "warm_up_sets": len(m["warm_up_sets"]),
                "avg_weight_lbs": round(sum(weights) / len(weights), 1) if weights else 0,
                "max_weight_lbs": max(weights) if weights else 0,
                "total_reps": sum(reps),
                "total_volume_lbs": sum(volumes),
                "best_1rm": max(orms) if orms else None,
                "avg_power_watts": round(sum(powers) / len(powers)) if powers else None,
                "avg_struggling": round(sum(struggles) / len(struggles), 2) if struggles else None,
                "set_details": working_sets,
            }
            # Include Tonal's suggested next weight if available
            suggestions = [s["suggested_weight"] for s in working_sets if s.get("suggested_weight")]
            if suggestions:
                summary["tonal_suggested_weight"] = round(max(suggestions), 1)
            movement_summaries.append(summary)

    return {
        "activity_id": data.get("id"),
        "workout_id": data.get("workoutId"),
        "type": data.get("workoutType"),
        "begin_time": data.get("beginTime"),
        "end_time": data.get("endTime"),
        "total_duration_min": round(data.get("totalDuration", 0) / 60),
        "active_duration_min": round(data.get("activeDuration", 0) / 60),
        "total_volume_lbs": data.get("totalVolume"),
        "total_concentric_work": data.get("totalConcentricWork"),
        "percent_completed": data.get("percentCompleted"),
        "movements": movement_summaries,
    }

def cmd_performance(args):
    """Formatted workout summary from Tonal — per-movement names, weights, L/R splits."""
    if not args:
        return {"error": "Usage: tonal_tool.py performance <activity_id>"}
    uid = get_user_id()
    if not uid:
        return {"error": "Not authenticated."}
    activity_id = args[0]
    data = api_get(f"/v6/formatted/users/{uid}/workout-summaries/{activity_id}")
    if "error" in data:
        return data

    result = {
        "activity_id": activity_id,
        "workout_name": data.get("name", ""),
        "program": data.get("programName", ""),
        "coach": data.get("coachName", ""),
        "target_area": data.get("targetArea", ""),
        "duration_sec": data.get("duration"),
        "time_under_tension_sec": data.get("timeUnderTension"),
        "date": data.get("localTimestamp", data.get("timestamp", ""))[:10],
        "movements": [],
    }

    for ms in data.get("movementSets", []):
        movement = {
            "name": ms.get("movementName", "Unknown"),
            "movement_id": ms.get("movementId", ""),
            "total_volume_lbs": ms.get("totalVolume", 0),
            "total_work": ms.get("totalWork", 0),
            "sets": [],
        }
        for s in ms.get("sets", []):
            set_info = {
                "reps": s.get("repCount", 0),
                "rep_goal": s.get("repGoal", 0),
                "weight_lbs": s.get("weight", 0),
                "avg_max_weight_lbs": s.get("avgMaxWeight", 0),
                "one_rep_max": s.get("oneRepMax"),
                "max_power_watts": s.get("maxConPower"),
                "warm_up": s.get("warmUp", False),
                "weight_percentage": s.get("weightPercentage", 100),
                "spotter": s.get("spotterMode", "OFF") != "OFF",
                "volume_lbs": s.get("totalVolume", 0),
                "suggested_weight_change": s.get("suggestedWeightChange", 0),
                "duration_sec": s.get("duration"),
            }
            # Include left/right side splits if present
            if s.get("leftSideMovementSet"):
                ls = s["leftSideMovementSet"]
                set_info["left_side"] = {
                    "reps": ls.get("repCount", 0), "weight_lbs": ls.get("weight", 0),
                    "one_rep_max": ls.get("oneRepMax"), "max_power_watts": ls.get("maxConPower"),
                    "volume_lbs": ls.get("totalVolume", 0),
                }
            if s.get("rightSideMovementSet"):
                rs = s["rightSideMovementSet"]
                set_info["right_side"] = {
                    "reps": rs.get("repCount", 0), "weight_lbs": rs.get("weight", 0),
                    "one_rep_max": rs.get("oneRepMax"), "max_power_watts": rs.get("maxConPower"),
                    "volume_lbs": rs.get("totalVolume", 0),
                }
            movement["sets"].append(set_info)
        result["movements"].append(movement)

    return result

def cmd_exercise_history(args):
    """Track a specific exercise across all workouts for progressive overload analysis."""
    if not args:
        return {"error": "Usage: tonal_tool.py exercise-history <exercise_name_or_id>"}
    uid = get_user_id()
    if not uid:
        return {"error": "Not authenticated."}

    search = " ".join(args).lower()
    movement_map = _get_movement_map()

    # Find matching movement(s)
    if search in movement_map:
        # Direct ID match
        target_ids = [search]
        target_name = _movement_name(movement_map, search)
    else:
        # Name search
        matches = [(mid, m) for mid, m in movement_map.items()
                    if search in m.get("name", "").lower()]
        if not matches:
            return {"error": f"No exercise found matching '{search}'",
                    "hint": "Try: movements <search> to find exercise names"}
        if len(matches) > 5:
            return {"too_many_matches": len(matches),
                    "matches": [{"id": mid, "name": m.get("name")} for mid, m in matches[:10]],
                    "hint": "Be more specific."}
        target_ids = [mid for mid, _ in matches]
        target_name = matches[0][1].get("name", search) if len(matches) == 1 else f"{len(matches)} exercises"

    # Fetch workout history (last 50 workouts)
    history_data = api_get(f"/v6/users/{uid}/activities", params={"limit": 50})
    if "error" in history_data:
        return history_data
    activities = history_data if isinstance(history_data, list) else history_data.get("activities", history_data.get("data", []))

    # For each workout, check if it contains the target movement(s)
    exercise_log = []
    for act in activities:
        activity_id = act.get("activityId")
        if not activity_id:
            continue

        detail = api_get(f"/v6/users/{uid}/workout-activities/{activity_id}")
        if "error" in detail:
            continue

        for s in detail.get("workoutSetActivity", []):
            if s.get("movementId") not in target_ids:
                continue
            if s.get("warmUp"):
                continue

            exercise_log.append({
                "date": act.get("activityTime", "")[:10],
                "workout": act.get("workoutPreview", {}).get("workoutTitle", "Unknown"),
                "movement_id": s.get("movementId"),
                "name": _movement_name(movement_map, s.get("movementId", "")),
                "weight_lbs": s.get("baseWeight", s.get("avgWeight", 0)),
                "reps": s.get("repCount", s.get("prescribedReps", 0)),
                "volume_lbs": s.get("volume", s.get("totalVolume", 0)),
                "one_rep_max": round(s.get("oneRepMax", 0)) if s.get("oneRepMax") else None,
                "max_power_watts": round(s.get("maxConPower", 0)) if s.get("maxConPower") else None,
                "struggling_score": round(s.get("strugglingScore", 0), 2) if s.get("strugglingScore") else None,
                "side": s.get("movementSide", "Both"),
            })

    if not exercise_log:
        return {"exercise": target_name, "message": "No working sets found in recent history."}

    # Group by date for summary
    by_date = {}
    for entry in exercise_log:
        d = entry["date"]
        if d not in by_date:
            by_date[d] = {"date": d, "workout": entry["workout"], "sets": []}
        by_date[d]["sets"].append(entry)

    sessions = []
    for d in sorted(by_date.keys()):
        session = by_date[d]
        weights = [s["weight_lbs"] for s in session["sets"] if s["weight_lbs"]]
        reps = [s["reps"] for s in session["sets"] if s["reps"]]
        orms = [s["one_rep_max"] for s in session["sets"] if s["one_rep_max"]]
        sessions.append({
            "date": d,
            "workout": session["workout"],
            "sets": len(session["sets"]),
            "weight_range": f"{min(weights)}-{max(weights)}" if weights else "N/A",
            "avg_weight_lbs": round(sum(weights) / len(weights), 1) if weights else 0,
            "total_reps": sum(reps),
            "total_volume_lbs": sum(s["volume_lbs"] for s in session["sets"]),
            "best_1rm": max(orms) if orms else None,
            "per_set": session["sets"],
        })

    # Progression analysis
    if len(sessions) >= 2:
        first, last = sessions[0], sessions[-1]
        weight_delta = last["avg_weight_lbs"] - first["avg_weight_lbs"]
        orm_first = first.get("best_1rm")
        orm_last = last.get("best_1rm")
        progression = {
            "weight_change_lbs": round(weight_delta, 1),
            "direction": "increasing" if weight_delta > 0 else "decreasing" if weight_delta < 0 else "flat",
        }
        if orm_first and orm_last:
            progression["1rm_change"] = orm_last - orm_first
    else:
        progression = None

    return {
        "exercise": target_name,
        "sessions_found": len(sessions),
        "progression": progression,
        "sessions": sessions,
    }


# ── Custom Workouts ───────────────────────────────────────────────────

def cmd_custom_workouts(args):
    data = api_get("/v6/user-workouts")
    if "error" in data:
        return data
    workouts = data if isinstance(data, list) else data.get("workouts", data.get("data", []))
    return {"workouts": [{"id": w.get("id"), "title": w.get("title"),
                          "duration_min": round(w.get("duration", 0) / 60) if w.get("duration") else None,
                          "target_area": w.get("targetArea"),
                          "body_regions": w.get("bodyRegions", []),
                          "movement_count": len(w.get("movementIds", [])),
                          "created_at": w.get("createdAt")} for w in workouts],
            "count": len(workouts)}


# ── Movement Catalog ──────────────────────────────────────────────────

def cmd_movements(args):
    catalog = _load_movement_cache()
    if not catalog:
        catalog = _sync_movements()
        if isinstance(catalog, dict) and "error" in catalog:
            return catalog

    search = " ".join(args).lower() if args else None
    if search:
        matches = [m for m in catalog
                   if search in m.get("name", "").lower()
                   or search in " ".join(m.get("muscleGroups", [])).lower()
                   or search in m.get("bodyRegion", "").lower()
                   or search in (m.get("onMachineInfo", {}) or {}).get("accessory", "").lower()]
    else:
        matches = catalog

    limit = 50 if len(matches) > 50 else len(matches)
    return {
        "total_matches": len(matches),
        "showing": limit,
        "movements": [{
            "id": m.get("id"), "name": m.get("name"),
            "muscle_groups": m.get("muscleGroups", []),
            "body_region": m.get("bodyRegion", ""),
            "skill_level": m.get("skillLevel"),
            "count_reps": m.get("countReps"),
            "is_alternating": m.get("isAlternating"),
            "is_two_sided": m.get("isTwoSided"),
            "accessory": (m.get("onMachineInfo") or {}).get("accessory", ""),
            "spotter_ok": not (m.get("onMachineInfo") or {}).get("spotterDisabled", True),
            "eccentric_ok": not (m.get("onMachineInfo") or {}).get("eccentricDisabled", True),
            "chains_ok": not (m.get("onMachineInfo") or {}).get("chainsDisabled", True),
            "training_types": m.get("trainingTypes", []),
        } for m in matches[:limit]],
    }


# ── Workout Creation ──────────────────────────────────────────────────

def _expand_blocks(blocks, movement_map):
    all_sets = []
    block_number = 1
    for block in blocks:
        exercises = block.get("exercises", [])
        if not exercises:
            continue
        max_rounds = max(ex.get("sets", 3) for ex in exercises)
        for round_num in range(1, max_rounds + 1):
            for ex_idx, ex in enumerate(exercises):
                if round_num > ex.get("sets", 3):
                    continue
                mid = ex.get("movement_id", ex.get("movementId", ""))
                movement = movement_map.get(mid, {})
                is_duration = not movement.get("countReps", True) if movement else False
                is_alternating = movement.get("isAlternating", False) if movement else False
                s = {
                    "movementId": mid,
                    "blockStart": (round_num == 1 and ex_idx == 0),
                    "blockNumber": block_number, "setGroup": ex_idx + 1,
                    "round": round_num, "repetition": round_num,
                    "repetitionTotal": ex.get("sets", 3),
                    "burnout": ex.get("burnout", False),
                    "spotter": ex.get("spotter", False),
                    "eccentric": ex.get("eccentric", False),
                    "chains": ex.get("chains", False),
                    "flex": False, "warmUp": ex.get("warm_up", ex.get("warmUp", False)),
                    "dropSet": ex.get("drop_set", ex.get("dropSet", False)),
                    "weightPercentage": ex.get("weight_percentage", 100),
                    "description": "",
                }
                if is_duration or ex.get("duration"):
                    s["prescribedDuration"] = ex.get("duration", 30)
                    s["prescribedResistanceLevel"] = 5
                else:
                    base_reps = ex.get("reps", 10)
                    s["prescribedReps"] = base_reps * 2 if is_alternating else base_reps
                all_sets.append({k: v for k, v in s.items() if v is not None})
        block_number += 1
    return all_sets

def cmd_create_workout(args):
    if not args:
        return {"error": "Usage: tonal_tool.py create-workout <json_file_or_inline_json>"}
    spec_input = " ".join(args)
    if os.path.exists(spec_input.strip()):
        with open(spec_input.strip()) as f:
            spec = json.load(f)
    else:
        try:
            spec = json.loads(spec_input)
        except json.JSONDecodeError:
            return {"error": "Argument must be a JSON file path or inline JSON."}

    title = spec.get("title", "FORGE Custom Workout")
    blocks = spec.get("blocks", [])
    if not blocks:
        return {"error": "Need at least one block with exercises."}

    movement_map = _get_movement_map()
    all_ids = [ex.get("movement_id", ex.get("movementId", ""))
               for block in blocks for ex in block.get("exercises", [])]
    invalid = [mid for mid in all_ids if mid and mid not in movement_map]
    if invalid:
        return {"error": "Invalid movement IDs", "invalid_ids": invalid}

    sets = _expand_blocks(blocks, movement_map)
    if not sets:
        return {"error": "No valid sets generated."}

    result = api_post("/v6/user-workouts", {"title": title, "sets": sets})
    if "error" in result:
        return result
    return {"status": "pushed", "workout_id": result.get("id", "unknown"), "title": title,
            "set_count": len(sets), "exercise_count": len(all_ids)}

def cmd_estimate(args):
    if not args:
        return {"error": "Usage: tonal_tool.py estimate <json_file_or_inline_json>"}
    spec_input = " ".join(args)
    if os.path.exists(spec_input.strip()):
        with open(spec_input.strip()) as f:
            spec = json.load(f)
    else:
        try:
            spec = json.loads(spec_input)
        except json.JSONDecodeError:
            return {"error": "Must be JSON file or inline JSON."}
    movement_map = _get_movement_map()
    sets = _expand_blocks(spec.get("blocks", []), movement_map)
    if not sets:
        return {"error": "No valid sets."}
    result = api_post("/v6/user-workouts/estimate", {"sets": sets})
    if "error" in result:
        return result
    return {"estimated_duration_min": result.get("duration"), "set_count": len(sets)}

def cmd_delete_workout(args):
    if not args:
        return {"error": "Usage: tonal_tool.py delete-workout <workout_id>"}
    result = api_delete(f"/v6/user-workouts/{args[0]}")
    if "error" in result:
        return result
    return {"status": "deleted", "workout_id": args[0]}


# ── Achievements ──────────────────────────────────────────────────────

def cmd_achievements(args):
    uid = get_user_id()
    if not uid:
        return {"error": "Not authenticated."}
    data = api_get(f"/v6/users/{uid}/achievements")
    if "error" in data:
        return data
    achievements = data if isinstance(data, list) else []
    return {"total": len(achievements), "achievements": [
        {"name": a.get("name", ""), "description": a.get("shortDescription", ""),
         "earned_at": a.get("createdAt", "")[:10],
         "category": a.get("achievement", {}).get("achievementCategory", {}).get("name", ""),
         "value": a.get("achievement", {}).get("value")} for a in achievements]}


# ── Volume Report ─────────────────────────────────────────────────────

def cmd_volume_report(args):
    """Training volume and frequency analysis over N days."""
    uid = get_user_id()
    if not uid:
        return {"error": "Not authenticated."}
    days = int(args[0]) if args else 30
    limit = min(days, 100)

    history_data = api_get(f"/v6/users/{uid}/activities", params={"limit": limit})
    if "error" in history_data:
        return history_data
    activities = history_data if isinstance(history_data, list) else history_data.get("activities", history_data.get("data", []))

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [a for a in activities if a.get("activityTime", "") >= cutoff]

    if not recent:
        return {"days": days, "workouts": 0, "message": "No workouts in this period."}

    total_volume = 0
    total_duration = 0
    by_area = {}
    by_week = {}

    for act in recent:
        p = act.get("workoutPreview", {})
        vol = p.get("totalVolume", 0)
        dur = p.get("totalDuration", 0)
        area = p.get("targetArea", "OTHER")
        total_volume += vol
        total_duration += dur
        by_area[area] = by_area.get(area, 0) + 1

        # Weekly grouping
        date_str = act.get("activityTime", "")[:10]
        if date_str:
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
                week_start = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
                if week_start not in by_week:
                    by_week[week_start] = {"sessions": 0, "volume_lbs": 0}
                by_week[week_start]["sessions"] += 1
                by_week[week_start]["volume_lbs"] += vol
            except Exception:
                pass

    return {
        "period_days": days,
        "total_workouts": len(recent),
        "workouts_per_week": round(len(recent) / (days / 7), 1),
        "total_volume_lbs": total_volume,
        "avg_volume_per_session": round(total_volume / len(recent)) if recent else 0,
        "total_duration_min": round(total_duration / 60),
        "avg_duration_min": round(total_duration / 60 / len(recent)) if recent else 0,
        "by_target_area": by_area,
        "by_week": dict(sorted(by_week.items())),
    }


# ── CLI Dispatch ──────────────────────────────────────────────────────

COMMANDS = {
    "auth": cmd_auth,
    "auth-start": cmd_auth_start,
    "auth-verify": cmd_auth_verify,
    "status": cmd_status,
    "check-health": cmd_check_health,
    "profile": cmd_profile,
    "readiness": cmd_readiness,
    "strength": cmd_strength,
    "strength-history": cmd_strength_history,
    "strength-distribution": cmd_strength_distribution,
    "history": cmd_history,
    "detail": cmd_detail,
    "performance": cmd_performance,
    "exercise-history": cmd_exercise_history,
    "custom-workouts": cmd_custom_workouts,
    "movements": cmd_movements,
    "create-workout": cmd_create_workout,
    "estimate": cmd_estimate,
    "delete-workout": cmd_delete_workout,
    "achievements": cmd_achievements,
    "volume-report": cmd_volume_report,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(json.dumps({
            "error": f"Usage: {sys.argv[0]} <command> [args...]",
            "available_commands": list(COMMANDS.keys()),
        }, indent=2))
        sys.exit(1)
    result = COMMANDS[sys.argv[1]](sys.argv[2:])
    print(json.dumps(result, indent=2, default=str))
