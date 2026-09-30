"""
Authorization tests for the intelligence router.

Every `/intelligence/*` endpoint reads or mutates data across the whole city,
so the router requires the `officer` role at router level:

  * no token          -> 401
  * authenticated citizen -> 403
  * authenticated officer -> allowed

The mutating endpoints (`/cluster`, `/priority/score-all`,
`/priority/{id}`, `/sync/bigquery`) are covered explicitly, because an
unauthenticated bulk commit is the worst of the four.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import router as M2
from database import models
from database.db import SessionLocal

READ_ENDPOINTS = [
    ("GET", "/intelligence/stats"),
    ("GET", "/intelligence/hotspots"),
    ("GET", "/intelligence/recommendations"),
    ("GET", "/intelligence/duplicates/1"),
    ("GET", "/intelligence/recommendations/1"),
]

MUTATION_ENDPOINTS = [
    ("POST", "/intelligence/cluster"),
    ("POST", "/intelligence/priority/score-all"),
    ("POST", "/intelligence/priority/1"),
    ("POST", "/intelligence/sync/bigquery"),
]

ALL_ENDPOINTS = READ_ENDPOINTS + MUTATION_ENDPOINTS


@pytest.fixture
def app():
    application = FastAPI()
    application.include_router(M2.router, prefix="/intelligence", tags=["intelligence"])
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def seeded(clean_db, make_location):
    loc = make_location("Kothrud")
    complaint = models.Complaint(
        text="huge potholes on the road near the college",
        category="Road Infrastructure", severity="High", urgency="High",
        location_id=loc.id)
    clean_db.add(complaint)
    clean_db.commit()
    return complaint


def _headers(make_auth_user, role, email):
    _user, token = make_auth_user(email, role=role)
    return {"Authorization": f"Bearer {token}"}


# --- unauthenticated -------------------------------------------------------

@pytest.mark.parametrize("method,path", ALL_ENDPOINTS)
def test_no_token_is_401(client, method, path):
    r = client.request(method, path)
    assert r.status_code == 401


@pytest.mark.parametrize("method,path", ALL_ENDPOINTS)
def test_garbage_token_is_401(client, method, path):
    r = client.request(method, path,
                       headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


# --- authenticated citizen --------------------------------------------------

@pytest.mark.parametrize("method,path", ALL_ENDPOINTS)
def test_citizen_is_403(client, make_auth_user, method, path):
    headers = _headers(make_auth_user, "citizen", "router-citizen@example.com")
    r = client.request(method, path, headers=headers)
    assert r.status_code == 403


# --- authenticated officer --------------------------------------------------

@pytest.mark.parametrize("method,path", ALL_ENDPOINTS)
def test_officer_is_allowed(client, make_auth_user, seeded, method, path):
    headers = _headers(make_auth_user, "officer", "router-officer-ok@example.com")
    r = client.request(method, path, headers=headers)
    assert r.status_code != 401
    assert r.status_code != 403, r.text


def test_officer_gets_real_data(client, make_auth_user, seeded):
    headers = _headers(make_auth_user, "officer", "router-officer-data@example.com")
    body = client.get("/intelligence/stats", headers=headers).json()
    assert body["complaints"] == 1


def test_mutation_endpoints_are_refused_before_they_act(client, make_auth_user, seeded):
    """
    A 403 has to mean "nothing happened", not "it ran and then complained".
    """
    citizen = _headers(make_auth_user, "citizen", "router-citizen-mutate@example.com")
    for method, path in MUTATION_ENDPOINTS:
        assert client.request(method, path, headers=citizen).status_code == 403

    assert seeded.cluster_id is None, "clustering must not have run"
    assert seeded.priority_score is None, "scoring must not have run"


def test_score_all_requires_an_officer(client, make_auth_user, clean_db, seeded):
    citizen = _headers(make_auth_user, "citizen", "router-citizen-score@example.com")
    assert client.post("/intelligence/priority/score-all",
                       headers=citizen).status_code == 403
    assert seeded.priority_score is None

    officer = _headers(make_auth_user, "officer", "router-officer-score@example.com")
    assert client.post("/intelligence/priority/score-all",
                       headers=officer).status_code == 200
    clean_db.expire_all()  # the endpoint committed through its own session
    assert seeded.priority_score is not None


# --- the guard itself -------------------------------------------------------

def test_guard_is_a_router_level_dependency():
    """
    So that a newly added endpoint is protected by default rather than by
    remembering to add a guard.
    """
    assert M2.router.dependencies, "router must carry the officer requirement"
    assert any(getattr(d.dependency, "__name__", "") == "require_officer"
               for d in M2.router.dependencies)


def test_role_matching_is_case_and_space_insensitive(client, make_auth_user, seeded):
    headers = _headers(make_auth_user, " Officer ", "router-officer-case@example.com")
    assert client.get("/intelligence/stats", headers=headers).status_code == 200


def test_missing_role_is_not_treated_as_officer(client, make_auth_user, seeded, clean_db):
    """
    A blank role must fail closed, not open.

    The role is read from the database on every request, so the row is the thing
    to change here. Mutating the in-memory response object would prove nothing:
    a client's idea of its own role is not what the guard consults, and a test
    that relied on that was measuring the wrong property.
    """
    from backend import auth as auth_module
    from database import models

    make_auth_user("router-norole@example.com", role="officer")

    row = clean_db.query(models.User).filter_by(email="router-norole@example.com").one()
    row.role = ""
    clean_db.commit()
    clean_db.expire_all()

    from backend.auth import create_access_token
    token = create_access_token(data={"sub": "router-norole@example.com"})
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/intelligence/stats", headers=headers).status_code == 403

    db = SessionLocal()
    try:
        assert auth_module.get_user_by_email(db, "router-norole@example.com") is not None
    finally:
        db.close()
