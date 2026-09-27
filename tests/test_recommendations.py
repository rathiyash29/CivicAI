"""Tests for recommendation generation, focused on idempotency."""
from backend import recommendations
from database import models

REQUIRED_FIELDS = {
    "cluster_id", "location", "action", "reason", "evidence",
    "priority_score", "priority_level", "estimated_affected_population",
}


def _cluster(db, ward="Kothrud", category="Road Infrastructure", members=4,
             priority=80.0):
    c = models.IssueCluster(label=f"{category} - {ward}", category=category, ward=ward)
    db.add(c)
    db.commit()
    loc = db.query(models.Location).filter_by(ward=ward).first()
    if loc is None:
        loc = models.Location(ward=ward, city="Pune")
        db.add(loc)
        db.commit()
    if not db.query(models.Demographics).filter_by(location_id=loc.id).first():
        db.add(models.Demographics(location_id=loc.id, population=200_000,
                                   source="test fixture"))
        db.commit()
    for _ in range(members):
        db.add(models.Complaint(text="issue", category=category, severity="High",
                                location_id=loc.id, cluster_id=c.id,
                                priority_score=priority))
    db.commit()
    return c


def test_recommendation_contains_every_contract_field(clean_db):
    cluster = _cluster(clean_db)
    rec = recommendations.generate_recommendation(clean_db, cluster)
    assert REQUIRED_FIELDS <= set(rec)
    assert rec["location"] == "Kothrud"
    assert rec["action"]
    assert rec["reason"]
    assert isinstance(rec["evidence"], dict)
    assert rec["priority_score"] == 80.0
    assert rec["priority_level"] == "High"
    assert rec["estimated_affected_population"] is not None


# --- the regression this fixes ---------------------------------------------

def test_generating_twice_does_not_duplicate_rows(clean_db):
    cluster = _cluster(clean_db)
    recommendations.generate_recommendation(clean_db, cluster)
    assert clean_db.query(models.Recommendation).count() == 1

    recommendations.generate_recommendation(clean_db, cluster)
    assert clean_db.query(models.Recommendation).count() == 1, \
        "dashboard polling created a duplicate Recommendation row"


def test_generate_all_is_idempotent(clean_db):
    _cluster(clean_db, "Kothrud", "Road Infrastructure")
    _cluster(clean_db, "Kondhwa", "Water Supply")

    first = recommendations.generate_all(clean_db)
    rows_after_first = clean_db.query(models.Recommendation).count()
    second = recommendations.generate_all(clean_db)

    assert len(first) == 2
    assert len(second) == 2
    assert clean_db.query(models.Recommendation).count() == rows_after_first == 2


def test_upsert_refreshes_values_in_place(clean_db):
    cluster = _cluster(clean_db, priority=20.0)
    first = recommendations.generate_recommendation(clean_db, cluster)
    assert first["priority_level"] == "Low"

    for c in clean_db.query(models.Complaint).filter_by(cluster_id=cluster.id).all():
        c.priority_score = 95.0
    clean_db.commit()

    second = recommendations.generate_recommendation(clean_db, cluster)
    assert second["priority_level"] == "High"
    assert second["priority_score"] == 95.0

    stored = clean_db.query(models.Recommendation).one()
    assert stored.priority_score == 95.0


def test_response_shape_is_preserved(clean_db):
    """Idempotency must not change the payload Member 3 renders."""
    cluster = _cluster(clean_db)
    rec = recommendations.generate_recommendation(clean_db, cluster)
    assert set(rec) == REQUIRED_FIELDS
    assert set(rec["evidence"]) == {
        "related_complaints", "high_severity_complaints", "infrastructure_gap",
        "population_impact", "investment_gap",
    }


# --- robustness ------------------------------------------------------------

def test_cluster_with_unknown_ward_degrades_instead_of_crashing(clean_db):
    c = models.IssueCluster(label="orphan", category="Healthcare", ward="Nowhere")
    clean_db.add(c)
    clean_db.commit()

    rec = recommendations.generate_recommendation(clean_db, c)
    assert rec["location"] == "Nowhere"
    assert rec["estimated_affected_population"] is None
    assert rec["evidence"]["infrastructure_gap"] == "Medium"


def test_empty_cluster_does_not_divide_by_zero(clean_db):
    c = models.IssueCluster(label="empty", category="Education", ward="Baner")
    clean_db.add(c)
    clean_db.commit()

    rec = recommendations.generate_recommendation(clean_db, c)
    assert rec["priority_score"] == 0.0
    assert rec["priority_level"] == "Low"


def test_unknown_category_gets_a_generic_action(clean_db):
    c = _cluster(clean_db, category="Public Transport")
    rec = recommendations.generate_recommendation(clean_db, c)
    assert "Public Transport" in rec["action"]


def test_reason_reflects_the_evidence(clean_db):
    low = _cluster(clean_db, "Aundh", "Healthcare", priority=10.0)
    rec = recommendations.generate_recommendation(clean_db, low)
    assert "High demand" in rec["reason"]
