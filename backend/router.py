"""
Member 2's FastAPI router.

Mounted by the app entrypoint with:
    from backend.router import router as intelligence_router
    app.include_router(intelligence_router, prefix="/intelligence", tags=["intelligence"])

The `prefix` is required, not cosmetic: `main.py` already serves `/hotspots`
from the mock engine, so mounting without it would shadow the existing
route.

The data-driven engines live in `db_priority`, `db_duplicates` and
`db_hotspots`. The mock `priority` / `duplicates` / `hotspots` modules belong
to Member 1's live endpoints and are deliberately left alone.
"""
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from database import models
from backend.authorization import require_officer
from backend import db_priority, db_duplicates, db_hotspots, recommendations, bigquery_client

# The officer requirement is a *router-level* dependency, not a per-endpoint
# one. It runs before every route below -- reads and mutations alike -- and any
# endpoint added to this router in future is protected automatically instead of
# relying on the author remembering to add a guard.
router = APIRouter(dependencies=[Depends(require_officer)])


def _require_complaint(db: Session, complaint_id: int) -> models.Complaint:
    complaint = db.query(models.Complaint).filter_by(id=complaint_id).first()
    if not complaint:
        raise HTTPException(404, "Complaint not found")
    return complaint


@router.get("/stats")
def get_data_engine_stats(db: Session = Depends(get_db)):
    """Row counts per table, so a judge can see the pipeline is really wired."""
    return {
        "locations": db.query(models.Location).count(),
        "complaints": db.query(models.Complaint).count(),
        "scored_complaints": db.query(models.Complaint)
                            .filter(models.Complaint.priority_score.isnot(None)).count(),
        "issue_clusters": db.query(models.IssueCluster).count(),
        "infrastructure": db.query(models.Infrastructure).count(),
        "demographics": db.query(models.Demographics).count(),
        "investments": db.query(models.Investment).count(),
        "recommendations": db.query(models.Recommendation).count(),
    }


# NOTE: declared before /priority/{complaint_id} on purpose. Starlette matches
# in declaration order, so the reverse order would swallow "score-all" as a
# complaint_id and return 422.
@router.post("/priority/score-all")
def score_all(db: Session = Depends(get_db)):
    return db_priority.score_all_pending(db)


@router.post("/priority/{complaint_id}")
def score_complaint(complaint_id: int, db: Session = Depends(get_db)):
    complaint = _require_complaint(db, complaint_id)
    result = db_priority.compute_priority(db, complaint)
    db.commit()
    return result


@router.get("/duplicates/{complaint_id}")
def get_duplicates(complaint_id: int, db: Session = Depends(get_db)):
    complaint = _require_complaint(db, complaint_id)
    return {
        "complaint_id": complaint_id,
        "threshold": db_duplicates.SIMILARITY_THRESHOLD,
        "duplicates": db_duplicates.find_duplicates(db, complaint),
    }


@router.post("/cluster")
def run_clustering(db: Session = Depends(get_db)):
    clusters = db_duplicates.cluster_all_unclustered(db)
    return {
        "clusters_created": len(clusters),
        "clusters": [
            {"id": c.id, "label": c.label, "ward": c.ward,
             "category": c.category, "complaint_count": c.complaint_count}
            for c in clusters
        ],
    }


@router.get("/hotspots")
def get_hotspots(
    min_complaints: int = db_hotspots.DEFAULT_MIN_COMPLAINTS,
    limit: int = 0,
    db: Session = Depends(get_db),
):
    return {
        "hotspots": db_hotspots.compute_hotspots(
            db, min_complaints=min_complaints, limit=limit or None
        )
    }


@router.get("/recommendations")
def get_recommendations(db: Session = Depends(get_db)):
    return {"recommendations": recommendations.generate_all(db)}


@router.get("/recommendations/{cluster_id}")
def get_recommendation_for_cluster(cluster_id: int, db: Session = Depends(get_db)):
    cluster = db.query(models.IssueCluster).filter_by(id=cluster_id).first()
    if not cluster:
        raise HTTPException(404, "Cluster not found")
    return recommendations.generate_recommendation(db, cluster)


@router.post("/sync/bigquery")
def sync_to_bigquery(db: Session = Depends(get_db)):
    """
    Optional: mirror scored complaints into BigQuery for ad-hoc analytics.

    Reports what actually happened. When the integration is switched off --
    the default, so local development stays free -- this says so instead of
    claiming rows were uploaded.
    """
    if not bigquery_client.SYNC_ENABLED:
        return {
            "synced": 0,
            "status": "disabled",
            "detail": "BigQuery sync is off. Set ENABLE_BIGQUERY_SYNC=true to enable "
                      "(requires a GCP project and may incur billing).",
        }
    if not bigquery_client.PROJECT:
        return {
            "synced": 0,
            "status": "not_configured",
            "detail": "ENABLE_BIGQUERY_SYNC is on but BIGQUERY_PROJECT is not set.",
        }

    rows = (
        db.query(models.Complaint)
        .filter(models.Complaint.priority_score.isnot(None))
        .all()
    )
    if not rows:
        return {"synced": 0, "status": "nothing_to_sync",
                "detail": "No scored complaints yet."}

    df = pd.DataFrame([{
        "complaint_id": r.id,
        "category": r.category,
        "severity": r.severity,
        "urgency": r.urgency,
        "priority_score": r.priority_score,
        "priority_level": r.priority_level,
        "ward": r.location.ward if r.location else None,
    } for r in rows])

    try:
        bigquery_client.sync_complaints(df)
    except Exception as exc:  # noqa: BLE001 - analytics must never break the API
        return {"synced": 0, "status": "error", "detail": str(exc)}

    return {"synced": len(df), "status": "ok",
            "detail": f"Uploaded {len(df)} rows to BigQuery."}
