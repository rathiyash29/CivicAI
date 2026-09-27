"""
Database connection layer (PostgreSQL via SQLAlchemy).

Member 1's auth.py and complaints.py can import `get_db` the same way —
we all share ONE database, ONE engine. Don't spin up a second engine
elsewhere in the codebase.

Configuration
-------------
`DATABASE_URL` is the only supported way to point this at a database, and it
must come from the environment (`backend/.env`, already git-ignored, or the
process environment). There is deliberately no credential of any kind baked
into this file: a password in source is a password that ends up in a git
history, a copy of the repository, and a container image.

If `DATABASE_URL` is absent the module falls back to a local SQLite file in
the system temp directory. That fallback carries no credentials and needs no
server, which keeps `import database.db` (and therefore the test suite and a
first `uvicorn` run) working on a fresh clone. It is logged loudly and must
not be used for anything real: point `DATABASE_URL` at PostgreSQL for that.
"""
import logging
import os
import tempfile
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

log = logging.getLogger("database")

# Load backend/.env explicitly, not just from the current working directory.
# `load_dotenv()` alone only searches the CWD upwards, so running
# `uvicorn backend.app:app` from the repo root would silently miss
# DATABASE_URL and fall back to the local SQLite file below.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_REPO_ROOT, "backend", ".env"))
load_dotenv()  # a root .env, if present, still wins

# Credential-free, server-free fallback. See the module docstring.
LOCAL_FALLBACK_URL = "sqlite:///" + os.path.join(
    tempfile.gettempdir(), "civicai_local_fallback.db"
).replace(os.sep, "/")

DATABASE_URL = os.getenv("DATABASE_URL") or LOCAL_FALLBACK_URL
if DATABASE_URL == LOCAL_FALLBACK_URL:
    log.warning(
        "DATABASE_URL is not set; falling back to a local SQLite file at %s. "
        "This is for local development only -- set DATABASE_URL to a "
        "PostgreSQL connection string for a real deployment.",
        LOCAL_FALLBACK_URL,
    )

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    """FastAPI dependency: `db: Session = Depends(get_db)`"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    """For use in scripts / data loaders (not inside FastAPI request handlers)."""
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Create all tables. Call once at startup / from a setup script."""
    from database import models  # noqa: F401  (ensures models are registered)
    models.Base.metadata.create_all(bind=engine)
