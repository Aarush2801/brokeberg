"""State name / USPS abbreviation -> state FIPS code. Pure lookup, no DB."""

from typing import NamedTuple

from brokeberg.ids.canonical import Namespace, make


class State(NamedTuple):
    fips: str
    abbrev: str
    name: str


STATES: tuple[State, ...] = (
    State("01", "AL", "Alabama"),
    State("02", "AK", "Alaska"),
    State("04", "AZ", "Arizona"),
    State("05", "AR", "Arkansas"),
    State("06", "CA", "California"),
    State("08", "CO", "Colorado"),
    State("09", "CT", "Connecticut"),
    State("10", "DE", "Delaware"),
    State("11", "DC", "District of Columbia"),
    State("12", "FL", "Florida"),
    State("13", "GA", "Georgia"),
    State("15", "HI", "Hawaii"),
    State("16", "ID", "Idaho"),
    State("17", "IL", "Illinois"),
    State("18", "IN", "Indiana"),
    State("19", "IA", "Iowa"),
    State("20", "KS", "Kansas"),
    State("21", "KY", "Kentucky"),
    State("22", "LA", "Louisiana"),
    State("23", "ME", "Maine"),
    State("24", "MD", "Maryland"),
    State("25", "MA", "Massachusetts"),
    State("26", "MI", "Michigan"),
    State("27", "MN", "Minnesota"),
    State("28", "MS", "Mississippi"),
    State("29", "MO", "Missouri"),
    State("30", "MT", "Montana"),
    State("31", "NE", "Nebraska"),
    State("32", "NV", "Nevada"),
    State("33", "NH", "New Hampshire"),
    State("34", "NJ", "New Jersey"),
    State("35", "NM", "New Mexico"),
    State("36", "NY", "New York"),
    State("37", "NC", "North Carolina"),
    State("38", "ND", "North Dakota"),
    State("39", "OH", "Ohio"),
    State("40", "OK", "Oklahoma"),
    State("41", "OR", "Oregon"),
    State("42", "PA", "Pennsylvania"),
    State("44", "RI", "Rhode Island"),
    State("45", "SC", "South Carolina"),
    State("46", "SD", "South Dakota"),
    State("47", "TN", "Tennessee"),
    State("48", "TX", "Texas"),
    State("49", "UT", "Utah"),
    State("50", "VT", "Vermont"),
    State("51", "VA", "Virginia"),
    State("53", "WA", "Washington"),
    State("54", "WV", "West Virginia"),
    State("55", "WI", "Wisconsin"),
    State("56", "WY", "Wyoming"),
)

BY_FIPS: dict[str, State] = {s.fips: s for s in STATES}
_LOOKUP: dict[str, State] = {
    **{s.abbrev.lower(): s for s in STATES},
    **{s.name.lower(): s for s in STATES},
    **{s.fips: s for s in STATES},
}


def lookup(value: str) -> State | None:
    """'Georgia' | 'GA' | 'ga' | '13' -> State, else None."""
    return _LOOKUP.get(" ".join(value.split()).lower().removesuffix("."))


def to_fips(value: str) -> str | None:
    state = lookup(value)
    return state.fips if state else None


def canonical(value: str) -> str | None:
    """'GA' -> 'fips:13'."""
    fips = to_fips(value)
    return make(Namespace.FIPS, fips) if fips else None
