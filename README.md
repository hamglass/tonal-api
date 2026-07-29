# tonal-api

Unofficial Python toolkit for programmatic access to the Tonal smart cable machine. Includes a CLI tool, MCP server for AI agents, and complete API documentation.

> **Not affiliated with Tonal Systems, Inc.** "Tonal" is a trademark of Tonal Systems, Inc. This project is for personal automation and educational purposes.

## What's here

| Component | Description |
|---|---|
| `tonal_tool.py` | CLI tool with 21 commands — readiness, strength, workout history with per-set weights/1RM, exercise catalog, workout creation, progressive overload tracking |
| `mcp/tonal_mcp.py` | MCP server exposing Tonal as native tools for AI agents (Claude Code, Cursor, etc.) |
| `docs/api-reference.md` | Full Tonal REST API documentation — endpoints, request/response formats, per-field descriptions |
| `tonal_refresh.sh` | Token refresh daemon for cron (keeps JWT alive) |
| `tonal_auth_pkce.py` | PKCE auth flow for browser-based login (if your account uses email OTP) |

## Quick start

### Prerequisites

- Python 3.10+
- A Tonal account with a password set
- For the MCP server: `pip install mcp`

### 1. Authenticate

```bash
python3 tonal_tool.py auth your.email@example.com your_password
```

This obtains a JWT + refresh token from Tonal's Auth0 and stores them in `tokens.json`. Your password is **never stored** — only the tokens.

### 2. Verify

```bash
python3 tonal_tool.py check-health
```

### 3. Use it

```bash
# Check what muscles are recovered
python3 tonal_tool.py readiness

# See your last 10 workouts
python3 tonal_tool.py history

# Get per-set weights, 1RM, power data from a workout
python3 tonal_tool.py detail <activity_id>

# Track an exercise over time (progressive overload)
python3 tonal_tool.py exercise-history "barbell front squat"

# Search the exercise catalog
python3 tonal_tool.py movements chest

# Push a custom workout to your Tonal
python3 tonal_tool.py create-workout examples/push_day.json
```

## CLI commands

### Auth & health
| Command | Description |
|---|---|
| `auth <email> <password>` | Authenticate (stores tokens, not password) |
| `auth-start <email>` | Send OTP code to email (passwordless flow) |
| `auth-verify <code>` | Verify OTP code |
| `status` | Token status |
| `check-health` | Full diagnostic — token, refresh daemon, live API test |

### Readiness & strength
| Command | Description |
|---|---|
| `readiness` | Muscle readiness 0-100 per group + push/pull/legs recommendation |
| `strength` | Current strength scores by body region |
| `strength-history [N]` | Strength progression over time |
| `strength-distribution` | Overall score + percentile ranking |

### Workout history & performance
| Command | Description |
|---|---|
| `history [N]` | Recent workout list (default 10) |
| `detail <id>` | Per-set actual weights, reps, 1RM, power (watts), struggling score, ROM, Tonal's suggested next weight |
| `performance <id>` | Formatted summary with movement names, L/R side splits, suggested weight changes |
| `exercise-history <name>` | Track any exercise across all workouts — weight/volume/1RM progression with trend analysis |

### Programming
| Command | Description |
|---|---|
| `movements [search]` | Search exercise catalog by name, muscle, body region, or accessory |
| `programs [search] [level=X] [max_weeks=N] [per_week=N]` | Search the multi-week program catalog (300+) by text, level, length, or weekly frequency |
| `create-workout <json>` | Build & push workout to Tonal |
| `estimate <json>` | Estimate workout duration |
| `delete-workout <id>` | Delete a custom workout |
| `custom-workouts` | List custom workouts on Tonal |

### Profile & analytics
| Command | Description |
|---|---|
| `profile` | User profile |
| `achievements` | Badges and milestones |
| `volume-report [days]` | Training volume/frequency by week and target area |

## Data available per set

When you pull workout details, Tonal gives you remarkably rich per-set data:

| Field | What it is |
|---|---|
| `baseWeight` / `avgWeight` | Actual weight lifted in lbs |
| `repCount` | Actual reps performed |
| `oneRepMax` | Tonal's estimated 1RM |
| `suggestedWeight` | What Tonal thinks you should lift next time |
| `maxConPower` | Peak concentric power in watts |
| `strugglingScore` | How hard the set was (0-1, higher = harder) |
| `rom` | Range of motion in inches |
| `inconsistencyScore` | Rep-to-rep consistency |
| `movementSide` | "Both", "Left", or "Right" |

## Workout JSON format

Workouts are defined as blocks of exercises. Exercises within a block are supersetted.

```json
{
  "title": "Push Day - Chest & Shoulders",
  "blocks": [
    {
      "exercises": [
        {"movement_id": "c9afad76-...", "sets": 3, "reps": 10, "spotter": true},
        {"movement_id": "15e61478-...", "sets": 3, "reps": 10}
      ]
    },
    {
      "exercises": [
        {"movement_id": "8571813d-...", "sets": 3, "reps": 12, "eccentric": true}
      ]
    }
  ]
}
```

**Exercise options:**
- `sets` (int) — number of sets, default 3
- `reps` (int) — reps per set, default 10. Auto-doubled for alternating movements
- `duration` (int) — seconds, for duration-based exercises (auto-detected from catalog)
- `spotter` (bool) — digital spotter
- `eccentric` (bool) — eccentric mode (slower negatives)
- `chains` (bool) — chains mode (variable resistance)
- `burnout` (bool) — burnout set
- `drop_set` (bool) — drop set
- `warm_up` (bool) — warm-up set (50% weight)
- `weight_percentage` (int) — % of working weight, default 100

## MCP server

The MCP server lets any MCP-compatible AI agent interact with Tonal natively.

### Install

```bash
pip install mcp
```

### Configure

Add to your Claude Code `settings.json`, Cursor config, or any MCP client:

```json
{
  "mcpServers": {
    "tonal": {
      "command": "python3",
      "args": ["/path/to/mcp/tonal_mcp.py"],
      "env": {
        "TONAL_TOKEN_DIR": "/path/to/directory/with/tokens.json"
      }
    }
  }
}
```

### Available MCP tools

| Tool | Description |
|---|---|
| `check_health` | Connection diagnostic |
| `get_readiness` | Muscle readiness + split recommendation |
| `get_strength` | Current strength scores |
| `get_strength_history` | Strength progression |
| `get_profile` | User profile |
| `get_workout_history` | Recent workouts |
| `get_workout_detail` | Per-set weights, 1RM, power, struggling scores |
| `get_performance_summary` | Formatted summary with L/R splits |
| `get_exercise_history` | Progressive overload tracking across sessions |
| `search_exercises` | Exercise catalog search |
| `search_programs` | Multi-week program catalog search (text, level, weeks, frequency) |
| `create_workout` | Build & push workout to Tonal |
| `estimate_duration` | Predict workout duration |
| `delete_workout` | Remove custom workout |
| `get_volume_report` | Training volume analysis |

## Token management

Tokens expire in ~10 hours. The refresh token lasts much longer.

### Automatic refresh (recommended)

Set up a cron job to refresh proactively:

```bash
# Add to crontab — every 6 hours
0 */6 * * * /path/to/tonal_refresh.sh >> /path/to/refresh.log 2>&1
```

The refresh script writes status to `refresh_status.json` so your tools can check if the daemon is healthy.

### Manual refresh

Any command will auto-refresh on 401. If the refresh token itself expires, re-authenticate with `auth`.

## API documentation

See [docs/api-reference.md](docs/api-reference.md) for the complete Tonal REST API reference including:

- All endpoint URLs and methods
- Request/response schemas with field descriptions
- Authentication flows (password, PKCE, token refresh)
- Per-set data fields (weights, 1RM, power, struggling scores, ROM)
- Workout creation payload structure
- Error handling patterns

## How this was built

The Tonal API was reverse-engineered from the [tonal-coach](https://github.com/JeffOtano/tonal-coach) open-source project and verified against the live API. Auth0 configuration was discovered through the Auth0 well-known endpoint and empirical testing of grant types and connection names.

## License

MIT
