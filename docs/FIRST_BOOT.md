# First boot: getting a fresh database running

This page covers the minimum safe procedure for bringing up CivicAI against a
brand-new PostgreSQL database. It is intentionally short: every step here is
idempotent and non-destructive.

## 1. Create the database and user

```sql
CREATE DATABASE civicai;
CREATE USER civicai WITH PASSWORD 'civicai_dev_password';
GRANT ALL PRIVILEGES ON DATABASE civicai TO civicai;
```

## 2. Point the app at it

`backend/.env` is already git-ignored and ships a working local default. Copy
the template and set the two values that matter for a real deployment:

```bash
cp backend/.env.example backend/.env
```

```env
DATABASE_URL=postgresql://civicai:civicai_dev_password@localhost:5432/civicai
JWT_SECRET_KEY=change_me_to_a_random_secret
```

Generate a secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

`JWT_SECRET_KEY` is required: without it the app signs tokens with a random
per-process key and warns that they will not survive a restart.

## 3. Create the tables

```bash
python -m scripts.db_first_boot --apply
```

This runs `CREATE TABLE IF NOT EXISTS` for every model in
`database/models.py`. It is safe to re-run and never touches existing rows.
The application also calls this at startup
(`backend/main.py:_ensure_schema`), so this step is only needed if you want the
tables to exist before uvicorn starts.

## 4. (Optional) Apply historical migrations

If you are upgrading from a database created before a schema change, run the
matching migration. Each is non-destructive and idempotent:

```bash
python -m scripts.migrate_add_auth_key --apply
python -m scripts.migrate_add_location_text --apply
python -m scripts.migrate_add_officer_decisions --apply
python -m scripts.migrate_add_project_impact --apply
```

A fresh database does not need any of these: `init_db()` creates those columns
and tables directly from `models.py`.

## 5. (Optional) Seed demo data

Demo data is a separate, explicit step and is **not** part of first boot:

```bash
python -m scripts.seed_demo_complaints
```

## 6. Start the server

```bash
uvicorn backend.app:app --reload
```

The citizen frontend proxies `/api` to this server. See
`frontend/citizen/README.md` and `frontend/government/README.md`.

## What first boot does NOT do

It does not create users, seed complaints, run the intelligence pipeline, or
start any background process. Each of those is a deliberate, separate step so a
fresh deployment starts empty and stays under the operator's control.