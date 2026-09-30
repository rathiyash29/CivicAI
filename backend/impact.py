"""
Impact tracking service for completed projects.

Provides the write/read path for project impact measurements. An impact record
is an officer-authored observation of what changed after a project reached
Completed status. It does NOT assert causation -- only observed measurements.
"""
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import models
from backend.projects import STATUS_COMPLETED, DecisionError
from backend.complaint_service import ensure_user_row

log = logging.getLogger("impact")

# Severity to numeric score for averaging
SEVERITY_SCORE = {"Low": 10.0, "Medium": 50.0, "High": 90.0}


class ImpactError(Exception):
    """An impact operation that cannot be carried out."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def find_project(db: Session, project_id: int) -> models.Project:
    project = db.query(models.Project).filter_by(id=project_id).first()
    if project is None:
        raise ImpactError(f"Project {project_id} not found.", 404)
    return project


def _officer_row(db: Session, officer: Any) -> models.User:
    row = ensure_user_row(db, officer)
    if row is None:
        raise ImpactError(
            "The officer account could not be resolved to a database user.",
            400,
        )
    return row


def _require_completed(project: models.Project) -> None:
    if project.status != STATUS_COMPLETED:
        raise ImpactError(
            f"Project {project.id} is '{project.status}', not 'Completed'. "
            f"Impact can only be recorded for completed projects.",
            409,
        )


def _get_related_complaints(db: Session, project: models.Project):
    """
    Get complaints related to this project through its recommendation's cluster.
    Returns (complaints_query, cluster_id) or (None, None) if no recommendation.
    """
    if not project.recommendation_id:
        return None, None
    rec = (
        db.query(models.Recommendation)
        .filter_by(id=project.recommendation_id)
        .first()
    )
    if rec is None or not rec.cluster_id:
        return None, None
    complaints = db.query(models.Complaint).filter_by(cluster_id=rec.cluster_id)
    return complaints, rec.cluster_id


def _calculate_complaint_metrics(
    db: Session, cluster_id: int, before_date: Optional[datetime], after_date: Optional[datetime]
) -> dict:
    """
    Calculate complaint-based metrics for a cluster within a time window.

    If dates are not provided, falls back to project created_at as the boundary.
    """
    complaints_q = db.query(models.Complaint).filter_by(cluster_id=cluster_id)

    if before_date:
        before_count = complaints_q.filter(models.Complaint.created_at < before_date).count()
        before_severity = (
            complaints_q.filter(models.Complaint.created_at < before_date)
            .with_entities(func.avg(models.Complaint.priority_score))
            .scalar()
        )
    else:
        before_count = complaints_q.count()
        before_severity = complaints_q.with_entities(func.avg(models.Complaint.priority_score)).scalar()

    if after_date:
        after_count = complaints_q.filter(models.Complaint.created_at >= after_date).count()
        after_severity = (
            complaints_q.filter(models.Complaint.created_at >= after_date)
            .with_entities(func.avg(models.Complaint.priority_score))
            .scalar()
        )
    else:
        after_count = 0
        after_severity = None

    return {
        "before_complaint_count": before_count,
        "after_complaint_count": after_count,
        "before_avg_priority_score": round(before_severity, 2) if before_severity else None,
        "after_avg_priority_score": round(after_severity, 2) if after_severity else None,
    }


def _calculate_severity_metrics(
    db: Session, cluster_id: int, before_date: Optional[datetime], after_date: Optional[datetime]
) -> dict:
    """
    Calculate severity-based metrics using the severity field (Low/Medium/High).
    """
    complaints_q = db.query(models.Complaint).filter_by(cluster_id=cluster_id)

    if before_date:
        before_complaints = complaints_q.filter(models.Complaint.created_at < before_date).all()
    else:
        before_complaints = complaints_q.all()

    if after_date:
        after_complaints = complaints_q.filter(models.Complaint.created_at >= after_date).all()
    else:
        after_complaints = []

    def avg_severity(complaints):
        if not complaints:
            return None
        scores = [SEVERITY_SCORE.get(c.severity, 50.0) for c in complaints if c.severity]
        return round(sum(scores) / len(scores), 2) if scores else None

    return {
        "before_avg_severity_score": avg_severity(before_complaints),
        "after_avg_severity_score": avg_severity(after_complaints),
    }


def record_impact(
    db: Session,
    project_id: int,
    officer: Any,
    # Optional calculated fields (if provided, used as-is; if not, calculated)
    before_complaint_count: Optional[int] = None,
    after_complaint_count: Optional[int] = None,
    complaints_resolved: Optional[int] = None,
    before_avg_severity_score: Optional[float] = None,
    after_avg_severity_score: Optional[float] = None,
    before_avg_priority_score: Optional[float] = None,
    after_avg_priority_score: Optional[float] = None,
    measurement_period_start: Optional[datetime] = None,
    measurement_period_end: Optional[datetime] = None,
    officer_notes: Optional[str] = None,
    # If True, calculate missing fields from complaint data
    auto_calculate: bool = True,
) -> models.ProjectImpact:
    """
    Record an impact measurement for a completed project.

    Validation:
    - Project must exist and be Completed
    - Officer must be valid
    - No existing impact record for this project (unique constraint)
    - At least one measurement field or officer_notes must be provided

    If auto_calculate=True (default), missing measurement fields are derived
    from the project's cluster complaint data using the measurement period
    dates (or project created_at as fallback boundary).
    """
    project = find_project(db, project_id)
    _require_completed(project)

    officer_row = _officer_row(db, officer)

    # Check for existing impact (unique constraint will also catch this)
    existing = db.query(models.ProjectImpact).filter_by(project_id=project_id).first()
    if existing is not None:
        raise ImpactError(
            f"Project {project_id} already has an impact record. "
            f"Use update if you need to change it.",
            409,
        )

    # If auto_calculate and we have a cluster, fill in missing calculated fields
    if auto_calculate:
        complaints_q, cluster_id = _get_related_complaints(db, project)
        if cluster_id and complaints_q is not None:
            # Use measurement dates or project created_at as boundary
            boundary_start = measurement_period_start or project.created_at
            boundary_end = measurement_period_end or project.created_at

            calc_complaint = _calculate_complaint_metrics(
                db, cluster_id, boundary_start, boundary_end
            )
            calc_severity = _calculate_severity_metrics(
                db, cluster_id, boundary_start, boundary_end
            )

            # Only fill in if not explicitly provided
            if before_complaint_count is None:
                before_complaint_count = calc_complaint["before_complaint_count"]
            if after_complaint_count is None:
                after_complaint_count = calc_complaint["after_complaint_count"]
            if before_avg_priority_score is None:
                before_avg_priority_score = calc_complaint["before_avg_priority_score"]
            if after_avg_priority_score is None:
                after_avg_priority_score = calc_complaint["after_avg_priority_score"]
            if before_avg_severity_score is None:
                before_avg_severity_score = calc_severity["before_avg_severity_score"]
            if after_avg_severity_score is None:
                after_avg_severity_score = calc_severity["after_avg_severity_score"]

    # Validate at least something was provided
    provided_any = any(
        v is not None
        for v in [
            before_complaint_count,
            after_complaint_count,
            complaints_resolved,
            before_avg_severity_score,
            after_avg_severity_score,
            before_avg_priority_score,
            after_avg_priority_score,
            officer_notes,
        ]
    )
    if not provided_any:
        raise ImpactError(
            "At least one measurement field or officer_notes must be provided.",
            400,
        )

    # Validate non-negative counts
    for field_name, value in [
        ("before_complaint_count", before_complaint_count),
        ("after_complaint_count", after_complaint_count),
        ("complaints_resolved", complaints_resolved),
    ]:
        if value is not None and value < 0:
            raise ImpactError(f"{field_name} cannot be negative.", 400)

    # Validate score ranges (0-100)
    for field_name, value in [
        ("before_avg_severity_score", before_avg_severity_score),
        ("after_avg_severity_score", after_avg_severity_score),
        ("before_avg_priority_score", before_avg_priority_score),
        ("after_avg_priority_score", after_avg_priority_score),
    ]:
        if value is not None and not (0 <= value <= 100):
            raise ImpactError(f"{field_name} must be between 0 and 100.", 400)

    impact = models.ProjectImpact(
        project_id=project_id,
        before_complaint_count=before_complaint_count,
        after_complaint_count=after_complaint_count,
        complaints_resolved=complaints_resolved,
        before_avg_severity_score=before_avg_severity_score,
        after_avg_severity_score=after_avg_severity_score,
        before_avg_priority_score=before_avg_priority_score,
        after_avg_priority_score=after_avg_priority_score,
        measurement_period_start=measurement_period_start,
        measurement_period_end=measurement_period_end,
        officer_notes=officer_notes,
        recorded_by_officer_id=officer_row.id,
    )
    db.add(impact)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Race condition: another request created it
        raise ImpactError(
            f"Project {project_id} already has an impact record.",
            409,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        log.exception("Failed to record impact for project %s", project_id)
        raise ImpactError(f"Database error: {exc}", 500)

    db.refresh(impact)
    return impact


def get_impact(db: Session, project_id: int) -> Optional[models.ProjectImpact]:
    """Retrieve the impact record for a project, if any."""
    return db.query(models.ProjectImpact).filter_by(project_id=project_id).first()


def list_project_impacts(
    db: Session,
    completed_only: bool = True,
) -> list[models.ProjectImpact]:
    """
    List all project impact records, optionally filtered to completed projects only.
    """
    query = db.query(models.ProjectImpact).join(models.Project)
    if completed_only:
        query = query.filter(models.Project.status == STATUS_COMPLETED)
    return query.order_by(models.ProjectImpact.created_at.desc()).all()


def update_impact(
    db: Session,
    project_id: int,
    officer: Any,
    before_complaint_count: Optional[int] = None,
    after_complaint_count: Optional[int] = None,
    complaints_resolved: Optional[int] = None,
    before_avg_severity_score: Optional[float] = None,
    after_avg_severity_score: Optional[float] = None,
    before_avg_priority_score: Optional[float] = None,
    after_avg_priority_score: Optional[float] = None,
    measurement_period_start: Optional[datetime] = None,
    measurement_period_end: Optional[datetime] = None,
    officer_notes: Optional[str] = None,
) -> models.ProjectImpact:
    """
    Update an existing impact record.

    Only the recording officer or another officer can update. All fields optional.
    """
    project = find_project(db, project_id)
    _require_completed(project)

    _officer_row(db, officer)  # validates officer

    impact = db.query(models.ProjectImpact).filter_by(project_id=project_id).first()
    if impact is None:
        raise ImpactError(f"No impact record found for project {project_id}.", 404)

    # Track if anything changed
    changed = False

    fields = {
        "before_complaint_count": before_complaint_count,
        "after_complaint_count": after_complaint_count,
        "complaints_resolved": complaints_resolved,
        "before_avg_severity_score": before_avg_severity_score,
        "after_avg_severity_score": after_avg_severity_score,
        "before_avg_priority_score": before_avg_priority_score,
        "after_avg_priority_score": after_avg_priority_score,
        "measurement_period_start": measurement_period_start,
        "measurement_period_end": measurement_period_end,
        "officer_notes": officer_notes,
    }

    for field, value in fields.items():
        if value is not None:
            setattr(impact, field, value)
            changed = True

    if not changed:
        raise ImpactError("No fields provided to update.", 400)

    # Validate
    for field_name, value in [
        ("before_complaint_count", impact.before_complaint_count),
        ("after_complaint_count", impact.after_complaint_count),
        ("complaints_resolved", impact.complaints_resolved),
    ]:
        if value is not None and value < 0:
            raise ImpactError(f"{field_name} cannot be negative.", 400)

    for field_name, value in [
        ("before_avg_severity_score", impact.before_avg_severity_score),
        ("after_avg_severity_score", impact.after_avg_severity_score),
        ("before_avg_priority_score", impact.before_avg_priority_score),
        ("after_avg_priority_score", impact.after_avg_priority_score),
    ]:
        if value is not None and not (0 <= value <= 100):
            raise ImpactError(f"{field_name} must be between 0 and 100.", 400)

    impact.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(impact)
    return impact


def calculate_observed_change(impact: models.ProjectImpact) -> dict:
    """
    Calculate observed changes from an impact record.

    Returns a dict with calculated fields. Does NOT imply causation.
    """
    result = {
        "complaint_change": None,
        "complaint_change_percent": None,
        "severity_change": None,
        "priority_change": None,
    }

    # Complaint count change
    if impact.before_complaint_count is not None and impact.after_complaint_count is not None:
        change = impact.after_complaint_count - impact.before_complaint_count
        result["complaint_change"] = change
        if impact.before_complaint_count > 0:
            result["complaint_change_percent"] = round(
                (change / impact.before_complaint_count) * 100, 1
            )

    # Severity change
    if impact.before_avg_severity_score is not None and impact.after_avg_severity_score is not None:
        result["severity_change"] = round(
            impact.after_avg_severity_score - impact.before_avg_severity_score, 2
        )

    # Priority change
    if impact.before_avg_priority_score is not None and impact.after_avg_priority_score is not None:
        result["priority_change"] = round(
            impact.after_avg_priority_score - impact.before_avg_priority_score, 2
        )

    return result


def get_aggregate_impact_stats(db: Session) -> dict:
    """
    Get aggregate statistics for the impact dashboard.
    """
    # Total completed projects
    total_completed = (
        db.query(models.Project)
        .filter(models.Project.status == STATUS_COMPLETED)
        .count()
    )

    # Projects with impact records
    with_impact = db.query(models.ProjectImpact).count()

    # Projects awaiting impact (completed but no impact record)
    awaiting = total_completed - with_impact

    # Total complaints associated with completed projects
    completed_projects = (
        db.query(models.Project)
        .filter(models.Project.status == STATUS_COMPLETED)
        .all()
    )

    total_complaints = 0
    for project in completed_projects:
        if project.recommendation_id:
            rec = (
                db.query(models.Recommendation)
                .filter_by(id=project.recommendation_id)
                .first()
            )
            if rec and rec.cluster_id:
                count = (
                    db.query(models.Complaint)
                    .filter_by(cluster_id=rec.cluster_id)
                    .count()
                )
                total_complaints += count

    # Observed complaint reduction (sum of negative changes where calculable)
    impacts = db.query(models.ProjectImpact).all()
    total_reduction = 0
    projects_with_reduction = 0
    for impact in impacts:
        change_data = calculate_observed_change(impact)
        if change_data["complaint_change"] is not None and change_data["complaint_change"] < 0:
            total_reduction += abs(change_data["complaint_change"])
            projects_with_reduction += 1

    return {
        "total_completed_projects": total_completed,
        "projects_with_measured_impact": with_impact,
        "projects_awaiting_impact_measurement": awaiting,
        "total_complaints_associated": total_complaints,
        "observed_complaint_reduction": total_reduction,
        "projects_showing_reduction": projects_with_reduction,
    }