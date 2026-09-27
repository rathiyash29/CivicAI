from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import timedelta, datetime
from enum import Enum

from ai import analyze_complaint, AI_PROVIDER
from priority import calculate_priority, determine_factors_from_analysis
from duplicates import check_duplicate, find_similarity, are_duplicates
from hotspots import detect_hotspots
from auth import (
    UserCreate, UserLogin, UserResponse, Token, TokenData,
    create_user, authenticate_user, get_user_by_id, MOCK_USERS_DB,
    create_access_token, decode_access_token, ACCESS_TOKEN_EXPIRE_MINUTES,
    UserRole
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
    global COMPLAINT_ID_COUNTER
    COMPLAINT_ID_COUNTER += 1
    return f"CA-{COMPLAINT_ID_COUNTER:06d}"


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

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserResponse:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token_data = decode_access_token(token)
    if token_data is None:
        raise credentials_exception
    user = get_user_by_id(int(token_data.email)) if token_data.email.isdigit() else None
    if user is None:
        user = next((u for u in MOCK_USERS_DB.values() if u.email == token_data.email), None)
    if user is None:
        raise credentials_exception
    return UserResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        created_at=user.created_at
    )


async def get_current_user_optional(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[UserResponse]:
    if not token:
        return None
    try:
        return await get_current_user(token)
    except HTTPException:
        return None


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
    factors = determine_factors_from_analysis(analysis)
    priority = calculate_priority(
        factors["citizen_demand"],
        factors["infrastructure_gap"],
        factors["population_impact"],
        factors["urgency"],
        factors["investment_gap"],
    )
    
    duplicate_result = check_duplicate(complaint.text, complaint.location)
    
    if current_user:
        stored_complaint = create_complaint(
            user_id=current_user.id,
            text=complaint.text,
            language=complaint.language,
            location=complaint.location,
            category=analysis.get("category"),
            severity=analysis.get("severity"),
            priority_score=priority.get("priority_score"),
            priority_level=priority.get("priority_level"),
        )
        return {
            "success": True,
            "complaint": {
                "complaint_id": stored_complaint.complaint_id,
                "user_id": stored_complaint.user_id,
                "text": stored_complaint.text,
                "language": stored_complaint.language,
                "location": stored_complaint.location,
                "category": stored_complaint.category,
                "severity": stored_complaint.severity,
                "priority_score": stored_complaint.priority_score,
                "priority_level": stored_complaint.priority_level,
                "status": stored_complaint.status,
                "created_at": stored_complaint.created_at.isoformat(),
            },
            "analysis": analysis,
            "priority": priority,
            "ai_provider": AI_PROVIDER,
            "duplicate": duplicate_result,
        }
    
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
    }


@app.get("/complaints/my", response_model=MyComplaintsResponse)
def get_my_complaints(current_user: UserResponse = Depends(get_current_user)):
    """
    Get all complaints submitted by the authenticated citizen.
    Requires valid JWT token.
    """
    complaints = get_user_complaints(current_user.id)
    # Sort by created_at descending (newest first)
    complaints.sort(key=lambda c: c.created_at, reverse=True)
    
    return {
        "success": True,
        "complaints": [
            {
                "complaint_id": c.complaint_id,
                "user_id": c.user_id,
                "text": c.text,
                "language": c.language,
                "location": c.location,
                "category": c.category,
                "severity": c.severity,
                "priority_score": c.priority_score,
                "priority_level": c.priority_level,
                "status": c.status,
                "created_at": c.created_at.isoformat(),
            }
            for c in complaints
        ],
        "total": len(complaints),
    }


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