"""
Member 2's FastAPI router.

Member 1 wires this into the shared `main.py` with:
    from backend.router import router as intelligence_router
    app.include_router(intelligence_router, prefix="/intelligence", tags=["intelligence"])

Endpoints match the Member 2 -> Member 3 JSON contract in the project doc.
"""
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from database import models
from backend import priority, duplicates, hotspots, recommendations, bigquery_client

router = APIRouter()


@router.post("/priority/{complaint_id}")
def score_complaint(complaint_id: int, db: Session = Depends(get_db)):
    complaint = db.query(models.Complaint).get(complaint_id)
    if not complaint:
        raise HTTPException(404, "Complaint not found")
    result = priority.compute_priority(db, complaint)
    db.commit()
    return result


@router.post("/priority/score-all")
def score_all(db: Session = Depends(get_db)):
    return {"scored": priority.score_all_pending(db)}


@router.get("/duplicates/{complaint_id}")
def get_duplicates(complaint_id: int, db: Session = Depends(get_db)):
    complaint = db.query(models.Complaint).get(complaint_id)
    if not complaint:
        raise HTTPException(404, "Complaint not found")
    return {"complaint_id": complaint_id, "duplicates": duplicates.find_duplicates(db, complaint)}


@router.post("/cluster")
def run_clustering(db: Session = Depends(get_db)):
    clusters = duplicates.cluster_all_unclustered(db)
    return {"clusters_created": len(clusters)}


@router.get("/hotspots")
def get_hotspots(min_complaints: int = 3, db: Session = Depends(get_db)):
    return {"hotspots": hotspots.compute_hotspots(db, min_complaints=min_complaints)}


@router.get("/recommendations")
def get_recommendations(db: Session = Depends(get_db)):
    return {"recommendations": recommendations.generate_all(db)}


@router.get("/recommendations/{cluster_id}")
def get_recommendation_for_cluster(cluster_id: int, db: Session = Depends(get_db)):
    cluster = db.query(models.IssueCluster).get(cluster_id)
    if not cluster:
        raise HTTPException(404, "Cluster not found")
    return recommendations.generate_recommendation(db, cluster)


@router.post("/sync/bigquery")
def sync_to_bigquery(db: Session = Depends(get_db)):
    """Optional: mirror scored complaints into BigQuery for analytics."""
    rows = db.query(models.Complaint).filter(models.Complaint.priority_score.isnot(None)).all()
    df = pd.DataFrame([{
        "complaint_id": r.id,
        "category": r.category,
        "severity": r.severity,
        "urgency": r.urgency,
        "priority_score": r.priority_score,
        "priority_level": r.priority_level,
        "ward": r.location.ward if r.location else None,
    } for r in rows])
    if df.empty:
        return {"synced": 0, "note": "No scored complaints yet"}
    bigquery_client.sync_complaints(df)
    return {"synced": len(df)}
