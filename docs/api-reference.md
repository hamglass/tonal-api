# Tonal API Reference

Unofficial documentation of the Tonal REST API at `https://api.tonal.com`. Reverse-engineered from the [tonal-coach](https://github.com/JeffOtano/tonal-coach) open-source project and verified against the live API.

> **Not affiliated with Tonal Systems, Inc.** "Tonal" is a trademark of Tonal Systems, Inc. This documentation is for educational and personal automation purposes.

## Authentication

Tonal uses [Auth0](https://auth0.com) for authentication. The Auth0 tenant is `tonal.auth0.com` and the public client ID is `ERCyexW-xoVG_Yy3RDe-eV4xsOnRHP6L`.

### Password Grant (simplest for automation)

```
POST https://tonal.auth0.com/oauth/token
Content-Type: application/json

{
  "grant_type": "password",
  "username": "user@example.com",
  "password": "their_password",
  "client_id": "ERCyexW-xoVG_Yy3RDe-eV4xsOnRHP6L",
  "scope": "openid profile email offline_access"
}
```

**Response:**
```json
{
  "id_token": "eyJ...",
  "refresh_token": "v1.M...",
  "access_token": "...",
  "token_type": "Bearer",
  "expires_in": 36000
}
```

Use `id_token` as the Bearer token for all API calls. The `refresh_token` is long-lived and can be used to obtain new tokens without re-entering credentials.

### Token Refresh

```
POST https://tonal.auth0.com/oauth/token
Content-Type: application/json

{
  "grant_type": "refresh_token",
  "client_id": "ERCyexW-xoVG_Yy3RDe-eV4xsOnRHP6L",
  "refresh_token": "v1.M..."
}
```

### PKCE Flow (for browser-based apps)

See `tonal_auth_pkce.py` for a complete implementation. Uses the `/authorize` endpoint with `response_type=code`, S256 challenge, and the mobile app redirect URI `com.tonal.tonalapp://tonal.auth0.com/ios/com.tonal.tonalapp/callback`.

### Auth Headers

All API requests require:
```
Authorization: Bearer <id_token>
Content-Type: application/json
```

---

## User Endpoints

### Get User Info
```
GET /v6/users/userinfo
```
Returns the authenticated user's profile. Use this to get the `id` (userId) needed for other endpoints.

### Get User Profile
```
GET /v6/users/{userId}
```

**Response fields:**
| Field | Type | Description |
|---|---|---|
| `id` | string | UUID |
| `email` | string | Account email |
| `firstName`, `lastName` | string | Name |
| `gender` | string | "MALE" / "FEMALE" |
| `heightInches` | number | Height in inches |
| `weightPounds` | number | Weight in lbs |
| `workoutsPerWeek` | number | Target frequency |
| `workoutDurationMin` | number | Min duration preference (seconds) |
| `workoutDurationMax` | number | Max duration preference (seconds) |
| `tonalStatus` | string | "purchased", etc. |
| `accountType` | string | "PublicUser", etc. |
| `createdAt` | string | ISO 8601 |

---

## Strength & Readiness

### Current Strength Scores
```
GET /v6/users/{userId}/strength-scores/current
```

Returns an array of scores by body region:
```json
[
  {"id": "...", "userId": "...", "strengthBodyRegion": "Upper", "bodyRegionDisplay": "Upper", "score": 525, "current": true},
  {"id": "...", "strengthBodyRegion": "Core", "bodyRegionDisplay": "Core", "score": 489, "current": true},
  {"id": "...", "strengthBodyRegion": "Lower", "bodyRegionDisplay": "Lower", "score": 490, "current": true},
  {"id": "...", "strengthBodyRegion": "", "bodyRegionDisplay": "", "score": 501, "current": true}
]
```
The entry with empty `strengthBodyRegion` is the overall score.

### Strength Score History
```
GET /v6/users/{userId}/strength-scores/history?limit=20
```

Returns array of historical entries:
```json
[
  {"id": "...", "userId": "...", "upper": 525, "lower": 490, "core": 489, "overall": 501, "activityTime": "2026-04-11T18:33:21Z", "workoutActivityId": "..."}
]
```

### Strength Distribution
```
GET /v6/users/{userId}/strength-scores/distribution
```

```json
{"userId": "...", "overallScore": 501, "percentile": 42, "distributionPoints": [...]}
```

### Muscle Readiness
```
GET /v6/users/{userId}/muscle-readiness/current
```

Returns readiness scores (0-100) per muscle group. Higher = more recovered.
```json
{
  "Chest": 100, "Shoulders": 100, "Back": 100,
  "Triceps": 100, "Biceps": 100,
  "Abs": 100, "Obliques": 100,
  "Quads": 79, "Glutes": 79, "Hamstrings": 100, "Calves": 100
}
```

---

## Workout History

### List Activities
```
GET /v6/users/{userId}/activities?limit=10
```

Returns recent workout activities (Tonal sessions, external activities):
```json
[
  {
    "activityId": "uuid",
    "userId": "uuid",
    "activityTime": "2026-04-11T18:33:21.38Z",
    "activityType": "workout",
    "workoutPreview": {
      "activityId": "uuid",
      "workoutId": "uuid",
      "workoutTitle": "Breakthrough: Level II - WO9",
      "programName": "Breakthrough: Level II",
      "coachName": "Joe",
      "level": "Expert",
      "targetArea": "LOWER BODY",
      "isGuidedWorkout": true,
      "workoutType": "Linear",
      "beginTime": "2026-04-11T18:33:21.38Z",
      "totalDuration": 2966,
      "totalVolume": 7411,
      "totalWork": 16141,
      "totalAchievements": 0
    }
  }
]
```

### Workout Detail (Raw Sets)
```
GET /v6/users/{userId}/workout-activities/{activityId}
```

Returns the full workout with per-set data. This is the richest data source.

**Top-level fields:**
| Field | Type | Description |
|---|---|---|
| `totalDuration` | number | Total time in seconds |
| `activeDuration` | number | Time under tension in seconds |
| `totalMovements` | number | Unique exercises |
| `totalSets` | number | Total sets including warm-ups |
| `totalReps` | number | Total reps |
| `totalVolume` | number | Total volume in lbs |
| `totalConcentricWork` | number | Total concentric work |
| `percentCompleted` | number | 0-100 |

**Per-set fields** (in `workoutSetActivity[]`):
| Field | Type | Description |
|---|---|---|
| `movementId` | string | Exercise UUID |
| `baseWeight` | number | **Actual weight in lbs** |
| `avgWeight` | number | Average weight across set |
| `maxWeight` | number | Peak weight in set |
| `minWeight` | number | Minimum weight in set |
| `repCount` | number | **Actual reps performed** |
| `prescribedReps` | number | Programmed rep target |
| `volume` | number | Set volume (weight x reps) |
| `totalVolume` | number | Cumulative volume |
| `oneRepMax` | number | **Estimated 1RM** |
| `suggestedWeight` | number | **Tonal's suggestion for next time** |
| `maxConPower` | number | **Peak concentric power (watts)** |
| `velAtMaxConPower` | number | Velocity at peak power |
| `rom` | number | Range of motion (inches) |
| `strugglingScore` | number | **Difficulty 0-1** (higher = harder) |
| `inconsistencyScore` | number | Rep-to-rep consistency 0-1 |
| `warmUp` | boolean | Warm-up set flag |
| `spotter` | boolean | Digital spotter enabled |
| `eccentric` | boolean | Eccentric mode enabled |
| `chains` | boolean | Chains mode enabled |
| `burnout` | boolean | Burnout set |
| `dropSet` | boolean | Drop set |
| `weightPercentage` | number | % of working weight |
| `spotterMode` | string | "SPOTTER", "OFF" |
| `movementSide` | string | "Both", "Left", "Right" |
| `blockNumber` | number | Block grouping |
| `repetition` | number | Current round |
| `repetitionTotal` | number | Total rounds |
| `duration` | number | Set duration in seconds |
| `beginTime` | string | ISO 8601 |
| `endTime` | string | ISO 8601 |

### Formatted Workout Summary
```
GET /v6/formatted/users/{userId}/workout-summaries/{activityId}
```

Returns a pre-aggregated summary with movement names and per-movement totals. Includes left/right side splits for unilateral exercises.

**Response structure:**
```json
{
  "name": "Breakthrough: Level II - WO9 (W3D1)",
  "programName": "Breakthrough: Level II",
  "coachName": "Joe",
  "targetArea": "LOWER BODY",
  "duration": 2966,
  "timeUnderTension": 1076,
  "movementSets": [
    {
      "movementName": "Barbell Front Squat",
      "movementId": "uuid",
      "totalVolume": 2076,
      "totalWork": 5678,
      "sets": [
        {
          "repCount": 8,
          "repGoal": 8,
          "weight": 61,
          "avgMaxWeight": 61,
          "oneRepMax": 35,
          "maxConPower": 456,
          "totalVolume": 488,
          "warmUp": false,
          "weightPercentage": 100,
          "suggestedWeightChange": 0,
          "spotterMode": "SPOTTER",
          "duration": 25,
          "leftSideMovementSet": { "repCount": 8, "weight": 61, "..." },
          "rightSideMovementSet": { "repCount": 8, "weight": 61, "..." }
        }
      ]
    }
  ]
}
```

---

## Movement Catalog

### List All Movements
```
GET /v6/movements
```

Returns the complete exercise catalog (~300+ movements). This is a global endpoint (not user-specific) but requires authentication.

**Key fields per movement:**
| Field | Type | Description |
|---|---|---|
| `id` | string | UUID — use this in workout creation |
| `name` | string | Display name (e.g., "Barbell Front Squat") |
| `shortName` | string | Abbreviated name |
| `muscleGroups` | string[] | Target muscles (e.g., ["Quads", "Glutes"]) |
| `bodyRegion` | string | "Upper Body", "Lower Body", "Core" |
| `skillLevel` | number | 1-3 difficulty |
| `countReps` | boolean | `true` = rep-based, `false` = duration-based |
| `isAlternating` | boolean | Alternates sides (reps are per-side, Tonal doubles internally) |
| `isTwoSided` | boolean | Has separate L/R sides |
| `isBilateral` | boolean | Works both sides simultaneously |
| `onMachine` | boolean | Requires Tonal machine |
| `inFreeLift` | boolean | Available in free lift mode |
| `trainingTypes` | string[] | e.g., ["Strength", "Warm-up"] |
| `onMachineInfo.accessory` | string | Required accessory: "Handles", "Rope", "StraightBar", "RopeBar", "PilatesLoops" |
| `onMachineInfo.spotterDisabled` | boolean | Whether spotter mode is available |
| `onMachineInfo.eccentricDisabled` | boolean | Whether eccentric mode is available |
| `onMachineInfo.chainsDisabled` | boolean | Whether chains mode is available |
| `descriptionHow` | string | Exercise instructions |
| `descriptionWhy` | string | Why this exercise is beneficial |

---

## Custom Workouts (Read/Write)

### List Custom Workouts
```
GET /v6/user-workouts
```

Returns all user-created custom workouts on the Tonal.

### Create Custom Workout
```
POST /v6/user-workouts
Content-Type: application/json

{
  "title": "My Custom Workout",
  "sets": [
    {
      "movementId": "uuid",
      "blockStart": true,
      "blockNumber": 1,
      "setGroup": 1,
      "round": 1,
      "repetition": 1,
      "repetitionTotal": 3,
      "prescribedReps": 10,
      "spotter": true,
      "eccentric": false,
      "chains": false,
      "flex": false,
      "warmUp": false,
      "burnout": false,
      "dropSet": false,
      "weightPercentage": 100,
      "description": ""
    }
  ]
}
```

**Response:** `{"id": "new-workout-uuid"}`

**Important notes:**
- `movementId` must be a valid UUID from `/v6/movements`
- For duration-based exercises (where `countReps=false`), use `prescribedDuration` (seconds) instead of `prescribedReps`, and set `prescribedResistanceLevel: 5`
- For alternating exercises (`isAlternating=true`), Tonal expects total reps (both sides). If you want 8 reps per side, send `prescribedReps: 16`
- `blockNumber` groups exercises into supersets. Exercises with the same `blockNumber` are performed back-to-back
- `setGroup` identifies the exercise within a block (1-indexed)
- `round` / `repetition` track which round of the superset this set belongs to
- `repetitionTotal` is the total number of rounds for this exercise
- `blockStart: true` on the first set of each block
- Tonal rejects `null` for optional fields — omit them entirely or send valid values
- `weightPercentage: 100` means use the user's working weight. Use lower values (e.g., 50-60) for warm-ups

### Estimate Workout Duration
```
POST /v6/user-workouts/estimate
Content-Type: application/json

{"sets": [ ... same format as create ... ]}
```

**Response:** `{"duration": 45}` (minutes)

### Delete Custom Workout
```
DELETE /v6/user-workouts/{workoutId}
```

**Response:** 204 No Content

---

## Other Endpoints

### External Activities
```
GET /v6/users/{userId}/external-activities?limit=10
```
Returns activities from connected devices (Apple Watch, etc.). May be empty if no external integrations.

### Achievements
```
GET /v6/users/{userId}/achievements
```
Returns earned badges and milestones with names, descriptions, and dates.

### Training Types
```
GET /v6/training-types
```
Returns the list of training type categories (Strength, Yoga, etc.).

### Explore Workouts
```
GET /v6/explore/workouts
```
Returns the public Tonal workout library grouped by category. Large response (~100KB).

---

## Rate Limits & Best Practices

- No documented rate limits, but be respectful. The tonal-coach project uses these timeouts:
  - GET: 15 seconds
  - POST: 30 seconds
- Cache the movement catalog locally (it changes rarely — refresh daily at most)
- JWT tokens expire in ~10 hours. Use refresh tokens proactively
- On 401 responses, refresh the token and retry once before failing
- The formatted summary endpoint (`/v6/formatted/...`) is more expensive — use it for detailed reports, not bulk fetches
- Batch workout detail fetches with delays (2+ seconds between requests) when processing history

## Error Handling

- **401**: Token expired. Refresh and retry.
- **404**: Resource not found (invalid userId, activityId, or workoutId).
- **400**: Bad request (invalid workout structure, missing required fields).
- **204**: Success with no body (DELETE operations).
- **5xx**: Tonal API is having issues. Retry with backoff.
