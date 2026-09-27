"""
Google BigQuery integration (Member 2's "meaningful BigQuery use" piece).

We don't force every calculation through BigQuery — priority/hotspots/
recommendations still run in Postgres for speed. BigQuery is used for:
  1. A mirrored analytics copy of scored complaints (for ad-hoc SQL /
     Looker-style exploration the officer dashboard doesn't need live).
  2. City-wide aggregate queries that are awkward in Postgres at demo
     scale but showcase real GCP usage for the hackathon judges.

Setup:
  1. Create a GCP project + BigQuery dataset (e.g. `civicai_analytics`).
  2. Create a service account with "BigQuery Data Editor" + "BigQuery Job
     User", download its JSON key.
  3. Set GOOGLE_APPLICATION_CREDENTIALS, BIGQUERY_PROJECT, BIGQUERY_DATASET
     in .env (see .env.example).
  4. Set ENABLE_BIGQUERY_SYNC=true to turn syncing on.

If credentials aren't configured, every function here no-ops with a log
warning instead of crashing the rest of the pipeline — BigQuery is a
bonus, not a dependency for the core app to run.
"""
import logging
import os

import pandas as pd
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("bigquery_client")

PROJECT = os.getenv("BIGQUERY_PROJECT")
DATASET = os.getenv("BIGQUERY_DATASET", "civicai_analytics")
SYNC_ENABLED = os.getenv("ENABLE_BIGQUERY_SYNC", "false").lower() == "true"

_client = None


def _get_client():
    global _client
    if not SYNC_ENABLED:
        return None
    if _client is None:
        try:
            from google.cloud import bigquery
            _client = bigquery.Client(project=PROJECT)
        except Exception as exc:  # noqa: BLE001
            log.warning("BigQuery client unavailable (%s) — skipping sync", exc)
            return None
    return _client


def sync_complaints(complaints_df: pd.DataFrame, table: str = "complaints_scored"):
    """Upload/replace a snapshot of scored complaints for analytics."""
    client = _get_client()
    if client is None:
        return
    table_id = f"{PROJECT}.{DATASET}.{table}"
    from google.cloud import bigquery
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    job = client.load_table_from_dataframe(complaints_df, table_id, job_config=job_config)
    job.result()
    log.info("Synced %d rows to %s", len(complaints_df), table_id)


def run_city_wide_query(sql: str) -> pd.DataFrame:
    """
    Run an arbitrary read query against BigQuery, e.g. for a "priority
    trend by ward over time" chart Member 3 wants but Postgres doesn't
    have enough historical volume to make interesting yet.
    """
    client = _get_client()
    if client is None:
        log.warning("BigQuery not configured — returning empty DataFrame")
        return pd.DataFrame()
    return client.query(sql).to_dataframe()


def example_top_wards_query() -> str:
    return f"""
        SELECT ward, category, AVG(priority_score) AS avg_priority,
               COUNT(*) AS complaint_count
        FROM `{PROJECT}.{DATASET}.complaints_scored`
        GROUP BY ward, category
        ORDER BY avg_priority DESC
        LIMIT 20
    """
