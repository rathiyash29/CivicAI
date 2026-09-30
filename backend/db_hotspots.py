"""
DB-backed hotspot detection (Member 2).

The mock `backend/hotspots.py` aggregates 50 hardcoded rows and is left
untouched, because `main.py` imports it for `/hotspots` and the citizen
frontend already renders its output shape. This module performs the same
aggregation over real `complaints` rows and backs
`GET /intelligence/hotspots`.

Output keys are identical to the mock version (`location`, `category`,
`complaint_count`, `high_severity_count`, `hotspot_score`,
`hotspot_level`) so a dashboard can consume either source unchanged.

Scoring
-------
A flat `count * 10 + high * 5` saturates at 100 after ten complaints, which
collapses every busy ward into a tie. Instead each group earns weighted
points, and those points are mapped onto 0-100 with a saturating curve:

    points = count + 1.5 * high_severity + 0.5 * medium_severity
    score  = 100 * points / (points + 15)

This keeps small quiet groups clearly Low, ranks genuinely busy ones above
them, and only reaches High once a group is both large *and* severe.
"""
from typing import Optional

from sqlalchemy.orm import Session

from database import models

# Softening constant: a group needs ~15 points (e.g. 15 complaints with no
# severe cases, or 6 with 6 high-severity) to reach half the maximum score.
SCORE_SOFTENING = 15.0
HIGH_SEVERITY_WEIGHT = 1.5
MEDIUM_SEVERITY_WEIGHT = 0.5

BANDS = (("Low", 29.0), ("Medium", 59.0), ("High", 100.0))

DEFAULT_MIN_COMPLAINTS = 3

# The ward bucket used when a complaint has no resolvable location. This is the
# same literal `db_duplicates.assign_cluster` uses when it keys a cluster, and
# the two must stay identical or the cluster join below silently returns
# nothing.
UNASSIGNED_WARD = "Unassigned"


def _level_for(score: float) -> str:
    for label, ceiling in BANDS:
        if score <= ceiling:
            return label
    return "High"


def _points(count: int, high: int, medium: int) -> float:
    return count + HIGH_SEVERITY_WEIGHT * high + MEDIUM_SEVERITY_WEIGHT * medium


def hotspot_score(count: int, high_severity: int, medium_severity: int = 0) -> float:
    """0-100 hotspot score for one (location, category) group."""
    if count <= 0:
        return 0.0
    points = _points(count, high_severity, medium_severity)
    return round(min(100.0, 100.0 * points / (points + SCORE_SOFTENING)), 1)


def _ward_for(db: Session, complaint: models.Complaint) -> str:
    if complaint.location_id:
        location = db.query(models.Location).filter_by(id=complaint.location_id).first()
        if location and location.ward:
            return location.ward
    return UNASSIGNED_WARD


def _clusters_for_scope(db: Session, ward: str, category: str) -> list[int]:
    """
    Ids of every cluster in exactly this (ward, category) scope.

    This is the one join that is safe between clusters and hotspots, because
    both are keyed on the same pair, derived the same way: `assign_cluster`
    uses `Location.ward or "Unassigned"` and `category or "Other"`, and the
    grouping below uses the identical expressions. So the cluster set for a
    hotspot is fully determined by the data.

    It is deliberately a LIST, never a single id. One (ward, category) scope can
    hold several clusters -- that is exactly what `assign_cluster` creates when
    the complaint texts in one ward differ -- and picking one of them would be a
    guess presented to an officer as fact.
    """
    return [
        cluster.id
        for cluster in db.query(models.IssueCluster)
        .filter_by(ward=ward, category=category)
        .order_by(models.IssueCluster.id)
        .all()
    ]


def _location_for_ward(db: Session, ward: str) -> Optional[models.Location]:
    """The `Location` row for a ward, or None when the ward is unknown.

    Coordinates are returned exactly as stored. Every column here is nullable
    and, in the current dataset, empty -- a hotspot with no known position
    reports `None` rather than a fabricated point.
    """
    if ward == UNASSIGNED_WARD:
        return None
    return db.query(models.Location).filter_by(ward=ward).first()


def compute_hotspots(
    db: Session,
    min_complaints: int = DEFAULT_MIN_COMPLAINTS,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Aggregate stored complaints by ward and category, worst first.

    `min_complaints` keeps a single stray report from lighting up a map;
    `limit` trims the list for dashboard display.

    Each hotspot also carries the ids of the clusters inside its scope, so a
    consumer can follow a hotspot through to its clusters and on to the
    recommendations that hang off them. See `_clusters_for_scope` for why that
    is a list.
    """
    groups: dict[tuple[str, str], dict] = {}

    complaints = db.query(models.Complaint).order_by(models.Complaint.id).all()
    for complaint in complaints:
        ward = _ward_for(db, complaint)
        category = complaint.category or "Other"
        bucket = groups.setdefault(
            (ward, category),
            {"complaint_count": 0, "high_severity_count": 0, "medium_severity_count": 0},
        )
        bucket["complaint_count"] += 1
        severity = (complaint.severity or "").capitalize()
        if severity == "High":
            bucket["high_severity_count"] += 1
        elif severity == "Medium":
            bucket["medium_severity_count"] += 1

    hotspots: list[dict] = []
    for (ward, category), bucket in groups.items():
        count = bucket["complaint_count"]
        if count < min_complaints:
            continue

        high = bucket["high_severity_count"]
        medium = bucket["medium_severity_count"]
        score = hotspot_score(count, high, medium)

        location = _location_for_ward(db, ward)
        hotspots.append({
            "location": ward,
            "category": category,
            "complaint_count": count,
            "high_severity_count": high,
            "medium_severity_count": medium,
            "hotspot_score": score,
            "hotspot_level": _level_for(score),
            # Additive. Deterministic scope join -- see `_clusters_for_scope`.
            "cluster_ids": _clusters_for_scope(db, ward, category),
            # Additive, and nullable by design. The columns already exist on
            # `locations`; these are passed through untouched, so a ward with no
            # recorded position reports None instead of an invented one.
            "area": location.area if location else None,
            "latitude": location.latitude if location else None,
            "longitude": location.longitude if location else None,
        })

    # Ties broken by volume so the ordering is stable and meaningful.
    hotspots.sort(key=lambda h: (-h["hotspot_score"], -h["complaint_count"], h["location"]))
    return hotspots[:limit] if limit else hotspots
