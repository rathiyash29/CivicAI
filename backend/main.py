from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import timedelta, datetime
from enum import Enum
import logging
import os as _os
import sys as _sys

# --- startup compatibility -------------------------------------------------
# This module is started two ways: `uvicorn main:app` from inside backend/ and
# `uvicorn backend.main:app` from the repo root. The first needs backend/ on
# sys.path, the second needs the repo root (Member 2's modules import
# `database.*` and `backend.*`). Put the repo root on the path unconditionally
# so package-style imports below resolve either way, and load backend/.env
# explicitly so DATABASE_URL / GEMINI_API_KEY are found regardless of cwd.
_REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_os.path.join(_REPO_ROOT, "backend", ".env"))
    _load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("main")

from backend.ai import analyze_complaint, AI_PROVIDER
from backend.priority import calculate_priority, determine_factors_from_analysis
from backend.duplicates import check_duplicate, find_similarity, are_duplicates
from backend.hotspots import detect_hotspots
from backend.auth import (
    UserCreate, UserLogin, UserResponse, Token, TokenData,
    create_user, authenticate_user,
    create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES,
    UserRole
)
from backend import complaint_service
from backend.authorization import (
    get_current_user, get_current_user_optional, require_officer,
    oauth2_scheme,
)


class ComplaintStatus(str, Enum):
    SUBMITTED = "Submitted"
    UNDER_REVIEW = "Under Review"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"
    REJECTED = "Rejected"


class Complaint(BaseModel):
    complaint_id: str
    user_id: int
    text: str
    language: str
    location: str
    category: Optional[str] = None
    severity: Optional[str] = None
    priority_score: Optional[float] = None
    priority_level: Optional[str] = None
    status: str = ComplaintStatus.SUBMITTED
    created_at: datetime


MOCK_COMPLAINTS_DB: dict[str, Complaint] = {}
COMPLAINT_ID_COUNTER = 0


def generate_complaint_id() -> str:
    """
    Public id for a complaint that only exists in the in-memory fallback.

    Deliberately *not* `CA-%06d`. The database issues `CA-%06d` from its own
    primary key, and that key is not reset when the process restarts, so a
    local counter starting at 1 would hand out CA-000001 for a second, entirely
    different complaint. The `CA-MEM-` prefix keeps the two namespaces apart
    while staying an ordinary opaque string for the frontend.
    """
    global COMPLAINT_ID_COUNTER
    COMPLAINT_ID_COUNTER += 1
    return complaint_service.format_memory_complaint_id(COMPLAINT_ID_COUNTER)


def create_complaint(
    user_id: int,
    text: str,
    language: str,
    location: str,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    priority_score: Optional[float] = None,
    priority_level: Optional[str] = None,
) -> Complaint:
    """
    In-memory complaint store.

    PostgreSQL is the system of record; this dict is only the degraded-mode
    fallback used when the database cannot be reached. See
    backend/complaint_service.py.
    """
    complaint_id = generate_complaint_id()
    now = datetime.utcnow()
    complaint = Complaint(
        complaint_id=complaint_id,
        user_id=user_id,
        text=text,
        language=language,
        location=location,
        category=category,
        severity=severity,
        priority_score=priority_score,
        priority_level=priority_level,
        status=ComplaintStatus.SUBMITTED,
        created_at=now,
    )
    MOCK_COMPLAINTS_DB[complaint_id] = complaint
    return complaint


def complaint_to_contract_dict(complaint: Complaint) -> dict:
    return {
        "complaint_id": complaint.complaint_id,
        "user_id": complaint.user_id,
        "text": complaint.text,
        "language": complaint.language,
        "location": complaint.location,
        "category": complaint.category,
        "severity": complaint.severity,
        "priority_score": complaint.priority_score,
        "priority_level": complaint.priority_level,
        "status": complaint.status,
        "created_at": complaint.created_at,
    }


def get_user_complaints(user_id: int) -> list[Complaint]:
    return [c for c in MOCK_COMPLAINTS_DB.values() if c.user_id == user_id]


def get_complaint_by_id(complaint_id: str) -> Optional[Complaint]:
    return MOCK_COMPLAINTS_DB.get(complaint_id)


app = FastAPI(
    title="CivicAI",
    description="AI-powered citizen feedback and development intelligence platform",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# `get_current_user`, `get_current_user_optional`, `require_officer` and
# `oauth2_scheme` are imported from backend.authorization (see the import block
# at the top of this file). They live there, not here, so that the intelligence
# router can require an officer without importing this module -- importing
# main from router would be circular.


class ComplaintSubmitRequest(BaseModel):
    text: str = Field(..., min_length=10, description="Complaint description")
    language: Literal["English", "Hindi", "Marathi"]
    location: str = Field(..., min_length=1, description="Location of the issue")


class ComplaintSubmitResponse(BaseModel):
    success: bool
    complaint: dict
    analysis: Optional[dict] = None
    priority: Optional[dict] = None
    ai_provider: Optional[str] = None
    duplicate: Optional[dict] = None
    # Additive: "postgres" | "memory". Makes the storage mode explicit so a
    # fallback can never be mistaken for a successful write.
    persistence: Optional[str] = None


class AnalysisRequest(BaseModel):
    text: str = Field(..., min_length=10, description="Complaint description")
    language: Literal["English", "Hindi", "Marathi"]
    location: str = Field(..., min_length=1, description="Location of the issue")


class AnalysisResponse(BaseModel):
    success: bool
    analysis: dict
    ai_provider: str


class PriorityRequest(BaseModel):
    citizen_demand: float = Field(..., ge=0, le=100, description="Citizen demand score (0-100)")
    infrastructure_gap: float = Field(..., ge=0, le=100, description="Infrastructure gap score (0-100)")
    population_impact: float = Field(..., ge=0, le=100, description="Population impact score (0-100)")
    urgency: float = Field(..., ge=0, le=100, description="Urgency score (0-100)")
    investment_gap: float = Field(..., ge=0, le=100, description="Investment gap score (0-100)")


class PriorityResponse(BaseModel):
    success: bool
    priority: dict


class AnalyzeAndPrioritizeRequest(BaseModel):
    text: str = Field(..., min_length=10, description="Complaint description")
    language: Literal["English", "Hindi", "Marathi"]
    location: str = Field(..., min_length=1, description="Location of the issue")


class AnalyzeAndPrioritizeResponse(BaseModel):
    success: bool
    analysis: dict
    priority: dict
    ai_provider: str


class DuplicateCheckRequest(BaseModel):
    text: str = Field(..., min_length=10, description="Complaint description to check")
    location: str = Field(default="", description="Location of the issue (optional)")


class DuplicateCheckResponse(BaseModel):
    success: bool
    is_duplicate: bool
    similar_complaints: list
    duplicate_count: int


class HotspotResponse(BaseModel):
    success: bool
    hotspots: list


@app.get("/")
def root():
    return {
        "message": "CivicAI backend is running!",
        "status": "success"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.get("/hotspots", response_model=HotspotResponse)
def get_hotspots():
    hotspots = detect_hotspots()
    return {
        "success": True,
        "hotspots": hotspots
    }


class MyComplaintsResponse(BaseModel):
    success: bool
    complaints: list
    total: int


@app.post("/complaints", response_model=ComplaintSubmitResponse)
async def submit_complaint(
    complaint: ComplaintSubmitRequest,
    current_user: Optional[UserResponse] = Depends(get_current_user_optional)
):
    """
    Submit a complaint. If authenticated, associate with user and perform analysis.
    If not authenticated, just return the complaint data (legacy behavior).
    """
    analysis = analyze_complaint(complaint.text, complaint.language, complaint.location)

    if not current_user:
        # Unauthenticated submissions are processed but not stored. This is the
        # pre-existing contract and is deliberately unchanged.
        factors = determine_factors_from_analysis(analysis)
        priority = calculate_priority(
            factors["citizen_demand"],
            factors["infrastructure_gap"],
            factors["population_impact"],
            factors["urgency"],
            factors["investment_gap"],
        )
        duplicate_result = check_duplicate(complaint.text, complaint.location)
        return {
            "success": True,
            "complaint": {
                "text": complaint.text,
                "language": complaint.language,
                "location": complaint.location,
                "status": "received"
            },
            "analysis": analysis,
            "priority": priority,
            "ai_provider": AI_PROVIDER,
            "duplicate": duplicate_result,
            "persistence": None,
        }

    # Authenticated: persist to PostgreSQL (system of record) and run the
    # intelligence pipeline in the same transaction.
    stored = complaint_service.persist_complaint(
        text_value=complaint.text,
        language=complaint.language,
        raw_location=complaint.location,
        analysis=analysis,
        user=current_user,
    )

    if stored["persistence"] == complaint_service.PERSISTENCE_POSTGRES:
        return {
            "success": True,
            "complaint": stored["complaint"],
            "analysis": analysis,
            "priority": stored["priority"],
            "ai_provider": AI_PROVIDER,
            "duplicate": stored["duplicate"],
            "persistence": complaint_service.PERSISTENCE_POSTGRES,
        }

    # Database unavailable: fall back to the in-memory store, keeping the
    # original mock scoring and telling the caller this was not persisted.
    logger.warning("Complaint accepted but NOT persisted to PostgreSQL: %s",
                   stored.get("fallback_reason"))
    fallback = create_complaint(
        user_id=current_user.id,
        text=complaint.text,
        language=complaint.language,
        location=complaint.location,
        category=analysis.get("category"),
        severity=analysis.get("severity"),
    )
    factors = determine_factors_from_analysis(analysis)
    priority = calculate_priority(
        factors["citizen_demand"],
        factors["infrastructure_gap"],
        factors["population_impact"],
        factors["urgency"],
        factors["investment_gap"],
    )
    fallback.priority_score = priority["priority_score"]
    fallback.priority_level = priority["priority_level"]

    return {
        "success": True,
        "complaint": complaint_to_contract_dict(fallback),
        "analysis": analysis,
        "priority": priority,
        "ai_provider": AI_PROVIDER,
        "duplicate": check_duplicate(complaint.text, complaint.location),
        "persistence": complaint_service.PERSISTENCE_MEMORY,
    }


@app.get("/complaints/my", response_model=MyComplaintsResponse)
def get_my_complaints(current_user: UserResponse = Depends(get_current_user)):
    """
    Complaints submitted by the authenticated citizen.
    Requires a valid JWT. Served from PostgreSQL when it is available, and
    from the in-memory fallback store otherwise.
    """
    rows = complaint_service.list_user_complaints(current_user)
    if rows is not None:
        return {"success": True, "complaints": rows, "total": len(rows)}

    # PostgreSQL could not be queried. The in-memory fallback store is
    # authoritative for complaints that never reached the database, so serve
    # those if there are any.
    logger.warning("Serving /complaints/my from the in-memory fallback store; "
                   "PostgreSQL is unavailable")
    complaints = get_user_complaints(current_user.id)
    if complaints:
        # Sort by created_at descending (newest first)
        complaints.sort(key=lambda c: c.created_at, reverse=True)
        return {
            "success": True,
            "complaints": [complaint_to_contract_dict(c) for c in complaints],
            "total": len(complaints),
        }

    # Neither store can answer. An empty list here would read as "you have no
    # complaints" when the truth is "we could not check", so say so instead of
    # returning a confident, wrong answer.
    logger.error("PostgreSQL is unavailable and the in-memory store has nothing "
                 "for user %s; returning 503 rather than a false empty list",
                 current_user.email)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=("Complaint storage is temporarily unavailable, so your complaints "
                "could not be retrieved. Please try again shortly."),
    )


@app.post("/complaints/analyze", response_model=AnalysisResponse)
def analyze_complaint_endpoint(request: AnalysisRequest):
    analysis = analyze_complaint(request.text, request.language, request.location)
    return {
        "success": True,
        "analysis": analysis,
        "ai_provider": AI_PROVIDER
    }


@app.post("/complaints/priority", response_model=PriorityResponse)
def calculate_priority_endpoint(request: PriorityRequest):
    priority = calculate_priority(
        request.citizen_demand,
        request.infrastructure_gap,
        request.population_impact,
        request.urgency,
        request.investment_gap,
    )
    return {
        "success": True,
        "priority": priority
    }


@app.post("/complaints/analyze-and-prioritize", response_model=AnalyzeAndPrioritizeResponse)
def analyze_and_prioritize_endpoint(request: AnalyzeAndPrioritizeRequest):
    # Step 1: Run AI analysis
    analysis = analyze_complaint(request.text, request.language, request.location)

    # Step 2: Determine mock factor values from analysis
    factors = determine_factors_from_analysis(analysis)

    # Step 3: Calculate priority
    priority = calculate_priority(
        factors["citizen_demand"],
        factors["infrastructure_gap"],
        factors["population_impact"],
        factors["urgency"],
        factors["investment_gap"],
    )

    return {
        "success": True,
        "analysis": analysis,
        "priority": priority,
        "ai_provider": AI_PROVIDER
    }


@app.post("/complaints/check-duplicate", response_model=DuplicateCheckResponse)
def check_duplicate_endpoint(request: DuplicateCheckRequest):
    result = check_duplicate(request.text, request.location)
    return result


@app.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate):
    try:
        user = create_user(user_data)
        return UserResponse(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=user.role,
            created_at=user.created_at
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.post("/auth/login", response_model=Token)
def login(user_credentials: UserLogin):
    user = authenticate_user(user_credentials.email, user_credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/auth/me", response_model=UserResponse)
def get_current_user_info(current_user: UserResponse = Depends(get_current_user)):
    return current_user


def mount_intelligence(target_app=FastAPI) -> None:
    """
    Attach Member 2's intelligence router under /intelligence.

    Idempotent, so both entrypoints can call it without double-registering the
    routes. The prefix is required rather than cosmetic: this module already
    serves /hotspots, and mounting the intelligence router at the root would
    shadow it.

    The import is guarded on purpose. If the intelligence modules cannot be
    imported -- a missing optional dependency, say -- the citizen-facing app
    must still boot and serve every existing endpoint. Intelligence is an
    add-on, not a prerequisite.
    """
    if getattr(target_app, "_intelligence_mounted", False):
        return
    try:
        from backend.router import router as intelligence_router
    except Exception as exc:  # noqa: BLE001 - never break the core app
        logger.warning("Intelligence router unavailable (%s); the core API is "
                       "unaffected and will still start.", exc)
        return
    target_app.include_router(
        intelligence_router, prefix="/intelligence", tags=["intelligence"]
    )
    target_app._intelligence_mounted = True


mount_intelligence(app)