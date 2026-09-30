"""
Schema migration: `project_impacts` table for impact tracking.

Adds a table to record observed impact measurements for completed projects.
This is an append-only, officer-authored record of what was measured after
a project reached "Completed" status.

Alembic is not configured in this repository, so -- exactly like the other
migrations in `scripts/` -- this is a plain, non-destructive script:

  * `CREATE TABLE IF NOT EXISTS` only
  * it never issues DROP, TRUNCATE, or DELETE
  * it never drops or recreates an existing table
  * it is safe to run repeatedly

A fresh database does not need it at all: `database.db.init_db()` creates the
table from `models.py`. Run this only against a database that already has a
`projects` table from before this was added.

Usage:
    python -m scripts.migrate_add_project_impact            # dry run, prints plan
    python -m scripts.migrate_add_project_impact --apply    # actually alter
"""
import argparse
import logging
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("migrate")

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS project_impacts (
        id SERIAL PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id) UNIQUE NOT NULL,
        before_complaint_count INTEGER,
        after_complaint_count INTEGER,
        complaints_resolved INTEGER,
        before_avg_severity_score FLOAT,
        after_avg_severity_score FLOAT,
        before_avg_priority_score FLOAT,
        after_avg_priority_score FLOAT,
        measurement_period_start TIMESTAMP,
        measurement_period_end TIMESTAMP,
        officer_notes TEXT,
        recorded_by_officer_id INTEGER REFERENCES users(id) NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="run the statements (default is a dry run)")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(os.path.join(_REPO_ROOT, "backend", ".env"))

    from sqlalchemy import create_engine, inspect, text
    from database.db import DATABASE_URL

    engine = create_engine(DATABASE_URL)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if "projects" not in tables:
        log.info("No `projects` table found - nothing to migrate. "
                 "A fresh database gets the table from models.py via init_db().")
        return 0

    pending = []
    if "project_impacts" not in tables:
        pending.append(("project_impacts table", STATEMENTS[0]))

    if not pending:
        log.info("Already up to date - `project_impacts` table present.")
    else:
        for label, statement in pending:
            if args.apply:
                with engine.begin() as conn:
                    conn.execute(text(statement))
                log.info("applied: %s", label)
            else:
                log.info("would run: %s", label)

        if not args.apply and pending:
            log.info("Dry run complete. Re-run with --apply to make the change.")

    # Confirm the end state either way.
    final = inspect(engine)
    has_table = "project_impacts" in set(final.get_table_names())
    log.info("project_impacts present: %s", has_table)
    return 0 if has_table else 1


if __name__ == "__main__":
    raise SystemExit(main())