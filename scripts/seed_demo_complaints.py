"""
Seeds demo complaints so the full Member 2 pipeline can be exercised
(priority -> cluster -> score -> hotspots -> recommendations) without
waiting on the citizen frontend or a live database.

Run:
    python -m data.data_loader --load-all   # first, to populate wards
    python -m scripts.seed_demo_complaints
"""
from database.db import session_scope, init_db
from database import models
from backend import db_priority, db_duplicates, db_hotspots, recommendations
from data.data_loader import PUNE_WARDS, SYNTHETIC_SOURCE

SAMPLE_COMPLAINTS = [
    # (ward, category, severity, urgency, text)
    ("Kothrud", "Road Infrastructure", "High", "High",
     "Large potholes near the college are causing accidents on the main road"),
    ("Kothrud", "Road Infrastructure", "High", "High",
     "The main road is full of potholes near the college gate, very dangerous for students"),
    ("Kothrud", "Electricity", "Medium", "Medium",
     "Streetlights have not been working on the main stretch for two weeks"),
    ("Kothrud", "Electricity", "Medium", "Medium",
     "There are no working street lights on this road at night, unsafe for pedestrians"),
    ("Kothrud", "Water Supply", "High", "High",
     "Water supply has been irregular for the past month in this area"),
    ("Hadapsar", "Water Supply", "High", "High",
     "No water supply in our residential colony for two days now"),
    ("Hadapsar", "Sanitation", "Medium", "Medium",
     "Garbage has not been collected for a week in our society"),
    ("Baner", "Road Infrastructure", "High", "High",
     "Big pothole on the main road causes accidents for vehicles"),
    ("Baner", "Electricity", "Low", "Low",
     "One streetlight near the park is broken"),
    ("Viman Nagar", "Public Transport", "Medium", "Medium",
     "Bus frequency is very low in the morning during peak hours"),
    ("Viman Nagar", "Healthcare", "High", "High",
     "There is no ambulance available at the clinic during emergencies"),
    ("Kondhwa", "Sanitation", "High", "High",
     "Large garbage dump near the temple is creating a health hazard"),
]


def seed_complaints(db) -> int:
    """Insert the demo complaints, skipping any that are already present."""
    locations = {}
    existing = {c.text for c in db.query(models.Complaint).all()}
    added = 0

    for ward, category, severity, urgency, text in SAMPLE_COMPLAINTS:
        if text in existing:
            continue
        if ward not in locations:
            loc = db.query(models.Location).filter_by(ward=ward, city="Pune").first()
            if loc is None:
                loc = models.Location(ward=ward, city="Pune")
                db.add(loc)
                db.flush()
            locations[ward] = loc

        db.add(models.Complaint(
            text=text,
            language="English",
            category=category,
            severity=severity,
            urgency=urgency,
            affected_group="Residents",
            issue_summary=f"{category} issue reported in {ward}.",
            location_id=locations[ward].id,
        ))
        added += 1

    db.commit()
    return added


def run() -> dict:
    init_db()

    with session_scope() as db:
        added = seed_complaints(db)
    print(f"Seeded {added} demo complaints ({SYNTHETIC_SOURCE})")

    with session_scope() as db:
        clusters = db_duplicates.cluster_all_unclustered(db)
    print(f"Formed {len(clusters)} new clusters")

    with session_scope() as db:
        scored = db_priority.score_all_pending(db)
    print(f"Scored {scored['scored']} complaints"
          + (f", {len(scored['failed'])} failed" if scored["failed"] else ""))

    with session_scope() as db:
        hs = db_hotspots.compute_hotspots(db, min_complaints=1)
    print("Hotspots:")
    for h in hs:
        print(f"  {h['hotspot_level']:6} {h['hotspot_score']:>5}  "
              f"{h['location']:14} {h['category']:20} "
              f"({h['complaint_count']} complaints, {h['high_severity_count']} high)")

    with session_scope() as db:
        recs = recommendations.generate_all(db)
    print(f"Recommendations ({len(recs)}):")
    for r in recs:
        print(f"  [{r['priority_level']}] {r['priority_score']:>5}  {r['location']}: {r['action']}")
        print(f"      reason: {r['reason']}")
        print(f"      affected: {r['estimated_affected_population']}")

    return {
        "wards": len(PUNE_WARDS),
        "complaints": added,
        "clusters": len(clusters),
        "scored": scored["scored"],
        "hotspots": len(hs),
        "recommendations": len(recs),
    }


if __name__ == "__main__":
    run()
