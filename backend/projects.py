"""
Officer decision workflow: recommendation -> project, and the decision ledger.

This is the write side of the government dashboard. Everything an officer
decides about a recommendation lands here, in one place, so the rules about what
may be decided and when are stated once rather than per route.

Two rules shape the whole module:

1. **A recommendation is engine output and is never rewritten here.** The
   engine refreshes those rows in place, so the officer's decision is kept in
   `officer_decisions` and their wording in `projects.description`. Approving a
   recommendation does not modify the recommendation.

2. **One recommendation, at most one project.** A second approval is a conflict,
   not a second project. The check is here rather than in a database unique
   constraint because the workflow deliberately supports *modifying* an
   existing project for the same recommendation, and a unique index would have
   to be dropped to allow that.

Status progression is strictly forward and one step at a time
(Approved -> In Progress -> Completed). Anything else is refused rather than
silently accepted, because a project that jumps from Approved straight to
Completed would erase the record of the work in between.
"""
import logging
from typing import Any, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import models
from backend.complaint_service import ensure_user_row

log = logging.getLogger("projects")

# Project.status, in the only order a project may move through.
STATUS_APPROVED = "Approved"
STATUS_UNDER_REVIEW = "Under Review"
STATUS_IN_PROGRESS = "In Progress"
STATUS_COMPLETED = "Completed"

# A project may only advance to exactly this next status. A project found in any
# other state has to be repaired by hand before it can move again.
ALLOWED_TRANSITIONS = {
    STATUS_UNDER_REVIEW: STATUS_APPROVED,
    STATUS_APPROVED: STATUS_IN_PROGRESS,
    STATUS_IN_PROGRESS: STATUS_COMPLETED,
}

DECISION_APPROVED = "Approved"
DECISION_MODIFIED = "Modified"
DECISION_REJECTED = "Rejected"
DECISION_STATUS_CHANGED = "Status Changed"

# A recommendation with no complaints has no evidence behind it, so there is
# nothing for an officer to approve. The recommendation engine already refuses to
# emit one; this re-checks at the point of decision rather than trusting that.
MIN_RELATED_COMPLAINTS = 1


class DecisionError(Exception):
    """
    A decision that cannot be carried out.

    `status` is the HTTP code the route should surface: 404 for something that
    does not exist, 409 for something that exists but conflicts with the current
    state, 400 for a malformed request.
    """

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------
# lookup helpers
# --------------------------------------------------------------------------

def find_recommendation(db: Session, recommendation_id: int) -> models.Recommendation:
    rec = db.query(models.Recommendation).filter_by(id=recommendation_id).first()
    if rec is None:
        raise DecisionError(f"Recommendation {recommendation_id} not found.", 404)
    return rec


def related_complaints(db: Session, rec: models.Recommendation) -> list[models.Complaint]:
    return db.query(models.Complaint).filter_by(cluster_id=rec.cluster_id).all()


def project_for_recommendation(
    db: Session, rec: models.Recommendation
) -> Optional[models.Project]:
    return (
        db.query(models.Project)
        .filter_by(recommendation_id=rec.id)
        .order_by(models.Project.id)
        .first()
    )


def _officer_row(db: Session, officer: Any) -> models.User:
    """
    The `users` mirror row for the authenticated officer.

    Uses `ensure_user_row`, the same seam the complaint path uses, so an officer
    who has never filed a complaint still gets a valid `officer_id`. No password
    or token is stored: the auth module's own id is deliberately not used as an
    identity (it restarts from 1), and `auth_key` is the stable key.
    """
    row = ensure_user_row(db, officer)
    if row is None:
        raise DecisionError(
            "The officer account could not be resolved to a database user.",
            400,
        )
    return row


def _require_evidence(db: Session, rec: models.Recommendation) -> list[models.Complaint]:
    """
    A decision needs real complaints behind it.

    Membership is counted from the complaints, never from the cluster's cached
    count, so an empty cluster cannot be approved on stale numbers.
    """
    complaints = related_complaints(db, rec)
    if len(complaints) < MIN_RELATED_COMPLAINTS:
        raise DecisionError(
            "This recommendation has no related complaints, so it cannot be decided on.",
            409,
        )
    return complaints


def _record_decision(
    db: Session,
    rec: models.Recommendation,
    officer: models.User,
    decision: str,
    reason: Optional[str],
    project: Optional[models.Project],
) -> models.OfficerDecision:
    entry = models.OfficerDecision(
        recommendation_id=rec.id,
        project_id=project.id if project else None,
        officer_id=officer.id,
        decision=decision,
        reason=reason,
        # The plan as it stood when the officer decided, so a later edit to the
        # project is still auditable against what was originally approved.
        action_snapshot=rec.action,
    )
    db.add(entry)
    return entry


# --------------------------------------------------------------------------
# decisions
# --------------------------------------------------------------------------

def approve(
    db: Session,
    recommendation_id: int,
    officer: Any,
    title: Optional[str] = None,
    description: Optional[str] = None,
    reason: Optional[str] = None,
) -> tuple[models.Project, models.OfficerDecision]:
    """
    Approve a recommendation as-is, producing a project.

    Idempotency is deliberately NOT silent: a recommendation that already has a
    project is a conflict, because quietly returning the old project would let a
    second click look like a second approval while recording nothing.
    """
    rec = find_recommendation(db, recommendation_id)
    _require_evidence(db, rec)

    existing = project_for_recommendation(db, rec)
    if existing is not None:
        raise DecisionError(
            f"This recommendation already has project {existing.id} "
            f"({existing.status}). Use modify to change it, or update its status.",
            409,
        )

    officer_row = _officer_row(db, officer)
    project = models.Project(
        recommendation_id=rec.id,
        title=(title or rec.action or "Untitled project")[:200],
        description=description,
        status=STATUS_APPROVED,
        officer_id=officer_row.id,
    )
    db.add(project)
    db.flush()  # need the id for the decision row's FK

    decision = _record_decision(
        db, rec, officer_row, DECISION_APPROVED, reason, project
    )
    db.commit()
    db.refresh(project)
    db.refresh(decision)
    return project, decision


def modify(
    db: Session,
    recommendation_id: int,
    officer: Any,
    title: str,
    description: Optional[str] = None,
    reason: Optional[str] = None,
) -> tuple[models.Project, models.OfficerDecision]:
    """
    Record the officer's own version of the recommended action.

    The recommendation is never touched. The first modification of a
    recommendation creates its project in "Under Review", because an officer
    who has rewritten the plan has not yet signed it off; a later modification
    updates the existing project and leaves its status alone, so re-ordering a
    live project does not silently reset its progress.
    """
    rec = find_recommendation(db, recommendation_id)
    _require_evidence(db, rec)

    cleaned = (title or "").strip()
    if not cleaned:
        raise DecisionError("A modified action title is required.", 400)

    officer_row = _officer_row(db, officer)
    project = project_for_recommendation(db, rec)

    if project is None:
        project = models.Project(
            recommendation_id=rec.id,
            title=cleaned[:200],
            description=description,
            status=STATUS_UNDER_REVIEW,
            officer_id=officer_row.id,
        )
        db.add(project)
        db.flush()
    else:
        if project.status == STATUS_COMPLETED:
            raise DecisionError(
                f"Project {project.id} is Completed and can no longer be modified.",
                409,
            )
        project.title = cleaned[:200]
        if description is not None:
            project.description = description
        project.officer_id = officer_row.id

    decision = _record_decision(
        db, rec, officer_row, DECISION_MODIFIED, reason, project
    )
    db.commit()
    db.refresh(project)
    db.refresh(decision)
    return project, decision


def reject(
    db: Session,
    recommendation_id: int,
    officer: Any,
    reason: str,
) -> models.OfficerDecision:
    """
    Reject a recommendation. No project is created -- a rejected plan must not
    appear in the Projects list as work in progress.

    A reason is mandatory: "we are not doing this" is not an auditable decision.
    """
    rec = find_recommendation(db, recommendation_id)

    cleaned = (reason or "").strip()
    if not cleaned:
        raise DecisionError("A rejection reason is required.", 400)

    existing = project_for_recommendation(db, rec)
    if existing is not None:
        raise DecisionError(
            f"This recommendation already has project {existing.id} "
            f"({existing.status}); a rejected recommendation must not also have a project.",
            409,
        )

    officer_row = _officer_row(db, officer)
    decision = _record_decision(db, rec, officer_row, DECISION_REJECTED, cleaned, None)
    db.commit()
    db.refresh(decision)
    return decision


def set_status(
    db: Session,
    project_id: int,
    officer: Any,
    new_status: str,
    reason: Optional[str] = None,
) -> tuple[models.Project, models.OfficerDecision]:
    """
    Move a project one step along Approved -> In Progress -> Completed.

    An unrecognised status or a jump is refused with 409 and nothing is
    written, rather than accepted and logged.
    """
    project = db.query(models.Project).filter_by(id=project_id).first()
    if project is None:
        raise DecisionError(f"Project {project_id} not found.", 404)

    if new_status not in ALLOWED_TRANSITIONS.values():
        raise DecisionError(
            f"'{new_status}' is not a valid project status. "
            f"Expected one of: {', '.join(ALLOWED_TRANSITIONS.values())}.",
            400,
        )

    current = project.status
    if current == new_status:
        raise DecisionError(
            f"Project {project_id} is already '{new_status}'.", 409
        )

    expected = ALLOWED_TRANSITIONS.get(current)
    if expected != new_status:
        if expected is None:
            raise DecisionError(
                f"Project {project_id} is in state '{current}', which this workflow "
                f"does not know how to move on from.", 409
            )
        raise DecisionError(
            f"A project cannot go from '{current}' to '{new_status}'. "
            f"The next step is '{expected}'.",
            409,
        )

    officer_row = _officer_row(db, officer)
    project.status = new_status

    rec = None
    if project.recommendation_id:
        rec = db.query(models.Recommendation).filter_by(id=project.recommendation_id).first()

    if rec is not None:
        decision = _record_decision(
            db, rec, officer_row, DECISION_STATUS_CHANGED,
            reason or f"Status moved from '{current}' to '{new_status}'", project,
        )
    else:
        # A project created outside a recommendation still has to record who
        # moved it, so the ledger entry is written without the recommendation.
        decision = models.OfficerDecision(
            project_id=project.id,
            officer_id=officer_row.id,
            decision=DECISION_STATUS_CHANGED,
            reason=reason or f"Status moved from '{current}' to '{new_status}'",
        )
        db.add(decision)

    db.commit()
    db.refresh(project)
    db.refresh(decision)
    return project, decision
