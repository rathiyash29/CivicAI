"""
Regression tests for the auth-mirror identity fix.

`backend/auth.py` keeps users in a process-local dict and hands out integer
ids from a counter that restarts at 1. Before this fix the `users` mirror row
was keyed on that integer, so after a restart a different account could be
given an id an earlier account already held, overwrite its row, and read its
complaints through `/complaints/my`.

The mirror is now keyed on `users.auth_key`, a stable per-account identity, and
the primary key is issued by the database.
"""
import pytest
from fastapi.testclient import TestClient

from backend import auth as auth_module
from backend import complaint_service as svc
from backend import main
from database import models

ANALYSIS = {
    "category": "Road Infrastructure",
    "severity": "High",
    "urgency": "High",
    "affected_group": "Commuters",
    "issue_summary": "s",
    "recommended_action": "r",
}


class AuthUser:
    """Stand-in for backend.auth's in-memory UserInDB."""

    def __init__(self, uid, name, email, role="citizen"):
        from datetime import datetime
        self.id = uid
        self.full_name = name
        self.email = email
        self.role = role
        self.created_at = datetime.utcnow()


def _simulate_auth_restart(monkeypatch) -> None:
    """
    Reproduce exactly what a process restart does to the auth module: the user
    dict is empty and the id counter is back at 0, so the next account
    registered is handed id 1 again.
    """
    monkeypatch.setattr(auth_module, "MOCK_USERS_DB", {})
    monkeypatch.setattr(auth_module, "USER_ID_COUNTER", 0)


def _complaint(text):
    return svc.persist_complaint(
        text_value=text, language="English", raw_location="Kothrud",
        analysis=ANALYSIS, user=None, session=None,
    )


def test_auth_key_is_derived_from_the_surviving_identifier():
    user = AuthUser(1, "Alice", "Alice@Example.com")
    assert svc.auth_key_for(user) == "alice@example.com"
    assert svc.auth_key_for(AuthUser(1, "No Email", None)) is None
    assert svc.auth_key_for(None) is None


def test_reused_auth_id_does_not_overwrite_or_inherit(clean_db, monkeypatch):
    """The full Alice -> restart -> Bob story, in the order it actually happens."""
    # --- 1. Alice files a complaint ---
    alice = AuthUser(1, "Alice Original", "alice@example.com")
    stored = svc.persist_complaint(
        text_value="Alice private complaint about the potholes",
        language="English", raw_location="Kothrud", analysis=ANALYSIS,
        user=alice, session=clean_db,
    )
    alice_complaint_id = stored["complaint"]["complaint_id"]
    alice_row_id = stored["complaint"]["user_id"]

    # --- 2/3. the process restarts, so Bob is handed auth id 1 as well ---
    _simulate_auth_restart(monkeypatch)
    assert auth_module.USER_ID_COUNTER == 0
    bob = AuthUser(1, "Bob Newcomer", "bob@example.com")
    assert bob.id == alice.id, "the point of the test is that this id repeats"

    bob_stored = svc.persist_complaint(
        text_value="Bob entirely different garbage problem",
        language="English", raw_location="Kothrud", analysis=ANALYSIS,
        user=bob, session=clean_db,
    )

    # --- 4/5. two rows, and Alice's is untouched ---
    rows = clean_db.query(models.User).all()
    assert len(rows) == 2
    alice_row = clean_db.query(models.User).filter_by(auth_key="alice@example.com").one()
    bob_row = clean_db.query(models.User).filter_by(auth_key="bob@example.com").one()
    assert alice_row.name == "Alice Original"
    assert alice_row.email == "alice@example.com"
    assert bob_row.name == "Bob Newcomer"
    assert alice_row.id != bob_row.id

    # --- 6. Bob does not see Alice's complaint ---
    bob_complaints = svc.list_user_complaints(bob, session=clean_db)
    assert [c["text"] for c in bob_complaints] == [
        "Bob entirely different garbage problem"]

    # --- 7. Alice's complaint is still owned by Alice ---
    alice_complaints = svc.list_user_complaints(alice, session=clean_db)
    assert [c["complaint_id"] for c in alice_complaints] == [alice_complaint_id]
    assert clean_db.query(models.Complaint).get(
        int(alice_complaint_id.split("-")[1])).user_id == alice_row_id
    assert bob_stored["complaint"]["user_id"] == bob_row.id


def test_complaint_ids_stay_unique_across_the_restart(clean_db, monkeypatch):
    stored = svc.persist_complaint(
        text_value="Alice private complaint about the potholes",
        language="English", raw_location="Kothrud", analysis=ANALYSIS,
        user=AuthUser(1, "Alice", "alice@example.com"), session=clean_db,
    )
    _simulate_auth_restart(monkeypatch)
    bob_stored = svc.persist_complaint(
        text_value="Bob entirely different garbage problem",
        language="English", raw_location="Kothrud", analysis=ANALYSIS,
        user=AuthUser(1, "Bob", "bob@example.com"), session=clean_db,
    )
    assert stored["complaint"]["complaint_id"] != bob_stored["complaint"]["complaint_id"]


def test_complaint_user_id_is_never_the_auth_id(clean_db):
    """
    A high auth id must not leak into `Complaint.user_id`. The value has to be
    a key the database itself issued, or the foreign key is a coin toss.
    """
    stored = svc.persist_complaint(
        text_value="A complaint filed by a late auth id", language="English",
        raw_location="Kothrud", analysis=ANALYSIS,
        user=AuthUser(4321, "Late", "late@example.com"), session=clean_db,
    )
    mirror = clean_db.query(models.User).filter_by(auth_key="late@example.com").one()
    assert stored["complaint"]["user_id"] == mirror.id
    assert mirror.id != 4321


def test_postgres_never_issues_a_user_id_we_chose(clean_db):
    """The mirror insert must not carry an explicit primary key at all."""
    svc.ensure_user_row(clean_db, AuthUser(7, "Explicit", "explicit@example.com"))
    clean_db.commit()
    row = clean_db.query(models.User).filter_by(auth_key="explicit@example.com").one()
    assert row.id != 7


def test_mirror_lookup_after_restart_finds_the_same_row(clean_db, monkeypatch):
    svc.persist_complaint(
        text_value="A complaint that must survive a restart", language="English",
        raw_location="Kothrud", analysis=ANALYSIS,
        user=AuthUser(1, "Alice", "alice@example.com"), session=clean_db,
    )
    _simulate_auth_restart(monkeypatch)

    # The same person comes back after the restart, under a fresh auth id.
    returning = AuthUser(1, "Alice Again", "alice@example.com")
    svc.persist_complaint(
        text_value="A second complaint from the same person",
        language="English", raw_location="Kothrud", analysis=ANALYSIS,
        user=returning, session=clean_db,
    )
    assert clean_db.query(models.User).count() == 1
    assert len(svc.list_user_complaints(returning, session=clean_db)) == 2


# --- through the API --------------------------------------------------------

@pytest.fixture
def client():
    svc.reset_health_cache()
    with TestClient(main.app) as c:
        yield c


def _register(client, email, name, role="citizen"):
    r = client.post("/auth/register", json={
        "full_name": name, "email": email, "password": "password123",
        "role": role})
    assert r.status_code == 201
    token = client.post("/auth/login", json={
        "email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_api_ownership_survives_an_auth_restart(client, clean_db, monkeypatch):
    alice = _register(client, "restart-alice@example.com", "Alice Original")
    client.post("/complaints", headers=alice, json={
        "text": "Alice private complaint about the potholes",
        "language": "English", "location": "Kothrud"})

    _simulate_auth_restart(monkeypatch)
    bob = _register(client, "restart-bob@example.com", "Bob Newcomer")
    client.post("/complaints", headers=bob, json={
        "text": "Bob entirely different garbage problem",
        "language": "English", "location": "Kothrud"})

    bob_mine = client.get("/complaints/my", headers=bob)
    assert bob_mine.status_code == 200
    assert all("Alice" not in c["text"] for c in bob_mine.json()["complaints"])
    assert len(bob_mine.json()["complaints"]) == 1

    # The pre-restart token no longer resolves to a live account, so Alice's
    # own view is re-established by logging back in as her.
    alice_again = _register(client, "restart-alice@example.com", "Alice Original")
    alice_mine = client.get("/complaints/my", headers=alice_again)
    assert alice_mine.status_code == 200
    assert len(alice_mine.json()["complaints"]) == 1
    assert "Alice" in alice_mine.json()["complaints"][0]["text"]

    rows = clean_db.query(models.User).all()
    assert {r.name for r in rows} == {"Alice Original", "Bob Newcomer"}


def test_my_complaints_still_requires_a_token(client):
    assert client.get("/complaints/my").status_code == 401
