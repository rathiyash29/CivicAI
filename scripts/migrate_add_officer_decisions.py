"""
Schema migration: `officer_decisions` table and `projects.description`.

Why this exists
---------------
An officer decision workflow needs somewhere to record what an officer decided
about a recommendation. The existing tables cannot carry it:

  * `recommendations` is engine output. `recommendations.generate_all`
    refreshes those rows in place on every read, so an officer's decision
    written there would be overwritten.
  * `projects` cannot hold a rejection, because a rejected recommendation
    deliberately creates no project.

So this adds an append-only `officer_decisions` ledger, plus a `description`
column on `projects` so an officer's own wording about a plan survives with the
project rather than only in the ledger.

Alembic is not configured in this repository, so -- exactly like the other
migrations in `scripts/` -- this is a plain, non-destructive script:

  * `CREATE TABLE IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS` only
  * it never issues DROP, TRUNCATE, or DELETE
  * it never drops or recreates an existing table
  * it is safe to run repeatedly

A fresh database does not need it at all: `database.db.init_db()` creates both
from `models.py`. Run this only against a database that already has a
`projects` table from before these were added.

Usage:
    python -m scripts.migrate_add_officer_decisions            # dry run, prints plan
    python -m scripts.migrate_add_officer_decisions --apply    # actually alter
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
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS description TEXT",
    """
    CREATE TABLE IF NOT EXISTS officer_decisions (
        id SERIAL PRIMARY KEY,
        recommendation_id INTEGER REFERENCES recommendations(id),
        project_id INTEGER REFERENCES projects(id),
        officer_id INTEGER REFERENCES users(id),
        decision VARCHAR(30),
        reason TEXT,
        action_snapshot VARCHAR(300),
        created_at TIMESTAMP DEFAULT NOW()
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
                 "A fresh database gets both from models.py via init_db().")
        return 0

    pending = []
    if "description" not in {c["name"] for c in inspector.get_columns("projects")}:
        pending.append(("projects.description", STATEMENTS[0]))
    if "officer_decisions" not in tables:
        pending.append(("officer_decisions table", STATEMENTS[1]))

    if not pending:
        log.info("Already up to date - `projects.description` and "
                 "`officer_decisions` both present.")
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
    has_column = "description" in {c["name"] for c in final.get_columns("projects")}
    has_table = "officer_decisions" in set(final.get_table_names())
    log.info("projects.description present: %s", has_column)
    log.info("officer_decisions present: %s", has_table)
    return 0 if (has_column and has_table) else 1


if __name__ == "__main__":
    raise SystemExit(main())
