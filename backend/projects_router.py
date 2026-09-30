"""
Officer decision, project, and impact routes.

Mounted at `/projects` from `main.py`. Every route here requires an officer:
`require_officer` is the same dependency the intelligence router uses, so an
unauthenticated call is 401 and a citizen token is 403, with no route-specific
role logic to drift out of step.

The decision routes are namespaced under `/projects/recommendations/...` and are
declared before `/projects/{project_id}` so the literal path always wins. The
read side that has nothing to do with a project -- the decision for a given
recommendation -- lives under `/decisions` instead, where no id can shadow it.

Impact routes are under `/projects/{project_id}/impact` for recording and
retrieving impact measurements on completed projects, and `/impact/summary`
for aggregate dashboard statistics.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import models
from database.db import get_db
from backend import projects as service, impact as impact_service
from backend.authorization import require_officer
from backend.auth import UserResponse

router = APIRouter(tags=["projects"])


# --------------------------------------------------------------------------
# request / response shapes
# --------------------------------------------------------------------------

class ApproveRequest(BaseModel):
    """Every field is optional: approving as proposed is the normal case."""
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    reason: Optional[str] = None


class ModifyRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    reason: Optional[str] = None


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class StatusRequest(BaseModel):
    status: str = Field(..., min_length=1)
    reason: Optional[str] = None


class OfficerRef(BaseModel):
    """The officer behind a record. Identity only -- never a credential."""
    id: int
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None


class DecisionOut(BaseModel):
    id: int
    recommendation_id: Optional[int] = None
    project_id: Optional[int] = None
    decision: str
    reason: Optional[str] = None
    action_snapshot: Optional[str] = None
    created_at: Optional[str] = None
    officer: Optional[OfficerRef] = None


class ProjectOut(BaseModel):
    id: int
    recommendation_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: str
    created_at: Optional[str] = None
    officer: Optional[OfficerRef] = None
    # The recommendation's context, joined for the dashboard. Absent when the
    # project has no recommendation.
    action: Optional[str] = None
    location: Optional[str] = None
    priority_score: Optional[float] = None
    priority_level: Optional[str] = None
    related_complaints: Optional[int] = None
    decisions: list[DecisionOut] = Field(default_factory=list)

class DecisionResultOut(BaseModel):
    project: Optional[ProjectOut] = None
    decision: DecisionOut


# --------------------------------------------------------------------------
# impact request / response shapes
# --------------------------------------------------------------------------


class ImpactRecordRequest(BaseModel):
    """Record or update an impact measurement for a completed project.

    At least one field must be provided. Missing calculated fields are
    auto-filled from complaint data when possible.
    """
    before_complaint_count: Optional[int] = Field(default=None, ge=0)
    after_complaint_count: Optional[int] = Field(default=None, ge=0)
    complaints_resolved: Optional[int] = Field(default=None, ge=0)
    before_avg_severity_score: Optional[float] = Field(default=None, ge=0, le=100)
    after_avg_severity_score: Optional[float] = Field(default=None, ge=0, le=100)
    before_avg_priority_score: Optional[float] = Field(default=None, ge=0, le=100)
    after_avg_priority_score: Optional[float] = Field(default=None, ge=0, le=100)
    measurement_period_start: Optional[datetime] = None
    measurement_period_end: Optional[datetime] = None
    officer_notes: Optional[str] = None
    auto_calculate: bool = True


class ImpactObservedChange(BaseModel):
    """Calculated observed changes from an impact record.

    These are OBSERVED measurements only -- they do not imply the project
    caused the change.
    """
    complaint_change: Optional[int] = None
    complaint_change_percent: Optional[float] = None
    severity_change: Optional[float] = None
    priority_change: Optional[float] = None


class ImpactOut(BaseModel):
    id: int
    project_id: int
    before_complaint_count: Optional[int] = None
    after_complaint_count: Optional[int] = None
    complaints_resolved: Optional[int] = None
    before_avg_severity_score: Optional[float] = None
    after_avg_severity_score: Optional[float] = None
    before_avg_priority_score: Optional[float] = None
    after_avg_priority_score: Optional[float] = None
    measurement_period_start: Optional[str] = None
    measurement_period_end: Optional[str] = None
    officer_notes: Optional[str] = None
    recorded_by_officer_id: int
    recorded_by: Optional[OfficerRef] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    observed_change: ImpactObservedChange


class ImpactSummaryOut(BaseModel):
    """Aggregate impact statistics for the dashboard."""
    total_completed_projects: int
    projects_with_measured_impact: int
    projects_awaiting_impact_measurement: int
    total_complaints_associated: int
    observed_complaint_reduction: int
    projects_showing_reduction: int


# --------------------------------------------------------------------------
# serialisation
# --------------------------------------------------------------------------


def _officer_out(row: Optional[models.User]) -> Optional[OfficerRef]:
    if row is None:
        return None
    return OfficerRef(id=row.id, name=row.name, email=row.email, role=row.role)


def _decision_out(entry: models.OfficerDecision) -> DecisionOut:
    return DecisionOut(
        id=entry.id,
        recommendation_id=entry.recommendation_id,
        project_id=entry.project_id,
        decision=entry.decision,
        reason=entry.reason,
        action_snapshot=entry.action_snapshot,
        created_at=entry.created_at.isoformat() if entry.created_at else None,
        officer=_officer_out(entry.officer),
    )


def _project_out(db: Session, project: models.Project) -> ProjectOut:
    """
    A project plus the recommendation context the dashboard shows beside it.

    The ward lives on the issue cluster, not on the recommendation, so it is
    read through `cluster.ward` rather than invented here.

    `related_complaints` is counted from the complaints, not read from the
    cluster's cached count, so a stale number can never appear here.
    """
    action = location = None
    priority_score = None
    priority_level = None
    related = None

    if project.recommendation_id:
        rec = db.query(models.Recommendation).filter_by(id=project.recommendation_id).first()
        if rec is not None:
            action = rec.action
            priority_score = rec.priority_score
            priority_level = _level(rec.priority_score)
            cluster = db.query(models.IssueCluster).filter_by(id=rec.cluster_id).first()
            location = cluster.ward if cluster else None
            related = db.query(models.Complaint).filter_by(cluster_id=rec.cluster_id).count()

    return ProjectOut(
        id=project.id,
        recommendation_id=project.recommendation_id,
        title=project.title,
        description=project.description,
        status=project.status,
        created_at=project.created_at.isoformat() if project.created_at else None,
        officer=_officer_out(
            db.query(models.User).filter_by(id=project.officer_id).first()
            if project.officer_id else None
        ),
        action=action,
        location=location,
        priority_score=priority_score,
        priority_level=priority_level,
        related_complaints=related,
        decisions=[
            _decision_out(d) for d in db.query(models.OfficerDecision)
            .filter_by(project_id=project.id)
            .order_by(models.OfficerDecision.created_at, models.OfficerDecision.id)
            .all()
        ],
    )


def _level(score: Optional[float]) -> Optional[str]:
    """The engine's own banding (recommendations._label), reproduced once."""
    if score is None:
        return None
    if score >= 60:
        return "High"
    if score >= 35:
        return "Medium"
    return "Low"


def _fail(exc: service.DecisionError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


# --------------------------------------------------------------------------
# decisions
# --------------------------------------------------------------------------

@router.post("/projects/recommendations/{recommendation_id}/approve",
             response_model=DecisionResultOut)
def approve_recommendation(
    recommendation_id: int,
    payload: ApproveRequest,
    db: Session = Depends(get_db),
    officer: UserResponse = Depends(require_officer),
):
    try:
        project, decision = service.approve(
            db, recommendation_id, officer,
            title=payload.title, description=payload.description, reason=payload.reason,
        )
    except service.DecisionError as exc:
        raise _fail(exc)
    return DecisionResultOut(project=_project_out(db, project), decision=_decision_out(decision))


@router.post("/projects/recommendations/{recommendation_id}/modify",
             response_model=DecisionResultOut)
def modify_recommendation(
    recommendation_id: int,
    payload: ModifyRequest,
    db: Session = Depends(get_db),
    officer: UserResponse = Depends(require_officer),
):
    try:
        project, decision = service.modify(
            db, recommendation_id, officer,
            title=payload.title, description=payload.description, reason=payload.reason,
        )
    except service.DecisionError as exc:
        raise _fail(exc)
    return DecisionResultOut(project=_project_out(db, project), decision=_decision_out(decision))


@router.post("/projects/recommendations/{recommendation_id}/reject",
             response_model=DecisionOut)
def reject_recommendation(
    recommendation_id: int,
    payload: RejectRequest,
    db: Session = Depends(get_db),
    officer: UserResponse = Depends(require_officer),
):
    try:
        decision = service.reject(db, recommendation_id, officer, payload.reason)
    except service.DecisionError as exc:
        raise _fail(exc)
    return _decision_out(decision)


@router.get("/decisions/recommendation/{recommendation_id}",
            response_model=list[DecisionOut])
def decisions_for_recommendation(
    recommendation_id: int,
    db: Session = Depends(get_db),
    _: UserResponse = Depends(require_officer),
):
    """
    The decision history for one recommendation, oldest first.

    Kept under /decisions rather than /projects/{id} so the lookup key can never
    be shadowed by a project id.
    """
    if db.query(models.Recommendation).filter_by(id=recommendation_id).first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recommendation {recommendation_id} not found.",
        )
    return [
        _decision_out(d) for d in db.query(models.OfficerDecision)
        .filter_by(recommendation_id=recommendation_id)
        .order_by(models.OfficerDecision.created_at, models.OfficerDecision.id)
        .all()
    ]


# --------------------------------------------------------------------------
# projects
# --------------------------------------------------------------------------

@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    db: Session = Depends(get_db),
    _: UserResponse = Depends(require_officer),
):
    return [
        _project_out(db, p) for p in db.query(models.Project)
        .order_by(models.Project.created_at.desc(), models.Project.id.desc())
        .all()
    ]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    _: UserResponse = Depends(require_officer),
):
    project = db.query(models.Project).filter_by(id=project_id).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    return _project_out(db, project)


@router.patch("/projects/{project_id}/status", response_model=DecisionResultOut)
def update_project_status(
    project_id: int,
    payload: StatusRequest,
    db: Session = Depends(get_db),
    officer: UserResponse = Depends(require_officer),
):
    try:
        project, decision = service.set_status(
            db, project_id, officer, payload.status, reason=payload.reason
        )
    except service.DecisionError as exc:
        raise _fail(exc)
    return DecisionResultOut(project=_project_out(db, project), decision=_decision_out(decision))


# --------------------------------------------------------------------------
# impact
# --------------------------------------------------------------------------


def _impact_out(db: Session, impact: models.ProjectImpact) -> ImpactOut:
    """Serialize a ProjectImpact with calculated observed changes."""
    recorded_by = _officer_out(
        db.query(models.User).filter_by(id=impact.recorded_by_officer_id).first()
    )
    observed_change = impact_service.calculate_observed_change(impact)
    return ImpactOut(
        id=impact.id,
        project_id=impact.project_id,
        before_complaint_count=impact.before_complaint_count,
        after_complaint_count=impact.after_complaint_count,
        complaints_resolved=impact.complaints_resolved,
        before_avg_severity_score=impact.before_avg_severity_score,
        after_avg_severity_score=impact.after_avg_severity_score,
        before_avg_priority_score=impact.before_avg_priority_score,
        after_avg_priority_score=impact.after_avg_priority_score,
        measurement_period_start=(
            impact.measurement_period_start.isoformat() if impact.measurement_period_start else None
        ),
        measurement_period_end=(
            impact.measurement_period_end.isoformat() if impact.measurement_period_end else None
        ),
        officer_notes=impact.officer_notes,
        recorded_by_officer_id=impact.recorded_by_officer_id,
        recorded_by=recorded_by,
        created_at=impact.created_at.isoformat() if impact.created_at else None,
        updated_at=impact.updated_at.isoformat() if impact.updated_at else None,
        observed_change=ImpactObservedChange(**observed_change),
    )


def _impact_fail(exc: impact_service.ImpactError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/projects/{project_id}/impact", response_model=ImpactOut)
def record_project_impact(
    project_id: int,
    payload: ImpactRecordRequest,
    db: Session = Depends(get_db),
    officer: UserResponse = Depends(require_officer),
):
    """
    Record an impact measurement for a completed project.

    Only completed projects can have impact recorded. Missing calculated fields
    are auto-filled from the project's cluster complaint data when possible.
    """
    try:
        impact = impact_service.record_impact(
            db,
            project_id,
            officer,
            before_complaint_count=payload.before_complaint_count,
            after_complaint_count=payload.after_complaint_count,
            complaints_resolved=payload.complaints_resolved,
            before_avg_severity_score=payload.before_avg_severity_score,
            after_avg_severity_score=payload.after_avg_severity_score,
            before_avg_priority_score=payload.before_avg_priority_score,
            after_avg_priority_score=payload.after_avg_priority_score,
            measurement_period_start=payload.measurement_period_start,
            measurement_period_end=payload.measurement_period_end,
            officer_notes=payload.officer_notes,
            auto_calculate=payload.auto_calculate,
        )
    except impact_service.ImpactError as exc:
        raise _impact_fail(exc)
    return _impact_out(db, impact)


@router.get("/projects/{project_id}/impact", response_model=ImpactOut)
def get_project_impact(
    project_id: int,
    db: Session = Depends(get_db),
    _: UserResponse = Depends(require_officer),
):
    """Retrieve the impact record for a project, if any."""
    project = db.query(models.Project).filter_by(id=project_id).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    impact = impact_service.get_impact(db, project_id)
    if impact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No impact record found for project {project_id}.",
        )
    return _impact_out(db, impact)


@router.patch("/projects/{project_id}/impact", response_model=ImpactOut)
def update_project_impact(
    project_id: int,
    payload: ImpactRecordRequest,
    db: Session = Depends(get_db),
    officer: UserResponse = Depends(require_officer),
):
    """Update an existing impact record for a completed project."""
    try:
        impact = impact_service.update_impact(
            db,
            project_id,
            officer,
            before_complaint_count=payload.before_complaint_count,
            after_complaint_count=payload.after_complaint_count,
            complaints_resolved=payload.complaints_resolved,
            before_avg_severity_score=payload.before_avg_severity_score,
            after_avg_severity_score=payload.after_avg_severity_score,
            before_avg_priority_score=payload.before_avg_priority_score,
            after_avg_priority_score=payload.after_avg_priority_score,
            measurement_period_start=payload.measurement_period_start,
            measurement_period_end=payload.measurement_period_end,
            officer_notes=payload.officer_notes,
        )
    except impact_service.ImpactError as exc:
        raise _impact_fail(exc)
    return _impact_out(db, impact)


class ImpactListOut(BaseModel):
    """
    Every recorded impact measurement, newest first.

    The dashboard's Impact page needs to know, per project, whether a
    measurement exists at all. Asking for each project individually would mean
    one request per completed project and a 404-as-expected control flow for
    the common "not measured yet" case; this returns the measured subset in one
    call so absence is a missing key rather than an error.
    """

    impacts: list[ImpactOut]
    measured_project_ids: list[int]


@router.get("/impact", response_model=ImpactListOut)
def list_impacts(
    db: Session = Depends(get_db),
    _: UserResponse = Depends(require_officer),
):
    """
    All recorded project impact measurements.

    `completed_only` is deliberately not a parameter here. `list_project_impacts`
    defaults to completed projects because that is the state an impact record
    is legal in, and widening the query would report a measurement the backend
    would refuse to let an officer create. `measured_project_ids` is the same
    list projected onto the project ids, so a client can test membership
    without a lookup.
    """
    records = impact_service.list_project_impacts(db)
    impacts = [_impact_out(db, record) for record in records]
    return {
        "impacts": impacts,
        "measured_project_ids": [impact.project_id for impact in impacts],
    }


@router.get("/impact/summary", response_model=ImpactSummaryOut)
def get_impact_summary(
    db: Session = Depends(get_db),
    _: UserResponse = Depends(require_officer),
):
    """Aggregate impact statistics for the dashboard."""
    stats = impact_service.get_aggregate_impact_stats(db)
    return ImpactSummaryOut(**stats)
