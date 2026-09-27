"""
Regression test: no database credential is baked into the source.

`database/db.py` used to fall back to a hardcoded
`postgresql://<user>:<password>@localhost/civicai` when `DATABASE_URL` was
absent. A password in source is a password that ends up in a git history, in
every clone, and in any container image built from the tree -- and it silently
"works" on a developer's machine, so nobody notices until it leaks.

`DATABASE_URL` must come from the environment, and the no-configuration
fallback must carry no credential at all.
"""
import os
import re

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIRS = ("backend", "database", "data", "scripts", "tests")
# Vendored code is not our source and is not something this test can govern.
SKIP_DIRS = {".venv", "venv", "env", "site-packages", "node_modules",
             "__pycache__", ".git", ".kilo", "dist", "build"}

# The development credential that used to be hardcoded in database/db.py.
LEGACY_CREDENTIALS = ("civicai_pass", "civicai_user:")


def _source_files():
    """Every first-party source file, minus this test file itself."""
    this_file = os.path.normcase(os.path.abspath(__file__))
    for directory in SOURCE_DIRS:
        root = os.path.join(REPO_ROOT, directory)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if not name.endswith((".py", ".sql", ".toml", ".ini", ".cfg", ".md")):
                    continue
                path = os.path.join(dirpath, name)
                if os.path.normcase(os.path.abspath(path)) == this_file:
                    continue  # this file names the credential in order to ban it
                yield path


def test_no_source_file_contains_the_legacy_credential():
    offenders = []
    for path in _source_files():
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
        for credential in LEGACY_CREDENTIALS:
            if credential in text:
                offenders.append(f"{os.path.relpath(path, REPO_ROOT)}: {credential}")
    assert not offenders, "credential found in source: " + ", ".join(offenders)


def test_no_source_file_hardcodes_a_password_bearing_connection_string():
    """`scheme://user:password@host` written as a literal, in any file."""
    pattern = re.compile(r"[\"']([a-z][a-z0-9+]*://[^\"'/\s:@]+:[^\"'/\s@]+@[^\"'\s]+)[\"']",
                         re.IGNORECASE)
    offenders = []
    for path in _source_files():
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                for match in pattern.finditer(line):
                    if match.group(1).startswith("sqlite"):
                        continue
                    offenders.append(
                        f"{os.path.relpath(path, REPO_ROOT)}: {match.group(1)}")
    assert not offenders, "connection string with a password in source: " + \
        ", ".join(offenders)


def test_database_url_falls_back_to_a_credential_free_local_file():
    from database import db

    assert db.LOCAL_FALLBACK_URL.startswith("sqlite:///")
    assert "postgres" not in db.LOCAL_FALLBACK_URL
    assert "@" not in db.LOCAL_FALLBACK_URL


def _database_url_in_subprocess(env_overrides):
    """
    Read `database.db.DATABASE_URL` in a fresh interpreter.

    Deliberately a subprocess: the module resolves the URL at import time and
    owns a process-wide engine, so reloading it in-process would repoint every
    other module in the suite at a different database.
    """
    import json
    import subprocess
    import sys

    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, "-c",
         "import json, database.db as d; print(json.dumps(d.DATABASE_URL))"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


def test_database_url_is_read_from_the_environment():
    """The value that is used is the one in the environment, verbatim."""
    assert _database_url_in_subprocess(
        {"DATABASE_URL": "sqlite:///from_env.db"}) == "sqlite:///from_env.db"


def test_missing_database_url_does_not_invent_a_password():
    """
    With nothing configured, the module must not reach for a credential. It
    may fall back to a local file, but that file must be SQLite and anonymous.

    An empty `DATABASE_URL` stands in for "not configured" here: it is what a
    deployment that forgot to set the variable effectively has, and
    `load_dotenv` will not overwrite it.
    """
    import subprocess
    import sys

    script = ("import database.db as d; print(d.DATABASE_URL); "
              "print(d.LOCAL_FALLBACK_URL)")
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True,
        text=True, env={**os.environ, "DATABASE_URL": ""})
    assert result.returncode == 0, result.stderr
    used, fallback = result.stdout.strip().splitlines()
    assert used == fallback
    assert used.startswith("sqlite:///")
    assert "postgres" not in used and "@" not in used


def test_engine_points_at_the_configured_url():
    from database import db
    assert str(db.engine.url) == db.DATABASE_URL
