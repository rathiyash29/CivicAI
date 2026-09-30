"""Tests for the free-text location resolver (backend/locations.py)."""
import pytest

from backend import locations
from database import models


@pytest.fixture
def wards(clean_db):
    for ward, area, city in [
        ("Kothrud", "Paud Road", "Pune"),
        ("Hadapsar", "Sahyadri Nagar", "Pune"),
        ("Baner", None, "Pune"),
        ("Viman Nagar", None, "Pune"),
    ]:
        clean_db.add(models.Location(ward=ward, area=area, city=city))
    clean_db.commit()
    return True


@pytest.mark.parametrize("raw", [
    "Kothrud",
    "kothrud",
    "KOTHRUD",
    "  Kothrud  ",
    "Kothrud, Pune",
    "Pune, Kothrud",
    "kothrud.",
    "Kothrud - Pune",
])
def test_exact_and_punctuated_matches(clean_db, wards, raw):
    loc = locations.resolve_location(clean_db, raw)
    assert loc is not None and loc.ward == "Kothrud"


def test_exact_match_on_area(clean_db, wards):
    loc = locations.resolve_location(clean_db, "Paud Road")
    assert loc is not None and loc.ward == "Kothrud"


def test_substring_match_on_area(clean_db, wards):
    loc = locations.resolve_location(clean_db, "shop near Paud Road side")
    assert loc is not None and loc.ward == "Kothrud"


def test_unknown_location_returns_none(clean_db, wards):
    assert locations.resolve_location(clean_db, "near Balewadi stadium") is None


def test_blank_location_returns_none(clean_db, wards):
    assert locations.resolve_location(clean_db, "") is None
    assert locations.resolve_location(clean_db, "   ") is None
    assert locations.resolve_location(clean_db, None) is None


def test_resolver_never_creates_location_rows(clean_db, wards):
    """A long list of junk must not pollute the ward table."""
    for junk in ["some random place", "zzzz", "12345", "opposite the temple",
                 "corner shop", "unknown road name"]:
        locations.resolve_location(clean_db, junk)
    clean_db.commit()
    assert clean_db.query(models.Location).count() == 4


def test_no_locations_configured_returns_none(clean_db):
    assert locations.resolve_location(clean_db, "Kothrud") is None


def test_known_wards_lists_configured_wards(clean_db, wards):
    assert locations.known_wards(clean_db) == [
        "Kothrud", "Hadapsar", "Baner", "Viman Nagar"]


def test_normalize_collapses_punctuation_and_case():
    assert locations.normalize("  Kothrud,   Pune!! ") == "kothrud pune"
    assert locations.normalize("") == ""


# --- minimum substring length ----------------------------------------------
#
# Before this, matching was plain substring containment, so "a" resolved to
# Hadapsar and "ban" to Baner purely because of the order rows came back in.

@pytest.mark.parametrize("raw", ["a", "an", "as", "b", "ba", "ban", "ko", "kot"])
def test_short_fragments_do_not_match_a_ward(clean_db, wards, raw):
    assert locations.resolve_location(clean_db, raw) is None


@pytest.mark.parametrize("raw", ["ban", "b", "banr"])
def test_short_fragments_do_not_match_even_a_five_letter_ward(clean_db, wards, raw):
    """The limit applies to what the citizen typed, not just to the ward."""
    assert locations.resolve_location(clean_db, raw) is None


def test_a_long_enough_fragment_of_a_ward_is_still_fine(clean_db, wards):
    """The rule is a length floor, not a ban on partial wards."""
    loc = locations.resolve_location(clean_db, "baner p")
    assert loc is not None and loc.ward == "Baner"


@pytest.mark.parametrize("raw,expected", [
    ("Kothrud bus stand", "Kothrud"),
    ("shop near Paud Road side", "Kothrud"),
    ("pune viman nagar", "Viman Nagar"),
    ("road near Hadapsar", "Hadapsar"),
    ("baner", "Baner"),
])
def test_reasonable_substrings_still_resolve(clean_db, wards, raw, expected):
    loc = locations.resolve_location(clean_db, raw)
    assert loc is not None and loc.ward == expected


def test_substring_match_respects_word_boundaries(clean_db, wards):
    """
    "Kothrudgram" is a different place from "Kothrud". Matching mid-word is
    how a fragment ends up owning somebody else's ward.
    """
    assert locations.resolve_location(clean_db, "Kothrudgram") is None


def test_ambiguous_input_does_not_pick_an_arbitrary_ward(clean_db):
    """
    When two wards can equally claim the text, guessing silently corrupts
    every downstream aggregate, so the resolver declines instead.
    """
    for ward in ("Kothrud", "Kothrud Nagar"):
        clean_db.add(models.Location(ward=ward, city="Pune"))
    clean_db.commit()

    # An exact match is still unambiguous, and still wins.
    exact = locations.resolve_location(clean_db, "Kothrud")
    assert exact is not None and exact.ward == "Kothrud"

    # "Kothrud Nagar area" is a whole-word match against both wards.
    assert locations.resolve_location(clean_db, "Kothrud Nagar area") is None


def test_resolver_never_invents_a_row_for_a_short_fragment(clean_db, wards):
    before = clean_db.query(models.Location).count()
    for junk in ["a", "an", "ban", "the", "x"]:
        assert locations.resolve_location(clean_db, junk) is None
    clean_db.commit()
    assert clean_db.query(models.Location).count() == before


# --- comma-separated locality labels ---------------------------------------
#
# `Location.area` holds "ward, locality, locality" (see
# `data.data_loader.ward_area_label`), so a citizen who types a neighbourhood
# name resolves to the same ward as one who types the ward name.

@pytest.fixture
def aliased_wards(clean_db):
    # Exactly one row per ward, carrying the comma-separated label shape the
    # loader writes. Two rows for the same ward would be genuine ambiguity and
    # would make these tests pass or fail for the wrong reason.
    clean_db.add(models.Location(
        ward="Kothrud", area="Kothrud, Sukhsagar Nagar, Sukhsagarnagar", city="Pune"))
    clean_db.add(models.Location(ward="Hadapsar", area="Hadapsar, Bibvewadi", city="Pune"))
    clean_db.commit()
    return True


@pytest.mark.parametrize("raw,expected", [
    ("sukhsagarnagar,Pune", "Kothrud"),
    ("Sukhsagar Nagar", "Kothrud"),
    ("bibvewadi,Pune", "Hadapsar"),
    ("Bibvewadi", "Hadapsar"),
    # The ward's own name still resolves, with or without the city token.
    ("Kothrud", "Kothrud"),
    ("Kothrud, Pune", "Kothrud"),
])
def test_locality_aliases_resolve_to_their_ward(clean_db, aliased_wards, raw, expected):
    loc = locations.resolve_location(clean_db, raw)
    assert loc is not None and loc.ward == expected


def test_a_bare_city_name_never_resolves(clean_db, aliased_wards):
    """
    A city is not a ward. If a locality entry ever carried a city name, the
    comma split would make that city an alias and every "Pune" complaint would
    silently land in an arbitrary ward.
    """
    for raw in ["Pune", "Pune, Maharashtra", "near Pune"]:
        assert locations.resolve_location(clean_db, raw) is None


def test_locality_aliases_do_not_create_location_rows(clean_db, aliased_wards):
    before = clean_db.query(models.Location).count()
    for raw in ["Sukhsagar Nagar", "Bibvewadi", "sukhsagarnagar,Pune"]:
        locations.resolve_location(clean_db, raw)
    clean_db.commit()
    assert clean_db.query(models.Location).count() == before


def test_a_single_valued_area_behaves_exactly_as_before(clean_db, wards):
    """Splitting on commas must not change a plain area like 'Paud Road'."""
    loc = locations.resolve_location(clean_db, "Paud Road")
    assert loc is not None and loc.ward == "Kothrud"
    assert locations.resolve_location(clean_db, "Sahyadri Nagar").ward == "Hadapsar"
