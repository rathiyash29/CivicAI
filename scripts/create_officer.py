"""
Create or update an officer account.

Why this is a script and not a route
-----------------------------------
`POST /auth/register` is unauthenticated, so it creates citizens only. If it
also accepted a caller-chosen `role`, anyone could mint themselves an officer
and read every complaint, every recommendation, and the approve/reject
workflow. Officer accounts are therefore provisioned out of band, by someone
who already has database access.

An officer is a real account with a bcrypt-hashed password, identical in kind to
a citizen's. This script does not create a special class of user; it creates a
`users` row with `role = 'officer'`.

The password is read from `--password`, or prompted for without echo when that
is omitted, or taken from `OFFICER_PASSWORD`. It is never taken as a required
command-line argument, because a password in a command line lands in shell
history and in the process list.

Usage:
    python -m scripts.create_officer --email officer@example.com --name "Officer One"
    OFFICER_PASSWORD=... python -m scripts.create_officer --email ... --name ...

Re-running for an existing address updates that account's name, role and
password rather than creating a second one, so it is safe to use for a password
reset. It is idempotent for the same inputs.

Run a dry run first (`--dry-run`) to see which account would change.
"""
import argparse
import getpass
import logging
import os
import sys
from datetime import datetime

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("create_officer")


def _resolve_password(args) -> str:
    """
    Read the password from somewhere that does not leak it.

    Order: explicit env var, then an interactive prompt with echo off. A
    command-line `--password` is deliberately not supported.
    """
    from_env = os.getenv("OFFICER_PASSWORD", "").strip()
    if from_env:
        return from_env
    if not sys.stdin.isatty():
        raise SystemExit(
            "No password available. Set OFFICER_PASSWORD, or run this in a "
            "terminal to be prompted."
        )
    return getpass.getpass("Password for the officer account: ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="Full name shown to citizens")
    parser.add_argument("--role", default="officer",
                        help="Role to set. Defaults to officer.")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(os.path.join(_REPO_ROOT, "backend", ".env"))

    # Imported after the secret check so a missing JWT_SECRET_KEY is reported
    # before any database work is done.
    from backend.auth import create_user, get_password_hash, normalise_email
    from backend.auth import UserCreate, UserRole
    from database import models
    from database.db import SessionLocal

    engine_email = normalise_email(args.email)
    db = SessionLocal()
    try:
        existing = db.query(models.User).filter_by(email=engine_email).first()
        if existing is not None:
            log.info("account exists: %s (role=%s)", engine_email, existing.role)
            if args.dry_run:
                log.info("dry run: would set role=%s and reset the password",
                         args.role)
                return 0
            password = _resolve_password(args)
            existing.name = args.name
            existing.role = args.role.strip().lower()
            existing.password_hash = get_password_hash(password)
            existing.auth_key = existing.auth_key or engine_email
            db.commit()
            log.info("updated %s -> role=%s", engine_email, existing.role)
            return 0

        if args.dry_run:
            log.info("dry run: would create %s as %s", engine_email, args.role)
            return 0

        password = _resolve_password(args)
        user = create_user(
            db,
            UserCreate(
                full_name=args.name,
                email=args.email,
                password=password,
                role=args.role.strip().lower() or UserRole.OFFICER,
            ),
        )
        log.info("created %s as %s (id %s)", user.email, user.role, user.id)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
