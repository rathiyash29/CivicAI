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
  "ai_provider": "mock | gemini",
  "duplicate": {
    "success": true,
    "is_duplicate": "boolean",
    "similar_complaints": "array",
    "duplicate_count": "number"
  }
}
```

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
  "ai_provider": "mock | gemini",
  "duplicate": { ... }
}
```

**Behavior:**
- When authenticated: Complaint is stored in database, associated with user, and full analysis/priority/duplicate data returned
- When unauthenticated: Complaint is processed but not stored, legacy response format returned

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
      "created_at": "2026-01-15T10:30:00Z"
    }
  ],
  "total": 1
}
```

**Error Responses:**
- 401: Could not validate credentials

**Ownership:** Each citizen can only access their own complaints. The endpoint filters by the authenticated user's ID.

**Owner:** Member 1 (citizen complaint tracking)

---

### POST /complaints/analyze

**Purpose:** Analyze a complaint using the configured AI provider (mock or Gemini).

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
  "ai_provider": "mock | gemini"
}
```

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
  "ai_provider": "mock | gemini"
}
```

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
5. `JWT_SECRET_KEY` must be a secure random string (generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`)

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