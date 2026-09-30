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

In DEVELOPMENT, an absent `DATABASE_URL` falls back to a local SQLite file in
the system temp directory. That fallback carries no credentials and needs no
server, which keeps `import database.db` (and therefore the test suite and a
first `uvicorn` run) working on a fresh clone. It is logged loudly.

In PRODUCTION that fallback is refused. Silently accepting a missing
`DATABASE_URL` there is the dangerous case: every write appears to succeed
while landing in a throwaway file that is lost on the next deploy or restart,
and nothing in the API response says so. Set `CIVICAI_ENV=production` and the
module raises at import instead.

Declare the environment with `CIVICAI_ENV` (`production`/`prod`, or anything
else for local work). Production also refuses a `sqlite://` `DATABASE_URL`,
since pointing a deployment at a file-based database is the same data-loss
mistake spelled differently.
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

_PRODUCTION_ENV_NAMES = {"production", "prod"}
APP_ENV = (os.getenv("CIVICAI_ENV") or "").strip().lower()
IS_PRODUCTION = APP_ENV in _PRODUCTION_ENV_NAMES

# Credential-free, server-free fallback. Development only. See the docstring.
LOCAL_FALLBACK_URL = "sqlite:///" + os.path.join(
    tempfile.gettempdir(), "civicai_local_fallback.db"
).replace(os.sep, "/")


class DatabaseConfigurationError(RuntimeError):
    """DATABASE_URL is missing or unusable for the declared environment."""


_configured_url = (os.getenv("DATABASE_URL") or "").strip()

if IS_PRODUCTION:
    if not _configured_url:
        raise DatabaseConfigurationError(
            "DATABASE_URL is not set, but CIVICAI_ENV="
            f"{APP_ENV or 'production'} declares a production environment. "
            "Refusing to start: without it every citizen complaint would be "
            "written to a throwaway local SQLite file and silently lost. Set "
            "DATABASE_URL to your PostgreSQL connection string, for example "
            "postgresql://USER:PASSWORD@HOST:5432/DBNAME (see "
            "backend/.env.example)."
        )
    if _configured_url.startswith("sqlite"):
        raise DatabaseConfigurationError(
            "DATABASE_URL points at a SQLite file, but CIVICAI_ENV="
            f"{APP_ENV or 'production'} declares a production environment. "
            "A file-based database does not survive a redeploy and cannot be "
            "shared between instances. Point DATABASE_URL at PostgreSQL "
            "(see backend/.env.example)."
        )
    DATABASE_URL = _configured_url
else:
    DATABASE_URL = _configured_url or LOCAL_FALLBACK_URL
    if not _configured_url:
        log.warning(
            "DATABASE_URL is not set; falling back to a local SQLite file at %s. "
            "This is for local development only -- set DATABASE_URL to a "
            "PostgreSQL connection string for a real deployment. In production "
            "this fallback is refused and startup fails instead.",
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
