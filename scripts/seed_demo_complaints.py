"""
Seeds a handful of complaints on top of the loaded dataset so you can run
the full Member 2 pipeline (priority -> cluster -> hotspots -> recommendations)
without waiting on Member 1's citizen frontend / AI engine.

Run:
    python -m data.data_loader --load-all   # first, to populate wards
    python -m scripts.seed_demo_complaints
"""
from database.db import session_scope, init_db
from database import models
from backend import priority, duplicates, hotspots, recommendations
from data.data_loader import PUNE_WARDS

SAMPLE_TEXTS = [
    "Large potholes near college causing accidents on the main road",
    "Road full of potholes near the college gate, very dangerous for students",
    "Streetlights not working for the last two weeks on the main stretch",
    "No streetlights on this road at night, unsafe for pedestrians",
    "Water supply has been irregular for the past month in this area",
]


def run():
    init_db()
    with session_scope() as db:
        loc = db.query(models.Location).filter_by(ward=PUNE_WARDS[0]).first()
        if not loc:
            loc = models.Location(ward=PUNE_WARDS[0], city="Pune")
            db.add(loc)
            db.flush()

        for i, text in enumerate(SAMPLE_TEXTS):
            category = "Road Infrastructure" if "road" in text.lower() or "pothole" in text.lower() else (
                "Electricity" if "streetlight" in text.lower() else "Water Supply"
            )
            complaint = models.Complaint(
                text=text,
                language="English",
                category=category,
                severity="High" if i % 2 == 0 else "Medium",
                urgency="High" if i % 2 == 0 else "Medium",
                affected_group="Students" if "college" in text.lower() else "Residents",
                location_id=loc.id,
            )
            db.add(complaint)
        db.commit()
        print(f"Seeded {len(SAMPLE_TEXTS)} complaints in {loc.ward}")

    with session_scope() as db:
        clusters = duplicates.cluster_all_unclustered(db)
        print(f"Formed {len(clusters)} clusters")

    with session_scope() as db:
        results = priority.score_all_pending(db)
        print(f"Scored {len(results)} complaints")

    with session_scope() as db:
        hs = hotspots.compute_hotspots(db, min_complaints=1)
        print("Hotspots:", hs)

    with session_scope() as db:
        recs = recommendations.generate_all(db)
        print("Recommendations:", recs)


if __name__ == "__main__":
    run()
