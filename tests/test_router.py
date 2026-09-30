"""
Router tests: registration, ordering, and that every endpoint answers.

The headline regression from review was that four of eight endpoints raised
AttributeError at call time, because router.py referenced a DB-backed API
that did not exist. These tests pin that shut.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import router as M2
from database import models
from database.db import SessionLocal


@pytest.fixture
def app():
    application = FastAPI()
    application.include_router(M2.router, prefix="/intelligence", tags=["intelligence"])
    return application


@pytest.fixture
def officer_headers(make_auth_user):
    """Every intelligence endpoint is officer-only, so tests act as one."""
    _user, token = make_auth_user("router-officer@example.com", role="officer")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(app, officer_headers):
    return TestClient(app, headers=officer_headers)


@pytest.fixture
def seeded(clean_db, make_location):
    loc = make_location("Kothrud")
    cluster = models.IssueCluster(label="c", category="Road Infrastructure",
                                  ward="Kothrud", complaint_count=0)
    clean_db.add(cluster)
    clean_db.commit()
    a = models.Complaint(text="huge potholes on the road near the college",
                         category="Road Infrastructure", severity="High",
                         urgency="High", location_id=loc.id, cluster_id=cluster.id)
    b = models.Complaint(text="road full of potholes near the college gate",
                         category="Road Infrastructure", severity="High",
                         urgency="High", location_id=loc.id)
    clean_db.add_all([a, b])
    clean_db.commit()
    return {"db": clean_db, "location": loc, "cluster": cluster,
            "complaints": [a, b]}


# --- registration ----------------------------------------------------------

def test_router_registers_expected_paths(app):
    # `router.routes` hold paths relative to the router; the prefix is only
    # applied once the router is included, so check the mounted app.
    assert sorted(app.openapi()["paths"]) == [
        "/intelligence/cluster",
        "/intelligence/clusters/{cluster_id}",
        "/intelligence/duplicates/{complaint_id}",
        "/intelligence/hotspots",
        "/intelligence/priority/score-all",
        "/intelligence/priority/{complaint_id}",
        "/intelligence/priority/{complaint_id}/explanation",
        "/intelligence/recommendations",
        "/intelligence/recommendations/{cluster_id}",
        "/intelligence/stats",
        "/intelligence/sync/bigquery",
    ]


def test_score_all_is_declared_before_the_path_parameter():
    """
    Starlette matches in declaration order. Declared after
    /priority/{complaint_id}, the literal "score-all" would be parsed as an
    int and every call would 422.
    """
    order = [r.path for r in M2.router.routes]
    assert order.index("/priority/score-all") < order.index("/priority/{complaint_id}")


def test_router_uses_the_db_engines_not_the_mocks():
    assert M2.db_priority.__name__ == "backend.db_priority"
    assert M2.db_duplicates.__name__ == "backend.db_duplicates"
    assert M2.db_hotspots.__name__ == "backend.db_hotspots"
    for engine in (M2.db_priority, M2.db_duplicates, M2.db_hotspots):
        for required in ("compute_priority", "find_duplicates",
                         "cluster_all_unclustered", "compute_hotspots"):
            if required in dir(engine):
                assert callable(getattr(engine, required))


# --- endpoints -------------------------------------------------------------

def test_stats_endpoint(client, seeded):
    r = client.get("/intelligence/stats")
    assert r.status_code == 200
    assert r.json()["complaints"] == 2
    assert r.json()["issue_clusters"] == 1


def test_score_all_endpoint_is_reachable(client, seeded):
    r = client.post("/intelligence/priority/score-all")
    assert r.status_code == 200, "route shadowing regression"
    assert r.json()["scored"] == 2


def test_score_single_complaint(client, seeded):
    cid = seeded["complaints"][0].id
    r = client.post(f"/intelligence/priority/{cid}")
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["priority_score"] <= 100
    assert body["priority_level"] in ("Low", "Medium", "High")
    assert "factors" in body and "evidence" in body


def test_score_all_is_idempotent_via_api(client, seeded):
    client.post("/intelligence/priority/score-all")
    r = client.post("/intelligence/priority/score-all")
    assert r.json()["scored"] == 0


# --- priority explanation --------------------------------------------------

def test_explanation_returns_the_five_weighted_factors(client, seeded):
    """The officer asking "why this score" gets the engine's own factors."""
    cid = seeded["complaints"][0].id
    r = client.get(f"/intelligence/priority/{cid}/explanation")
    assert r.status_code == 200
    body = r.json()
    assert set(body["factors"]) == set(M2.db_priority.WEIGHTS)
    # Weights are data, so the UI can label each bar without restating the
    # algorithm in prose that could drift from it.
    assert body["weights"] == M2.db_priority.WEIGHTS
    for name, weight in M2.db_priority.WEIGHTS.items():
        assert 0 <= body["factors"][name] <= 100
        assert weight > 0


def test_explanation_reports_the_stored_score_not_a_rescore(client, seeded):
    """
    The explanation must describe the score that is actually stored. Rescoring
    here would silently move a complaint's number just by being looked at.
    """
    client.post("/intelligence/priority/score-all")
    cid = seeded["complaints"][0].id
    before = seeded["db"].get(models.Complaint, cid).priority_score

    r = client.get(f"/intelligence/priority/{cid}/explanation")
    assert r.json()["stored_score"] == before
    assert seeded["db"].get(models.Complaint, cid).priority_score == before


def test_explanation_does_not_write_a_score_to_an_unscored_complaint(client, seeded):
    cid = seeded["complaints"][0].id
    assert seeded["db"].get(models.Complaint, cid).priority_score is None

    r = client.get(f"/intelligence/priority/{cid}/explanation")
    assert r.status_code == 200
    # A current score is still reported, but nothing was persisted, so an
    # unscored complaint does not silently acquire a score from being viewed.
    assert seeded["db"].get(models.Complaint, cid).priority_score is None


def test_explanation_accepts_the_public_complaint_id(client, seeded):
    """
    The dashboard only ever holds "CA-000042". Without accepting that form the
    explanation would be unreachable from the UI, which is the whole point.
    """
    cid = seeded["complaints"][0].id
    public = f"CA-{cid:06d}"
    assert client.get(f"/intelligence/priority/{public}/explanation").status_code == 200


def test_explanation_rejects_a_memory_complaint_id(client, seeded):
    """An in-memory complaint has no database row, so there is nothing to explain."""
    r = client.get("/intelligence/priority/CA-MEM-000001/explanation")
    assert r.status_code == 404


def test_explanation_rejects_a_nonsense_id(client, seeded):
    assert client.get("/intelligence/priority/not-an-id/explanation").status_code == 404


def test_explanation_is_officer_only(client, seeded, make_auth_user):
    """
    Same guard as every other intelligence route: a citizen must not be able to
    read a complaint's priority evidence through the explanation endpoint just
    because it is a GET.
    """
    _citizen, token = make_auth_user("explan-citizen@example.com", role="citizen")
    cid = seeded["complaints"][0].id
    r = client.get(
        f"/intelligence/priority/{cid}/explanation",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


# --- single cluster --------------------------------------------------------

def test_cluster_endpoint_returns_category_and_ward(client, seeded):
    """
    A cluster's category and ward are plain string columns, unreachable from any
    other endpoint. The case file needs them and must not infer the category
    from the recommended action.
    """
    cluster_id = seeded["cluster"].id
    body = client.get(f"/intelligence/clusters/{cluster_id}").json()
    assert body["cluster_id"] == cluster_id
    assert body["category"] == "Road Infrastructure"
    assert body["ward"] == "Kothrud"
    assert body["label"] == "c"


def test_cluster_endpoint_lists_its_member_complaints(client, seeded):
    # Only `a` carries a cluster_id in this fixture; `b` is deliberately left
    # unclustered, so the endpoint must report one member and not two.
    members = [c for c in seeded["complaints"] if c.cluster_id == seeded["cluster"].id]
    body = client.get(f"/intelligence/clusters/{seeded['cluster'].id}").json()
    assert body["complaint_ids"] == [c.id for c in members]
    assert body["complaint_count"] == 1


def test_cluster_count_is_read_from_complaints_not_the_cached_column(client, seeded):
    """
    `IssueCluster.complaint_count` is a cache. If it drifts, showing it would put
    a number in the case header that contradicts the complaints listed below it.
    """
    cluster = seeded["cluster"]
    cluster.complaint_count = 99
    seeded["db"].commit()

    body = client.get(f"/intelligence/clusters/{cluster.id}").json()
    assert body["complaint_count"] == 1


def test_cluster_endpoint_reports_an_empty_cluster_honestly(client, seeded):
    """A cluster with no complaints is a real state, not an error."""
    empty = models.IssueCluster(label="empty", category="Water Supply", ward="Baner")
    seeded["db"].add(empty)
    seeded["db"].commit()

    body = client.get(f"/intelligence/clusters/{empty.id}").json()
    assert body["complaint_count"] == 0
    assert body["complaint_ids"] == []


def test_cluster_endpoint_404s_on_an_unknown_cluster(client, seeded):
    assert client.get("/intelligence/clusters/999999").status_code == 404


def test_cluster_endpoint_does_not_score_or_cluster(client, seeded):
    """Opening a case file must not move any number in it."""
    cid = seeded["complaints"][0].id
    assert seeded["db"].get(models.Complaint, cid).priority_score is None

    def membership(db):
        # `cluster_id` is nullable, so a list is compared rather than a sorted
        # set: None must stay distinguishable from a real cluster id.
        return sorted(
            (c.id, c.cluster_id) for c in db.query(models.Complaint).all()
        )

    before = membership(seeded["db"])
    client.get(f"/intelligence/clusters/{seeded['cluster'].id}")

    assert seeded["db"].get(models.Complaint, cid).priority_score is None
    assert membership(seeded["db"]) == before


def test_cluster_endpoint_is_officer_only(client, seeded, make_auth_user):
    _citizen, token = make_auth_user("cluster-citizen@example.com", role="citizen")
    r = client.get(
        f"/intelligence/clusters/{seeded['cluster'].id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


# --- recommendation_id, the key every officer decision is called with -------

def test_every_returned_recommendation_carries_a_usable_id(client, seeded):
    """
    The dashboard uses `recommendation_id` for three things at once: the
    expand/collapse state key, the "#N" it displays, and the path segment of
    every approve/modify/reject call. A row missing it is not a cosmetic gap --
    each of those three fails differently and silently, which is how a backend
    and a dashboard running different builds produced three unrelated-looking
    symptoms from one cause.
    """
    rows = client.get("/intelligence/recommendations").json()["recommendations"]
    assert rows
    for row in rows:
        assert isinstance(row["recommendation_id"], int)
        assert row["recommendation_id"] > 0


def test_returned_id_is_the_recommendation_row_not_the_cluster(client, seeded):
    """
    The two ids are different keys and swapping them is a silently wrong
    success: the endpoint would approve one recommendation while the officer
    believed they had approved another.
    """
    rows = client.get("/intelligence/recommendations").json()["recommendations"]
    stored = {rec.id: rec.cluster_id for rec in seeded["db"].query(models.Recommendation)}
    for row in rows:
        assert stored[row["recommendation_id"]] == row["cluster_id"]


def test_returned_id_is_stable_across_calls(client, seeded):
    """A second read must not hand back a different key for the same cluster."""
    first = {r["cluster_id"]: r["recommendation_id"]
             for r in client.get("/intelligence/recommendations").json()["recommendations"]}
    second = {r["cluster_id"]: r["recommendation_id"]
              for r in client.get("/intelligence/recommendations").json()["recommendations"]}
    assert first == second


def test_stats_reports_the_pipeline_stage_counts(client, seeded):
    """
    Overview renders one tile per pipeline stage, so the endpoint has to answer
    for each of them. `analysed_complaints` must count the column rather than
    assume every complaint was analysed.
    """
    body = client.get("/intelligence/stats").json()
    for key in ("analysed_complaints", "hotspots", "projects",
                "completed_projects", "measured_impact"):
        assert key in body
        assert isinstance(body[key], int)

    # The seeded complaints carry no issue_summary, so none are "analysed".
    # Counting `complaints` here instead would report the AI stage as complete
    # when it never ran.
    assert body["analysed_complaints"] == 0
    assert body["complaints"] == 2


def test_duplicates_endpoint(client, seeded):
    cid = seeded["complaints"][0].id
    r = client.get(f"/intelligence/duplicates/{cid}")
    assert r.status_code == 200
    assert len(r.json()["duplicates"]) == 1


def test_cluster_endpoint(client, seeded):
    # Clear the pre-assigned cluster so the endpoint has work to do.
    for c in seeded["complaints"]:
        c.cluster_id = None
    seeded["cluster"].complaint_count = 0
    seeded["db"].commit()

    r = client.post("/intelligence/cluster")
    assert r.status_code == 200
    assert r.json()["clusters_created"] == 1


def test_hotspots_endpoint(client, seeded):
    r = client.get("/intelligence/hotspots?min_complaints=1")
    assert r.status_code == 200
    hotspots = r.json()["hotspots"]
    assert hotspots
    assert {"location", "category", "complaint_count",
            "high_severity_count", "hotspot_score", "hotspot_level"} <= set(hotspots[0])
    # Additive fields: the deterministic cluster linkage and the location
    # passthrough. Both are optional additions, so the original keys above must
    # keep working unchanged.
    assert {"cluster_ids", "area", "latitude", "longitude"} <= set(hotspots[0])
    assert isinstance(hotspots[0]["cluster_ids"], list)


def test_hotspots_endpoint_links_the_seeded_cluster(client, seeded):
    r = client.get("/intelligence/hotspots?min_complaints=1")
    linked = {cid for hotspot in r.json()["hotspots"]
              for cid in hotspot["cluster_ids"]}
    assert seeded["cluster"].id in linked


def test_hotspots_respects_min_complaints(client, seeded):
    assert client.get("/intelligence/hotspots?min_complaints=99").json()["hotspots"] == []


def test_recommendations_endpoints(client, seeded):
    r = client.get("/intelligence/recommendations")
    assert r.status_code == 200
    assert r.json()["recommendations"]

    cid = seeded["cluster"].id
    r2 = client.get(f"/intelligence/recommendations/{cid}")
    assert r2.status_code == 200
    assert r2.json()["location"] == "Kothrud"


def test_recommendations_endpoint_is_idempotent_via_api(client, seeded):
    client.get("/intelligence/recommendations")
    before = client.get("/intelligence/stats").json()["recommendations"]
    client.get("/intelligence/recommendations")
    after = client.get("/intelligence/stats").json()["recommendations"]
    assert before == after


def test_recommendations_skip_a_cluster_with_no_complaints(client, seeded):
    """An empty cluster must not appear in the list the dashboard renders."""
    empty = models.IssueCluster(label="empty", category="Education", ward="Kothrud")
    client.app  # keep reference
    db = SessionLocal()
    try:
        db.add(empty)
        db.commit()
        empty_id = empty.id
    finally:
        db.close()

    listed = client.get("/intelligence/recommendations").json()["recommendations"]
    assert empty_id not in [r["cluster_id"] for r in listed]

    # The single-cluster route must agree with the list rather than inventing
    # a recommendation for a cluster that has no complaints.
    r = client.get(f"/intelligence/recommendations/{empty_id}")
    assert r.status_code == 404
    assert "no complaints" in r.json()["detail"]


# --- error handling --------------------------------------------------------

def test_missing_complaint_returns_404(client, clean_db):
    assert client.post("/intelligence/priority/9999").status_code == 404
    assert client.get("/intelligence/duplicates/9999").status_code == 404


def test_missing_cluster_returns_404(client, clean_db):
    assert client.get("/intelligence/recommendations/9999").status_code == 404


# --- BigQuery honesty ------------------------------------------------------

def test_bigquery_reports_disabled_honestly(client, seeded):
    """
    The old router returned {"synced": len(df)} even though nothing was
    uploaded, which claims a BigQuery write that never happened.
    """
    from backend import bigquery_client
    bigquery_client.SYNC_ENABLED = False
    try:
        r = client.post("/intelligence/sync/bigquery")
    finally:
        bigquery_client.SYNC_ENABLED = False
    assert r.status_code == 200
    body = r.json()
    assert body["synced"] == 0
    assert body["status"] == "disabled"


def test_bigquery_reports_not_configured_when_enabled_without_project(client, seeded):
    from backend import bigquery_client
    bigquery_client.SYNC_ENABLED = True
    bigquery_client.PROJECT = None
    try:
        r = client.post("/intelligence/sync/bigquery")
    finally:
        bigquery_client.SYNC_ENABLED = False
    assert r.json()["status"] == "not_configured"
    assert r.json()["synced"] == 0


def test_bigquery_reports_nothing_to_sync(client, clean_db):
    from backend import bigquery_client
    bigquery_client.SYNC_ENABLED = True
    bigquery_client.PROJECT = "some-project"
    try:
        r = client.post("/intelligence/sync/bigquery")
    finally:
        bigquery_client.SYNC_ENABLED = False
        bigquery_client.PROJECT = None
    assert r.json()["status"] == "nothing_to_sync"


# --- isolation from main.py's existing routes ------------------------------

def test_prefix_avoids_shadowing_main_hotspots(app):
    """main.py already serves /hotspots; the prefix keeps them distinct."""
    paths = list(app.openapi()["paths"])
    assert "/hotspots" not in paths
    assert "/intelligence/hotspots" in paths
