"""
DB-backed priority engine (Member 2).

This is the data-driven counterpart to the mock `backend/priority.py` that
Member 1's `main.py` already imports. That mock file is left untouched: it
stays in charge of `/complaints/analyze-and-prioritize` so the existing
frontend keeps working with zero changes.

Here the same 30/25/20/15/10 weights are fed with numbers read out of the
database instead of hardcoded category tables:

    Citizen demand     30%  -> how many complaints actually exist for this
                               location+category (or the size of its cluster)
    Infrastructure gap 25%  -> data_engine.get_infrastructure_gap()
    Population impact  20%  -> data_engine.get_population_impact()
    Urgency            15%  -> the AI's urgency label for this complaint
    Investment gap     10%  -> data_engine.get_investment_gap()

Every factor is normalised to 0-100 before weighting, so the weighted sum is
already on the 0-100 scale and needs no further rescaling.
"""
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from database import models
from backend import data_engine

# The agreed weighting. Must not drift from docs/API_CONTRACT.md.
WEIGHTS = {
    "citizen_demand": 0.30,
    "infrastructure_gap": 0.25,
    "population_impact": 0.20,
    "urgency": 0.15,
    "investment_gap": 0.10,
}

# Urgency arrives from the AI layer as a Low/Medium/High label.
URGENCY_SCORES = {"Low": 30.0, "Medium": 60.0, "High": 90.0}
DEFAULT_URGENCY_SCORE = 60.0

# Demand is a saturating curve rather than a raw count, so that a ward with
# 500 complaints does not permanently flatten every other ward to zero. This
# many complaints in a group scores 50.
DEMAND_HALF_POINT = 5.0

PRIORITY_BANDS = (("Low", 39.0), ("Medium", 69.0), ("High", 100.0))


def _saturating_score(count: int, half_point: float = DEMAND_HALF_POINT) -> float:
    """Map a raw count onto 0-100 with diminishing returns.

    0 -> 0.0, 1 -> 16.7, 3 -> 37.5, 5 -> 50.0, 10 -> 66.7, 20 -> 80.0.
    Monotonic and bounded, so it never needs a global maximum to be stable.
    """
    if count <= 0:
        return 0.0
    value = 100.0 * (1 - 1 / (1 + count / half_point))
    return round(min(100.0, value), 1)


def _level_for(score: float) -> str:
    for label, ceiling in PRIORITY_BANDS:
        if score <= ceiling:
            return label
    return "High"


def get_demand_group_count(db: Session, complaint: models.Complaint) -> Tuple[int, str]:
    """
    How many complaints represent the same citizen demand as this one, and
    how that number was arrived at.

    A clustered complaint is measured by its whole cluster, because that is
    the unit the officer dashboard actually acts on. An unclustered one is
    measured against every complaint sharing its location and category.
    """
    if complaint.cluster_id:
        cluster = db.query(models.IssueCluster).filter_by(id=complaint.cluster_id).first()
        if cluster is not None and cluster.complaint_count:
            return int(cluster.complaint_count), "cluster"

    query = db.query(models.Complaint).filter(models.Complaint.category == complaint.category)
    if complaint.location_id:
        query = query.filter(models.Complaint.location_id == complaint.location_id)
    else:
        return 1, "single"
    return query.count(), "location_category"


def get_citizen_demand(db: Session, complaint: models.Complaint) -> float:
    """0-100. Rises with the number of people reporting the same problem."""
    count, _ = get_demand_group_count(db, complaint)
    return _saturating_score(count)


def get_urgency(complaint: models.Complaint) -> float:
    return URGENCY_SCORES.get((complaint.urgency or "").strip().capitalize(),
                              DEFAULT_URGENCY_SCORE)


def compute_factors(db: Session, complaint: models.Complaint) -> dict:
    """Read all five factors out of the database."""
    demand_count, basis = get_demand_group_count(db, complaint)

    return {
        "citizen_demand": _saturating_score(demand_count),
        "infrastructure_gap": data_engine.get_infrastructure_gap(
            db, complaint.location_id, complaint.category
        ),
        "population_impact": data_engine.get_population_impact(db, complaint.location_id),
        "urgency": get_urgency(complaint),
        "investment_gap": data_engine.get_investment_gap(
            db, complaint.location_id, complaint.category
        ),
        "_demand_count": demand_count,
        "_demand_basis": basis,
    }


def compute_priority(db: Session, complaint: models.Complaint) -> dict:
    """
    Score one complaint and persist the result.

    Returns the same shape as the mock `priority.calculate_priority`
    (`priority_score`, `priority_level`, `factors`) plus an `evidence` block,
    so a dashboard can show *why* a ward was ranked the way it was.
    """
    raw = compute_factors(db, complaint)
    demand_count = raw.pop("_demand_count")
    demand_basis = raw.pop("_demand_basis")

    priority_score = round(
        sum(raw[name] * weight for name, weight in WEIGHTS.items()), 2
    )
    priority_score = round(min(100.0, max(0.0, priority_score)), 2)
    priority_level = _level_for(priority_score)

    complaint.priority_score = priority_score
    complaint.priority_level = priority_level

    return {
        "complaint_id": complaint.id,
        "priority_score": priority_score,
        "priority_level": priority_level,
        "factors": raw,
        "evidence": {
            "citizen_demand_basis": demand_basis,
            "complaints_in_demand_group": demand_count,
            "infrastructure_gap_source": "database" if complaint.location_id else "default",
            "investment_gap_source": "database" if complaint.location_id else "default",
        },
    }


def score_all_pending(db: Session, limit: Optional[int] = None) -> list[dict]:
    """
    Score every complaint that has not been scored yet, in a single commit.

    One malformed row must not abort the batch, so failures are collected and
    returned alongside the successful results instead of raising.
    """
    query = db.query(models.Complaint).filter(models.Complaint.priority_score.is_(None))
    query = query.order_by(models.Complaint.id)
    if limit:
        query = query.limit(limit)

    results: list[dict] = []
    failures: list[dict] = []

    for complaint in query.all():
        try:
            results.append(compute_priority(db, complaint))
        except Exception as exc:  # noqa: BLE001 - one bad row must not stop the batch
            failures.append({"complaint_id": complaint.id, "error": str(exc)})

    db.commit()

    return {
        "scored": len(results),
        "results": results,
        "failed": failures,
    }
