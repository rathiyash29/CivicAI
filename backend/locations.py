"""
Free-text location resolution for citizen complaints.

Citizens type free text: "Kothrud", "Kothrud, Pune", "near Balewadi stadium".
The intelligence engines work on `Location` rows (they join on `ward`), so the
text has to be mapped onto one before the analytics mean anything.

Deliberate constraints:
  * Never create a `Location` from arbitrary user input. Doing so would flood
    the ward table and make `data_engine.get_population_impact` meaningless,
    because it normalises population against the highest-population ward in
    the database.
  * Never discard the input. Whatever is typed is stored verbatim in
    `Complaint.location_text`, so an unrecognised location is still visible to
    the citizen and to an officer.
  * An unresolved location is not an error. `location_id` is simply left NULL
    and the priority/recommendation engines fall back to their neutral
    defaults, which is already covered by their tests.
"""
import re
from typing import Optional

from sqlalchemy.orm import Session

from database import models

# Minimum length of the *typed* text before a substring match is even
# considered. "Baner" is a useful match for "baner pune", but a three-letter
# fragment matches half the city: "a" resolved to Hadapsar and "ban" to Baner
# purely because of iteration order. Below this length only an exact match is
# allowed, which is unambiguous by construction.
MIN_SUBSTRING_LENGTH = 4


def normalize(text: str) -> str:
    """Lowercase and collapse punctuation/whitespace to single spaces."""
    if not text:
        return ""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _tokens(normalized: str) -> list[str]:
    return normalized.split() if normalized else []


def _contains_token_run(shorter: list[str], longer: list[str]) -> bool:
    """Is `shorter` a run of whole words inside `longer`?"""
    span = len(shorter)
    return any(longer[i:i + span] == shorter for i in range(len(longer) - span + 1))


def _matches_words(needle: str, haystack: str) -> bool:
    """
    Whole-word containment in either direction.

    Plain substring containment is what made matching unsafe: "ban" is inside
    "baner", and "kothrud" is inside "kothrudabad" only by coincidence. Requiring
    the match to line up with word boundaries keeps "Kothrud bus stand" and
    "near Paud Road side" working while rejecting fragments.
    """
    needle_tokens = _tokens(needle)
    haystack_tokens = _tokens(haystack)
    if not needle_tokens or not haystack_tokens:
        return False
    if _contains_token_run(needle_tokens, haystack_tokens):
        return True
    return _contains_token_run(haystack_tokens, needle_tokens)


def _aliases(field: Optional[str]) -> list[str]:
    """
    One `Location` field, split into the separate names it can match.

    `Location.area` holds a comma-separated label: the ward's own name followed
    by any curated localities it administers, written by
    `data.data_loader.ward_area_label`. A citizen who types a neighbourhood
    name ("sukhsagarnagar") must resolve to the same ward as one who types the
    ward ("Kothrud"), so every comma-separated part is an independent candidate
    for a match.

    A field with no comma is returned unchanged, so a plain single-valued area
    behaves exactly as it did before.
    """
    if not field:
        return []
    parts = [part.strip() for part in field.split(",")]
    return [part for part in parts if part]


def _matchable_fields(loc: models.Location) -> list[str]:
    """Every name a citizen could type that legitimately means this location."""
    return [*_aliases(loc.ward), *_aliases(loc.area)]


def _known_locations(db: Session) -> list[models.Location]:
    return db.query(models.Location).order_by(models.Location.id).all()


def resolve_location(db: Session, raw_location: str) -> Optional[models.Location]:
    """
    Best-effort map from free text to a known `Location`.

    Resolution ladder:
      1. exact match on ward / area, case- and punctuation-insensitive
      2. whole-word match, only for text at least MIN_SUBSTRING_LENGTH long,
         and only when exactly one ward can claim it
      3. otherwise None

    Returns None rather than raising: an unknown location is normal input.
    """
    needle = normalize(raw_location)
    if not needle:
        return None

    locations = _known_locations(db)
    if not locations:
        return None

    # 1. exact match, against every name the location is known by
    for loc in locations:
        for field in _matchable_fields(loc):
            if normalize(field) == needle:
                return loc

    # 2. substring match, on whole words only and only for text long enough to
    #    be specific. Collect *all* candidates first: if the text could equally
    #    belong to two wards, picking whichever was inserted first is a guess,
    #    and a wrong ward silently corrupts every downstream aggregate.
    if len(needle) < MIN_SUBSTRING_LENGTH:
        return None

    candidates: list[models.Location] = []
    for loc in locations:
        if loc in candidates:
            continue
        for field in _matchable_fields(loc):
            if not field:
                continue
            haystack = normalize(field)
            if len(haystack) < MIN_SUBSTRING_LENGTH:
                continue
            if _matches_words(needle, haystack):
                candidates.append(loc)
                break

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return None
    return None


def known_wards(db: Session) -> list[str]:
    """Wards currently in the database, for diagnostics and API responses."""
    return [loc.ward for loc in _known_locations(db) if loc.ward]
