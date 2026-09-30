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
import re

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

# Approximate administrative centre of each ward, plus the locality the ward
# administers. These are static constants on purpose:
#
#   * no geocoding API is called, so nothing here costs money, needs a key, or
#     changes between runs -- a demo that re-centres its own wards is impossible
#     to test;
#   * a ward centroid is a *label position* for an aggregate, not a claim that a
#     complaint happened at that exact point. The dashboard says as much.
#
# Every value is a rounded ward-level centre, accurate to roughly a kilometre.
# `load_coordinates` writes them into the existing nullable `latitude`,
# `longitude` and `area` columns; no schema change is involved.
#
#   ward            latitude  longitude  area
WARD_CENTROIDS: dict[str, tuple[float, float, str]] = {
    "Kothrud":      (18.5074, 73.8077, "Kothrud"),
    "Hadapsar":     (18.5089, 73.9260, "Hadapsar"),
    "Wanowrie":     (18.5087, 73.8620, "Wanowrie"),
    "Aundh":        (18.5590, 73.8080, "Aundh"),
    "Baner":        (18.5642, 73.7769, "Baner"),
    "Shivajinagar": (18.5308, 73.8470, "Shivajinagar"),
    "Kondhwa":      (18.4649, 73.8927, "Kondhwa"),
    "Katraj":       (18.4483, 73.8677, "Katraj"),
    "Yerawada":     (18.5515, 73.8795, "Yerawada"),
    "Viman Nagar":  (18.5679, 73.9143, "Viman Nagar"),
}

# Curated locality -> ward aliases, the same way a municipal gazetteer would.
#
# WHY THIS EXISTS
# ---------------
# Citizens type the neighbourhood they live in ("sukhsagarnagar,Pune"), not the
# administrative ward name. `backend/locations.py` can only resolve text that
# matches a `Location` row, and the ward names alone are not enough, so those
# complaints stayed `location_id = NULL` and landed in the "Unassigned" bucket --
# invisible on the map and excluded from every per-ward aggregate.
#
# WHY IT IS A CONSTANT, NOT A GUESS
# ---------------------------------
# This is an explicit, reviewable, version-controlled list. Each entry is a
# locality a human has placed inside a ward; it is never inferred at runtime,
# never fuzzy-matched, and never extended from a free-text string. A locality
# that is not listed here stays unresolved, which is the correct outcome -- an
# honest "unresolved" beats a confidently wrong ward, because a wrong ward
# silently corrupts every downstream aggregate (population normalisation,
# infrastructure gap, hotspot scores).
#
# Adding an entry is therefore a deliberate editorial act, reviewed in a diff
# like any other code change. Adding a locality this table does not name would
# mean inventing civic geography, so it is deliberately not possible.
#
# Only the ward's own localities belong here. A locality that straddles two
# wards must be left out entirely rather than guessed into one of them.
#
# Two constraints keep this table from poisoning the resolver:
#
#   * entries are LOCALITY NAMES ONLY. Never write a city, a district or a
#     "Locality, Pune" form here. The `area` column is comma-separated and the
#     resolver splits on commas, so an entry containing a city name would
#     become a bare alias for that city -- and "Pune" would then resolve to a
#     ward, which is exactly the kind of confidently wrong answer this whole
#     mechanism exists to prevent. A citizen typing "Bibvewadi, Pune" already
#     matches the "Bibvewadi" alias on its own, because whole-word matching
#     tolerates the extra city token.
#   * an entry may not equal a ward name. `validate_localities` refuses both
#     cases loudly rather than letting them reach the database.
#
#   ward          localities administered by that ward
WARD_LOCALITIES: dict[str, list[str]] = {
    "Kothrud": [
        "Sukhsagar Nagar",
        "Sukhsagarnagar",
    ],
    "Hadapsar": [
        "Bibvewadi",
    ],
}

# City, district and state names. A locality equal to one of these is a data
# error, not a location: see the constraints above.
NON_LOCALITY_NAMES = {
    "pune", "pimpri", "chinchwad", "pcmc", "maharashtra", "india",
}


def validate_localities() -> None:
    """
    Fail loudly on a locality entry that would resolve the wrong thing.

    Raises `ValueError` rather than silently skipping, because an entry like a
    bare city name is a data bug in *this file*, and quietly dropping it would
    leave a half-configured mapping that looks intentional.
    """
    ward_names = {w.lower() for w in PUNE_WARDS}
    problems: list[str] = []

    for ward, localities in WARD_LOCALITIES.items():
        if ward not in PUNE_WARDS:
            problems.append(f"{ward!r} has localities but is not in PUNE_WARDS")
        for locality in localities:
            key = re.sub(r"\s+", " ", locality.strip().lower())
            if not key:
                problems.append(f"{ward!r} has an empty locality")
            elif key in NON_LOCALITY_NAMES:
                problems.append(
                    f"{ward!r} lists the city/district name {locality!r}; "
                    "localities must be locality names only"
                )
            elif key in ward_names:
                problems.append(
                    f"{ward!r} lists {locality!r}, which is already a ward name"
                )

    if problems:
        raise ValueError(
            "WARD_LOCALITIES is invalid:\n  " + "\n  ".join(problems)
        )


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


def ward_area_label(ward: str) -> str:
    """
    The value written to `Location.area` for a ward: the ward's own name
    followed by any curated localities it administers, comma separated.

    The ward name stays in the list so the column still reads sensibly on its
    own, and so a `None` area remains impossible for a configured ward. The
    resolver (`backend/locations.resolve_location`) splits this on commas and
    matches each part independently, which is what lets a citizen who typed a
    neighbourhood name instead of the ward name be resolved correctly.

    Only names from `WARD_LOCALITIES` ever appear here. Nothing is derived from
    complaint text, so this function cannot invent a location.
    """
    parts = [ward, *WARD_LOCALITIES.get(ward, [])]
    return ", ".join(parts)


def load_coordinates(db: Session) -> int:
    """
    Fill in the existing nullable `latitude` / `longitude` / `area` columns.

    Idempotent by construction: it matches on the same (ward, city) key every
    other loader uses and only writes when the stored value differs, so running
    it twice leaves the table byte-identical. A ward missing from
    `WARD_CENTROIDS` is skipped and counted as unprocessed rather than being
    given a made-up point.

    This is what makes the dashboard map possible: `db_hotspots` already
    passes `latitude`, `longitude` and `area` straight through from this table,
    so filling it in here needs no API change at all.
    """
    validate_localities()

    processed = 0
    for ward, (latitude, longitude, _centroid_label) in WARD_CENTROIDS.items():
        if ward not in PUNE_WARDS:
            # The centroid table and the ward list are meant to agree. A stray
            # entry is a bug in this file, not a reason to invent a location.
            log.warning("Ward %r has a centroid but is not in PUNE_WARDS; skipped", ward)
            continue

        area = ward_area_label(ward)
        loc = get_or_create_location(db, ward)
        if (
            loc.latitude != latitude
            or loc.longitude != longitude
            or loc.area != area
        ):
            loc.latitude = latitude
            loc.longitude = longitude
            loc.area = area
        processed += 1

    log.info("Set ward centroids for %d wards", processed)
    return processed


def load_all() -> dict:
    """Create the schema if needed and (re)load every dataset. Idempotent."""
    init_db()
    with session_scope() as db:
        counts = {
            "coordinates": load_coordinates(db),
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
