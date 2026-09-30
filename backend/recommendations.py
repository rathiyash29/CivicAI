"""
Recommendation engine.

Input : priority + infrastructure gap + population impact + investment gap
        + complaint cluster.
Output: recommended intervention, reason, evidence, priority,
        estimated affected population — matches the contract Member 3 renders as-is.
"""
import logging

from sqlalchemy.orm import Session

from database import models
from backend import data_engine

log = logging.getLogger("recommendations")

ACTION_BY_CATEGORY = {
    "Road Infrastructure": "Road rehabilitation",
    "Water Supply": "Water pipeline upgrade",
    "Electricity": "Electrical grid reinforcement",
    "Sanitation": "Sanitation infrastructure expansion",
    "Healthcare": "Primary healthcare center upgrade",
    "Education": "School infrastructure investment",
}


def upsert_recommendation(
    db: Session,
    cluster: models.IssueCluster,
    **fields,
) -> models.Recommendation:
    """
    Create or update the single recommendation belonging to a cluster.

    A dashboard polls this endpoint repeatedly, so generating a fresh row on
    every call would grow the table without bound and give the UI an
    ever-lengthening history of what is really one recommendation. There is
    exactly one recommendation per cluster, refreshed in place.
    """
    rec = (
        db.query(models.Recommendation)
        .filter_by(cluster_id=cluster.id)
        .first()
    )
    if rec is None:
        rec = models.Recommendation(cluster_id=cluster.id)
        db.add(rec)

    for key, value in fields.items():
        setattr(rec, key, value)

    db.commit()
    db.refresh(rec)
    return rec


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

    rec = upsert_recommendation(
        db,
        cluster,
        action=action,
        reason=reason,
        evidence=evidence,
        priority_score=avg_priority,
        estimated_affected_population=estimated_affected,
    )

    return {
        # `recommendation_id` is the row this recommendation is stored as, and
        # is the key the officer decision endpoints are called with
        # (`/projects/recommendations/{recommendation_id}/approve` and friends).
        # It was missing from this projection, so a client could read a
        # recommendation, see its evidence, and then have no id to decide on.
        # `cluster_id` is unchanged: it stays the issue cluster this was
        # generated from, which is a different thing from the recommendation's
        # own primary key.
        "recommendation_id": rec.id,
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


def cluster_has_members(db: Session, cluster: models.IssueCluster) -> bool:
    """
    Does this cluster have at least one real complaint?

    Counted from the complaints themselves rather than read from
    `IssueCluster.complaint_count`. That column is a cache maintained by the
    clustering code, and using it here would make this decision depend on
    whether a reconciliation had happened to run.
    """
    return db.query(models.Complaint).filter_by(cluster_id=cluster.id).count() > 0


def _discard_stale_recommendation(db: Session, cluster: models.IssueCluster) -> bool:
    """
    Drop the recommendation of a cluster that no longer has any complaints.

    Returns True when a row was removed. A recommendation that an officer has
    already acted on is left alone and logged: the decision ledger and the
    project both point at it, and deleting it would break those links and
    destroy the record of the decision.
    """
    rec = db.query(models.Recommendation).filter_by(cluster_id=cluster.id).first()
    if rec is None:
        return False

    decided = db.query(models.OfficerDecision).filter_by(recommendation_id=rec.id).count()
    in_use = db.query(models.Project).filter_by(recommendation_id=rec.id).count()
    if decided or in_use:
        log.warning(
            "Cluster %s has no complaints but its recommendation %s carries %d "
            "project(s) and %d officer decision(s); keeping it rather than "
            "breaking those links",
            cluster.id, rec.id, in_use, decided,
        )
        return False

    db.delete(rec)
    log.info("Removed stale recommendation %s for empty cluster %s", rec.id, cluster.id)
    return True


def generate_all(db: Session) -> list[dict]:
    """
    Refresh the recommendation for every cluster that actually has complaints.

    Clusters with no members are skipped. A cluster can end up empty after its
    complaints move elsewhere (a re-cluster, a data reload), and a
    recommendation for one of those says nothing an officer can act on: zero
    related complaints, a priority score of 0.0 and "Low". Emitting those
    alongside real ones makes the list harder to read, and a dashboard cannot
    tell a genuine "Low priority, one complaint" from "this cluster is empty".

    The cluster itself is left in place -- it is a real historical group, and
    `issue_clusters` rows are referenced by the clustering code and by the
    hotspot scope join. Only its recommendation is dropped.

    Membership is counted from the complaints that point at the cluster, not
    read from the cached `IssueCluster.complaint_count`, so a stale cache
    cannot smuggle an empty cluster back into the list.

    A stale recommendation left over from an earlier run is deleted, which keeps
    the table consistent with what this function returns. One that an officer
    has already turned into a project is kept and logged instead.

    Safe to call repeatedly.
    """
    clusters = db.query(models.IssueCluster).order_by(models.IssueCluster.id).all()
    results = []
    for c in clusters:
        if not cluster_has_members(db, c):
            _discard_stale_recommendation(db, c)
            continue
        try:
            results.append(generate_recommendation(db, c))
        except Exception:  # noqa: BLE001 - one bad cluster must not blank the dashboard
            db.rollback()
    db.commit()
    return results
