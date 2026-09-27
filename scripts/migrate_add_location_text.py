"""
Schema migration: add `complaints.location_text`.

Why this exists
---------------
`Complaint.location_text` stores the raw free-text location a citizen typed.
`Complaint.location_id` is only set when that text resolves to a known ward, so
without this column an unrecognised location is silently lost.

Alembic is not configured in this repository yet, so this is a plain,
non-destructive migration script:

  * it uses `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
  * it never issues DROP, TRUNCATE, or DELETE
  * it never drops or recreates an existing table
  * it is safe to run repeatedly

A fresh database does not need it at all -- `database.db.init_db()` creates
the column directly from `models.py`. Run this only against a database that
already has a `complaints` table from before the column was added.

Usage:
    python -m scripts.migrate_add_location_text            # dry run, prints plan
    python -m scripts.migrate_add_location_text --apply    # actually alter
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
    # Non-destructive and idempotent. IF NOT EXISTS makes re-running a no-op.
    "ALTER TABLE complaints ADD COLUMN IF NOT EXISTS location_text VARCHAR(200)",
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

    if "complaints" not in inspector.get_table_names():
        log.info("No `complaints` table found - nothing to migrate. "
                 "A fresh database gets this column from models.py via init_db().")
        return 0

    columns = {c["name"] for c in inspector.get_columns("complaints")}
    if "location_text" in columns:
        log.info("`complaints.location_text` already exists - nothing to do.")
        return 0

    with engine.begin() as conn:
        for statement in STATEMENTS:
            if args.apply:
                conn.execute(text(statement))
                log.info("applied: %s", statement)
            else:
                log.info("would run: %s", statement)

    if not args.apply:
        log.info("Dry run complete. Re-run with --apply to make the change.")

    # Confirm the end state either way.
    after = {c["name"] for c in inspect(engine).get_columns("complaints")}
    log.info("location_text present after migration: %s", "location_text" in after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
