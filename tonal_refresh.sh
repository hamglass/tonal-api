#!/bin/bash
# Tonal Token Refresh — runs via crontab every 6 hours
# Refreshes the JWT token and logs results. If refresh fails,
# writes a failure marker that Forge checks in morning briefings.

TOOL_DIR="$(dirname "$(readlink -f "$0")")"
TOKEN_FILE="$TOOL_DIR/tokens.json"
STATUS_FILE="$TOOL_DIR/refresh_status.json"
LOG_FILE="$TOOL_DIR/refresh.log"

# Keep log file manageable (last 200 lines)
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt 200 ]; then
    tail -100 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Check if tokens exist
if [ ! -f "$TOKEN_FILE" ]; then
    echo "$TIMESTAMP FAIL: No token file found" >> "$LOG_FILE"
    echo '{"status":"no_tokens","last_attempt":"'"$TIMESTAMP"'","message":"Token file missing. Auth required."}' > "$STATUS_FILE"
    exit 1
fi

# Attempt refresh
RESULT=$(python3 "$TOOL_DIR/tonal_tool.py" status 2>&1)
CURRENT_STATUS=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null)

if [ "$CURRENT_STATUS" = "connected" ]; then
    # Token is still valid — try a proactive refresh anyway to extend it
    REFRESH_RESULT=$(python3 -c "
import sys
sys.path.insert(0, '$TOOL_DIR')
from tonal_tool import refresh_token
import json
result = refresh_token()
if result:
    print(json.dumps({'status': 'refreshed', 'expires_at': result.get('expires_at', 0)}))
else:
    print(json.dumps({'status': 'refresh_failed'}))
" 2>&1)

    REFRESH_STATUS=$(echo "$REFRESH_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null)

    if [ "$REFRESH_STATUS" = "refreshed" ]; then
        echo "$TIMESTAMP OK: Token refreshed successfully" >> "$LOG_FILE"
        echo '{"status":"healthy","last_refresh":"'"$TIMESTAMP"'","message":"Token refreshed."}' > "$STATUS_FILE"
        exit 0
    else
        # Refresh failed but token still valid — warn but don't alarm
        echo "$TIMESTAMP WARN: Refresh call failed but token still valid" >> "$LOG_FILE"
        echo '{"status":"warn_refresh_failed","last_attempt":"'"$TIMESTAMP"'","message":"Refresh failed but current token still valid. Will retry."}' > "$STATUS_FILE"
        exit 0
    fi
elif [ "$CURRENT_STATUS" = "expired" ]; then
    # Token expired — try refresh
    REFRESH_RESULT=$(python3 -c "
import sys
sys.path.insert(0, '$TOOL_DIR')
from tonal_tool import refresh_token
import json
result = refresh_token()
if result:
    print(json.dumps({'status': 'refreshed'}))
else:
    print(json.dumps({'status': 'refresh_failed'}))
" 2>&1)

    REFRESH_STATUS=$(echo "$REFRESH_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null)

    if [ "$REFRESH_STATUS" = "refreshed" ]; then
        echo "$TIMESTAMP OK: Expired token refreshed" >> "$LOG_FILE"
        echo '{"status":"healthy","last_refresh":"'"$TIMESTAMP"'","message":"Expired token refreshed."}' > "$STATUS_FILE"
        exit 0
    else
        echo "$TIMESTAMP FAIL: Token expired and refresh failed" >> "$LOG_FILE"
        echo '{"status":"expired","last_attempt":"'"$TIMESTAMP"'","message":"Token expired and refresh failed. Dan must re-authenticate."}' > "$STATUS_FILE"
        exit 1
    fi
else
    echo "$TIMESTAMP FAIL: Unexpected status: $CURRENT_STATUS" >> "$LOG_FILE"
    echo '{"status":"error","last_attempt":"'"$TIMESTAMP"'","message":"Unexpected state: '"$CURRENT_STATUS"'. Check tokens.json."}' > "$STATUS_FILE"
    exit 1
fi
