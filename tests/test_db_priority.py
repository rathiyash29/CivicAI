"""Tests for the DB-backed priority engine (backend/db_priority.py)."""
import pytest

from backend import db_priority
from database import models


def _seed_scale(db, location, n):
    """Insert n complaints in the same location+category and return them."""
    out = []
    for i in range(n):
        c = models.Complaint(
            text=f"complaint number {i} about a problem in this area",
            category="Road Infrastructure", severity="Medium", urgency="Medium",
            location_id=location.id,
        )
        db.add(c)
        out.append(c)
    db.commit()
    return out


# --- weights ---------------------------------------------------------------

def test_weights_are_30_25_20_15_10():
    assert db_priority.WEIGHTS == {
        "citizen_demand": 0.30,
        "infrastructure_gap": 0.25,
        "population_impact": 0.20,
        "urgency": 0.15,
        "investment_gap": 0.10,
    }
    assert sum(db_priority.WEIGHTS.values()) == pytest.approx(1.0)


def test_score_is_weighted_sum_of_factors(clean_db, make_location):
    """The returned score must be exactly the 30/25/20/15/10 blend."""
    loc = make_location("Kothrud")
    complaint = models.Complaint(text="x", category="Road Infrastructure",
                                 severity="High", urgency="High",
                                 location_id=loc.id)
    clean_db.add(complaint)
    clean_db.commit()

    clean_db.add(models.Demographics(location_id=loc.id, population=100_000))
    clean_db.add(models.Infrastructure(location_id=loc.id, category="Road Infrastructure",
                                      gap_score=80.0))
    clean_db.add(models.Investment(location_id=loc.id, category="Road Infrastructure",
                                   amount_allocated=10.0))
    clean_db.commit()

    result = db_priority.compute_priority(clean_db, complaint)
    f = result["factors"]

    expected = round(
        f["citizen_demand"] * 0.30
        + f["infrastructure_gap"] * 0.25
        + f["population_impact"] * 0.20
        + f["urgency"] * 0.15
        + f["investment_gap"] * 0.10, 2)
    assert result["priority_score"] == pytest.approx(expected, abs=0.01)
    # 80 is the only non-default value we injected, and it must show up.
    assert f["infrastructure_gap"] == 80.0
    assert f["urgency"] == 90.0


def test_score_stays_within_0_100(clean_db, make_location):
    loc = make_location("Aundh")
    c = models.Complaint(text="x", category="Healthcare", severity="High",
                         urgency="High", location_id=loc.id)
    clean_db.add(c)
    clean_db.commit()
    for _ in range(60):
        clean_db.add(models.Complaint(text="y", category="Healthcare",
                                      severity="High", urgency="High",
                                      location_id=loc.id))
    clean_db.commit()

    r = db_priority.compute_priority(clean_db, c)
    assert 0 <= r["priority_score"] <= 100
    assert r["priority_level"] in ("Low", "Medium", "High")


@pytest.mark.parametrize("label,ceiling", [
    ("Low", 39.0), ("Medium", 69.0), ("High", 100.0),
])
def test_level_bands_match_spec(label, ceiling):
    assert db_priority._level_for(ceiling) == label
    assert db_priority._level_for(0) == "Low"
    assert db_priority._level_for(100) == "High"


# --- citizen demand must come from real complaint volume --------------------

def test_citizen_demand_rises_with_actual_complaint_count(clean_db, make_location):
    make_location("Kothrud")
    scores = []
    for n in (1, 3, 5, 10, 20):
        clean_db.query(models.Complaint).delete()
        clean_db.commit()
        clean_db.expunge_all()
        # re-fetch: expunge_all detaches the previously returned instance
        loc = clean_db.query(models.Location).filter_by(ward="Kothrud").one()
        rows = _seed_scale(clean_db, loc, n)
        scores.append(db_priority.get_citizen_demand(clean_db, rows[0]))

    assert scores == sorted(scores), f"demand not monotonic: {scores}"
    assert scores[-1] > scores[0], "more complaints must mean more demand"


def test_citizen_demand_is_not_just_severity_and_urgency(clean_db, make_location):
    """
    Two complaints with identical severity/urgency but different real-world
    volume must get different demand scores. This is the specific defect
    called out in the review of the mock engine.
    """
    loc_a = make_location("Kothrud")
    loc_b = make_location("Kondhwa")

    quiet = models.Complaint(text="pothole", category="Road Infrastructure",
                             severity="High", urgency="High", location_id=loc_a.id)
    clean_db.add(quiet)
    clean_db.commit()

    loud = models.Complaint(text="pothole", category="Road Infrastructure",
                            severity="High", urgency="High", location_id=loc_b.id)
    clean_db.add(loud)
    _seed_scale(clean_db, loc_b, 12)
    clean_db.commit()

    assert db_priority.get_citizen_demand(clean_db, quiet) == 16.7
    assert db_priority.get_citizen_demand(clean_db, loud) > 65.0


def test_cluster_size_drives_demand_when_clustered(clean_db, make_location):
    loc = make_location("Kothrud")
    cluster = models.IssueCluster(label="c", category="Water Supply", ward="Kothrud",
                                  complaint_count=25)
    clean_db.add(cluster)
    clean_db.commit()
    c = models.Complaint(text="no water", category="Water Supply",
                         location_id=loc.id, cluster_id=cluster.id)
    clean_db.add(c)
    clean_db.commit()

    count, basis = db_priority.get_demand_group_count(clean_db, c)
    assert basis == "cluster"
    assert count == 25
    # 25 complaints on the saturating curve (half point 5) -> 83.3
    assert db_priority.get_citizen_demand(clean_db, c) == 83.3


# --- factors sourced from the database -------------------------------------

def test_infrastructure_gap_comes_from_database(clean_db, make_location):
    loc = make_location("Kondhwa")
    clean_db.add(models.Infrastructure(location_id=loc.id, category="Water Supply",
                                      gap_score=77.0))
    clean_db.commit()
    c = models.Complaint(text="x", category="Water Supply", location_id=loc.id)
    clean_db.add(c)
    clean_db.commit()

    assert db_priority.compute_factors(clean_db, c)["infrastructure_gap"] == 77.0


def test_investment_gap_comes_from_database(clean_db, make_location):
    poor = make_location("Kondhwa")
    rich = make_location("Aundh")
    clean_db.add(models.Investment(location_id=poor.id, category="Education",
                                   amount_allocated=10.0))
    clean_db.add(models.Investment(location_id=rich.id, category="Education",
                                   amount_allocated=90.0))
    clean_db.commit()

    c_poor = models.Complaint(text="x", category="Education", location_id=poor.id)
    c_rich = models.Complaint(text="x", category="Education", location_id=rich.id)
    clean_db.add_all([c_poor, c_rich])
    clean_db.commit()

    assert db_priority.compute_factors(clean_db, c_poor)["investment_gap"] == 90.0
    assert db_priority.compute_factors(clean_db, c_rich)["investment_gap"] == 10.0


def test_population_impact_comes_from_demographics(clean_db, make_location):
    small = make_location("Shivajinagar")
    big = make_location("Kondhwa")
    clean_db.add(models.Demographics(location_id=small.id, population=80_000))
    clean_db.add(models.Demographics(location_id=big.id, population=320_000))
    clean_db.commit()

    c_small = models.Complaint(text="x", location_id=small.id)
    c_big = models.Complaint(text="x", location_id=big.id)
    clean_db.add_all([c_small, c_big])
    clean_db.commit()

    assert db_priority.compute_factors(clean_db, c_big)["population_impact"] == 100.0
    assert db_priority.compute_factors(clean_db, c_small)["population_impact"] == 25.0


def test_missing_data_falls_back_to_neutral_defaults(clean_db):
    """A complaint with no location must still score, not crash."""
    c = models.Complaint(text="orphan", category="Other", severity="Medium",
                         urgency="Medium")
    clean_db.add(c)
    clean_db.commit()

    f = db_priority.compute_factors(clean_db, c)
    assert f["infrastructure_gap"] == 50.0
    assert f["population_impact"] == 30.0
    assert f["investment_gap"] == 50.0
    assert db_priority.compute_priority(clean_db, c)["priority_score"] > 0


# --- persistence + batch ---------------------------------------------------

def test_compute_priority_persists_onto_the_row(clean_db, make_location):
    loc = make_location("Kothrud")
    c = models.Complaint(text="x", severity="High", urgency="High", location_id=loc.id)
    clean_db.add(c)
    clean_db.commit()

    r = db_priority.compute_priority(clean_db, c)
    clean_db.commit()
    clean_db.refresh(c)

    assert c.priority_score == r["priority_score"]
    assert c.priority_level == r["priority_level"]


def test_score_all_pending_only_scores_unscored_rows(clean_db, make_location):
    loc = make_location("Kothrud")
    _seed_scale(clean_db, loc, 3)
    first = db_priority.score_all_pending(clean_db)
    assert first["scored"] == 3
    assert first["failed"] == []

    second = db_priority.score_all_pending(clean_db)
    assert second["scored"] == 0


def test_score_all_pending_reports_failures_without_aborting(clean_db, make_location):
    """One unwritable row must not lose the whole batch."""
    loc = make_location("Kothrud")
    _seed_scale(clean_db, loc, 2)
    broken = models.Complaint(text="broken", category=None, location_id=loc.id)
    clean_db.add(broken)
    clean_db.commit()

    original = db_priority.compute_priority
    calls = {"n": 0}

    def flaky(session, complaint):
        calls["n"] += 1
        if complaint.id == broken.id:
            raise RuntimeError("simulated failure")
        return original(session, complaint)

    db_priority.compute_priority = flaky
    try:
        out = db_priority.score_all_pending(clean_db)
    finally:
        db_priority.compute_priority = original

    assert out["scored"] == 2
    assert len(out["failed"]) == 1
    assert out["failed"][0]["complaint_id"] == broken.id
