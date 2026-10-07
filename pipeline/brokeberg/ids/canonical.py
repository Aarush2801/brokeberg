"""Namespaced canonical IDs: `<namespace>:<raw id>`, e.g. `bioguide:S000148`, `fips:13`.

`entities.canonical_id` is unique across every entity type, so the namespace prefix keeps
registries from colliding and makes an ID self-describing in edges and logs. Build and parse IDs
only through `make` / `split`; never concatenate the strings by hand.
"""

import re
from enum import StrEnum


class Namespace(StrEnum):
    BIOGUIDE = "bioguide"
    FEC = "fec"
    FRED = "fred"
    FIPS = "fips"
    RACE = "race"
    BILL = "bill"


_FORMATS: dict[Namespace, re.Pattern[str]] = {
    Namespace.BIOGUIDE: re.compile(r"^[A-Z]\d{6}$"),
    # Candidate IDs (H/S/P + 8) or committee IDs (C + 8 digits).
    Namespace.FEC: re.compile(r"^(?:[HSP][0-9A-Z]{8}|C\d{8})$"),
    Namespace.FRED: re.compile(r"^[A-Z0-9_]{1,30}$"),
    Namespace.FIPS: re.compile(r"^\d{2}$"),
    Namespace.RACE: re.compile(r"^[A-Z]{2}-[A-Z]+-\d{4}$"),
    # <congress>-<congress.gov bill type, lowercased>-<number>, e.g. 119-s-1234, 119-hr-9340.
    Namespace.BILL: re.compile(r"^\d{1,3}-(?:s|hr|sjres|hjres|sconres|hconres|sres|hres)-\d{1,5}$"),
}


class InvalidCanonicalIdError(ValueError):
    """A raw ID does not match its registry's format."""


def is_valid(ns: Namespace, raw: str) -> bool:
    return bool(_FORMATS[ns].fullmatch(raw))


def make(ns: Namespace, raw: str) -> str:
    """`make(Namespace.FIPS, "13") -> "fips:13"`. Raises if `raw` is malformed."""
    if not is_valid(ns, raw):
        raise InvalidCanonicalIdError(f"{raw!r} is not a valid {ns.value} id")
    return f"{ns.value}:{raw}"


def split(canonical_id: str) -> tuple[Namespace, str]:
    """`split("fips:13") -> (Namespace.FIPS, "13")`. Raises if malformed."""
    prefix, sep, raw = canonical_id.partition(":")
    try:
        ns = Namespace(prefix)
    except ValueError:
        raise InvalidCanonicalIdError(f"unknown namespace in {canonical_id!r}") from None
    if not sep or not is_valid(ns, raw):
        raise InvalidCanonicalIdError(f"{canonical_id!r} is not a valid {ns.value} id")
    return ns, raw
