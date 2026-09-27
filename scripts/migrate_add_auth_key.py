"""
Schema migration: add and backfill `users.auth_key`.

Why this exists
---------------
`users.auth_key` is the stable identity of a mirrored auth account. The auth
module's integer id restarts from 1 on every process restart, so it cannot be
used to link a complaint to the person who filed it: a later account can be
handed an id an earlier account already used and would then inherit that
account's complaints.

Existing rows were created before this column existed. They are backfilled
from `email`, which is the same value `auth_key` is derived from, so no row
changes identity and no complaint changes owner. Rows are left alone when they
have no email: they simply stay `NULL` and are matched by email at runtime
until the account is seen again.

Alembic is not configured in this repository yet, so this is a plain,
non-destructive migration script:

  * it uses `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
  * it never issues DROP, TRUNCATE, or DELETE
  * it never drops or recreates an existing table
  * it is safe to run repeatedly

A fresh database does not need it at all -- `database.db.init_db()` creates the
column directly from `models.py`. Run this only against a database that
already has a `users` table from before the column was added.

Usage:
    python -m scripts.migrate_add_auth_key            # dry run, prints plan
    python -m scripts.migrate_add_auth_key --apply    # actually alter
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

ADD_COLUMN = "ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_key VARCHAR(255)"

CREATE_INDEX = "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_auth_key ON users (auth_key)"


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

    if "users" not in inspector.get_table_names():
        log.info("No `users` table found - nothing to migrate. "
                 "A fresh database gets this column from models.py via init_db().")
        return 0

    columns = {c["name"] for c in inspector.get_columns("users")}
    needs_column = "auth_key" not in columns

    with engine.begin() as conn:
        if needs_column:
            for statement in (ADD_COLUMN, CREATE_INDEX):
                if args.apply:
                    conn.execute(text(statement))
                    log.info("applied: %s", statement)
                else:
                    log.info("would run: %s", statement)

        # Backfill. Non-destructive: only fills the new column, keyed off the
        # email that the row already had.
        if args.apply:
            result = conn.execute(text(
                "UPDATE users SET auth_key = LOWER(TRIM(email)) "
                "WHERE auth_key IS NULL AND email IS NOT NULL "
                "AND email <> ''"
            ))
            log.info("backfilled auth_key on %s existing user row(s)", result.rowcount)
        else:
            # The column may not exist yet in a dry run, so count the rows that
            # a backfill would touch using only columns that are already there.
            source = "email" if needs_column else "auth_key"
            pending = conn.execute(text(
                f"SELECT COUNT(*) FROM users "
                f"WHERE {source} IS NULL AND email IS NOT NULL AND email <> ''"
            )).scalar()
            log.info("would backfill auth_key on %s existing user row(s)", pending)

    if not args.apply:
        log.info("Dry run complete. Re-run with --apply to make the change.")

    after = {c["name"] for c in inspect(engine).get_columns("users")}
    log.info("auth_key present after migration: %s", "auth_key" in after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
