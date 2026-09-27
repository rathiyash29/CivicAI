"""
Recommendation engine.

Input : priority + infrastructure gap + population impact + investment gap
        + complaint cluster.
Output: recommended intervention, reason, evidence, priority,
        estimated affected population — matches the contract Member 3 renders as-is.
"""
from sqlalchemy.orm import Session

from database import models
from backend import data_engine

ACTION_BY_CATEGORY = {
    "Road Infrastructure": "Road rehabilitation",
    "Water Supply": "Water pipeline upgrade",
    "Electricity": "Electrical grid reinforcement",
    "Sanitation": "Sanitation infrastructure expansion",
    "Healthcare": "Primary healthcare center upgrade",
    "Education": "School infrastructure investment",
}


def generate_recommendation(db: Session, cluster: models.IssueCluster) -> dict:
    location = db.query(models.Location).filter_by(ward=cluster.ward).first()
    location_id = location.id if location else None

    infra_gap = (
        data_engine.get_infrastructure_gap(db, location_id, cluster.category)
        if location_id else 50.0
    )
    pop_impact = data_engine.get_population_impact(db, location_id) if location_id else 30.0
    invest_gap = (
        data_engine.get_investment_gap(db, location_id, cluster.category)
        if location_id else 50.0
    )

    complaints = db.query(models.Complaint).filter_by(cluster_id=cluster.id).all()
    high_severity = sum(1 for c in complaints if c.severity == "High")
    avg_priority = round(
        sum(c.priority_score or 0 for c in complaints) / len(complaints), 1
    ) if complaints else 0.0

    demo = db.query(models.Demographics).filter_by(location_id=location_id).first() if location_id else None
    estimated_affected = int(demo.population * 0.15) if demo and demo.population else None
    # 0.15 = rough share of ward population plausibly affected by a
    # localized infra issue; swap for a real catchment-area estimate
    # once Member 2's GIS data is richer.

    action = ACTION_BY_CATEGORY.get(cluster.category, f"{cluster.category} intervention")

    reason_parts = []
    if infra_gap >= 60:
        reason_parts.append("high infrastructure gap")
    if pop_impact >= 60:
        reason_parts.append("large population impact")
    if invest_gap >= 60:
        reason_parts.append("historically low investment in this area")
    if not reason_parts:
        reason_parts.append("sustained citizen demand")
    reason = "High demand and " + ", ".join(reason_parts) if len(reason_parts) else "Sustained citizen demand"

    evidence = {
        "related_complaints": len(complaints),
        "high_severity_complaints": high_severity,
        "infrastructure_gap": _label(infra_gap),
        "population_impact": _label(pop_impact),
        "investment_gap": _label(invest_gap),
    }

    rec = models.Recommendation(
        cluster_id=cluster.id,
        action=action,
        reason=reason,
        evidence=evidence,
        priority_score=avg_priority,
        estimated_affected_population=estimated_affected,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    return {
        "cluster_id": cluster.id,
        "location": cluster.ward,
        "action": rec.action,
        "reason": rec.reason,
        "evidence": evidence,
        "priority_score": avg_priority,
        "priority_level": _level(avg_priority),
        "estimated_affected_population": estimated_affected,
    }


def _label(score: float) -> str:
    if score >= 60:
        return "High"
    if score >= 35:
        return "Medium"
    return "Low"


def _level(score: float) -> str:
    return _label(score)


def generate_all(db: Session) -> list[dict]:
    clusters = db.query(models.IssueCluster).all()
    return [generate_recommendation(db, c) for c in clusters]
