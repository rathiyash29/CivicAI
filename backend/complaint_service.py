"""
Complaint persistence and orchestration.

This is the single place that knows how a complaint reaches storage. It is the
seam between Member 1's request handling and Member 2's intelligence engines:

    analyze (main.py)
        -> resolve location            (backend/locations.py)
        -> ensure user mirror row      (Complaint.user_id FK)
        -> INSERT complaint            (PostgreSQL, system of record)
        -> flush for an id
        -> find duplicates             (db_duplicates.find_duplicates)
        -> assign cluster incrementally(db_duplicates.assign_cluster)
        -> compute data-driven priority(db_priority.compute_priority)
        -> commit

PostgreSQL is the system of record. The in-memory dict that predates this
module survives only as a *guarded fallback*: if the database cannot be
reached, the citizen's complaint is still accepted and still gets the exact
same response shape, but the response says so explicitly via `persistence`,
and the fallback is logged. Nothing silently pretends the write succeeded.
"""
import logging
import time
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend import db_duplicates, db_priority, locations
from database.db import SessionLocal
from database import models

log = logging.getLogger("complaint_service")

# How long a successful health check stays valid. Checking on every request
# would add a round trip to the citizen's submit path for no benefit.
HEALTH_TTL_SECONDS = 10.0

PERSISTENCE_POSTGRES = "postgres"
PERSISTENCE_MEMORY = "memory"

_health_cache: dict = {"checked_at": 0.0, "available": False}


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------

def _probe(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        log.warning("PostgreSQL probe failed: %s", exc)
        db.rollback()
        return False


def database_available(force: bool = False) -> bool:
    """
    Is PostgreSQL usable right now?

    Cached briefly so a database outage does not add a connection timeout to
    every single request.
    """
    now = time.monotonic()
    if not force and (now - _health_cache["checked_at"]) < HEALTH_TTL_SECONDS:
        return _health_cache["available"]

    session = None
    try:
        session = SessionLocal()
        available = _probe(session)
    except SQLAlchemyError as exc:
        log.warning("Could not open a database session: %s", exc)
        available = False
    finally:
        if session is not None:
            session.close()

    if _health_cache["available"] != available:
        log.info("PostgreSQL availability changed: %s -> %s",
                 _health_cache["available"], available)
    _health_cache["checked_at"] = now
    _health_cache["available"] = available
    return available


def reset_health_cache() -> None:
    """Test hook: forget the cached probe result."""
    _health_cache["checked_at"] = 0.0
    _health_cache["available"] = False


# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------

def format_complaint_id(row_id: int) -> str:
    """
    Render the integer primary key in the format the frontend already expects.

    The citizen UI types this as a string, renders it directly, and uses it as
    a React key, so it must stay a string across the storage change.
    """
    return f"CA-{row_id:06d}"


# Prefix for complaints that could not reach PostgreSQL. A database-backed id
# is always `CA-` plus six digits, so this cannot collide with a real
# complaint id even after a restart, which a bare `CA-%06d` counter absolutely
# could: PostgreSQL may already hold CA-000001 while the in-memory counter
# starts again at 1. The value is still a plain string, so the React key, the
# rendered id and the `?complaint_id=` link all keep working.
MEMORY_ID_PREFIX = "CA-MEM-"


def format_memory_complaint_id(sequence: int) -> str:
    """Public id for a complaint that only exists in the in-memory fallback."""
    return f"{MEMORY_ID_PREFIX}{sequence:06d}"


def parse_complaint_id(public_id: str) -> int:
    """
    Inverse of `format_complaint_id`: `"CA-000042"` -> `42`.

    The officer dashboard only ever sees the public `CA-` form, but the
    intelligence routes key on the integer primary key. Without a parser the
    dashboard cannot reach a complaint's priority evidence at all, so the two
    forms have to be translatable in both directions.

    A bare integer is accepted too, so a caller holding the primary key does not
    have to format it first. Anything else raises `ValueError`, so a malformed
    id is rejected rather than silently read as a different row. The in-memory
    `CA-MEM-` form is rejected as well: those rows have no database identity to
    look up.
    """
    text = str(public_id).strip().upper()
    if text.isdigit():
        return int(text)
    if text.startswith(MEMORY_ID_PREFIX):
        raise ValueError(
            f"{public_id!r} is an in-memory complaint and has no database row"
        )
    if not text.startswith("CA-"):
        raise ValueError(f"Not a complaint id: {public_id!r}")
    digits = text[3:]
    if not digits.isdigit():
        raise ValueError(f"Not a complaint id: {public_id!r}")
    return int(digits)


def complaint_to_contract(
    complaint: models.Complaint,
    raw_location: Optional[str] = None,
) -> dict:
    """
    Project a database row onto the exact shape `/complaints` already returns.

    Field names and types are the frontend contract and must not drift. The
    additions below are all read from columns the table already has; none of
    them is derived, inferred or filled in, so a value that was never written
    comes back as `None` and the UI can show it as unavailable.

    `cluster_id` is the complaint's issue cluster. It was already stored
    (`Complaint.cluster_id`) but not returned, which left the dashboard unable
    to follow a complaint through to the hotspot and recommendation built from
    it.

    The four `analysis_*` fields are what the AI layer wrote at submission
    time. They are the officer's answer to "what did the system understand
    this complaint to be about", and they were stored and then never exposed.
    """
    return {
        "complaint_id": format_complaint_id(complaint.id),
        "user_id": complaint.user_id,
        "text": complaint.text,
        "language": complaint.language,
        "location": (raw_location
                     if raw_location is not None
                     else (complaint.location_text
                           or (complaint.location.ward
                               if complaint.location else ""))),
        "category": complaint.category,
        "severity": complaint.severity,
        "priority_score": complaint.priority_score,
        "priority_level": complaint.priority_level,
        "status": complaint.status,
        "created_at": complaint.created_at,
        "cluster_id": complaint.cluster_id,
        "analysis_urgency": complaint.urgency,
        "analysis_affected_group": complaint.affected_group,
        "analysis_issue_summary": complaint.issue_summary,
        "analysis_recommended_action": complaint.recommended_action,
    }


# --------------------------------------------------------------------------
# user mirror
# --------------------------------------------------------------------------

def auth_key_for(user: Any) -> Optional[str]:
    """
    Stable external identity for an in-memory auth user.

    `backend/auth.py` hands out integer ids from a process-local counter that
    restarts at 1, so that integer is only unique *within one process run*.
    Keying complaint ownership on it lets a different account inherit the
    previous one's complaints after a restart.

    The email is the one identifier that survives a restart: it is required at
    registration, unique per account, and it is the JWT `sub`. Normalising it
    keeps `Alice@Example.com ` and `alice@example.com` on the same row.
    """
    email = getattr(user, "email", None)
    if not email or not isinstance(email, str):
        return None
    normalized = email.strip().lower()
    return normalized or None


def ensure_user_row(db: Session, user: Any) -> Optional[models.User]:
    """
    Mirror an in-memory auth user into the `users` table.

    `backend/auth.py` still keeps users in a dict, but `Complaint.user_id` is a
    foreign key. This creates the row that makes that FK valid without
    touching the auth module. No password is stored -- that is a later,
    separate migration when auth itself moves to PostgreSQL.

    The row is keyed on `auth_key`, a stable per-account identity, and its
    primary key is assigned by the database. The auth module's integer id is
    deliberately *not* used as either key, because that id is reused after a
    restart: matching on it would let a new account overwrite an existing
    mirror row and inherit its complaints.

    An existing row is never overwritten by a different account. The only
    update is a profile refresh (name/role) for the same `auth_key`, which is
    the same person.

    Returns the database user row, or None if the user cannot be mirrored.
    """
    auth_key = auth_key_for(user)
    if not auth_key:
        return None

    # 1. the stable key is the lookup. `email` is a second chance for rows that
    #    predate the column and have not been backfilled yet.
    row = db.query(models.User).filter_by(auth_key=auth_key).first()
    if row is None:
        row = db.query(models.User).filter_by(email=auth_key).first()
        if row is not None and not row.auth_key:
            # Legacy row: adopt the stable key. This is a fill-in, not an
            # overwrite of the account's identity.
            row.auth_key = auth_key

    if row is not None:
        # Same account, possibly an updated profile.
        name = getattr(user, "full_name", None) or getattr(user, "name", None)
        if name and row.name != name:
            row.name = name
        role = getattr(user, "role", None) or "citizen"
        if row.role != role:
            row.role = role
        return row

    # 2. no row for this identity: insert a new one and let the database
    #    assign the primary key. Never reuse the auth id.
    row = models.User(
        name=getattr(user, "full_name", None) or getattr(user, "name", None),
        email=auth_key,
        auth_key=auth_key,
        role=getattr(user, "role", None) or "citizen",
        created_at=getattr(user, "created_at", None),
    )
    db.add(row)
    try:
        db.flush()
    except SQLAlchemyError as exc:
        # A concurrent request can insert the same identity first. Re-read it
        # rather than overwriting anything.
        log.warning("User mirror insert for %s raced (%s); re-reading", auth_key, exc)
        db.rollback()
        return db.query(models.User).filter_by(auth_key=auth_key).first()

    return row


def resolve_user_row(db: Session, user: Any) -> Optional[models.User]:
    """The mirror row for an auth user, or None if they have never complained."""
    auth_key = auth_key_for(user)
    if not auth_key:
        return None
    return db.query(models.User).filter_by(auth_key=auth_key).first()


# --------------------------------------------------------------------------
# the main flow
# --------------------------------------------------------------------------

def persist_complaint(
    *,
    text_value: str,
    language: str,
    raw_location: str,
    analysis: dict,
    user: Any = None,
    session: Optional[Session] = None,
) -> dict:
    """
    Store a complaint and run the intelligence pipeline over it.

    Returns a dict with:
      complaint      the frontend contract payload
      persistence    "postgres" or "memory"
      priority       the data-driven priority block
      duplicate      the duplicate block in the existing response shape
      cluster        the cluster the complaint landed in
      location       whether the free-text location resolved to a ward
      fallback_reason  populated only when persistence == "memory"

    `session` is injectable so tests can supply a SQLite session instead of
    opening a new one.
    """
    if session is not None:
        return _persist_with_session(
            session, text_value, language, raw_location, analysis, user,
        )

    if not database_available():
        reason = "PostgreSQL unavailable; stored in memory for this request only"
        log.warning("Falling back to in-memory complaint storage: %s", reason)
        return {
            "complaint": None,
            "persistence": PERSISTENCE_MEMORY,
            "fallback_reason": reason,
            "priority": None,
            "duplicate": None,
        }

    session = None
    try:
        session = SessionLocal()
        return _persist_with_session(
            session, text_value, language, raw_location, analysis, user,
        )
    except SQLAlchemyError as exc:
        # A failure part-way through must not leave a half-written complaint.
        if session is not None:
            session.rollback()
        log.exception("Complaint persistence failed (%s); using in-memory fallback", exc)
        _mark_unavailable()
        return {
            "complaint": None,
            "persistence": PERSISTENCE_MEMORY,
            "fallback_reason": f"database error: {exc.__class__.__name__}",
            "priority": None,
            "duplicate": None,
        }
    finally:
        if session is not None:
            session.close()


def _persist_with_session(
    db: Session,
    text_value: str,
    language: str,
    raw_location: str,
    analysis: dict,
    user: Any,
) -> dict:
    # 2. resolve the free-text location (never creates Location rows)
    location = locations.resolve_location(db, raw_location)

    # 3. mirror the authenticated user so Complaint.user_id has a valid FK
    user_row = ensure_user_row(db, user) if user is not None else None

    # 4-5. create the complaint row and flush to obtain its id
    complaint = models.Complaint(
        text=text_value,
        language=language,
        location_text=raw_location,
        location_id=location.id if location else None,
        # Only ever a database-assigned id from the mirror row. Falling back to
        # the auth id here would re-introduce an id the database never issued,
        # which is both a dangling foreign key and a cross-account leak.
        user_id=user_row.id if user_row else None,
        category=analysis.get("category"),
        severity=analysis.get("severity"),
        # These four come from the AI but were previously discarded, which is
        # why db_priority had nothing to read for the 15% urgency weight.
        urgency=analysis.get("urgency"),
        affected_group=analysis.get("affected_group"),
        issue_summary=analysis.get("issue_summary"),
        recommended_action=analysis.get("recommended_action"),
        status="Submitted",
    )
    db.add(complaint)
    db.flush()  # after this the row has a real id

    # 6. duplicate detection (after flush: find_duplicates excludes by id)
    matches = db_duplicates.find_duplicates(db, complaint)
    duplicate = {
        "success": True,
        "is_duplicate": len(matches) > 0,
        "similar_complaints": [
            {
                # The frontend types this field as a number.
                "id": m["complaint_id"],
                "text": m["text"],
                "location": m["location"],
                "similarity": m["similarity"],
            }
            for m in matches
        ],
        "duplicate_count": len(matches),
    }

    # 7. incremental clustering (never the full batch sweep on a request)
    cluster, _created = db_duplicates.assign_cluster(db, complaint)

    # 8. data-driven priority, reusing Member 2's engine and weights as-is
    priority = db_priority.compute_priority(db, complaint)

    # 9. one transaction for the whole pipeline
    db.commit()
    db.refresh(complaint)

    return {
        "complaint": complaint_to_contract(complaint, raw_location),
        "persistence": PERSISTENCE_POSTGRES,
        "fallback_reason": None,
        "priority": priority,
        "duplicate": duplicate,
        "cluster": {
            "id": cluster.id,
            "label": cluster.label,
            "ward": cluster.ward,
            "category": cluster.category,
            "complaint_count": cluster.complaint_count,
        },
        "location": {
            "resolved": location is not None,
            "ward": location.ward if location else None,
        },
    }


def _mark_unavailable() -> None:
    """Force the next request to re-probe rather than trusting a stale cache."""
    _health_cache["checked_at"] = 0.0


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------

def list_user_complaints(
    user: Any,
    session: Optional[Session] = None,
) -> Optional[list[dict]]:
    """
    Complaints belonging to one citizen, newest first.

    `user` is the authenticated user (anything with an `email`). Ownership is
    resolved through the stable `auth_key` mirror row, not through the auth
    module's reusable integer id.

    Returns None when PostgreSQL is unavailable, which tells the caller to use
    its in-memory store rather than reporting an empty list -- an empty list
    would look like "you have no complaints" when the truth is "we could not
    check". An empty list is therefore only ever returned when the database
    actually answered the question.
    """
    owned = session is not None
    if not owned:
        if not database_available():
            return None
        session = SessionLocal()
    try:
        user_row = resolve_user_row(session, user)
        if user_row is None:
            # The database answered: this account has no complaints.
            return []
        rows = (
            session.query(models.Complaint)
            .filter_by(user_id=user_row.id)
            .order_by(models.Complaint.created_at.desc(), models.Complaint.id.desc())
            .all()
        )
        return [complaint_to_contract(row) for row in rows]
    except SQLAlchemyError as exc:
        log.warning("Could not read complaints for %s: %s", auth_key_for(user), exc)
        session.rollback()
        return None
    finally:
        if not owned:
            session.close()


def list_all_complaints(
    session: Optional[Session] = None,
) -> Optional[list[dict]]:
    """
    Every complaint on the platform, newest first. Officer-facing counterpart to
    `list_user_complaints`.

    Same table, same projection, same ordering, same contract, so the citizen
    route and this one cannot drift apart. Rows are shaped by
    `complaint_to_contract`, which reads only complaint columns: the auth store
    is never queried, so no password hash, JWT or other credential can reach
    this response.

    Returns None when PostgreSQL is unavailable, exactly like the citizen read,
    so the caller can never turn "we could not check" into a confident empty
    list. An empty list is only ever returned when the database answered.
    """
    owned = session is not None
    if not owned:
        if not database_available():
            return None
        session = SessionLocal()
    try:
        rows = (
            session.query(models.Complaint)
            .order_by(models.Complaint.created_at.desc(), models.Complaint.id.desc())
            .all()
        )
        return [complaint_to_contract(row) for row in rows]
    except SQLAlchemyError as exc:
        log.warning("Could not read complaints for the officer dashboard: %s", exc)
        session.rollback()
        return None
    finally:
        if not owned:
            session.close()
