"""
Dataset loading for CivicAI (Member 2).

WHAT THIS LOADER ACTUALLY LOADS
-------------------------------
**Synthetic demo data.** It does not ingest any live external dataset.

The earlier version of this file advertised "real-world dataset ingestion"
and pointed at two CSV resource URLs on a public open-data portal. Both were
checked and both return HTTP 404, so the loader silently fell back to
`random`-generated rows on every single run while its docstring claimed real
data. The URLs and the claim have been removed rather than left to mislead
anyone reading the code before a demo.

The synthetic data is shaped to be *internally consistent and plausible* for
Pune -- plausible ward populations, population density derived from a real
per-ward area rather than a random divisor, and investment totals that are
skewed towards the wards the infrastructure table also rates as well served,
so that the investment-gap factor produces a meaningful spread instead of
collapsing to its neutral default. It is still invented, and every row is
labelled as synthetic in its `source` column so the dashboard can say so.

Swapping in a real open-data portal later means replacing the three
`_synthetic_*()` builders. Nothing downstream needs to change.

Usage:
    python -m data.data_loader --load-all
"""
import argparse
import logging

import pandas as pd
from sqlalchemy.orm import Session

from database.db import session_scope, init_db
from database import models

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("data_loader")

SYNTHETIC_SOURCE = "SYNTHETIC demo data (not real)"

# Wards used across the prototype. Keep in sync with whatever Member 3 uses
# for the map.
PUNE_WARDS = [
    "Kothrud", "Hadapsar", "Wanowrie", "Aundh", "Baner",
    "Shivajinagar", "Kondhwa", "Katraj", "Yerawada", "Viman Nagar",
]

CATEGORIES = [
    "Road Infrastructure", "Water Supply", "Electricity",
    "Sanitation", "Healthcare", "Education",
]

# Plausible land area in km^2 per ward, so population density is derived from
# something real rather than dividing by a random number.
WARD_AREA_KM2 = {
    "Kothrud": 12.4, "Hadapsar": 21.7, "Wanowrie": 10.8, "Aundh": 6.2,
    "Baner": 13.5, "Shivajinagar": 4.1, "Kondhwa": 19.3, "Katraj": 9.8,
    "Yerawada": 10.5, "Viman Nagar": 11.6,
}

# Fixed, not random: a demo where the numbers move on every reload is harder
# to reason about, and these are only placeholders anyway.
WARD_PROFILE = {
    #            population  literacy  coverage bias (0=worst served, 1=best)
    "Kothrud":      (118_000, 91.2, 0.55),
    "Hadapsar":     (203_000, 84.7, 0.30),
    "Wanowrie":     (142_000, 82.3, 0.40),
    "Aundh":         (31_000, 95.4, 0.85),
    "Baner":        (187_000, 89.1, 0.65),
    "Shivajinagar":  (76_000, 86.5, 0.70),
    "Kondhwa":      (256_000, 79.8, 0.25),
    "Katraj":       (164_000, 88.7, 0.50),
    "Yerawada":     (149_000, 83.9, 0.35),
    "Viman Nagar":  (127_000, 87.2, 0.60),
}


def _synthetic_demographics() -> pd.DataFrame:
    """Ward population, density and literacy. Deterministic."""
    rows = []
    for ward in PUNE_WARDS:
        population, literacy, _ = WARD_PROFILE[ward]
        rows.append({
            "ward": ward,
            "population": population,
            "population_density": round(population / WARD_AREA_KM2[ward], 1),
            "literacy_rate": literacy,
        })
    return pd.DataFrame(rows)


def _synthetic_infrastructure() -> pd.DataFrame:
    """
    Per-ward, per-category coverage and gap scores.

    Coverage is anchored to the ward's profile and nudged by category, so a
    well-served ward scores well on every category. Pure per-cell noise would
    look arbitrary and undermine the demo narrative.
    """
    category_bias = {
        "Road Infrastructure": 0.00,
        "Water Supply": 0.05,
        "Electricity": -0.05,
        "Sanitation": -0.10,
        "Healthcare": 0.10,
        "Education": 0.08,
    }
    rows = []
    for ward in PUNE_WARDS:
        _, _, base = WARD_PROFILE[ward]
        for cat in CATEGORIES:
            coverage = round(min(98.0, max(15.0, 25.0 + base * 70.0
                                            + category_bias[cat] * 70.0)), 1)
            rows.append({
                "ward": ward,
                "category": cat,
                "coverage_score": coverage,
                "gap_score": round(100.0 - coverage, 1),
            })
    return pd.DataFrame(rows)


def _synthetic_investments() -> pd.DataFrame:
    """
    Ward budgets over 2023-2025.

    Allocation tracks the ward's coverage bias: a ward that is already
    well served has historically received more money. That inverse
    relationship is exactly what the investment-gap factor is supposed to
    detect, so the demo data has to contain it for the factor to be
    meaningful.
    """
    status_by_year = {2023: "Completed", 2024: "Completed", 2025: "Ongoing"}
    rows = []
    for ward in PUNE_WARDS:
        _, _, base = WARD_PROFILE[ward]
        for cat in CATEGORIES:
            for year in (2023, 2024, 2025):
                # rupees, in lakhs
                amount = round(45.0 + base * 320.0 + (hash((ward, cat, year)) % 40), 1)
                rows.append({
                    "ward": ward,
                    "category": cat,
                    "amount_allocated": amount,
                    "project_status": status_by_year[year],
                    "year": year,
                })
    return pd.DataFrame(rows)


def get_or_create_location(db: Session, ward: str) -> models.Location:
    loc = db.query(models.Location).filter_by(ward=ward, city="Pune").first()
    if loc is None:
        loc = models.Location(ward=ward, city="Pune")
        db.add(loc)
        db.flush()  # get loc.id without committing yet
    return loc


def load_demographics(db: Session) -> int:
    """Upsert one Demographics row per ward. Returns rows processed."""
    df = _synthetic_demographics()
    processed = 0

    for _, row in df.iterrows():
        ward = str(row["ward"]).strip()
        if not ward or ward.lower() == "nan":
            continue
        loc = get_or_create_location(db, ward)
        demo = db.query(models.Demographics).filter_by(location_id=loc.id).first()
        if demo is None:
            demo = models.Demographics(location_id=loc.id)
            db.add(demo)
        demo.population = int(row["population"])
        demo.population_density = float(row["population_density"])
        demo.literacy_rate = float(row["literacy_rate"])
        demo.source = SYNTHETIC_SOURCE
        processed += 1

    log.info("Loaded demographics for %d wards (%s)", processed, SYNTHETIC_SOURCE)
    return processed


def load_infrastructure(db: Session) -> int:
    """
    Upsert one Infrastructure row per (ward, category).

    Upsert rather than insert: the previous version appended a new row on
    every run, so a second `load_all()` left two rows per pair and
    `get_infrastructure_gap` then picked whichever the query returned first.
    """
    df = _synthetic_infrastructure()
    processed = 0

    for _, row in df.iterrows():
        ward = str(row["ward"]).strip()
        if not ward or ward.lower() == "nan":
            continue
        loc = get_or_create_location(db, ward)
        infra = (
            db.query(models.Infrastructure)
            .filter_by(location_id=loc.id, category=row["category"])
            .first()
        )
        if infra is None:
            infra = models.Infrastructure(location_id=loc.id, category=row["category"])
            db.add(infra)
        infra.coverage_score = float(row["coverage_score"])
        infra.gap_score = float(row["gap_score"])
        infra.source = SYNTHETIC_SOURCE
        processed += 1

    log.info("Loaded infrastructure for %d ward/category pairs (%s)",
             processed, SYNTHETIC_SOURCE)
    return processed


def load_investments(db: Session) -> int:
    """
    Upsert one Investment row per (ward, category, year).

    Without this table the investment-gap factor had no data to read and
    always returned its neutral 50.0 default, making 10% of the priority
    formula inert.
    """
    df = _synthetic_investments()
    processed = 0

    for _, row in df.iterrows():
        ward = str(row["ward"]).strip()
        if not ward or ward.lower() == "nan":
            continue
        loc = get_or_create_location(db, ward)
        investment = (
            db.query(models.Investment)
            .filter_by(location_id=loc.id,
                       category=row["category"],
                       year=int(row["year"]))
            .first()
        )
        if investment is None:
            investment = models.Investment(
                location_id=loc.id,
                category=row["category"],
                year=int(row["year"]),
            )
            db.add(investment)
        investment.amount_allocated = float(row["amount_allocated"])
        investment.project_status = row["project_status"]
        investment.source = SYNTHETIC_SOURCE
        processed += 1

    log.info("Loaded %d investment rows (%s)", processed, SYNTHETIC_SOURCE)
    return processed


def load_all() -> dict:
    """Create the schema if needed and (re)load every dataset. Idempotent."""
    init_db()
    with session_scope() as db:
        counts = {
            "demographics": load_demographics(db),
            "infrastructure": load_infrastructure(db),
            "investments": load_investments(db),
        }
    log.info("Dataset load complete: %s", counts)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--load-all", action="store_true",
                        help="create tables and load all synthetic demo datasets")
    args = parser.parse_args()
    if args.load_all:
        load_all()
    else:
        parser.print_help()
