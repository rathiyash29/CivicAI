"""Tests for DB-backed hotspot aggregation (backend/db_hotspots.py)."""
import pytest

from backend import db_hotspots as DH
from database import models


def _add(db, location, category, severity, n=1):
    for _ in range(n):
        db.add(models.Complaint(text=f"{category} report {severity}",
                                category=category, severity=severity,
                                location_id=location.id if location else None))
    db.commit()


# --- scoring ---------------------------------------------------------------

def test_score_is_zero_for_empty_group():
    assert DH.hotspot_score(0, 0) == 0.0


def test_score_is_bounded_and_monotonic():
    # The curve approaches but never reaches 100, which is the point: a busy
    # ward and a busier one must stay distinguishable.
    assert DH.hotspot_score(500, 400) < 100.0
    low = DH.hotspot_score(2, 0)
    mid = DH.hotspot_score(6, 2)
    high = DH.hotspot_score(20, 15)
    assert 0 < low < mid < high < 100.0
    assert DH.hotspot_score(10_000, 10_000) <= 100.0


def test_severity_raises_the_score_at_equal_volume():
    mild = DH.hotspot_score(10, 0)
    severe = DH.hotspot_score(10, 10)
    assert severe > mild


def test_small_groups_stay_low_and_busy_ones_go_high():
    assert DH._level_for(DH.hotspot_score(1, 0)) == "Low"
    assert DH._level_for(DH.hotspot_score(3, 1)) == "Low"
    assert DH._level_for(DH.hotspot_score(20, 15)) == "High"


def test_score_does_not_saturate_like_the_old_formula():
    """count*10 + high*5 hit 100 after ten complaints; the new curve must not."""
    assert DH.hotspot_score(10, 0) < 100.0
    assert DH.hotspot_score(10, 5) < 100.0


# --- aggregation -----------------------------------------------------------

def test_aggregates_by_location_and_category(clean_db, make_location):
    a = make_location("Kothrud")
    b = make_location("Baner")
    _add(clean_db, a, "Road Infrastructure", "High", n=6)
    _add(clean_db, a, "Water Supply", "Medium", n=2)
    _add(clean_db, b, "Road Infrastructure", "High", n=3)
    clean_db.commit()

    hs = {h["location"] + "|" + h["category"]: h for h in DH.compute_hotspots(clean_db, 1)}
    assert len(hs) == 3
    assert hs["Kothrud|Road Infrastructure"]["complaint_count"] == 6
    assert hs["Kothrud|Road Infrastructure"]["high_severity_count"] == 6
    assert hs["Kothrud|Water Supply"]["complaint_count"] == 2
    assert hs["Kothrud|Water Supply"]["high_severity_count"] == 0
    assert hs["Baner|Road Infrastructure"]["complaint_count"] == 3


def test_results_are_sorted_worst_first(clean_db, make_location):
    quiet = make_location("Aundh")
    busy = make_location("Kondhwa")
    _add(clean_db, quiet, "Education", "Low", n=2)
    _add(clean_db, busy, "Sanitation", "High", n=15)
    clean_db.commit()

    hs = DH.compute_hotspots(clean_db, min_complaints=1)
    assert hs[0]["location"] == "Kondhwa"
    scores = [h["hotspot_score"] for h in hs]
    assert scores == sorted(scores, reverse=True)


def test_min_complaints_filters_noise(clean_db, make_location):
    loc = make_location("Yerawada")
    _add(clean_db, loc, "Healthcare", "High", n=2)
    _add(clean_db, loc, "Education", "High", n=5)
    clean_db.commit()

    assert len(DH.compute_hotspots(clean_db, min_complaints=3)) == 1
    assert len(DH.compute_hotspots(clean_db, min_complaints=1)) == 2


def test_limit_trims_the_list(clean_db, make_location):
    loc = make_location("Wanowrie")
    for cat in ("Road Infrastructure", "Water Supply", "Electricity"):
        _add(clean_db, loc, cat, "High", n=4)
    clean_db.commit()

    assert len(DH.compute_hotspots(clean_db, min_complaints=1, limit=2)) == 2


def test_empty_database(clean_db):
    assert DH.compute_hotspots(clean_db) == []


def test_complaints_without_location_group_as_unassigned(clean_db):
    _add(clean_db, None, "Other", "Medium", n=4)
    hs = DH.compute_hotspots(clean_db, min_complaints=1)
    assert len(hs) == 1
    assert hs[0]["location"] == "Unassigned"


def test_missing_category_becomes_other(clean_db, make_location):
    loc = make_location("Katraj")
    for _ in range(3):
        clean_db.add(models.Complaint(text="unclassified", category=None,
                                      severity="Medium", location_id=loc.id))
    clean_db.commit()
    hs = DH.compute_hotspots(clean_db, min_complaints=1)
    assert hs[0]["category"] == "Other"


# --- contract compatibility with the mock hotspots.py ----------------------

def test_output_keys_match_the_mock_engine(clean_db, make_location):
    """Member 3's dashboard can consume either engine unchanged."""
    from backend import hotspots as mock_hotspots

    loc = make_location("Kothrud")
    _add(clean_db, loc, "Road Infrastructure", "High", n=4)
    clean_db.commit()

    mine = set(DH.compute_hotspots(clean_db, min_complaints=1)[0])
    theirs = set(mock_hotspots.detect_hotspots()[0])
    assert theirs <= mine, f"missing keys the existing engine provides: {theirs - mine}"


# --- cluster linkage (additive) ---------------------------------------------
#
# A hotspot is an aggregate over a (ward, category) scope; a cluster is a text
# similarity group inside that same scope. So the join between them is by scope,
# and it is 1:N -- one scope can hold several clusters. These pin that down so
# a later "simplification" to a single cluster_id cannot slip in.


def _cluster(db, ward, category, label="c"):
    row = models.IssueCluster(label=label, ward=ward, category=category,
                              complaint_count=0)
    db.add(row)
    db.commit()
    return row


def test_hotspot_cluster_ids_match_its_scope(clean_db, make_location):
    loc = make_location("Kothrud")
    _add(clean_db, loc, "Road Infrastructure", "High", n=4)
    inside = _cluster(clean_db, "Kothrud", "Road Infrastructure")
    clean_db.commit()

    hs = DH.compute_hotspots(clean_db, min_complaints=1)[0]
    assert hs["cluster_ids"] == [inside.id]


def test_cluster_ids_is_always_a_list_even_when_empty(clean_db, make_location):
    loc = make_location("Kothrud")
    _add(clean_db, loc, "Road Infrastructure", "High", n=3)
    clean_db.commit()

    hs = DH.compute_hotspots(clean_db, min_complaints=1)[0]
    assert isinstance(hs["cluster_ids"], list)
    assert hs["cluster_ids"] == []


def test_multiple_clusters_in_one_scope_all_appear(clean_db, make_location):
    """
    The 1:N case. Picking one cluster out of a scope would tell an officer a
    fact the data does not support, so every id in the scope must be returned.
    """
    loc = make_location("Kothrud")
    _add(clean_db, loc, "Road Infrastructure", "High", n=5)
    first = _cluster(clean_db, "Kothrud", "Road Infrastructure", label="one")
    second = _cluster(clean_db, "Kothrud", "Road Infrastructure", label="two")
    third = _cluster(clean_db, "Kothrud", "Road Infrastructure", label="three")
    clean_db.commit()

    hs = DH.compute_hotspots(clean_db, min_complaints=1)[0]
    assert hs["cluster_ids"] == [first.id, second.id, third.id]


def test_clusters_from_other_wards_and_categories_are_excluded(clean_db, make_location):
    kothrud = make_location("Kothrud")
    baner = make_location("Baner")
    _add(clean_db, kothrud, "Road Infrastructure", "High", n=3)
    mine = _cluster(clean_db, "Kothrud", "Road Infrastructure")
    _cluster(clean_db, "Baner", "Road Infrastructure")       # different ward
    _cluster(clean_db, "Kothrud", "Water Supply")             # different category
    clean_db.commit()

    hs = DH.compute_hotspots(clean_db, min_complaints=1)[0]
    assert hs["cluster_ids"] == [mine.id]


def test_unassigned_hotspot_joins_unassigned_clusters(clean_db):
    """The 'Unassigned' bucket is a real grouping key on both sides."""
    _add(clean_db, None, "Road Infrastructure", "Medium", n=3)
    inside = _cluster(clean_db, DH.UNASSIGNED_WARD, "Road Infrastructure")
    clean_db.commit()

    hs = DH.compute_hotspots(clean_db, min_complaints=1)[0]
    assert hs["location"] == "Unassigned"
    assert hs["cluster_ids"] == [inside.id]


def test_cluster_ids_match_the_clustering_engine(clean_db, make_location):
    """End to end: clusters created by db_duplicates are the ones linked."""
    from backend import db_duplicates as DD

    loc = make_location("Kothrud")
    for text in ("huge potholes on the road", "road full of potholes, dangerous",
                 "no water supply for two days", "water supply missing in colony"):
        clean_db.add(models.Complaint(text=text, category="Road Infrastructure",
                                      severity="Medium", urgency="Medium",
                                      location_id=loc.id))
    clean_db.commit()
    DD.cluster_all_unclustered(clean_db)

    expected = sorted(c.id for c in clean_db.query(models.IssueCluster)
                      .filter_by(ward="Kothrud", category="Road Infrastructure").all())
    hs = DH.compute_hotspots(clean_db, min_complaints=1)[0]
    assert hs["cluster_ids"] == expected
    assert hs["cluster_ids"], "the engine created clusters, so the join must find them"


# --- location passthrough (additive) ----------------------------------------


def test_coordinates_are_passed_through_when_present(clean_db, make_location):
    loc = make_location("Kothrud")
    loc.latitude = 18.5074
    loc.longitude = 73.8077
    loc.area = "Kothrud East"
    clean_db.commit()
    _add(clean_db, loc, "Road Infrastructure", "High", n=3)

    hs = DH.compute_hotspots(clean_db, min_complaints=1)[0]
    assert hs["latitude"] == 18.5074
    assert hs["longitude"] == 73.8077
    assert hs["area"] == "Kothrud East"


def test_coordinates_are_null_not_invented_when_missing(clean_db, make_location):
    loc = make_location("Kothrud")  # no latitude/longitude/area recorded
    _add(clean_db, loc, "Road Infrastructure", "High", n=3)

    hs = DH.compute_hotspots(clean_db, min_complaints=1)[0]
    assert hs["latitude"] is None
    assert hs["longitude"] is None
    assert hs["area"] is None


def test_unassigned_hotspot_has_no_location_record(clean_db):
    _add(clean_db, None, "Road Infrastructure", "Medium", n=3)
    hs = DH.compute_hotspots(clean_db, min_complaints=1)[0]
    assert (hs["area"], hs["latitude"], hs["longitude"]) == (None, None, None)
