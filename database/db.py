"""
Database connection layer (PostgreSQL via SQLAlchemy).

Member 1's auth.py and complaints.py can import `get_db` the same way —
we all share ONE database, ONE engine. Don't spin up a second engine
elsewhere in the codebase.
"""
import os
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://civicai_user:civicai_pass@localhost:5432/civicai",
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
