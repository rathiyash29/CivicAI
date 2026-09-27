"""
Aggregation helpers over the database — the single place priority.py,
hotspots.py and recommendations.py go to read demographics/infrastructure/
investment data, so nobody writes raw queries in three different files.
"""
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import models


def get_location_by_ward(db: Session, ward: str) -> Optional[models.Location]:
    return db.query(models.Location).filter_by(ward=ward).first()


def get_infrastructure_gap(db: Session, location_id: int, category: str) -> float:
    """0-100. Higher = bigger infrastructure gap. Defaults to 50 (unknown)."""
    row = (
        db.query(models.Infrastructure)
        .filter_by(location_id=location_id, category=category)
        .first()
    )
    return float(row.gap_score) if row and row.gap_score is not None else 50.0


def get_population_impact(db: Session, location_id: int) -> float:
    """
    Normalized 0-100 population-impact score for a location, relative to
    the highest-population ward currently in the database.
    """
    demo = db.query(models.Demographics).filter_by(location_id=location_id).first()
    if not demo or not demo.population:
        return 30.0  # neutral default when we have no demographic data yet

    max_pop = db.query(func.max(models.Demographics.population)).scalar() or demo.population
    return round((demo.population / max_pop) * 100, 1)


def get_investment_gap(db: Session, location_id: int, category: str) -> float:
    """
    Higher = less has been invested here relative to other wards for this
    category (i.e. a bigger case for prioritizing it).
    """
    total = (
        db.query(func.sum(models.Investment.amount_allocated))
        .filter_by(category=category)
        .scalar()
    ) or 0
    here = (
        db.query(func.sum(models.Investment.amount_allocated))
        .filter_by(location_id=location_id, category=category)
        .scalar()
    ) or 0
    if total == 0:
        return 50.0  # no investment data yet — neutral
    share = here / total
    return round((1 - share) * 100, 1)


def get_complaint_count_for_cluster(db: Session, cluster_id: int) -> int:
    return db.query(models.Complaint).filter_by(cluster_id=cluster_id).count()
