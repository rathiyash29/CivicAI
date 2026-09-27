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
if os.path.exists(_DB_FILE):
    os.remove(_DB_FILE)
os.environ["DATABASE_URL"] = "sqlite:///" + _DB_FILE.replace(os.sep, "/")
# Keep BigQuery off so the suite can never touch the network.
os.environ["ENABLE_BIGQUERY_SYNC"] = "false"

from database.db import SessionLocal, init_db  # noqa: E402
from database import models  # noqa: E402

init_db()


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
    for table in (models.ImpactMetric, models.Project, models.Recommendation,
                  models.Investment, models.Infrastructure, models.Demographics,
                  models.Complaint, models.IssueCluster, models.Location,
                  models.User):
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
