"""
Shared pytest fixtures.

`database/db.py` reads DATABASE_URL at import time, so it is pointed at a
throwaway SQLite file here, before any application module is imported. That
keeps the suite runnable with no PostgreSQL server and no credentials -- one
of the review findings was that nothing could be verified without standing up
a real database.
"""
import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

_DB_FILE = os.path.join(tempfile.gettempdir(), "civicai_test_suite.db")
try:
    os.remove(_DB_FILE)
except OSError:
    # On Windows a previous run can still hold the file briefly. That is
    # harmless: init_db() is idempotent and the clean_db fixture truncates
    # every table between tests.
    pass
os.environ["DATABASE_URL"] = "sqlite:///" + _DB_FILE.replace(os.sep, "/")
# Keep BigQuery off so the suite can never touch the network.
os.environ["ENABLE_BIGQUERY_SYNC"] = "false"
# `backend.auth` refuses to import without a signing secret, by design: a
# generated one would invalidate every token whenever the process restarts.
# The suite is a process boundary of its own, so a fixed value here is
# correct and is not a credential -- it is the test fixture's own secret.
os.environ.setdefault("JWT_SECRET_KEY", "test-suite-only-not-a-real-secret")

from database.db import SessionLocal, init_db  # noqa: E402
from database import models  # noqa: E402

init_db()


@pytest.fixture
def make_auth_user(clean_db):
    """
    Create (or reuse) a persisted user and return (response, token).

    Accounts live in the database now, so this goes through the same service
    the HTTP route uses rather than reaching into a dict. Reusing an email
    updates the role instead of failing, which keeps the fixture usable across
    a whole session.

    The role is set here rather than through `/auth/register` on purpose: that
    route creates citizens only, because it is unauthenticated. Tests need
    officers, and the service layer is the supported way to provision one.

    Depending on `clean_db` is load-bearing, not tidiness. Accounts used to
    live in a process-local dict that `clean_db` could not reach, so an officer
    created by one fixture survived the truncation performed by another. Now
    that they are rows, a test that sets up `client` (which creates the officer)
    and then `seeded` (which truncates) would delete the officer mid-test and
    every call would 401. Declaring the dependency makes cleanup happen first;
    pytest resolves a fixture once per test, so the later request is a cache
    hit rather than a second truncation.
    """
    from backend import auth as auth_module
    from backend.auth import (UserCreate, create_access_token, create_user,
                              normalise_email)
    from database.db import SessionLocal

    def _make(email, role="citizen", name="Test User", password="password123"):
        db = SessionLocal()
        try:
            key = normalise_email(email)
            row = db.query(models.User).filter_by(email=key).first()
            if row is None:
                user = create_user(
                    db,
                    UserCreate(full_name=name, email=key, password=password,
                               role=role),
                )
            else:
                if row.role != role:
                    row.role = role
                    db.commit()
                user = auth_module.to_response(row)
            token = create_access_token(data={"sub": key})
            return user, token
        finally:
            db.close()

    return _make


@pytest.fixture
def auth_headers(make_auth_user):
    """`Authorization` header value for a citizen, or an officer when asked."""
    def _headers(email="fixture-citizen@example.com", role="citizen"):
        _user, token = make_auth_user(email, role=role)
        return {"Authorization": f"Bearer {token}"}

    return _headers


@pytest.fixture
def db():
    """A session on a clean database for each test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def clean_db(db):
    """Empties every table so tests do not leak state into each other."""
    # ProjectImpact first: it holds a FK to Project, so deleting the project
    # first would either fail or leave the measurement behind to leak into the
    # next test.
    for table in (models.ImpactMetric, models.ProjectImpact, models.Project,
                  models.OfficerDecision,
                  models.Recommendation, models.Investment, models.Infrastructure,
                  models.Demographics, models.Complaint, models.IssueCluster,
                  models.Location, models.User):
        db.query(table).delete()
    db.commit()
    return db


@pytest.fixture
def make_location(clean_db):
    def _make(ward, city="Pune"):
        loc = models.Location(ward=ward, city=city)
        clean_db.add(loc)
        clean_db.commit()
        return loc

    return _make


@pytest.fixture
def make_complaint(clean_db):
    def _make(text, location=None, category="Road Infrastructure",
              severity="Medium", urgency="Medium", cluster_id=None):
        c = models.Complaint(
            text=text,
            language="English",
            category=category,
            severity=severity,
            urgency=urgency,
            location_id=location.id if location else None,
            cluster_id=cluster_id,
        )
        clean_db.add(c)
        clean_db.commit()
        return c

    return _make
