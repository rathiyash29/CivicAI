"""
Re-resolve complaints whose free-text location did not match a ward.

Why this exists
---------------
Before `data.data_loader.WARD_LOCALITIES` existed, the only names a
`Location` row could be matched on were the ward names themselves. A citizen who
typed the neighbourhood they live in ("sukhsagarnagar,Pune") matched nothing, so
their complaint stored `location_id = NULL`, clustered under the literal
"Unassigned" bucket, and was invisible on the dashboard map.

Now that those localities are curated reference data, the same text resolves.
This script re-runs the resolver over the rows that were left behind.

What it guarantees
------------------
* Only complaints with `location_id IS NULL` are considered. A complaint that
  already resolved is never revisited, so a deliberate earlier assignment is not
  silently overwritten by a later change to the alias table.
* `location_text` is NEVER written. The citizen's own words are the historical
  record of what was reported and stay exactly as typed.
* Nothing is guessed. A row is only updated when `resolve_location` returns a
  concrete `Location` from an explicit entry in the curated table. Unresolved
  rows are reported and left alone, which is the correct end state -- "we could
  not place this" beats a confidently wrong ward.
* No complaints are deleted, and no rows are inserted.
* Idempotent: after a successful run, re-running finds no candidates.

Clustering
----------
A complaint's cluster is keyed on `(ward, category)`, so a complaint that was
clustered under "Unassigned" is now clustered under a different scope and its
old cluster assignment is stale. With `--recluster`, the affected complaints
have their `cluster_id` cleared and `db_duplicates.cluster_all_unclustered`
re-groups them into the correct scope, then `reconcile_cluster_stats` refreshes
every cluster's cached statistics. Without `--recluster`, `cluster_id` is left
exactly as it is.

The stale `Unassigned` clusters are NOT deleted: `reconcile_cluster_stats`
treats an orphaned cluster as a real historical group, and `recommendations`
references clusters by id. They simply fall to zero members.

Usage:
    python -m scripts.resolve_complaint_locations               # dry run
    python -m scripts.resolve_complaint_locations --apply
    python -m scripts.resolve_complaint_locations --apply --recluster
"""
import argparse
import logging
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("resolve_locations")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the resolutions (default is a dry run)")
    parser.add_argument("--recluster", action="store_true",
                        help="also re-group the affected complaints into the "
                             "correct (ward, category) cluster scope")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(os.path.join(_REPO_ROOT, "backend", ".env"))

    from database.db import SessionLocal
    from database import models
    from backend import db_duplicates, locations
    from data import data_loader

    # Fail before touching anything if the curated table is malformed.
    data_loader.validate_localities()

    db = SessionLocal()
    try:
        candidates = (
            db.query(models.Complaint)
            .filter(models.Complaint.location_id.is_(None))
            .order_by(models.Complaint.id)
            .all()
        )

        log.info("%d complaint(s) currently unresolved", len(candidates))
        if not candidates:
            log.info("Nothing to re-resolve.")
            return 0

        resolved: list[models.Complaint] = []
        for complaint in candidates:
            raw = complaint.location_text or ""
            loc = locations.resolve_location(db, raw)

            if loc is None:
                # Left unresolved on purpose. Reported so the gap is visible
                # rather than hidden behind a fabricated ward.
                log.info("  UNRESOLVED  #%s  location_text=%r  (no curated mapping)",
                         complaint.id, raw)
                continue

            log.info("  RESOLVED    #%s  location_text=%r -> %s (location_id=%s)",
                     complaint.id, raw, loc.ward, loc.id)
            if args.apply:
                complaint.location_id = loc.id
            resolved.append(complaint)

        if not args.apply:
            log.info("Dry run complete. Re-run with --apply to write these %d "
                     "resolution(s).", len(resolved))
            return 0

        db.commit()
        log.info("Committed %d resolution(s). location_text was not modified.",
                 len(resolved))

        if args.recluster and resolved:
            for complaint in resolved:
                complaint.cluster_id = None
            db.commit()
            created = db_duplicates.cluster_all_unclustered(db)
            log.info("Created %d new cluster(s) in the corrected scope", len(created))
            db_duplicates.reconcile_cluster_stats(db)
            log.info("Cluster statistics reconciled")

        if args.recluster:
            still_null = (
                db.query(models.Complaint)
                .filter(models.Complaint.location_id.is_(None))
                .count()
            )
            log.info("Complaints still unresolved after this run: %d", still_null)

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
