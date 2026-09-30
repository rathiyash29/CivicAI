"""
Schema migration: add `users.password_hash`.

Why this exists
---------------
Accounts used to live in a process-local dict in `backend/auth.py`, so they were
deleted by every restart. Users are now persisted in the existing `users`
table, which is the only table that has to change: it already holds identity,
role and complaint ownership, and now also holds the bcrypt hash that makes an
account log in.

Adding a password hash column is the one schema change auth requires, and it is
additive -- no existing column is dropped, renamed, retyped or rewritten, and
no row is modified.

Existing rows
-------------
Rows that already exist are left exactly as they are, with `password_hash` NULL.
They are complaint-ownership records for accounts that lived in the old
in-process dict; the password that unlocked them died with that process and is
not recoverable. A NULL hash means "cannot log in", and login refuses such a row
rather than treating it as an account with an empty password. Accounts are
re-created by registering again, which adopts the existing row.

Nothing here is a credential: the script never reads, writes, prints or logs a
hash, and there is no code path that produces a hash from an existing row.

Idempotency
-----------
Alembic is not configured in this repository yet, so this is a plain,
non-destructive script:

  * `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
  * never issues DROP, TRUNCATE, DELETE or UPDATE
  * never drops or recreates a table
  * safe to run repeatedly, and a no-op once the column exists

A fresh database does not need it -- `database.db.init_db()` creates the column
straight from `models.py`. Run this only against a database whose `users` table
predates the column.

Usage:
    python -m scripts.migrate_add_password_hash            # dry run, prints plan
    python -m scripts.migrate_add_password_hash --apply    # actually alter
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

# 255 is bcrypt's full output length. A wider column would invite something else
# being stored here.
ADD_COLUMN = "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="run the statement (default is a dry run)")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(os.path.join(_REPO_ROOT, "backend", ".env"))

    from sqlalchemy import create_engine, inspect, text
    from database.db import DATABASE_URL

    engine = create_engine(DATABASE_URL)
    inspector = inspect(engine)

    if "users" not in inspector.get_table_names():
        log.info("No `users` table found - nothing to migrate. A fresh database "
                 "gets this column from models.py via init_db().")
        return 0

    before = {c["name"] for c in inspector.get_columns("users")}
    if "password_hash" in before:
        log.info("users.password_hash already present - nothing to do.")
    elif args.apply:
        with engine.begin() as conn:
            conn.execute(text(ADD_COLUMN))
        log.info("applied: %s", ADD_COLUMN)
    else:
        log.info("would run: %s", ADD_COLUMN)

    # Reported as a count only. A hash is a credential and is never logged.
    if "password_hash" in before or args.apply:
        with engine.begin() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
            usable = conn.execute(
                text("SELECT COUNT(*) FROM users WHERE password_hash IS NOT NULL")
            ).scalar()
        log.info("users rows: %s total, %s able to log in, %s unable",
                 total, usable, total - usable)
    else:
        log.info("would add a nullable password_hash; no existing row is modified")

    if not args.apply:
        log.info("Dry run complete. Re-run with --apply to make the change.")

    after = {c["name"] for c in inspect(engine).get_columns("users")}
    log.info("password_hash present after migration: %s", "password_hash" in after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
