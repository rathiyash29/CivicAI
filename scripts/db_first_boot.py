"""
First-boot database setup for CivicAI.

A fresh PostgreSQL database needs its tables before the app can serve any
DB-backed route. This script does exactly that, and nothing else:

    python -m scripts.db_first_boot            # dry run: prints what it would do
    python -m scripts.db_first_boot --apply    # create the tables

What it does
------------
Runs `database.db.init_db()`, which emits `CREATE TABLE IF NOT EXISTS` for
every model in `database/models.py`. It is:

  * idempotent -- re-running on an already-initialized database is a no-op
  * non-destructive -- it never issues DROP, TRUNCATE, or DELETE, so existing
    data is untouched
  * schema-only -- it does not seed any complaints, users, or demo data

When to run it
--------------
Run it once, by hand, the first time a database is stood up:

    python -m scripts.db_first_boot --apply

The application itself also calls `init_db()` at startup (see
`backend/main.py:_ensure_schema`), so this script exists for operators who
want to prepare the database before starting uvicorn, or who want an explicit
step in a deploy pipeline rather than a silent one.

Migrations for databases created before a schema change already exist as
plain, non-destructive scripts in this same directory:

    scripts/migrate_add_auth_key.py
    scripts/migrate_add_location_text.py
    scripts/migrate_add_officer_decisions.py
    scripts/migrate_add_project_impact.py

Each is run the same way (`--apply` to actually alter, default is a dry run)
and each is safe to run repeatedly.

Seeding demo data
-----------------
Optional, and a separate step. It is NOT part of first boot:

    python -m scripts.seed_demo_complaints
"""
import argparse
import logging
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("first-boot")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="create the tables (default is a dry run)")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(os.path.join(_REPO_ROOT, "backend", ".env"))

    from sqlalchemy import create_engine, inspect
    from database.db import DATABASE_URL, init_db

    log.info("Database URL: %s", _mask(DATABASE_URL))

    if args.apply:
        init_db()
        log.info("init_db() complete")
    else:
        log.info("Dry run: would call init_db(). Re-run with --apply.")

    # Listing the tables is a convenience, not a requirement: it needs a live
    # connection, so it is skipped rather than allowed to crash the dry run on
    # a database that is not up yet.
    try:
        inspector = inspect(create_engine(DATABASE_URL))
        tables = sorted(inspector.get_table_names())
        log.info("Tables present after this run (%d): %s",
                 len(tables), ", ".join(tables))
    except Exception as exc:  # noqa: BLE001 - listing is best-effort
        log.info("Could not list tables (server may not be up yet): %s", exc)
    return 0


def _mask(url: str) -> str:
    """Hide any password in a connection string before logging it."""
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        head, tail = rest.rsplit("@", 1)
        if ":" in head:
            user = head.split(":", 1)[0]
            rest = f"{user}:***@{tail}"
    return f"{scheme}://{rest}"


if __name__ == "__main__":
    raise SystemExit(main())