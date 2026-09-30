"""Tests for the data loader: content, honesty and idempotency."""
import pytest

from data import data_loader
from database import models


def _counts(db):
    return {
        "locations": db.query(models.Location).count(),
        "demographics": db.query(models.Demographics).count(),
        "infrastructure": db.query(models.Infrastructure).count(),
        "investments": db.query(models.Investment).count(),
    }


# --- content ---------------------------------------------------------------

def test_loads_every_dataset(clean_db):
    data_loader.load_all()
    counts = _counts(clean_db)
    assert counts["locations"] == len(data_loader.PUNE_WARDS)
    assert counts["demographics"] == len(data_loader.PUNE_WARDS)
    assert counts["infrastructure"] == len(data_loader.PUNE_WARDS) * len(data_loader.CATEGORIES)
    assert counts["investments"] > 0


def test_investments_are_now_populated(clean_db):
    """Before the fix this table stayed empty, making the 10% factor inert."""
    data_loader.load_all()
    rows = clean_db.query(models.Investment).all()
    assert rows
    assert all(r.amount_allocated and r.amount_allocated > 0 for r in rows)
    assert all(r.year in (2023, 2024, 2025) for r in rows)
    assert all(r.source == data_loader.SYNTHETIC_SOURCE for r in rows)


def test_investment_gap_produces_a_real_spread(clean_db):
    from backend import data_engine
    data_loader.load_all()

    gaps = set()
    for loc in clean_db.query(models.Location).all():
        for cat in data_loader.CATEGORIES:
            gaps.add(data_engine.get_investment_gap(clean_db, loc.id, cat))

    assert 50.0 not in gaps or len(gaps) > 1, \
        "investment gap should not collapse to the neutral default"


def test_gap_and_coverage_are_complementary(clean_db):
    data_loader.load_all()
    for row in clean_db.query(models.Infrastructure).all():
        assert row.coverage_score + row.gap_score == pytest.approx(100.0)


def test_population_density_is_derived_from_real_area(clean_db):
    data_loader.load_all()
    for demo in clean_db.query(models.Demographics).all():
        expected = demo.population / data_loader.WARD_AREA_KM2[demo.location.ward]
        assert demo.population_density == pytest.approx(expected, abs=0.1)


# --- idempotency -----------------------------------------------------------

def test_loading_twice_does_not_duplicate_infrastructure(clean_db):
    """Regression: the old loader appended a row per run."""
    data_loader.load_all()
    first = _counts(clean_db)
    data_loader.load_all()
    assert _counts(clean_db) == first


def test_infrastructure_has_one_row_per_ward_category(clean_db):
    data_loader.load_all()
    data_loader.load_all()

    seen = {}
    for row in clean_db.query(models.Infrastructure).all():
        key = (row.location_id, row.category)
        seen[key] = seen.get(key, 0) + 1
    assert max(seen.values()) == 1
    assert len(seen) == len(data_loader.PUNE_WARDS) * len(data_loader.CATEGORIES)


def test_investments_have_one_row_per_ward_category_year(clean_db):
    data_loader.load_all()
    data_loader.load_all()

    seen = set()
    for row in clean_db.query(models.Investment).all():
        key = (row.location_id, row.category, row.year)
        assert key not in seen, f"duplicate investment row for {key}"
        seen.add(key)


def test_reloading_updates_values_in_place(clean_db):
    data_loader.load_all()
    data_loader.load_all()
    demo = clean_db.query(models.Demographics).first()
    assert demo.population > 0
    assert demo.population_density > 0


def test_load_all_is_deterministic(clean_db):
    data_loader.load_all()
    first = sorted((d.location.ward, d.population) for d in
                   clean_db.query(models.Demographics).all())
    clean_db.query(models.Demographics).delete()
    clean_db.commit()
    data_loader.load_all()
    second = sorted((d.location.ward, d.population) for d in
                    clean_db.query(models.Demographics).all())
    assert first == second


# --- honesty ---------------------------------------------------------------

def test_every_row_is_labelled_synthetic(clean_db):
    """A demo must never be mistakable for real civic data."""
    data_loader.load_all()
    for model in (models.Demographics, models.Infrastructure, models.Investment):
        for row in clean_db.query(model).all():
            assert "SYNTHETIC" in (row.source or "").upper(), \
                f"{model.__name__} row is not labelled synthetic"


def test_no_dead_external_urls_are_claimed(clean_db):
    source = open(data_loader.__file__, encoding="utf-8").read()
    assert "data.opencity.in" not in source
    assert "opendata.punecorporation.org" not in source


def test_loader_does_not_require_network(clean_db, monkeypatch):
    """Import-time the loader must not need requests or any outbound call."""
    import requests

    def explode(*a, **kw):
        raise AssertionError("loader attempted a network call")

    monkeypatch.setattr(requests, "get", explode)
    data_loader.load_all()  # must not raise


# --- ward localities --------------------------------------------------------
#
# The curated locality -> ward table is what lets a complaint written against a
# neighbourhood name ("sukhsagarnagar") resolve to a ward at all. It is data, so
# it gets the same honesty checks as everything else the loader writes.

def test_locality_table_is_valid():
    data_loader.validate_localities()


def test_every_locality_belongs_to_a_known_ward():
    assert set(data_loader.WARD_LOCALITIES) <= set(data_loader.PUNE_WARDS)


def test_localities_never_contain_a_city_or_ward_name():
    """A city name here would become a bare alias and hijack every 'Pune'."""
    wards = {w.lower() for w in data_loader.PUNE_WARDS}
    for ward, localities in data_loader.WARD_LOCALITIES.items():
        for locality in localities:
            key = locality.strip().lower()
            assert key not in data_loader.NON_LOCALITY_NAMES
            assert key not in wards


def test_required_localities_are_present():
    """The two localities the live complaints actually reference."""
    assert "Sukhsagar Nagar" in data_loader.WARD_LOCALITIES["Kothrud"]
    assert "Bibvewadi" in data_loader.WARD_LOCALITIES["Hadapsar"]


def test_area_column_carries_the_ward_name_plus_its_localities(clean_db):
    data_loader.load_all()
    kothrud = clean_db.query(models.Location).filter_by(ward="Kothrud").first()
    parts = [p.strip() for p in kothrud.area.split(",")]
    assert parts[0] == "Kothrud"
    assert "Sukhsagar Nagar" in parts


def test_localities_reach_the_resolver_through_the_database(clean_db):
    """End to end: loader -> locations table -> resolver, no shortcut."""
    from backend import locations

    data_loader.load_all()
    for raw, expected in [
        ("sukhsagarnagar,Pune", "Kothrud"),
        ("bibvewadi,Pune", "Hadapsar"),
        ("Pune", None),
    ]:
        loc = locations.resolve_location(clean_db, raw)
        assert (loc.ward if loc else None) == expected


def test_validate_localities_rejects_a_city_name():
    original = data_loader.WARD_LOCALITIES
    data_loader.WARD_LOCALITIES = {"Kothrud": ["Pune"]}
    try:
        with pytest.raises(ValueError, match="city/district"):
            data_loader.validate_localities()
    finally:
        data_loader.WARD_LOCALITIES = original


def test_validate_localities_rejects_a_ward_name():
    original = data_loader.WARD_LOCALITIES
    data_loader.WARD_LOCALITIES = {"Kothrud": ["Baner"]}
    try:
        with pytest.raises(ValueError, match="already a ward name"):
            data_loader.validate_localities()
    finally:
        data_loader.WARD_LOCALITIES = original
