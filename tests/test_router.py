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
        "/intelligence/duplicates/{complaint_id}",
        "/intelligence/hotspots",
        "/intelligence/priority/score-all",
        "/intelligence/priority/{complaint_id}",
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
