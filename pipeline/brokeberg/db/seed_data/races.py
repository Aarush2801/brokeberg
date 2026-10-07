"""Target 2026 Senate races (MVP slice).

Ratings are NOT seeded: they arrive with provenance from the rater scrape (Day 2).
`salient_topics` are an editorial prior for event->race linkage, tunable later.
Arizona has no 2026 Senate race (Kelly: 2028, Gallego: 2030), so it is not here.
"""

from typing import NamedTuple

from brokeberg.taxonomy import Topic as T


class RaceSeed(NamedTuple):
    state: str  # USPS abbreviation
    senate_class: int  # regular 2026 seats are class 2; the Ohio special fills a class 3 seat
    special: bool
    salient_topics: tuple[T, ...]


CYCLE = 2026

RACES: tuple[RaceSeed, ...] = (
    RaceSeed("GA", 2, False, (T.INFLATION_COST_OF_LIVING, T.HEALTHCARE, T.HOUSING, T.LABOR_JOBS)),
    RaceSeed("MI", 2, False, (T.TRADE_TARIFFS, T.LABOR_JOBS, T.ENERGY_CLIMATE, T.HEALTHCARE)),
    RaceSeed("NC", 2, False, (T.INFLATION_COST_OF_LIVING, T.HEALTHCARE, T.IMMIGRATION,
                              T.AGRICULTURE)),
    RaceSeed("ME", 2, False, (T.HEALTHCARE, T.SOCIAL_ABORTION, T.INFLATION_COST_OF_LIVING,
                              T.ENERGY_CLIMATE)),
    RaceSeed("NH", 2, False, (T.TAXATION, T.HOUSING, T.HEALTHCARE, T.INFLATION_COST_OF_LIVING)),
    RaceSeed("OH", 3, True, (T.TRADE_TARIFFS, T.LABOR_JOBS, T.ENERGY_CLIMATE,
                             T.INFLATION_COST_OF_LIVING)),
    RaceSeed("TX", 2, False, (T.IMMIGRATION, T.ENERGY_CLIMATE, T.SOCIAL_ABORTION, T.TAXATION)),
    RaceSeed("IA", 2, False, (T.AGRICULTURE, T.TRADE_TARIFFS, T.ENERGY_CLIMATE, T.HEALTHCARE)),
    RaceSeed("AK", 2, False, (T.ENERGY_CLIMATE, T.FOREIGN_POLICY_DEFENSE,
                              T.INFLATION_COST_OF_LIVING)),
    RaceSeed("MN", 2, False, (T.HEALTHCARE, T.AGRICULTURE, T.LABOR_JOBS, T.SOCIAL_ABORTION)),
)
