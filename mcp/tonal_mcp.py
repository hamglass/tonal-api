#!/usr/bin/env python3
"""
Tonal MCP Server
Exposes Tonal fitness machine capabilities as MCP tools for AI agents.

Run with:
  python3 tonal_mcp.py

Configure in Claude Code settings.json or MCP client config:
  {
    "mcpServers": {
      "tonal": {
        "command": "python3",
        "args": ["/path/to/tonal_mcp.py"],
        "env": {
          "TONAL_TOKEN_DIR": "/path/to/token/directory"
        }
      }
    }
  }

Requires: pip install mcp
Tokens: Authenticate first with tonal_tool.py, then point TONAL_TOKEN_DIR
         at the directory containing tokens.json.
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

# MCP SDK
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Install the MCP SDK: pip install mcp", file=sys.stderr)
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────

TOKEN_DIR = os.environ.get("TONAL_TOKEN_DIR", os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(TOKEN_DIR, "tokens.json")
MOVEMENTS_CACHE = os.path.join(TOKEN_DIR, "movements_cache.json")
PROGRAMS_CACHE = os.path.join(TOKEN_DIR, "programs_cache.json")
TONAL_API_BASE = "https://api.tonal.com"
AUTH0_DOMAIN = "tonal.auth0.com"
AUTH0_CLIENT_ID = "ERCyexW-xoVG_Yy3RDe-eV4xsOnRHP6L"
GET_TIMEOUT = 15
POST_TIMEOUT = 30

mcp = FastMCP("tonal", instructions="""Tonal smart cable machine integration.
Provides muscle readiness, strength tracking, workout history with per-set weights/1RM,
exercise catalog search, custom workout creation, and progressive overload analysis.
Authenticate first with tonal_tool.py, then use these tools.""")


# ── Token & HTTP helpers ──────────────────────────────────────────────

def _load_tokens():
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE) as f:
        return json.load(f)

def _save_tokens(tokens):
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    os.chmod(TOKEN_FILE, 0o600)

def _is_expired(tokens):
    if not tokens or "expires_at" not in tokens:
        return True
    return time.time() >= tokens["expires_at"] - 300

def _refresh():
    tokens = _load_tokens()
    if not tokens or "refresh_token" not in tokens:
        return None
    body = json.dumps({"grant_type": "refresh_token", "client_id": AUTH0_CLIENT_ID,
                       "refresh_token": tokens["refresh_token"]}).encode()
    req = Request(f"https://{AUTH0_DOMAIN}/oauth/token", data=body,
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=POST_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    tokens["id_token"] = data.get("id_token", tokens["id_token"])
    tokens["refresh_token"] = data.get("refresh_token", tokens["refresh_token"])
    try:
        payload = json.loads(base64.b64decode(tokens["id_token"].split(".")[1] + "=="))
        tokens["expires_at"] = payload.get("exp", int(time.time()) + 86400)
    except Exception:
        tokens["expires_at"] = int(time.time()) + 86400
    tokens["last_refreshed"] = datetime.now(timezone.utc).isoformat()
    _save_tokens(tokens)
    return tokens

def _get_token():
    tokens = _load_tokens()
    if not tokens:
        raise ValueError("Not authenticated. Run tonal_tool.py auth first.")
    if _is_expired(tokens):
        tokens = _refresh()
        if not tokens:
            raise ValueError("Token expired and refresh failed. Re-authenticate.")
    return tokens["id_token"], tokens.get("user_id", "")

def _api_get(endpoint, params=None):
    token, _ = _get_token()
    url = f"{TONAL_API_BASE}{endpoint}"
    if params:
        url += "?" + "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    req = Request(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=GET_TIMEOUT) as resp:
            return json.loads(resp.read()) if resp.status != 204 else {}
    except HTTPError as e:
        if e.code == 401:
            new = _refresh()
            if new:
                req = Request(url, headers={"Authorization": f"Bearer {new['id_token']}",
                                            "Content-Type": "application/json"})
                with urlopen(req, timeout=GET_TIMEOUT) as resp:
                    return json.loads(resp.read())
            raise ValueError("Auth failed after refresh")
        raise ValueError(f"Tonal API {e.code}: {e.read().decode()[:200]}")

def _api_post(endpoint, body):
    token, _ = _get_token()
    url = f"{TONAL_API_BASE}{endpoint}"
    data = json.dumps(body).encode()
    req = Request(url, data=data, headers={"Authorization": f"Bearer {token}",
                  "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=POST_TIMEOUT) as resp:
            return json.loads(resp.read()) if resp.status != 204 else {"status": "ok"}
    except HTTPError as e:
        raise ValueError(f"Tonal API {e.code}: {e.read().decode()[:500]}")

def _api_delete(endpoint):
    token, _ = _get_token()
    url = f"{TONAL_API_BASE}{endpoint}"
    req = Request(url, headers={"Authorization": f"Bearer {token}",
                  "Content-Type": "application/json"}, method="DELETE")
    try:
        with urlopen(req, timeout=POST_TIMEOUT) as resp:
            return {"status": "deleted"}
    except HTTPError as e:
        raise ValueError(f"Tonal API {e.code}: {e.read().decode()[:200]}")

def _uid():
    _, uid = _get_token()
    if not uid:
        raise ValueError("No user ID. Re-authenticate.")
    return uid

def _movement_map():
    if os.path.exists(MOVEMENTS_CACHE):
        with open(MOVEMENTS_CACHE) as f:
            cache = json.load(f)
        if time.time() - cache.get("cached_at", 0) < 86400:
            return {m["id"]: m for m in cache.get("movements", [])}
    data = _api_get("/v6/movements")
    movements = data if isinstance(data, list) else data.get("movements", [])
    with open(MOVEMENTS_CACHE, "w") as f:
        json.dump({"cached_at": time.time(), "movements": movements}, f)
    return {m["id"]: m for m in movements}


# ── MCP Tools ─────────────────────────────────────────────────────────

@mcp.tool()
def check_health() -> dict:
    """Check Tonal connection health — token status, expiry, live API test."""
    tokens = _load_tokens()
    if not tokens:
        return {"health": "DEAD", "fix": "Run tonal_tool.py auth <email> <password>"}
    expired = _is_expired(tokens)
    result = {"token_status": "expired" if expired else "valid",
              "expires_at": datetime.fromtimestamp(tokens.get("expires_at", 0), tz=timezone.utc).isoformat(),
              "last_refreshed": tokens.get("last_refreshed", "never")}
    if not expired:
        try:
            _api_get(f"/v6/users/{tokens.get('user_id', '')}")
            result["api_check"] = "OK"
            result["health"] = "HEALTHY"
        except Exception:
            result["api_check"] = "FAIL"
            result["health"] = "API_FAILING"
    else:
        result["health"] = "EXPIRED"
    return result


@mcp.tool()
def get_readiness() -> dict:
    """Get muscle readiness scores (0-100 per muscle group) with training split recommendation."""
    uid = _uid()
    data = _api_get(f"/v6/users/{uid}/muscle-readiness/current")
    muscles = {k: data[k] for k in ["Chest","Shoulders","Back","Triceps","Biceps",
                                     "Abs","Obliques","Quads","Glutes","Hamstrings","Calves"] if k in data}
    sorted_m = dict(sorted(muscles.items(), key=lambda x: x[1]))
    def avg(ml): vals = [muscles.get(m, 50) for m in ml]; return round(sum(vals)/len(vals))
    push, pull, legs = avg(["Chest","Triceps","Shoulders"]), avg(["Back","Biceps"]), avg(["Quads","Glutes","Hamstrings","Calves"])
    return {"readiness_scores": sorted_m,
            "split_readiness": {"push": push, "pull": pull, "legs": legs},
            "fatigued": [k for k,v in sorted_m.items() if v < 40],
            "ready": [k for k,v in sorted_m.items() if v >= 70]}


@mcp.tool()
def get_strength() -> dict:
    """Get current strength scores by body region."""
    uid = _uid()
    data = _api_get(f"/v6/users/{uid}/strength-scores/current")
    if isinstance(data, list):
        return {"scores": [{"region": s.get("bodyRegionDisplay",""), "score": s.get("score")} for s in data]}
    return data


@mcp.tool()
def get_strength_history(limit: int = 20) -> dict:
    """Get strength score progression over time."""
    uid = _uid()
    data = _api_get(f"/v6/users/{uid}/strength-scores/history", params={"limit": limit})
    if isinstance(data, list):
        return {"history": [{"date": e.get("activityTime","")[:10], "overall": e.get("overall"),
                             "upper": e.get("upper"), "lower": e.get("lower"), "core": e.get("core")} for e in data]}
    return data


@mcp.tool()
def get_profile() -> dict:
    """Get Tonal user profile (height, weight, preferences)."""
    uid = _uid()
    data = _api_get(f"/v6/users/{uid}")
    return {"name": f"{data.get('firstName','')} {data.get('lastName','')}".strip(),
            "height_inches": data.get("heightInches"), "weight_lbs": data.get("weightPounds"),
            "workouts_per_week": data.get("workoutsPerWeek"), "member_since": data.get("createdAt")}


@mcp.tool()
def get_workout_history(limit: int = 10) -> dict:
    """Get recent workout history with titles, volume, duration, and target areas."""
    uid = _uid()
    data = _api_get(f"/v6/users/{uid}/activities", params={"limit": limit})
    activities = data if isinstance(data, list) else data.get("activities", data.get("data", []))
    return {"workouts": [{"activity_id": a.get("activityId"), "date": a.get("activityTime","")[:10],
                          "title": a.get("workoutPreview",{}).get("workoutTitle",""),
                          "duration_min": round(a.get("workoutPreview",{}).get("totalDuration",0)/60),
                          "total_volume_lbs": a.get("workoutPreview",{}).get("totalVolume"),
                          "target_area": a.get("workoutPreview",{}).get("targetArea","")}
                         for a in activities]}


@mcp.tool()
def get_workout_detail(activity_id: str) -> dict:
    """Get full workout detail with per-set actual weights, reps, 1RM, power, and struggling scores."""
    uid = _uid()
    data = _api_get(f"/v6/users/{uid}/workout-activities/{activity_id}")
    mm = _movement_map()
    movements = {}
    for s in data.get("workoutSetActivity", []):
        mid = s.get("movementId", "")
        if mid not in movements:
            m = mm.get(mid, {})
            movements[mid] = {"name": m.get("name", mid[:8]), "movement_id": mid, "sets": [], "warmup_sets": []}
        sd = {"reps": s.get("repCount", 0), "weight_lbs": s.get("baseWeight", 0),
              "volume_lbs": s.get("volume", 0), "one_rep_max": round(s.get("oneRepMax", 0)) or None,
              "max_power_watts": round(s.get("maxConPower", 0)) or None,
              "struggling_score": round(s.get("strugglingScore", 0), 2) if s.get("strugglingScore") else None,
              "suggested_weight": round(s.get("suggestedWeight", 0), 1) if s.get("suggestedWeight") else None,
              "side": s.get("movementSide", "Both")}
        if s.get("warmUp"):
            movements[mid]["warmup_sets"].append(sd)
        else:
            movements[mid]["sets"].append(sd)

    summaries = []
    for mid, m in movements.items():
        ws = m["sets"]
        if ws:
            weights = [s["weight_lbs"] for s in ws if s["weight_lbs"]]
            summaries.append({"name": m["name"], "movement_id": mid,
                              "working_sets": len(ws), "warmup_sets": len(m["warmup_sets"]),
                              "avg_weight_lbs": round(sum(weights)/len(weights),1) if weights else 0,
                              "total_reps": sum(s["reps"] for s in ws),
                              "total_volume_lbs": sum(s["volume_lbs"] for s in ws),
                              "best_1rm": max((s["one_rep_max"] for s in ws if s["one_rep_max"]), default=None),
                              "set_details": ws})
    return {"activity_id": data.get("id"), "total_duration_min": round(data.get("totalDuration",0)/60),
            "total_volume_lbs": data.get("totalVolume"), "percent_completed": data.get("percentCompleted"),
            "movements": summaries}


@mcp.tool()
def get_performance_summary(activity_id: str) -> dict:
    """Get formatted workout summary with movement names, per-set weights, and L/R side splits."""
    uid = _uid()
    data = _api_get(f"/v6/formatted/users/{uid}/workout-summaries/{activity_id}")
    result = {"workout_name": data.get("name",""), "coach": data.get("coachName",""),
              "target_area": data.get("targetArea",""), "date": data.get("localTimestamp","")[:10],
              "movements": []}
    for ms in data.get("movementSets", []):
        mov = {"name": ms.get("movementName",""), "total_volume_lbs": ms.get("totalVolume",0), "sets": []}
        for s in ms.get("sets", []):
            si = {"reps": s.get("repCount",0), "weight_lbs": s.get("weight",0),
                  "one_rep_max": s.get("oneRepMax"), "warm_up": s.get("warmUp", False),
                  "suggested_weight_change": s.get("suggestedWeightChange", 0)}
            if s.get("leftSideMovementSet"):
                si["left"] = {"reps": s["leftSideMovementSet"].get("repCount"),
                              "weight_lbs": s["leftSideMovementSet"].get("weight")}
            if s.get("rightSideMovementSet"):
                si["right"] = {"reps": s["rightSideMovementSet"].get("repCount"),
                               "weight_lbs": s["rightSideMovementSet"].get("weight")}
            mov["sets"].append(si)
        result["movements"].append(mov)
    return result


@mcp.tool()
def search_exercises(query: str) -> dict:
    """Search the Tonal exercise catalog by name, muscle group, body region, or accessory type."""
    mm = _movement_map()
    q = query.lower()
    matches = [m for m in mm.values()
               if q in m.get("name","").lower() or q in " ".join(m.get("muscleGroups",[])).lower()
               or q in m.get("bodyRegion","").lower()
               or q in (m.get("onMachineInfo") or {}).get("accessory","").lower()]
    return {"total": len(matches), "movements": [
        {"id": m["id"], "name": m.get("name",""), "muscle_groups": m.get("muscleGroups",[]),
         "accessory": (m.get("onMachineInfo") or {}).get("accessory",""),
         "count_reps": m.get("countReps"), "is_alternating": m.get("isAlternating"),
         "spotter_ok": not (m.get("onMachineInfo") or {}).get("spotterDisabled", True),
         "eccentric_ok": not (m.get("onMachineInfo") or {}).get("eccentricDisabled", True)}
        for m in matches[:50]]}


def _program_catalog():
    if os.path.exists(PROGRAMS_CACHE):
        with open(PROGRAMS_CACHE) as f:
            cache = json.load(f)
        if time.time() - cache.get("cached_at", 0) < 86400:
            return cache.get("programs", [])
    data = _api_get("/v6/programs")
    programs = data if isinstance(data, list) else data.get("programs", [])
    with open(PROGRAMS_CACHE, "w") as f:
        json.dump({"cached_at": time.time(), "count": len(programs), "programs": programs}, f)
    return programs


@mcp.tool()
def search_programs(query: str = "", level: str = "", max_weeks: int = 0, max_per_week: int = 0) -> dict:
    """Search Tonal's multi-week program catalog (300+ guided programs).

    query: free text matched against program name and description (e.g. "hypertrophy", "upper body").
    level: BEGINNER, INTERMEDIATE, or ADVANCED (programs marked ALL always match).
    max_weeks: only programs this many weeks or shorter (0 = no limit).
    max_per_week: only programs with at most this many workouts per week (0 = no limit).
    Returns program id, name, weeks, workouts_per_week, level, accessories, and description."""
    matches = [p for p in _program_catalog() if p.get("publishState", "published") == "published"]
    if level:
        matches = [p for p in matches if p.get("level", "").upper() in (level.upper(), "ALL")]
    if max_weeks:
        matches = [p for p in matches if (p.get("weeks") or 0) <= max_weeks]
    if max_per_week:
        matches = [p for p in matches if (p.get("workoutsPerWeek") or 0) <= max_per_week]
    if query:
        q = query.lower()
        matches = [p for p in matches
                   if q in p.get("name", "").lower() or q in (p.get("description") or "").lower()]
    return {"total": len(matches), "programs": [
        {"id": p.get("id"), "name": p.get("name"), "weeks": p.get("weeks"),
         "workouts_per_week": p.get("workoutsPerWeek"), "level": p.get("level"),
         "accessories": p.get("accessories", []),
         "description": (p.get("description") or "")[:400]}
        for p in matches[:50]]}


@mcp.tool()
def get_exercise_history(exercise_name: str) -> dict:
    """Track a specific exercise across all past workouts for progressive overload analysis.
    Returns weight/volume/1RM progression over time."""
    uid = _uid()
    mm = _movement_map()
    q = exercise_name.lower()
    targets = {mid: m for mid, m in mm.items() if q in m.get("name","").lower()}
    if not targets:
        return {"error": f"No exercise matching '{exercise_name}'"}
    if len(targets) > 5:
        return {"too_many": len(targets), "matches": [{"id": mid, "name": m.get("name")}
                for mid, m in list(targets.items())[:10]]}

    history = _api_get(f"/v6/users/{uid}/activities", params={"limit": 50})
    activities = history if isinstance(history, list) else history.get("activities", history.get("data", []))

    by_date = {}
    for act in activities:
        aid = act.get("activityId")
        if not aid:
            continue
        detail = _api_get(f"/v6/users/{uid}/workout-activities/{aid}")
        if isinstance(detail, dict) and "error" in detail:
            continue
        for s in detail.get("workoutSetActivity", []):
            if s.get("movementId") not in targets or s.get("warmUp"):
                continue
            d = act.get("activityTime","")[:10]
            if d not in by_date:
                by_date[d] = {"date": d, "workout": act.get("workoutPreview",{}).get("workoutTitle",""), "sets": []}
            by_date[d]["sets"].append({
                "weight_lbs": s.get("baseWeight", 0), "reps": s.get("repCount", 0),
                "volume_lbs": s.get("volume", 0), "one_rep_max": round(s.get("oneRepMax", 0)) or None})

    sessions = []
    for d in sorted(by_date):
        sets = by_date[d]["sets"]
        weights = [s["weight_lbs"] for s in sets if s["weight_lbs"]]
        orms = [s["one_rep_max"] for s in sets if s["one_rep_max"]]
        sessions.append({"date": d, "workout": by_date[d]["workout"], "sets": len(sets),
                         "avg_weight_lbs": round(sum(weights)/len(weights),1) if weights else 0,
                         "total_volume_lbs": sum(s["volume_lbs"] for s in sets),
                         "best_1rm": max(orms) if orms else None})

    name = list(targets.values())[0].get("name", exercise_name) if len(targets) == 1 else exercise_name
    progression = None
    if len(sessions) >= 2:
        delta = sessions[-1]["avg_weight_lbs"] - sessions[0]["avg_weight_lbs"]
        progression = {"weight_change_lbs": round(delta,1),
                       "direction": "increasing" if delta > 0 else "decreasing" if delta < 0 else "flat"}
    return {"exercise": name, "sessions_found": len(sessions), "progression": progression, "sessions": sessions}


@mcp.tool()
def create_workout(title: str, blocks: list[dict]) -> dict:
    """Create and push a custom workout to Tonal.
    blocks: list of {"exercises": [{"movement_id": "uuid", "sets": 3, "reps": 10, ...}]}
    Exercise options: sets, reps, duration, spotter, eccentric, chains, burnout, drop_set, warm_up, weight_percentage."""
    mm = _movement_map()
    all_ids = [ex.get("movement_id","") for b in blocks for ex in b.get("exercises",[])]
    invalid = [mid for mid in all_ids if mid and mid not in mm]
    if invalid:
        return {"error": "Invalid movement IDs", "invalid": invalid}

    all_sets = []
    bn = 1
    for block in blocks:
        exercises = block.get("exercises", [])
        if not exercises:
            continue
        max_r = max(ex.get("sets", 3) for ex in exercises)
        for r in range(1, max_r + 1):
            for ei, ex in enumerate(exercises):
                if r > ex.get("sets", 3):
                    continue
                mid = ex.get("movement_id", "")
                m = mm.get(mid, {})
                s = {"movementId": mid, "blockStart": (r==1 and ei==0), "blockNumber": bn,
                     "setGroup": ei+1, "round": r, "repetition": r, "repetitionTotal": ex.get("sets",3),
                     "spotter": ex.get("spotter",False), "eccentric": ex.get("eccentric",False),
                     "chains": ex.get("chains",False), "flex": False,
                     "warmUp": ex.get("warm_up", ex.get("warmUp",False)),
                     "burnout": ex.get("burnout",False), "dropSet": ex.get("drop_set",False),
                     "weightPercentage": ex.get("weight_percentage",100), "description": ""}
                if (not m.get("countReps", True)) or ex.get("duration"):
                    s["prescribedDuration"] = ex.get("duration", 30)
                    s["prescribedResistanceLevel"] = 5
                else:
                    reps = ex.get("reps", 10)
                    s["prescribedReps"] = reps * 2 if m.get("isAlternating") else reps
                all_sets.append({k:v for k,v in s.items() if v is not None})
        bn += 1

    result = _api_post("/v6/user-workouts", {"title": title, "sets": all_sets})
    return {"status": "pushed", "workout_id": result.get("id",""), "title": title, "set_count": len(all_sets)}


@mcp.tool()
def estimate_duration(blocks: list[dict]) -> dict:
    """Estimate how long a workout will take before pushing it to Tonal."""
    mm = _movement_map()
    all_sets = []
    bn = 1
    for block in blocks:
        exercises = block.get("exercises", [])
        if not exercises:
            continue
        max_r = max(ex.get("sets", 3) for ex in exercises)
        for r in range(1, max_r + 1):
            for ei, ex in enumerate(exercises):
                if r > ex.get("sets", 3):
                    continue
                mid = ex.get("movement_id", "")
                m = mm.get(mid, {})
                s = {"movementId": mid, "blockStart": (r==1 and ei==0), "blockNumber": bn,
                     "setGroup": ei+1, "round": r, "repetition": r, "repetitionTotal": ex.get("sets",3),
                     "weightPercentage": 100, "description": ""}
                if not m.get("countReps", True):
                    s["prescribedDuration"] = ex.get("duration", 30)
                else:
                    reps = ex.get("reps", 10)
                    s["prescribedReps"] = reps * 2 if m.get("isAlternating") else reps
                all_sets.append({k:v for k,v in s.items() if v is not None})
        bn += 1
    result = _api_post("/v6/user-workouts/estimate", {"sets": all_sets})
    return {"estimated_duration_min": result.get("duration"), "set_count": len(all_sets)}


@mcp.tool()
def delete_workout(workout_id: str) -> dict:
    """Delete a custom workout from Tonal."""
    return _api_delete(f"/v6/user-workouts/{workout_id}")


@mcp.tool()
def get_volume_report(days: int = 30) -> dict:
    """Training volume and frequency analysis over N days, broken down by week and target area."""
    uid = _uid()
    data = _api_get(f"/v6/users/{uid}/activities", params={"limit": min(days, 100)})
    activities = data if isinstance(data, list) else data.get("activities", data.get("data", []))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [a for a in activities if a.get("activityTime","") >= cutoff]
    if not recent:
        return {"days": days, "workouts": 0}

    total_vol, total_dur, by_area, by_week = 0, 0, {}, {}
    for a in recent:
        p = a.get("workoutPreview", {})
        v, d = p.get("totalVolume", 0), p.get("totalDuration", 0)
        total_vol += v; total_dur += d
        area = p.get("targetArea", "OTHER")
        by_area[area] = by_area.get(area, 0) + 1
        ds = a.get("activityTime","")[:10]
        try:
            dt = datetime.strptime(ds, "%Y-%m-%d")
            ws = (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
            if ws not in by_week: by_week[ws] = {"sessions": 0, "volume_lbs": 0}
            by_week[ws]["sessions"] += 1; by_week[ws]["volume_lbs"] += v
        except Exception: pass

    return {"period_days": days, "total_workouts": len(recent),
            "workouts_per_week": round(len(recent)/(days/7), 1),
            "total_volume_lbs": total_vol, "avg_volume_per_session": round(total_vol/len(recent)),
            "by_target_area": by_area, "by_week": dict(sorted(by_week.items()))}


if __name__ == "__main__":
    mcp.run()
