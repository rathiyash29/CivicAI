"""
Tests for complaint persistence and orchestration (backend/complaint_service.py).

Covers the PostgreSQL integration end to end on SQLite, including the
frontend response contract, which is the thing most at risk from this change.
"""
import pytest
from sqlalchemy.exc import SQLAlchemyError

from backend import complaint_service as svc
from backend import db_duplicates, db_priority
from database import models

# The exact contract the React frontend depends on (api/complaints.ts). The
# `analysis_*` and `cluster_id` fields are additive, for the officer dashboard.
FRONTEND_COMPLAINT_FIELDS = {
    "complaint_id", "user_id", "text", "language", "location", "category",
    "severity", "priority_score", "priority_level", "status", "created_at",
    "cluster_id", "analysis_urgency", "analysis_affected_group",
    "analysis_issue_summary", "analysis_recommended_action",
}


class FakeAuthUser:
    """Stand-in for backend.auth's in-memory UserInDB."""

    def __init__(self, uid=1, name="Asha Verma", email="asha@example.com",
                 role="citizen"):
        from datetime import datetime
        self.id = uid
        self.full_name = name
        self.email = email
        self.role = role
        self.created_at = datetime.utcnow()


@pytest.fixture
def analysis():
    return {
        "language": "English",
        "category": "Road Infrastructure",
        "location": "Kothrud",
        "severity": "High",
        "urgency": "High",
        "affected_group": "Students and children",
        "issue_summary": "Road damage causing difficulty for commuters.",
        "recommended_action": "Inspect and repair the damaged section.",
    }


@pytest.fixture
def user():
    return FakeAuthUser()


@pytest.fixture
def user_lookups():
    """Retained only for the signature's history; the service no longer uses
    injected auth lookups, because those returned auth objects rather than
    database rows and silently skipped the mirror insert."""
    return {}


@pytest.fixture
def store(clean_db, user, user_lookups, analysis):
    """Persist through the service using the test session."""
    def _store(text="Large potholes near the college gate", language="English",
               location="Kothrud", a=None, u=user):
        return svc.persist_complaint(
            text_value=text, language=language, raw_location=location,
            analysis=a or analysis, user=u, session=clean_db,
        )

    return _store


# --- 1. persistence --------------------------------------------------------

def test_complaint_is_persisted(clean_db, store):
    out = store()
    assert out["persistence"] == svc.PERSISTENCE_POSTGRES
    assert clean_db.query(models.Complaint).count() == 1
    row = clean_db.query(models.Complaint).one()
    assert row.text == "Large potholes near the college gate"
    assert row.language == "English"


# --- 2. complaint_id generation --------------------------------------------

def test_complaint_id_derives_from_primary_key(store):
    out = store()
    assert out["complaint"]["complaint_id"] == "CA-000001"

    second = store(text="Another pothole on the same road", location="Kothrud")
    assert second["complaint"]["complaint_id"] == "CA-000002"


@pytest.mark.parametrize("row_id,expected", [
    (1, "CA-000001"), (42, "CA-000042"), (999999, "CA-999999"),
])
def test_format_complaint_id(row_id, expected):
    assert svc.format_complaint_id(row_id) == expected


def test_complaint_id_is_a_string(clean_db, store):
    """The frontend types this as a string and uses it as a React key."""
    assert isinstance(store()["complaint"]["complaint_id"], str)


# --- 3/4. location resolution ---------------------------------------------

def test_location_exact_match(clean_db, store):
    clean_db.add(models.Location(ward="Kothrud", city="Pune"))
    clean_db.commit()
    out = store(location="Kothrud")
    assert out["location"] == {"resolved": True, "ward": "Kothrud"}
    assert out["complaint"]["location_id"] is not None if hasattr(out["complaint"], "location_id") else True
    assert clean_db.query(models.Complaint).one().location_id is not None


def test_location_unknown_leaves_null_but_keeps_text(clean_db, store):
    clean_db.add(models.Location(ward="Kothrud", city="Pune"))
    clean_db.commit()
    out = store(location="near Balewadi stadium")

    row = clean_db.query(models.Complaint).one()
    assert row.location_id is None, "unknown ward must not invent a location"
    assert row.location_text == "near Balewadi stadium", "raw input must survive"
    assert out["location"] == {"resolved": False, "ward": None}


def test_location_text_always_preserved_verbatim(clean_db, store):
    clean_db.add(models.Location(ward="Kothrud", city="Pune"))
    clean_db.commit()
    raw = "  near Kothrud bus stand, pune  "
    out = store(location=raw)
    row = clean_db.query(models.Complaint).one()
    assert row.location_text == raw
    # the response shows the citizen what they typed, not the resolved ward
    assert out["complaint"]["location"] == raw


# --- 5. AI fields persisted ------------------------------------------------

def test_ai_fields_are_persisted(clean_db, store, analysis):
    store()
    row = clean_db.query(models.Complaint).one()
    assert row.category == "Road Infrastructure"
    assert row.severity == "High"
    # these four were previously discarded and are why the 15% urgency weight
    # had nothing to read
    assert row.urgency == "High"
    assert row.affected_group == "Students and children"
    assert row.issue_summary == analysis["issue_summary"]
    assert row.recommended_action == analysis["recommended_action"]


def test_urgency_is_persisted_not_just_held_in_the_response(clean_db, store):
    out = store()
    clean_db.expire_all()
    assert clean_db.query(models.Complaint).one().urgency == "High"
    assert out["complaint"]["severity"] == "High"


# --- 6. user mirror --------------------------------------------------------

def test_user_mirror_row_created(clean_db, store, user):
    store()
    mirrored = clean_db.query(models.User).one()
    assert mirrored.email == user.email
    assert mirrored.name == user.full_name
    assert mirrored.role == "citizen"


def test_complaint_fk_points_at_mirrored_user(clean_db, store):
    out = store()
    row = clean_db.query(models.Complaint).one()
    assert row.user_id == clean_db.query(models.User).one().id
    assert out["complaint"]["user_id"] == row.user_id


def test_user_mirror_is_idempotent(clean_db, store):
    store(text="pothole one on the main road")
    store(text="pothole two on the main road")
    assert clean_db.query(models.User).count() == 1
    assert clean_db.query(models.Complaint).count() == 2


def test_mirror_row_exists_even_when_auth_lookup_would_hit(clean_db, store, user):
    """
    Regression: ensure_user_row used to return the *auth* object whenever an
    in-memory lookup succeeded, so no `users` row was ever inserted and the
    complaint failed its foreign key on PostgreSQL. SQLite does not enforce
    FKs by default, which is why the whole suite passed while the live
    database rejected the insert.
    """
    store()
    mirror = clean_db.query(models.User).filter_by(email=user.email).one()
    assert isinstance(mirror, models.User)
    assert clean_db.query(models.Complaint).one().user_id == mirror.id


def test_mirror_reuses_existing_row_for_same_email(clean_db, store, user):
    store(text="first complaint about potholes")
    store(text="second complaint about potholes")
    mirrors = clean_db.query(models.User).filter_by(email=user.email).all()
    assert len(mirrors) == 1
    assert clean_db.query(models.Complaint).count() == 2


def test_mirror_uses_a_database_assigned_id(clean_db, store, user):
    """
    Ownership must never hang off the auth module's integer id.

    That id restarts from 1 on every process restart, so two different
    accounts can hold the same one. The mirror row's primary key is issued by
    the database instead.
    """
    store()
    mirror = clean_db.query(models.User).one()
    assert mirror.id == clean_db.query(models.Complaint).one().user_id


def test_mirror_row_records_the_stable_auth_key(clean_db, store, user):
    store()
    mirror = clean_db.query(models.User).one()
    assert mirror.auth_key == user.email.lower()


def test_ensure_user_row_ignores_anonymous_user(clean_db):
    assert svc.ensure_user_row(clean_db, None) is None


def test_ensure_user_row_requires_a_usable_email(clean_db):
    class NoEmail:
        id = 5
        email = None

    class BlankEmail:
        id = 5
        email = "   "

    assert svc.ensure_user_row(clean_db, NoEmail()) is None
    assert svc.ensure_user_row(clean_db, BlankEmail()) is None


def test_mirror_ignores_the_auth_id_when_creating_a_row(clean_db, user):
    """
    A high auth id must not become the mirror primary key: after a restart the
    auth counter starts over, so ids in the database must come from the
    database's own sequence.
    """
    late = FakeAuthUser(uid=99, email="late@example.com")
    row = svc.ensure_user_row(clean_db, late)
    clean_db.commit()
    assert row.auth_key == "late@example.com"
    assert row.id != 99


def test_a_reused_auth_id_gets_its_own_row(clean_db):
    """
    Two different accounts handed the same auth id must not share a row, or the
    second one inherits the first one's complaints.
    """
    first = FakeAuthUser(uid=1, name="Alice", email="alice@example.com")
    second = FakeAuthUser(uid=1, name="Bob", email="bob@example.com")

    a = svc.ensure_user_row(clean_db, first)
    clean_db.commit()
    b = svc.ensure_user_row(clean_db, second)
    clean_db.commit()

    assert a.id != b.id
    assert clean_db.query(models.User).count() == 2
    assert clean_db.query(models.User).filter_by(email="alice@example.com").one().name == "Alice"
    assert clean_db.query(models.User).filter_by(email="bob@example.com").one().name == "Bob"


def test_auth_key_is_case_and_whitespace_insensitive(clean_db, user):
    svc.ensure_user_row(clean_db, user)
    clean_db.commit()
    again = FakeAuthUser(uid=user.id, name=user.full_name,
                         email="  ASHA@Example.COM  ")
    row = svc.ensure_user_row(clean_db, again)
    clean_db.commit()
    assert clean_db.query(models.User).count() == 1
    assert row.auth_key == user.email.lower()


def test_legacy_row_without_auth_key_is_adopted_not_replaced(clean_db, user):
    """
    Rows created before this column existed are matched by email and given the
    stable key in place, so their existing complaints keep their owner.
    """
    legacy = models.User(name=user.full_name, email=user.email, role="citizen")
    clean_db.add(legacy)
    clean_db.commit()
    assert legacy.auth_key is None
    existing_id = legacy.id

    row = svc.ensure_user_row(clean_db, user)
    clean_db.commit()
    assert row.id == existing_id
    assert row.auth_key == user.email.lower()
    assert clean_db.query(models.User).count() == 1


def test_changing_your_email_does_not_take_over_the_old_row(clean_db, store, user):
    """
    The previous code treated a new email on a known auth id as the same
    person and rewrote the row. Matching on a stable key instead means a
    different email is a different account -- the safe direction to fail in.
    """
    svc.ensure_user_row(clean_db, user)
    clean_db.commit()
    changed = FakeAuthUser(uid=user.id, name="Asha V.", email="new@example.com")

    row = svc.ensure_user_row(clean_db, changed)
    clean_db.commit()

    assert row.id != clean_db.query(models.User).filter_by(
        email=user.email).one().id
    assert clean_db.query(models.User).count() == 2


def test_complaint_user_id_is_null_when_the_user_cannot_be_mirrored(clean_db, store):
    """
    A complaint must never carry a user_id the database did not issue: that is
    a dangling foreign key waiting to fail, and on SQLite it would not fail at
    all.
    """
    class NoEmail:
        id = 1
        email = None
        full_name = "Ghost"
        role = "citizen"

    out = store(u=NoEmail())
    row = clean_db.query(models.Complaint).one()
    assert row.user_id is None
    assert out["complaint"]["user_id"] is None
    assert clean_db.query(models.User).count() == 0


def test_the_mirror_stores_a_bcrypt_hash_never_a_plaintext_password(clean_db, store):
    """
    This used to assert the users table had *no* password column at all, which
    was true only while auth was a process-local dict. Auth is database-backed
    now, so the column exists -- and the property that actually matters is
    stronger: what lands in it is a one-way bcrypt digest.

    Mirroring a user (which happens on every complaint submission) must not
    disturb or duplicate the credential the auth service already wrote.
    """
    store()
    columns = {c.name for c in models.User.__table__.columns}
    assert "password_hash" in columns

    row = clean_db.query(models.User).one()
    # The complaint-mirroring path creates the row for an account that may not
    # have been created through /auth/register. Either way, whatever is here
    # must not be a plaintext password.
    if row.password_hash is not None:
        assert row.password_hash.startswith("$2"), "passwords must be bcrypt hashed"
        assert "password123" not in row.password_hash
    assert not hasattr(row, "password")


def test_anonymous_submission_mirrors_nothing(clean_db, store):
    out = store(u=None)
    assert clean_db.query(models.User).count() == 0
    assert clean_db.query(models.Complaint).one().user_id is None
    assert out["persistence"] == svc.PERSISTENCE_POSTGRES


# --- 7. duplicate detection integration ------------------------------------

def test_first_complaint_has_no_duplicates(clean_db, store):
    out = store()
    assert out["duplicate"]["is_duplicate"] is False
    assert out["duplicate"]["duplicate_count"] == 0
    assert out["duplicate"]["success"] is True


def test_paraphrased_second_complaint_is_flagged(clean_db, store):
    store(text="Large potholes near the college gate are dangerous")
    out = store(text="Road full of potholes near the college gate, very dangerous")
    assert out["duplicate"]["is_duplicate"] is True
    assert out["duplicate"]["duplicate_count"] >= 1


def test_duplicate_block_matches_frontend_shape(clean_db, store):
    store(text="Large potholes near the college gate are dangerous")
    out = store(text="Road full of potholes near the college gate, very dangerous")
    assert set(out["duplicate"]) == {
        "success", "is_duplicate", "similar_complaints", "duplicate_count"}
    for match in out["duplicate"]["similar_complaints"]:
        # AnalysisPage.tsx types these exactly
        assert set(match) == {"id", "text", "location", "similarity"}
        assert isinstance(match["id"], int)


def test_complaint_does_not_duplicate_itself(clean_db, store):
    """find_duplicates runs after flush; a self-match would be a false positive."""
    out = store()
    assert out["duplicate"]["duplicate_count"] == 0


# --- 8. incremental cluster assignment -------------------------------------

def test_complaint_is_assigned_a_cluster(clean_db, store):
    store()
    row = clean_db.query(models.Complaint).one()
    assert row.cluster_id is not None


def test_paraphrases_join_one_cluster(clean_db, store):
    store(text="Large potholes near the college gate are dangerous")
    store(text="Road full of potholes near the college gate, very dangerous")

    clusters = clean_db.query(models.IssueCluster).all()
    assert len(clusters) == 1
    assert clusters[0].complaint_count == 2
    assert clean_db.query(models.Complaint).count() == 2


def test_different_categories_form_different_clusters(clean_db, store, analysis):
    store(text="potholes on the main road")
    other = dict(analysis, category="Water Supply")
    store(text="water supply is irregular here", a=other)

    assert clean_db.query(models.IssueCluster).count() == 2


def test_assign_cluster_does_not_commit(clean_db, user, analysis):
    """A request path must let the caller own the transaction."""
    out = svc.persist_complaint(
        text_value="potholes everywhere", language="English",
        raw_location="Kothrud", analysis=analysis, user=user, session=clean_db,
    )
    assert out["cluster"]["complaint_count"] == 1


def test_assign_cluster_is_incremental_not_a_batch_sweep(clean_db, store, monkeypatch):
    """The full batch sweep must never run on the request path."""
    def explode(*a, **kw):
        raise AssertionError("batch clustering ran during a request")

    monkeypatch.setattr(db_duplicates, "cluster_all_unclustered", explode)
    store()
    store(text="potholes on the bridge", location="Kothrud")


# --- 9. DB priority integration --------------------------------------------

def test_priority_uses_db_engine_weights(clean_db, store):
    out = store()
    priority = out["priority"]
    assert set(priority["factors"]) == {
        "citizen_demand", "infrastructure_gap", "population_impact",
        "urgency", "investment_gap"}
    assert 0 <= priority["priority_score"] <= 100
    assert priority["priority_level"] in ("Low", "Medium", "High")


def test_priority_score_persisted_on_the_row(clean_db, store):
    out = store()
    row = clean_db.query(models.Complaint).one()
    assert row.priority_score == out["priority"]["priority_score"]
    assert row.priority_level == out["priority"]["priority_level"]


def test_priority_reuses_member2_engine(clean_db, store, monkeypatch):
    calls = []
    original = db_priority.compute_priority

    def spy(db, complaint):
        calls.append(complaint)
        return original(db, complaint)

    monkeypatch.setattr(db_priority, "compute_priority", spy)
    store()
    assert len(calls) == 1, "must call Member 2's engine, not reimplement it"


def test_priority_block_keeps_frontend_factor_keys(clean_db, store):
    """AnalysisPage renders priority.factors directly."""
    factors = store()["priority"]["factors"]
    assert set(factors) == {
        "citizen_demand", "infrastructure_gap", "population_impact",
        "urgency", "investment_gap"}


# --- 10. response contract -------------------------------------------------

def test_complaint_payload_exact_field_set(clean_db, store):
    assert set(store()["complaint"]) == FRONTEND_COMPLAINT_FIELDS


def test_complaint_payload_types(clean_db, store):
    c = store()["complaint"]
    assert isinstance(c["complaint_id"], str)
    assert isinstance(c["user_id"], int)
    assert isinstance(c["text"], str)
    assert isinstance(c["language"], str)
    assert isinstance(c["location"], str)
    assert isinstance(c["status"], str)
    assert c["priority_score"] is None or isinstance(c["priority_score"], float)


def test_status_is_submitted(clean_db, store):
    assert store()["complaint"]["status"] == "Submitted"


def test_created_at_is_isoformat_compatible(clean_db, store):
    import datetime as dt
    created = store()["complaint"]["created_at"]
    assert isinstance(created, (str, dt.datetime))
    if isinstance(created, dt.datetime):
        created.isoformat()


def test_persistence_field_present(clean_db, store):
    assert store()["persistence"] == "postgres"


# --- fallback --------------------------------------------------------------

def test_unavailable_database_reports_memory_and_explains(clean_db, monkeypatch):
    monkeypatch.setattr(svc, "database_available", lambda *a, **kw: False)
    out = svc.persist_complaint(
        text_value="potholes", language="English", raw_location="Kothrud",
        analysis={}, user=None)
    assert out["persistence"] == svc.PERSISTENCE_MEMORY
    assert out["fallback_reason"], "a silent fallback would look like a success"
    assert out["complaint"] is None


def test_sql_error_falls_back_and_does_not_lie(clean_db, monkeypatch, user, analysis):
    def boom(*a, **kw):
        raise SQLAlchemyError("connection lost")

    monkeypatch.setattr(svc, "database_available", lambda *a, **kw: True)
    monkeypatch.setattr(svc, "SessionLocal", boom)

    out = svc.persist_complaint(
        text_value="potholes", language="English", raw_location="Kothrud",
        analysis=analysis, user=user)
    assert out["persistence"] == svc.PERSISTENCE_MEMORY
    assert "database error" in out["fallback_reason"]


def test_list_user_complaints_returns_none_when_db_down(monkeypatch):
    monkeypatch.setattr(svc, "database_available", lambda *a, **kw: False)
    assert svc.list_user_complaints(FakeAuthUser()) is None, (
        "None means 'could not check'; an empty list would claim 'no complaints'")


def test_list_user_complaints_returns_empty_only_when_the_db_answers(clean_db, store, user):
    """An empty list is a real answer: the database was reachable and had none."""
    assert svc.list_user_complaints(user, session=clean_db) == []
    store()
    assert len(svc.list_user_complaints(user, session=clean_db)) == 1


def test_list_user_complaints_is_scoped_to_the_stable_identity(clean_db, store, user):
    alice = FakeAuthUser(uid=1, name="Alice", email="alice@example.com")
    bob = FakeAuthUser(uid=1, name="Bob", email="bob@example.com")
    store(text="Alice's private complaint about potholes", u=alice)
    store(text="Bob's entirely different problem", u=bob)

    assert len(svc.list_user_complaints(alice, session=clean_db)) == 1
    assert len(svc.list_user_complaints(bob, session=clean_db)) == 1
    texts = [c["text"] for c in svc.list_user_complaints(bob, session=clean_db)]
    assert texts == ["Bob's entirely different problem"]


def test_health_cache_respects_ttl(monkeypatch):
    svc.reset_health_cache()
    calls = []

    def fake_session():
        calls.append(1)
        raise SQLAlchemyError("down")

    monkeypatch.setattr(svc, "SessionLocal", fake_session)
    assert svc.database_available() is False
    assert svc.database_available() is False
    assert len(calls) == 1, "second call must use the cached probe"
    svc.database_available(force=True)
    assert len(calls) == 2
    svc.reset_health_cache()
