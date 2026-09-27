"""
Degraded-mode tests: complaint ids and `/complaints/my` when PostgreSQL is
unreachable.

Two failures are pinned here.

1. The in-memory fallback used to number its own complaints `CA-000001`,
   `CA-000002`, ... from a counter that restarts with the process. PostgreSQL
   keeps its own rows and their ids, so a restart could hand out the public id
   of a complaint that already exists in the database.

2. `/complaints/my` served a confident empty list when the database could not
   be queried, which reads as "you have never filed a complaint".
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from backend import complaint_service as svc
from backend import main
from database import models

FRONTEND_COMPLAINT_FIELDS = {
    "complaint_id", "user_id", "text", "language", "location", "category",
    "severity", "priority_score", "priority_level", "status", "created_at",
}


@pytest.fixture
def client():
    svc.reset_health_cache()
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def citizen(client, make_auth_user):
    _user, token = make_auth_user("resilience-citizen@example.com")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def database_is_down(monkeypatch):
    """Make every attempt to reach the database fail."""
    monkeypatch.setattr(svc, "database_available", lambda *a, **kw: False)

    def boom(*a, **kw):
        raise SQLAlchemyError("connection refused")

    monkeypatch.setattr(svc, "SessionLocal", boom)
    svc.reset_health_cache()
    yield
    svc.reset_health_cache()


@pytest.fixture
def empty_memory_store(monkeypatch):
    monkeypatch.setattr(main, "MOCK_COMPLAINTS_DB", {})
    monkeypatch.setattr(main, "COMPLAINT_ID_COUNTER", 0)


# --- 1. id collision --------------------------------------------------------

def test_fallback_ids_cannot_collide_with_database_ids(clean_db, database_is_down,
                                                       empty_memory_store):
    """
    The database already holds CA-000001 and CA-000002; the fallback must not
    reuse either of them.
    """
    for i in range(2):
        svc.persist_complaint(
            text_value=f"Stored complaint number {i} about potholes",
            language="English", raw_location="Kothrud",
            analysis={"category": "Road Infrastructure", "severity": "High"},
            user=None, session=clean_db,
        )
    database_ids = {c["complaint_id"] for c in
                    [svc.complaint_to_contract(r) for r in
                     clean_db.query(models.Complaint).all()]}
    assert database_ids == {"CA-000001", "CA-000002"}

    stored = svc.persist_complaint(
        text_value="A complaint that cannot reach the database",
        language="English", raw_location="Kothrud", analysis={}, user=None)
    assert stored["persistence"] == svc.PERSISTENCE_MEMORY

    fallback = main.create_complaint(user_id=1, text="fallback", language="English",
                                     location="Kothrud")
    second = main.create_complaint(user_id=1, text="fallback two",
                                   language="English", location="Kothrud")

    for cid in (fallback.complaint_id, second.complaint_id):
        assert isinstance(cid, str)
        assert cid.startswith("CA-"), "the frontend filters on this prefix"
        assert cid not in database_ids
        # the numeric part must not be parseable as a database id
        assert not cid[len("CA-"):].isdigit()


def test_fallback_ids_are_unique_among_themselves(empty_memory_store):
    ids = {main.create_complaint(user_id=1, text=f"t{i}", language="English",
                                 location="Kothrud").complaint_id
           for i in range(50)}
    assert len(ids) == 50


def test_fallback_id_survives_a_restart_of_the_counter(clean_db, database_is_down,
                                                        empty_memory_store):
    """
    A restart resets the counter, not the guarantee: the prefix, not the
    number, is what keeps the namespaces apart.
    """
    first = main.create_complaint(user_id=1, text="a", language="English",
                                  location="Kothrud").complaint_id
    main.COMPLAINT_ID_COUNTER = 0  # what a process restart does
    second = main.create_complaint(user_id=1, text="b", language="English",
                                   location="Kothrud").complaint_id
    assert first != second or svc.MEMORY_ID_PREFIX in first
    assert svc.MEMORY_ID_PREFIX in first and svc.MEMORY_ID_PREFIX in second


def test_database_id_format_is_unchanged(clean_db):
    """PostgreSQL ids keep the exact format the frontend already parses."""
    out = svc.persist_complaint(
        text_value="A properly stored complaint about the road",
        language="English", raw_location="Kothrud",
        analysis={"category": "Road Infrastructure", "severity": "High"},
        user=None, session=clean_db,
    )
    cid = out["complaint"]["complaint_id"]
    assert cid == "CA-000001"
    assert len(cid) == 9 and cid[3:].isdigit()


def test_fallback_id_keeps_the_frontend_response_shape(client, citizen,
                                                        database_is_down,
                                                        empty_memory_store):
    r = client.post("/complaints", headers=citizen, json={
        "text": "A complaint submitted while the database is down",
        "language": "English", "location": "Kothrud"})
    assert r.status_code == 200
    body = r.json()
    assert body["persistence"] == "memory"
    assert set(body["complaint"]) == FRONTEND_COMPLAINT_FIELDS
    assert isinstance(body["complaint"]["complaint_id"], str)
    assert body["complaint"]["complaint_id"].startswith("CA-")


# --- 2. /complaints/my during an outage -------------------------------------

def test_my_complaints_returns_memory_complaints_when_the_db_is_down(
        client, citizen, database_is_down, empty_memory_store):
    posted = client.post("/complaints", headers=citizen, json={
        "text": "Submitted while PostgreSQL was unreachable",
        "language": "English", "location": "Kothrud"}).json()["complaint"]

    r = client.get("/complaints/my", headers=citizen)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"success", "complaints", "total"}
    assert [c["complaint_id"] for c in body["complaints"]] == [
        posted["complaint_id"]]
    assert body["total"] == 1
    assert set(body["complaints"][0]) == FRONTEND_COMPLAINT_FIELDS


def test_my_complaints_never_claims_empty_while_the_db_is_down(
        client, citizen, database_is_down, empty_memory_store):
    """
    No memory complaints and no database: the honest answer is "we could not
    check", not "you have none".
    """
    r = client.get("/complaints/my", headers=citizen)
    assert r.status_code == 503
    assert "unavailable" in r.json()["detail"].lower()


def test_a_503_does_not_look_like_an_empty_success(client, citizen,
                                                   database_is_down,
                                                   empty_memory_store):
    """The frontend reads `success`/`total`; neither may claim a false zero."""
    r = client.get("/complaints/my", headers=citizen)
    body = r.json()
    assert "total" not in body and "complaints" not in body
    assert "detail" in body


def test_my_complaints_still_reports_a_real_empty_list_when_the_db_answers(
        client, citizen, empty_memory_store):
    """The 503 is for outages only. A healthy database with no rows is a 200."""
    r = client.get("/complaints/my", headers=citizen)
    assert r.status_code == 200
    assert r.json() == {"success": True, "complaints": [], "total": 0}


def test_my_complaints_uses_postgres_when_it_is_available(client, citizen,
                                                          empty_memory_store,
                                                          clean_db):
    client.post("/complaints", headers=citizen, json={
        "text": "A complaint that must round trip through PostgreSQL",
        "language": "English", "location": "Kothrud"})
    body = client.get("/complaints/my", headers=citizen).json()
    assert body["total"] == 1
    assert body["complaints"][0]["complaint_id"].startswith("CA-")
    assert body["complaints"][0]["complaint_id"][3:].isdigit()
