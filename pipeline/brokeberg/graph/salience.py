"""Feed salience: deterministic, computed at read time (recency decays), weights in `Settings`.

salience = w1*recency_decay + w2*log(1+independent sources) + w3*entity_importance
         + w4*verification_bonus + w5*election_proximity
"""

import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.config import Settings
from brokeberg.db.models import Entity, Race
from brokeberg.ids.canonical import Namespace, make


def election_day(cycle: int) -> date:
    """US general election: the Tuesday after the first Monday in November."""
    nov1 = date(cycle, 11, 1)
    first_monday = nov1 + timedelta(days=(7 - nov1.weekday()) % 7)
    return first_monday + timedelta(days=1)


def recency_decay(event_time: datetime, now: datetime, half_life_hours: float) -> float:
    age_hours = max(0.0, (now - event_time).total_seconds() / 3600)
    return float(0.5 ** (age_hours / half_life_hours))


def election_proximity(edge_confidence: float, cycle: int, now: datetime, tau_days: float) -> float:
    """Link confidence, decayed by days until that race's election; 0 once it has passed."""
    days = (election_day(cycle) - now.date()).days
    if days < 0:
        return 0.0
    return edge_confidence * math.exp(-days / tau_days)


def incumbents(session: Session) -> set[str]:
    """Canonical IDs of the incumbents in seeded races."""
    out = set()
    for meta in session.scalars(select(Race.meta)):
        if bioguide := meta.get("incumbent_bioguide"):
            out.add(make(Namespace.BIOGUIDE, bioguide))
    return out


def entity_importance(entity: Entity, incumbent_ids: set[str], settings: Settings) -> float:
    if entity.importance > 0:
        return entity.importance
    if entity.canonical_id in incumbent_ids:
        return settings.importance_incumbent
    return settings.importance_by_type.get(entity.entity_type, settings.importance_default)


@dataclass(frozen=True)
class Salience:
    recency: float
    sources: float
    importance: float
    verification: float
    election: float
    total: float

    def components(self) -> dict[str, float]:
        return {k: round(v, 4) for k, v in asdict(self).items() if k != "total"}


def salience(
    *,
    event_time: datetime,
    now: datetime,
    independent_sources: int,
    importance: float,
    verification_status: str,
    election: float,
    settings: Settings,
) -> Salience:
    recency = recency_decay(event_time, now, settings.salience_half_life_hours)
    sources = math.log1p(independent_sources)
    verification = settings.salience_verification_bonus.get(verification_status, 0.0)
    total = (
        settings.salience_w1 * recency
        + settings.salience_w2 * sources
        + settings.salience_w3 * importance
        + settings.salience_w4 * verification
        + settings.salience_w5 * election
    )
    return Salience(recency, sources, importance, verification, election, total)
