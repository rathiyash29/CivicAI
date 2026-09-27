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
    return "Unassigned"


def compute_hotspots(
    db: Session,
    min_complaints: int = DEFAULT_MIN_COMPLAINTS,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Aggregate stored complaints by ward and category, worst first.

    `min_complaints` keeps a single stray report from lighting up a map;
    `limit` trims the list for dashboard display.
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

        hotspots.append({
            "location": ward,
            "category": category,
            "complaint_count": count,
            "high_severity_count": high,
            "medium_severity_count": medium,
            "hotspot_score": score,
            "hotspot_level": _level_for(score),
        })

    # Ties broken by volume so the ordering is stable and meaningful.
    hotspots.sort(key=lambda h: (-h["hotspot_score"], -h["complaint_count"], h["location"]))
    return hotspots[:limit] if limit else hotspots
