"""
Tests for DB-backed duplicate detection and clustering.

The regression cases here are the ones that failed in review: real
paraphrases of the same complaint scored below threshold, and "street
lights" vs "streetlights" scored 0.0 because they share no whitespace
tokens.
"""
import pytest

from backend import db_duplicates as DD
from database import models


def _add(db, text, location, category="Road Infrastructure", **kw):
    c = models.Complaint(
        text=text, category=category, severity=kw.get("severity", "Medium"),
        urgency=kw.get("urgency", "Medium"),
        location_id=location.id if location else None,
    )
    db.add(c)
    db.commit()
    return c


# --- similarity ------------------------------------------------------------

PARAPHRASES = [
    ("There are huge potholes on the road near the college",
     "Road full of potholes near the college gate, very dangerous for students"),
    ("Street lights are not working in our area",
     "The streetlights are broken in this locality"),
    ("No water supply in our residential area for two days",
     "Water supply missing in our colony for two days"),
    ("Garbage not collected for a week in our society",
     "Garbage collection has not happened in our society for 7 days"),
    ("Big pothole on the main road causes accidents",
     "Dangerous potholes on main road leading to accidents"),
    ("Water is dirty and contaminated in the tap",
     "Contaminated dirty water coming from the tap"),
]

UNRELATED = [
    ("Potholes on the road near the college", "Water supply is irregular in the colony"),
    ("Street lights are not working", "There is a hospital nearby with no ambulance"),
    ("Water is contaminated in the tap", "The road surface is completely damaged"),
    ("No electricity for four days", "Garbage pile near the school is very unhealthy"),
    ("Broken footpath near the bus stop", "Doctors are not available at the clinic"),
    ("Street lights are not working", "The transformer in our lane keeps sparking"),
    ("The hospital has no ambulance", "The transformer in our lane keeps sparking"),
    ("Large garbage dump near the temple", "Bus frequency is very low in the morning"),
    ("Bus frequency is very low in the morning", "The school playground has no boundary wall"),
]


@pytest.mark.parametrize("a,b", PARAPHRASES)
def test_true_paraphrases_score_above_threshold(a, b):
    score = DD.similarity(a, b)
    assert score >= DD.SIMILARITY_THRESHOLD, f"{score} below threshold: {a!r} vs {b!r}"


@pytest.mark.parametrize("a,b", UNRELATED)
def test_unrelated_complaints_score_below_threshold(a, b):
    score = DD.similarity(a, b)
    assert score < DD.SIMILARITY_THRESHOLD, f"{score} false positive: {a!r} vs {b!r}"


def test_compound_word_variant_is_not_zero():
    """The specific 0.0 failure from review: no shared whitespace tokens."""
    score = DD.similarity("Street lights are not working in our area",
                          "The streetlights are broken in this locality")
    assert score > 0.0
    assert score >= DD.SIMILARITY_THRESHOLD


def test_identical_text_scores_100():
    assert DD.similarity("potholes everywhere", "potholes everywhere") == 100.0


def test_similarity_is_symmetric():
    a, b = PARAPHRASES[0]
    assert DD.similarity(a, b) == DD.similarity(b, a)


def test_empty_and_blank_text_are_safe():
    assert DD.similarity("", "potholes") == 0.0
    assert DD.similarity("   ", "") == 0.0
    assert DD.similarity("", "") == 0.0


def test_stopwords_do_not_create_similarity():
    assert DD.similarity("the of and is", "of the and is") == 0.0


# --- find_duplicates -------------------------------------------------------

def test_find_duplicates_matches_stored_rows(clean_db, make_location):
    loc = make_location("Kothrud")
    target = _add(clean_db, PARAPHRASES[0][0], loc)
    _add(clean_db, PARAPHRASES[0][1], loc)

    matches = DD.find_duplicates(clean_db, target)
    assert len(matches) == 1
    assert matches[0]["similarity"] >= DD.SIMILARITY_THRESHOLD
    assert matches[0]["location"] == "Kothrud"


def test_find_duplicates_never_matches_the_complaint_itself(clean_db, make_location):
    loc = make_location("Kothrud")
    c = _add(clean_db, "potholes everywhere on the main road", loc)
    assert DD.find_duplicates(clean_db, c) == []


def test_find_duplicates_excludes_other_wards(clean_db, make_location):
    """Location gating: identical wording in two wards is not a duplicate."""
    kothrud = make_location("Kothrud")
    baner = make_location("Baner")
    target = _add(clean_db, "potholes everywhere on the main road", kothrud)
    _add(clean_db, "potholes everywhere on the main road", baner)

    assert DD.find_duplicates(clean_db, target) == []


def test_find_duplicates_allows_ward_agnostic_when_location_missing(clean_db):
    target = _add(clean_db, "potholes everywhere on the main road", None)
    _add(clean_db, "potholes everywhere on the main road", None)
    assert len(DD.find_duplicates(clean_db, target)) == 1


def test_find_duplicates_sorted_by_similarity(clean_db, make_location):
    loc = make_location("Kothrud")
    target = _add(clean_db, "potholes on the road near the college", loc)
    _add(clean_db, "huge potholes near the college on the road", loc)
    _add(clean_db, "potholes road college", loc)

    matches = DD.find_duplicates(clean_db, target)
    scores = [m["similarity"] for m in matches]
    assert scores == sorted(scores, reverse=True)


# --- clustering ------------------------------------------------------------

def test_cluster_all_unclustered_groups_paraphrases(clean_db, make_location):
    loc = make_location("Kothrud")
    _add(clean_db, PARAPHRASES[0][0], loc)
    _add(clean_db, PARAPHRASES[0][1], loc)
    _add(clean_db, PARAPHRASES[1][0], loc, category="Electricity")
    clean_db.commit()

    clusters = DD.cluster_all_unclustered(clean_db)
    assert len(clusters) == 2, "two distinct problems should form two clusters"

    sizes = sorted(
        (db_count(clean_db, c.id) for c in clusters), reverse=True)
    assert sizes == [2, 1]
    assert clean_db.query(models.Complaint).filter(
        models.Complaint.cluster_id.is_(None)).count() == 0


def db_count(db, cluster_id):
    return db.query(models.Complaint).filter_by(cluster_id=cluster_id).count()


def test_clustering_separates_categories_in_same_ward(clean_db, make_location):
    loc = make_location("Kothrud")
    _add(clean_db, "potholes on the main road", loc, category="Road Infrastructure")
    _add(clean_db, "potholes on the main road", loc, category="Water Supply")
    clean_db.commit()

    clusters = DD.cluster_all_unclustered(clean_db)
    assert len(clusters) == 2


def test_clustering_sets_count_and_severity(clean_db, make_location):
    loc = make_location("Kothrud")
    _add(clean_db, PARAPHRASES[0][0], loc, severity="High")
    _add(clean_db, PARAPHRASES[0][1], loc, severity="Low")
    clean_db.commit()

    DD.cluster_all_unclustered(clean_db)
    cluster = clean_db.query(models.IssueCluster).one()
    assert cluster.complaint_count == 2
    assert cluster.avg_severity_score == 2.0  # (High=3 + Low=1) / 2
    assert cluster.ward == "Kothrud"
    assert cluster.category == "Road Infrastructure"


def test_cluster_all_unclustered_is_idempotent(clean_db, make_location):
    loc = make_location("Kothrud")
    _add(clean_db, PARAPHRASES[0][0], loc)
    _add(clean_db, PARAPHRASES[0][1], loc)
    clean_db.commit()

    DD.cluster_all_unclustered(clean_db)
    first = clean_db.query(models.IssueCluster).count()
    again = DD.cluster_all_unclustered(clean_db)

    assert again == [], "nothing is unclustered on a second run"
    assert clean_db.query(models.IssueCluster).count() == first


def test_clustering_handles_complaints_with_no_location(clean_db):
    _add(clean_db, "potholes on the main road", None)
    clusters = DD.cluster_all_unclustered(clean_db)
    assert len(clusters) == 1
    assert clusters[0].ward == "Unassigned"


def test_clustering_nothing_to_do(clean_db):
    assert DD.cluster_all_unclustered(clean_db) == []
