"""Controlled vocabulary — the SINGLE SOURCE OF TRUTH.

Nothing else in the codebase hardcodes these strings; import the enums from here.
"""

from enum import StrEnum


class EventType(StrEnum):
    LEGISLATIVE_ACTION = "legislative_action"
    EXECUTIVE_ACTION = "executive_action"
    STATEMENT = "statement"
    ECONOMIC_RELEASE = "economic_release"
    JUDICIAL_ACTION = "judicial_action"
    POLL_RELEASE = "poll_release"
    CAMPAIGN_FINANCE_FILING = "campaign_finance_filing"
    ELECTION_RESULT = "election_result"
    CONTROVERSY = "controversy"
    NOMINATION = "nomination"
    REGULATORY_ACTION = "regulatory_action"
    GEOPOLITICAL = "geopolitical"


class Topic(StrEnum):
    """Topic / policy area."""

    INFLATION_COST_OF_LIVING = "inflation_cost_of_living"
    TAXATION = "taxation"
    TRADE_TARIFFS = "trade_tariffs"
    IMMIGRATION = "immigration"
    HEALTHCARE = "healthcare"
    ENERGY_CLIMATE = "energy_climate"
    LABOR_JOBS = "labor_jobs"
    HOUSING = "housing"
    MONETARY_POLICY = "monetary_policy"
    FISCAL_DEBT = "fiscal_debt"
    FOREIGN_POLICY_DEFENSE = "foreign_policy_defense"
    SOCIAL_ABORTION = "social_abortion"
    CRIME_JUSTICE = "crime_justice"
    TECH_AI_REGULATION = "tech_ai_regulation"
    EDUCATION = "education"
    AGRICULTURE = "agriculture"


class Stance(StrEnum):
    STRONGLY_SUPPORT = "strongly_support"
    SUPPORT = "support"
    LEAN_SUPPORT = "lean_support"
    NEUTRAL_UNCLEAR = "neutral_unclear"
    LEAN_OPPOSE = "lean_oppose"
    OPPOSE = "oppose"
    STRONGLY_OPPOSE = "strongly_oppose"


# Stance intensity is a float in this closed range.
INTENSITY_RANGE: tuple[float, float] = (0.0, 1.0)


class EntityType(StrEnum):
    POLITICIAN = "Politician"
    AGENCY = "Agency"
    COMMITTEE = "Committee"
    PARTY = "Party"
    CANDIDATE = "Candidate"
    RACE = "Race"
    OFFICE = "Office"
    JURISDICTION = "Jurisdiction"
    ECONOMIC_INDICATOR = "EconomicIndicator"
    INDUSTRY = "Industry"
    COMPANY = "Company"
    INTEREST_GROUP_PAC = "InterestGroup_PAC"
    COUNTRY = "Country"
    POLICY_BILL = "Policy_Bill"


class JurisdictionLevel(StrEnum):
    FEDERAL = "federal"
    STATE = "state"
    DISTRICT = "district"
    LOCAL = "local"


class RaceType(StrEnum):
    SENATE = "Senate"
    HOUSE = "House"
    GOVERNOR = "Governor"
    PRESIDENT = "President"
    BALLOT_MEASURE = "ballot_measure"


class RaceRating(StrEnum):
    """{Safe, Likely, Lean, Tossup} x {D, R}, plus a pure Toss-up when the rater gives no tilt."""

    SAFE_D = "safe_d"
    LIKELY_D = "likely_d"
    LEAN_D = "lean_d"
    TOSSUP_D = "tossup_d"
    TOSSUP = "tossup"
    TOSSUP_R = "tossup_r"
    LEAN_R = "lean_r"
    LIKELY_R = "likely_r"
    SAFE_R = "safe_r"


class SourceType(StrEnum):
    GOVERNMENT_PRIMARY = "government_primary"
    OFFICIAL_STATEMENT = "official_statement"
    DATA_RELEASE = "data_release"
    PRESS_RELEASE = "press_release"
    POLL = "poll"
    NEWS = "news"
    SOCIAL_POST = "social_post"


class TrustTier(StrEnum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


SOURCE_TRUST: dict[SourceType, TrustTier] = {
    SourceType.GOVERNMENT_PRIMARY: TrustTier.T1,
    SourceType.OFFICIAL_STATEMENT: TrustTier.T1,
    SourceType.DATA_RELEASE: TrustTier.T1,
    SourceType.PRESS_RELEASE: TrustTier.T2,
    SourceType.POLL: TrustTier.T2,
    SourceType.NEWS: TrustTier.T3,
    SourceType.SOCIAL_POST: TrustTier.T4,
}


class EdgeType(StrEnum):
    """Graph edge types. Correlation, never causation: there is deliberately no CAUSES."""

    SUPPORTS = "SUPPORTS"
    OPPOSES = "OPPOSES"
    PROPOSES = "PROPOSES"
    VOTED_FOR = "VOTED_FOR"
    VOTED_AGAINST = "VOTED_AGAINST"
    AFFECTS = "AFFECTS"
    EXPOSED_TO = "EXPOSED_TO"
    LOCATED_IN = "LOCATED_IN"
    COMPETES_IN = "COMPETES_IN"
    ENDORSES = "ENDORSES"
    FUNDED_BY = "FUNDED_BY"
    RESPONDS_TO = "RESPONDS_TO"
    CORRELATES_WITH = "CORRELATES_WITH"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    SINGLE_SOURCE = "single_source"
    CORROBORATED = "corroborated"
    CONTRADICTED = "contradicted"
    FACT_CHECKED = "fact_checked"


ALL_ENUMS: tuple[type[StrEnum], ...] = (
    EventType,
    Topic,
    Stance,
    EntityType,
    JurisdictionLevel,
    RaceType,
    RaceRating,
    SourceType,
    TrustTier,
    EdgeType,
    VerificationStatus,
)
