"""
PostgreSQL-specific tests.

The SQLite suite cannot catch foreign-key violations, SERIAL/sequence
collisions, or dialect differences -- SQLite does not enforce FKs unless
`PRAGMA foreign_keys=ON`, and it reuses ids after deletes. These tests run
against the real database when one is configured, and skip cleanly otherwise,
so they never become a reason to stand up infrastructure for the fast suite.

Enable with:
    CIVICAI_TEST_PG_URL=postgresql://user:pass@localhost:5432/civicai
"""
import os

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from database import models

PG_URL = os.getenv("CIVICAI_TEST_PG_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="set CIVICAI_TEST_PG_URL to run PostgreSQL-specific tests",
)

if PG_URL:
    engine = sa.create_engine(PG_URL)


@pytest.fixture
def pg():
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_foreign_keys_are_actually_enforced(pg):
    """
    The regression this whole file exists for: a Complaint pointing at a
    non-existent user must be rejected, not silently accepted.
    """
    with pytest.raises(IntegrityError):
        pg.add(models.Complaint(text="orphan", language="English", user_id=987654))
        pg.commit()
    pg.rollback()


def test_location_text_column_exists():
    columns = {c["name"] for c in sa.inspect(engine).get_columns("complaints")}
    assert "location_text" in columns


def test_auth_key_column_exists_and_is_unique():
    inspector = sa.inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("users")}
    assert "auth_key" in columns, (
        "run `python -m scripts.migrate_add_auth_key --apply` on an existing database")
    unique = {tuple(i["column_names"]) for i in inspector.get_indexes("users")
              if i.get("unique")}
    assert ("auth_key",) in unique


class _FakeUser:
    """Stand-in for backend.auth's in-memory user."""

    def __init__(self, auth_id, name, email, role="citizen"):
        from datetime import datetime
        self.id = auth_id
        self.full_name = name
        self.email = email
        self.role = role
        self.created_at = datetime.utcnow()


def test_mirror_uses_the_database_sequence_not_the_auth_id(pg):
    """
    The mirror must never write the auth module's integer id into `users.id`.

    That id restarts from 1 on every process restart, so keying ownership on it
    lets a later account inherit an earlier account's complaints. Letting the
    database assign the key also means the SERIAL sequence stays correct.
    """
    import uuid

    from backend import complaint_service as svc

    email = f"seqtest-{uuid.uuid4().hex[:8]}@example.com"
    # An id the sequence would never hand out, so "did we write it ourselves?"
    # has an unambiguous answer.
    auth_id = 987654

    row = svc.ensure_user_row(pg, _FakeUser(auth_id, "Sequence Test", email))
    pg.commit()
    assert row.id != auth_id, "the database must own the primary key"
    assert row.auth_key == email

    # A later auto-generated id must not collide either.
    auto = models.User(name="Auto",
                       email=f"auto-{uuid.uuid4().hex[:8]}@example.com")
    pg.add(auto)
    pg.commit()
    assert auto.id != auth_id and auto.id != row.id

    pg.execute(sa.text("DELETE FROM users WHERE id = :a OR id = :b"),
               {"a": row.id, "b": auto.id})
    pg.commit()


def test_two_accounts_sharing_an_auth_id_get_separate_rows(pg):
    """
    The exact scenario the review found: the auth counter restarts, a second
    account is handed id 1 again, and it must not land on the first account's
    row.
    """
    import uuid

    from backend import complaint_service as svc

    tag = uuid.uuid4().hex[:8]
    alice = svc.ensure_user_row(
        pg, _FakeUser(1, "Alice", f"alice-{tag}@example.com"))
    pg.commit()
    bob = svc.ensure_user_row(
        pg, _FakeUser(1, "Bob", f"bob-{tag}@example.com"))
    pg.commit()

    assert alice.id != bob.id
    assert pg.query(models.User).filter_by(
        auth_key=f"alice-{tag}@example.com").one().name == "Alice"

    pg.execute(sa.text("DELETE FROM users WHERE id = :a OR id = :b"),
               {"a": alice.id, "b": bob.id})
    pg.commit()


def test_full_pipeline_commits_cleanly(pg):
    """Location resolve -> mirror -> complaint -> cluster -> priority -> commit."""
    from backend import complaint_service as svc

    import uuid
    user_email = f"pipeline-{uuid.uuid4().hex[:8]}@example.com"
    ward = pg.query(models.Location).first()
    if ward is None:
        pytest.skip("no locations loaded; run data_loader first")

    class FakeUser:
        pass

    FakeUser.id = 1
    FakeUser.full_name = "Pipeline Test"
    FakeUser.email = user_email
    FakeUser.role = "citizen"

    out = svc.persist_complaint(
        text_value="Huge pothole blocking the main road",
        language="English",
        raw_location=ward.ward,
        analysis={"category": "Road Infrastructure", "severity": "High",
                  "urgency": "High", "affected_group": "Commuters",
                  "issue_summary": "s", "recommended_action": "r"},
        user=FakeUser(),
        session=pg,
    )
    assert out["persistence"] == "postgres"
    assert out["complaint"]["complaint_id"].startswith("CA-")
    assert 0 <= out["priority"]["priority_score"] <= 100
    assert out["cluster"]["id"] is not None
    # Ownership now travels on auth_key, not on the auth integer.
    assert out["complaint"]["user_id"] is not None
    assert len(svc.list_user_complaints(FakeUser(), session=pg)) == 1

    pg.rollback()  # leave the demo database as we found it


def test_legacy_rows_without_auth_key_are_backfilled_not_rewritten(pg):
    """
    A row created before the column existed must keep its id -- and therefore
    its complaints -- and simply gain the key.
    """
    import uuid

    from backend import complaint_service as svc

    email = f"legacy-{uuid.uuid4().hex[:8]}@example.com"
    legacy = models.User(name="Legacy", email=email, role="citizen")
    pg.add(legacy)
    pg.commit()
    original_id = legacy.id
    assert legacy.auth_key is None

    row = svc.ensure_user_row(pg, _FakeUser(1, "Legacy", email))
    pg.commit()
    assert row.id == original_id
    assert row.auth_key == email

    pg.execute(sa.text("DELETE FROM users WHERE id = :a"), {"a": original_id})
    pg.commit()
