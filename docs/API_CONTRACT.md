# CivicAI API Contract

This document defines the current backend API endpoints, response schemas, and team ownership for integration between three team members.

---

## API Endpoints

### GET /

**Purpose:** Root endpoint to verify the backend is running.

**Method:** GET

**URL:** `/`

**Request:** None

**Response:**
```json
{
  "message": "CivicAI backend is running!",
  "status": "success"
}
```

**Owner:** All members (health check)

---

### GET /health

**Purpose:** Health check endpoint for monitoring and load balancers.

**Method:** GET

**URL:** `/health`

**Request:** None

**Response:**
```json
{
  "status": "healthy"
}
```

**Owner:** All members (monitoring)

---

### POST /auth/register

**Purpose:** Register a new citizen user.

**Method:** POST

**URL:** `/auth/register`

**Request:**
```json
{
  "full_name": "string (1-100 chars)",
  "email": "string (valid email format)",
  "password": "string (min 8 chars, max 100 chars)",
  "role": "citizen | officer (optional, default: citizen)"
}
```

**Response (201 Created):**
```json
{
  "id": 1,
  "full_name": "string",
  "email": "string",
  "role": "citizen",
  "created_at": "2026-01-15T10:30:00Z"
}
```

**Error Responses:**
- 400: Email already registered

**Owner:** Member 1 (citizen authentication)

---

### POST /auth/login

**Purpose:** Login and obtain JWT access token.

**Method:** POST

**URL:** `/auth/login`

**Request:**
```json
{
  "email": "string (valid email format)",
  "password": "string"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Error Responses:**
- 401: Incorrect email or password

**Owner:** Member 1 (citizen authentication)

---

### GET /auth/me

**Purpose:** Get current authenticated user info.

**Method:** GET

**URL:** `/auth/me`

**Headers:**
```
Authorization: Bearer <access_token>
```

**Response:**
```json
{
  "id": 1,
  "full_name": "string",
  "email": "string",
  "role": "citizen",
  "created_at": "2026-01-15T10:30:00Z"
}
```

**Error Responses:**
- 401: Could not validate credentials

**Owner:** Member 1 (citizen authentication)

---

### POST /complaints

**Purpose:** Submit a new citizen complaint. If authenticated, the complaint is stored with analysis, priority, and duplicate detection results, and associated with the user.

**Method:** POST

**URL:** `/complaints`

**Request:**
```json
{
  "text": "string (min 10 chars)",
  "language": "English | Hindi | Marathi",
  "location": "string (min 1 char)"
}
```

**Headers (Optional - for authenticated submission):**
```
Authorization: Bearer <access_token>
```

**Response (Authenticated - 200 OK):**
```json
{
  "success": true,
  "complaint": {
    "complaint_id": "CA-000001",
    "user_id": 1,
    "text": "string",
    "language": "string",
    "location": "string",
    "category": "string",
    "severity": "Low | Medium | High",
    "priority_score": "number",
    "priority_level": "Low | Medium | High",
    "status": "Submitted",
    "created_at": "2026-01-15T10:30:00Z"
  },
  "analysis": {
    "language": "string",
    "category": "string",
    "location": "string",
    "severity": "Low | Medium | High",
    "urgency": "Low | Medium | High",
    "affected_group": "string",
    "issue_summary": "string",
    "recommended_action": "string"
  },
  "priority": {
    "priority_score": "number",
    "priority_level": "Low | Medium | High",
    "factors": {
      "citizen_demand": "number",
      "infrastructure_gap": "number",
      "population_impact": "number",
      "urgency": "number",
      "investment_gap": "number"
    }
  },
  "ai_provider": "gemini | mock",
  "fallback_reason": "quota_exhausted | api_error | invalid_response | not_configured | unexpected_error | null",
  "duplicate": {
    "success": true,
    "is_duplicate": "boolean",
    "similar_complaints": "array",
    "duplicate_count": "number"
  }
}
```

**`ai_provider` reports the provider that ACTUALLY ran, not the configured one.**

`AI_PROVIDER` in the environment is only a *preference*. When Gemini is
unavailable the backend falls back to its offline keyword engine, and this
field reports `"mock"` in that case. It is deliberately not the configured
value, because reporting the preference would claim real AI that never
executed and leave a client with no way to tell the difference.

**`fallback_reason` is populated only when a fallback occurred**; it is `null`
when Gemini answered normally. The values are a fixed, coarse vocabulary:

| Value | Meaning |
|-------|---------|
| `quota_exhausted` | The provider's quota was exhausted (HTTP 429). On the free tier this is a *daily* per-project allowance, so it is not retried. |
| `api_error` | Any other provider-side failure: authentication, permission, a rejected request, a network error. |
| `invalid_response` | The provider answered, but the payload was empty, not JSON, not an object, or missing a required field. |
| `not_configured` | The Gemini provider was selected but no API key was available. |
| `unexpected_error` | A failure outside the provider call itself, e.g. a programming fault. |

These codes are safe to return over HTTP. The raw vendor error message, the
provider's project identifiers and the API key are **never** included in any
response; they are logged server-side only.

**Response (Unauthenticated - 200 OK):**
```json
{
  "success": true,
  "complaint": {
    "text": "string",
    "language": "string",
    "location": "string",
    "status": "received"
  },
  "analysis": { ... },
  "priority": { ... },
  "ai_provider": "gemini | mock",
  "fallback_reason": "string | null",
  "duplicate": { ... }
}
```

**Behavior:**
- When authenticated: Complaint is stored in database, associated with user, and full analysis/priority/duplicate data returned
- When unauthenticated: Complaint is processed but not stored, legacy response format returned
- `ai_provider` and `fallback_reason` follow the same rules on both paths, as described above

**Owner:** Member 1 (citizen complaint flow)

---

### GET /complaints/my

**Purpose:** Get all complaints submitted by the authenticated citizen.

**Method:** GET

**URL:** `/complaints/my`

**Headers:**
```
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "success": true,
  "complaints": [
    {
      "complaint_id": "CA-000001",
      "user_id": 1,
      "text": "string",
      "language": "string",
      "location": "string",
      "category": "string",
      "severity": "Low | Medium | High",
      "priority_score": "number",
      "priority_level": "Low | Medium | High",
      "status": "Submitted",
      "created_at": "2026-01-15T10:30:00Z",
      "cluster_id": 12,
      "analysis_urgency": "Low | Medium | High | null",
      "analysis_affected_group": "string | null",
      "analysis_issue_summary": "string | null",
      "analysis_recommended_action": "string | null"
    }
  ],
  "total": 1
}
```

**The five `analysis_*` and `cluster_id` fields are additive.** The original
eleven fields are unchanged in name and type, so the existing citizen frontend
keeps working against this same shape.

They are read from columns the complaint row already had. The `analysis_*`
fields are what the AI layer wrote at submission time and are the officer's
answer to "what did the system understand this to be about". `cluster_id` is the
issue cluster the complaint was grouped into, which is the join from one
complaint to the hotspot and recommendation built from it.

Every one of them is **nullable, and null means exactly that**: a complaint
created before these were written, or through a path that skipped analysis, has
no value. Nothing is derived, inferred or back-filled, so a null here means
"not recorded" rather than "not applicable".

**Error Responses:**
- 401: Could not validate credentials

**Ownership:** Each citizen can only access their own complaints. The endpoint filters by the authenticated user's ID.

**Owner:** Member 1 (citizen complaint tracking)

---

### POST /complaints/analyze

**Purpose:** Analyze a complaint, reporting the provider that actually answered.

**Method:** POST

**URL:** `/complaints/analyze`

**Request:**
```json
{
  "text": "string (min 10 chars)",
  "language": "English | Hindi | Marathi",
  "location": "string (min 1 char)"
}
```

**Response:**
```json
{
  "success": true,
  "analysis": {
    "language": "string",
    "category": "string",
    "location": "string",
    "severity": "Low | Medium | High",
    "urgency": "Low | Medium | High",
    "affected_group": "string",
    "issue_summary": "string",
    "recommended_action": "string"
  },
  "ai_provider": "gemini | mock",
  "fallback_reason": "string | null"
}
```

`ai_provider` keeps its original name but is now the provider that **actually
ran**, not the `AI_PROVIDER` preference the process was configured with — a
deployment configured for Gemini that fell back reports `"mock"`. A successful
Gemini call reports `"gemini"` with `fallback_reason` `null`; a mock fallback
reports `"mock"` with the reason it fell back.

`ai_provider` and `fallback_reason` are top-level fields here, as on
`POST /complaints`. `analysis` also carries `provider_used` and, when a
fallback occurred, `fallback_reason`; those are additive and every field listed
above keeps its existing name and type.

**Owner:** Member 1 (AI analysis)

---

### POST /complaints/analyze-and-prioritize

**Purpose:** Analyze a complaint and calculate its development priority in one call.

**Method:** POST

**URL:** `/complaints/analyze-and-prioritize`

**Request:**
```json
{
  "text": "string (min 10 chars)",
  "language": "English | Hindi | Marathi",
  "location": "string (min 1 char)"
}
```

**Response:**
```json
{
  "success": true,
  "analysis": {
    "language": "string",
    "category": "string",
    "location": "string",
    "severity": "Low | Medium | High",
    "urgency": "Low | Medium | High",
    "affected_group": "string",
    "issue_summary": "string",
    "recommended_action": "string"
  },
  "priority": {
    "priority_score": "number",
    "priority_level": "Low | Medium | High",
    "factors": {
      "citizen_demand": "number",
      "infrastructure_gap": "number",
      "population_impact": "number",
      "urgency": "number",
      "investment_gap": "number"
    }
  },
  "ai_provider": "gemini | mock",
  "fallback_reason": "string | null"
}
```

`ai_provider` and `fallback_reason` follow the same rules as on
`POST /complaints`. `analysis` also carries `provider_used` and, when a
fallback occurred, `fallback_reason`.

**Owner:** Member 1 (analysis), Member 2 (priority calculation)

---

### POST /complaints/priority

**Purpose:** Calculate development priority from explicit factor scores.

**Method:** POST

**URL:** `/complaints/priority`

**Request:**
```json
{
  "citizen_demand": "number (0-100)",
  "infrastructure_gap": "number (0-100)",
  "population_impact": "number (0-100)",
  "urgency": "number (0-100)",
  "investment_gap": "number (0-100)"
}
```

**Response:**
```json
{
  "success": true,
  "priority": {
    "priority_score": "number",
    "priority_level": "Low | Medium | High",
    "factors": {
      "citizen_demand": "number",
      "infrastructure_gap": "number",
      "population_impact": "number",
      "urgency": "number",
      "investment_gap": "number"
    }
  }
}
```

**Owner:** Member 2 (priority engine)

---

### POST /complaints/check-duplicate

**Purpose:** Check if a complaint is a duplicate of existing complaints.

**Method:** POST

**URL:** `/complaints/check-duplicate`

**Request:**
```json
{
  "text": "string (min 10 chars)",
  "location": "string (optional)"
}
```

**Response:**
```json
{
  "success": true,
  "is_duplicate": "boolean",
  "similar_complaints": "array",
  "duplicate_count": "number"
}
```

**Owner:** Member 2 (duplicate detection)

---

### GET /hotspots

**Purpose:** Retrieve detected complaint hotspots for map visualization.

**Method:** GET

**URL:** `/hotspots`

**Request:** None

**Response:**
```json
{
  "success": true,
  "hotspots": [
    {
      "location": "string",
      "count": "number",
      "category": "string",
      "severity_distribution": "object"
    }
  ]
}
```

**Owner:** Member 2 (hotspot engine), Member 3 (map visualization)

---

## Member 1 AI Output Schema

The AI analysis response (used by `/complaints/analyze` and `/complaints/analyze-and-prioritize`) follows this exact structure:

```json
{
  "language": "English | Hindi | Marathi",
  "category": "Road Infrastructure | Water Supply | Electricity | Sanitation | Public Transport | Healthcare | Education | Other",
  "location": "string",
  "severity": "Low | Medium | High",
  "urgency": "Low | Medium | High",
  "affected_group": "string",
  "issue_summary": "string",
  "recommended_action": "string"
}
```

**Field Definitions:**

| Field | Type | Description |
|-------|------|-------------|
| language | string | Input language of the complaint |
| category | string | One of 8 predefined categories |
| location | string | Original location string from request |
| severity | enum | Impact severity: Low, Medium, High |
| urgency | enum | Time sensitivity: Low, Medium, High |
| affected_group | string | Identified affected population group |
| issue_summary | string | One-sentence summary of the issue |
| recommended_action | string | Suggested remediation action |

---

## AI Provider Configuration

### Current Configuration

```env
AI_PROVIDER=mock
```

### Provider Behavior

| Provider | Status | Description |
|----------|--------|-------------|
| `mock` | **Active (Default)** | Keyword-based analysis using predefined dictionaries. Works offline, no API keys required. Default provider. |
| `gemini` | **Implemented & Tested** | Google Gemini AI via `google-genai` SDK. Requires `GEMINI_API_KEY` and accessible Google AI project. Default model: `gemini-3-flash-preview`. Automatically falls back to mock on configuration errors, 403/401/429, network issues, or invalid JSON responses. **Successfully tested with current Free Tier project and API key.** |

### Security Rules

1. **Never commit `.env` or API keys to Git**
2. `.env.example` contains only placeholders:
   ```env
   AI_PROVIDER=mock
   # GEMINI_API_KEY=your_api_key_here
   # GEMINI_MODEL=gemini-3-flash-preview
   JWT_SECRET_KEY=your_jwt_secret_key_here_change_in_production
   ```
3. Each developer creates their own `.env` locally
4. `GEMINI_API_KEY` is only needed when `AI_PROVIDER=gemini`
5. `JWT_SECRET_KEY` must be a secure random string (generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`). When unset, `backend/auth.py` signs tokens with a random per-process key and warns that they will not survive a restart.

### Switching Providers

```bash
# Use mock (default, works offline)
AI_PROVIDER=mock

# Use Gemini (requires valid API key and accessible project)
AI_PROVIDER=gemini
GEMINI_API_KEY=your_actual_key
# Optional: GEMINI_MODEL=gemini-3-flash-preview
```

### Known Limitations

- **Gemini 403 PERMISSION_DENIED**: Some Google AI projects may not have Generative Language API access enabled. If you encounter 403, the system will automatically fall back to the mock provider and log a warning. Ensure your Google Cloud project has the "Generative Language API" enabled and billing configured if required.
- **API Key Security**: The API key is never logged, exposed in responses, or included in error messages.
- **Fallback Behavior**: On any Gemini failure (missing key, auth error, quota, network, JSON parsing), the mock analyzer is used transparently.

---

## OFFICER INTELLIGENCE ENDPOINTS

Everything in this section lives under `/intelligence` and is **officer-only**:
401 without a usable token, 403 for a citizen. These are the endpoints the
government dashboard reads, and between them they cover the pipeline
complaint → analysis → cluster → hotspot → recommendation.

### GET /intelligence/clusters/{cluster_id}

**Purpose:** One issue cluster, with the ids of the complaints grouped into it.
The head of the case file the government dashboard shows at
`/dashboard/case/:cluster_id`.

**Method:** GET

**URL:** `/intelligence/clusters/{cluster_id}`

**Response (200 OK):**
```json
{
  "cluster_id": 1,
  "label": "Road Infrastructure - Kothrud #1",
  "category": "Road Infrastructure",
  "ward": "Kothrud",
  "complaint_count": 12,
  "complaint_ids": [8, 10, 11, 14, 15, 16, 18, 20, 22, 32, 34, 36],
  "created_at": "2026-09-27T19:15:15.382925"
}
```

**This is a strict read.** It returns the cluster's own columns untouched and
lists member ids with an ordered select. No clustering, scoring or
recommendation is run here, so opening a case file cannot change any number in
it.

**Why it exists.** A cluster's `category` and `ward` are plain string columns
with no foreign key, so they were reachable from nowhere else: a hotspot lists
cluster *ids* but not their category, and a recommendation carries the ward but
not the category. A client without this endpoint would have had to infer the
category from the recommended action text — a guess presented as fact.

`complaint_count` is counted from the complaint rows rather than read from
`IssueCluster.complaint_count`. That column is a cache maintained by the
clustering code, so trusting it would let the case header disagree with the
complaints listed beneath it. `ward` is the literal `"Unassigned"` when the
complaints never resolved to a known ward, which is a real answer rather than a
gap.

**Error Responses:**
- 401 / 403: not an officer
- 404: no cluster with that id

---

### GET /intelligence/stats

Row counts per table, plus derived counts for the stages that have no table of
their own. Used by the Overview pipeline.

**Response (200 OK):**
```json
{
  "locations": 10,
  "complaints": 15,
  "scored_complaints": 15,
  "issue_clusters": 11,
  "infrastructure": 60,
  "demographics": 10,
  "investments": 180,
  "recommendations": 9,

  "analysed_complaints": 15,
  "hotspots": 1,
  "projects": 3,
  "completed_projects": 2,
  "measured_impact": 1
}
```

The first eight keys are per-table counts and are unchanged. The rest are:

| Key | What it counts |
|-----|----------------|
| `analysed_complaints` | Complaints with a non-null `issue_summary`, i.e. ones the AI layer actually wrote a reading for. Counting the column is the honest test; counting every complaint would report the stage complete when it never ran. |
| `hotspots` | `db_hotspots.compute_hotspots` at `DEFAULT_MIN_COMPLAINTS`, so this and the Hotspots page cannot disagree. |
| `projects` / `completed_projects` | Rows in `projects`, and those in `Completed` status. |
| `measured_impact` | Rows in `project_impacts`. |

**These are not cumulative.** A cluster groups complaints, it does not consume
them, so `issue_clusters` may exceed or fall below any count beside it.

---

### GET /intelligence/priority/{complaint_id}/explanation

**Purpose:** The five weighted factors behind a complaint's stored priority
score, plus the evidence used to derive them. Backs "Why this score?" in the
officer's complaint detail view.

**Method:** GET

**URL:** `/intelligence/priority/{complaint_id}/explanation`

`complaint_id` accepts the public `CA-000042` form, a bare integer, or both. The
`CA-MEM-` form is refused with 404: an in-memory complaint has no database row to
explain.

**Response (200 OK):**
```json
{
  "complaint_id": 42,
  "stored_score": 72.4,
  "stored_level": "High",
  "current_score": 72.4,
  "factors": {
    "citizen_demand": 71.0,
    "infrastructure_gap": 80.0,
    "population_impact": 65.0,
    "urgency": 90.0,
    "investment_gap": 40.0
  },
  "weights": {
    "citizen_demand": 0.30,
    "infrastructure_gap": 0.25,
    "population_impact": 0.20,
    "urgency": 0.15,
    "investment_gap": 0.10
  },
  "evidence": {
    "citizen_demand_basis": "cluster",
    "complaints_in_demand_group": 6,
    "infrastructure_gap_source": "database",
    "investment_gap_source": "database",
    "population_impact_source": "database"
  }
}
```

**This endpoint is a read and changes nothing.** It calls the same
`db_priority.compute_factors` that `compute_priority` weights, and it does not
write, rescore or otherwise modify the complaint. Looking at a complaint's score
does not move that score.

`factors` and `weights` are read straight from `db_priority`, so this cannot
drift from the algorithm. **`*_source` is `"database"` when the value came from a
real ward row and `"default"` when no location resolved**, in which case the
engine used a neutral constant: honest, but weaker evidence, and labelled as
such.

`stored_score` is the score on the complaint row, which is the one the dashboard
displays. `current_score` is what the same factors would produce now; they are
equal unless the underlying data moved since the complaint was scored. An
unscored complaint reports `stored_score: null` and still gets a `current_score`,
but no score is written by asking.

**Error Responses:**
- 401 / 403: not an officer
- 404: no such complaint, or an id this endpoint cannot resolve

---

### GET /intelligence/recommendations/{cluster_id}

**Purpose:** The single recommendation generated from one issue cluster, the same
object as one entry of the list endpoint.

**Response:** identical to one element of `GET /intelligence/recommendations`.

**Error Responses:**
- 404: no such cluster, or the cluster has no complaints and so no recommendation

Note that this route reads the cluster and **upserts** its `Recommendation` row
through `generate_recommendation`, exactly as the list endpoint does for every
cluster. That is pre-existing behaviour of the recommendations routes, not new
here, and it is why the case file treats `recommendation` as "what the engine
currently holds" rather than as a frozen historical record.

---

### GET /intelligence/recommendations

**Response (200 OK):**
```json
{
  "recommendations": [
    {
      "recommendation_id": 4,
      "cluster_id": 1,
      "location": "Kothrud",
      "action": "string",
      "reason": "string",
      "evidence": {
        "related_complaints": 12,
        "high_severity_complaints": 5,
        "infrastructure_gap": "High",
        "population_impact": "High",
        "investment_gap": "Medium"
      },
      "priority_score": 80.0,
      "priority_level": "High",
      "estimated_affected_population": 17700
    }
  ]
}
```

**`recommendation_id` is additive and is the row's own primary key** — the value
the officer decision endpoints are called with
(`/projects/recommendations/{recommendation_id}/approve`). It was previously
absent, so a client could read a recommendation's evidence and then have no id to
decide on.

**`cluster_id` is unchanged and is a different thing:** the issue cluster the
recommendation was generated from, and the key `cluster_ids[]` on a hotspot
already carries. They are not interchangeable, and using one where the other
belongs would act on the wrong row.

`evidence` values are band labels ("High" / "Medium" / "Low"); the underlying
factor numbers for a *recommendation* are not serialised. The raw numbers are
available per complaint via the explanation endpoint above.

**Owner:** Member 2 (analytics engine), Member 3 (dashboard)

---

## PROJECT AND IMPACT ENDPOINTS

Officer-only, and mounted at the **root** (no prefix), because the router
declares these paths itself.

### GET /impact

**Purpose:** Every recorded impact measurement, so a client can tell a measured
project from one still awaiting measurement in a single request.

**Response (200 OK):**
```json
{
  "impacts": [ { "id": 1, "project_id": 2, "observed_change": { "...": "..." } } ],
  "measured_project_ids": [2]
}
```

`impacts` holds the same objects as `GET /projects/{project_id}/impact`, newest
first. `measured_project_ids` is the same set projected onto project ids.

**Only completed projects are included,** matching the state an impact record is
legal in; the backend refuses to record one for any other status. A project
absent from `measured_project_ids` genuinely has no record — that is the only
condition under which "awaiting measurement" is accurate, and it is why
`GET /impact` exists rather than treating every unqueried project as unmeasured.

**Error Responses:**
- 401 / 403: not an officer

---

## TEAM OWNERSHIP

### Member 1 — Citizen + Multilingual AI + Authentication
- `frontend/citizen/` — Citizen-facing web application
- `backend/ai.py` — AI analysis module (mock + Gemini placeholder)
- `backend/auth.py` — Authentication module (JWT, password hashing, user management)
- Citizen complaint submission flow
- Multilingual input (English, Hindi, Marathi)
- Voice input integration
- Citizen signup, login, and session management

### Member 2 — Data + Analytics Engine
- `data/` — Data storage and processing
- `backend/priority.py` — Priority calculation engine
- `backend/duplicates.py` — Duplicate detection
- `backend/hotspots.py` — Hotspot detection
- Database and analytics
- Development recommendations

### Member 3 — Government Dashboard
- `frontend/dashboard/` — Officer/government dashboard
- Maps integration (Google Maps / Leaflet)
- Government dashboard UI
- Officer workflow and case management

---

## IMPORTANT INTEGRATION RULES

1. **Do not delete or rewrite another member's module without coordination.**
   - Discuss changes in shared modules before implementing.

2. **Use the documented API contracts.**
   - Request/response formats defined here are the contract.
   - Changes require communication with affected members.

3. **Keep API response field names stable.**
   - Do not rename fields (e.g., `priority_score` → `score`).
   - Add new fields only; never remove or rename existing ones.

4. **Never commit `.env` or API keys.**
   - `.env` is in `.gitignore`.
   - Use `.env.example` for placeholder documentation only.

5. **All three modules must eventually run as one CivicAI application.**
   - Frontend (citizen + dashboard) + Backend (AI + priority + duplicates + hotspots)
   - Shared database layer (to be integrated)
   - Single deployment target

---

## Version

API Contract v1.0 — Generated for CivicAI Hackathon Team Integration