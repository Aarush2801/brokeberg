"""event -AFFECTS-> race: which competitive races an event object bears on.

A race links iff the event shares a topic with `race.salient_topics`, the event's states include
the race's state, and the race is rated Lean or Tossup. The event's states are its jurisdiction,
the home states of politicians in it, and races it names; a federal event reaches every state at a
lower weight. Every link carries the rule's rationale and a code-computed confidence. Correlation
of interest, not a claim the event moves the race.
"""

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from brokeberg.config import Settings
from brokeberg.db.models import (
    Entity,
    Event,
    EventEntity,
    EventRaceEdge,
    Race,
    RaceRatingHistory,
)
from brokeberg.ids.canonical import Namespace, split
from brokeberg.taxonomy import EdgeType, EntityType, RaceRating

FEDERAL = "federal"
RATING_CLASS: dict[RaceRating, str] = {
    RaceRating.TOSSUP: "tossup",
    RaceRating.TOSSUP_D: "tossup",
    RaceRating.TOSSUP_R: "tossup",
    RaceRating.LEAN_D: "lean",
    RaceRating.LEAN_R: "lean",
}


@dataclass(frozen=True)
class EventStates:
    direct: dict[str, str]  # state fips -> why (jurisdiction / named race)
    politician: dict[str, str]  # state fips -> the politician's canonical id
    federal: bool


def event_states(session: Session, head: Event) -> EventStates:
    direct: dict[str, str] = {}
    politician: dict[str, str] = {}
    if head.jurisdiction and head.jurisdiction != FEDERAL:
        ns, raw = split(head.jurisdiction)
        if ns == Namespace.FIPS:
            direct[raw] = f"event jurisdiction {head.jurisdiction}"
    for ent in session.scalars(
        select(Entity)
        .join(EventEntity, EventEntity.entity_id == Entity.id)
        .where(
            EventEntity.event_id == head.id,
            Entity.entity_type.in_([EntityType.POLITICIAN, EntityType.RACE]),
        )
        .distinct()
        .order_by(Entity.canonical_id)
    ):
        fips = ent.meta.get("state_fips")
        if not fips:
            continue
        if ent.entity_type == EntityType.RACE:
            direct.setdefault(fips, f"event names {ent.canonical_id}")
        else:
            politician.setdefault(fips, ent.canonical_id)
    return EventStates(direct, politician, head.jurisdiction == FEDERAL)


def _rated_by(session: Session, race: Race) -> str:
    row = session.scalars(
        select(RaceRatingHistory)
        .where(RaceRatingHistory.race_id == race.id, RaceRatingHistory.rating == race.rating)
        .order_by(RaceRatingHistory.asof.desc(), RaceRatingHistory.id.desc())
        .limit(1)
    ).first()
    return f", {row.rater} {row.asof.isoformat()}" if row else ""


def link_races(session: Session, head: Event, settings: Settings) -> int:
    """Recompute the head's race links. Returns the number of links."""
    assert head.cluster_id == head.id, f"event {head.id} is not a cluster head"
    session.execute(delete(EventRaceEdge).where(EventRaceEdge.event_id == head.id))
    topics = set(head.topics)
    if not topics:
        session.flush()
        return 0
    states = event_states(session, head)
    n = 0
    for race in session.scalars(
        select(Race).where(Race.rating.in_(list(RATING_CLASS))).order_by(Race.id)
    ):
        assert race.rating is not None
        matched = sorted(topics & set(race.salient_topics))
        if not matched:
            continue
        fips = race.state_fips
        if fips in states.direct:
            match, why = "state", states.direct[fips]
        elif fips in states.politician:
            match, why = "politician", f"involves {states.politician[fips]}"
        elif states.federal:
            match, why = "federal", "federal event"
        else:
            continue
        rating_class = RATING_CLASS[race.rating]
        confidence = (
            settings.race_rating_weight[rating_class]
            * settings.race_match_weight[match]
            * head.confidence
        )
        rationale = (
            f"{', '.join(matched)} salient in {race.id} "
            f"(rated {race.rating.value}{_rated_by(session, race)}); {why}"
        )
        session.add(EventRaceEdge(
            event_id=head.id, race_id=race.id, relation=EdgeType.AFFECTS, rationale=rationale,
            confidence=min(max(confidence, 0.0), 1.0), matched_topics=matched,
        ))
        n += 1
    session.flush()
    return n
