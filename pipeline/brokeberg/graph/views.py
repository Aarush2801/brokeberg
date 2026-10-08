"""Rollup views the terminal reads: feed, event object, race dossier, entity dossier, stance
timeline. Every row carries provenance (source URL + verbatim span + trust tier); a row that has
none is dropped, never shown bare. Events are read from `event_objects` (cluster heads).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from brokeberg.cluster.event_object import EventObject, Reaction, load_event_object
from brokeberg.config import Settings, get_settings
from brokeberg.db.models import (
    Entity,
    Event,
    EventEntity,
    EventRaceEdge,
    EventSource,
    HeadEvent,
    PollAverage,
    Race,
    RaceRatingHistory,
)
from brokeberg.graph import salience as sal
from brokeberg.graph.edges import Neighbor, neighborhood
from brokeberg.ids.canonical import Namespace, make
from brokeberg.taxonomy import EventType, RaceRating, Stance, TrustTier, VerificationStatus

# --- shared ------------------------------------------------------------------------------------


def top_sources(session: Session, head_ids: list[int]) -> dict[int, EventSource]:
    """Each head's best source: lowest trust tier, then first stored."""
    out: dict[int, EventSource] = {}
    if not head_ids:
        return out
    for s in session.scalars(
        select(EventSource)
        .where(EventSource.event_id.in_(head_ids))
        .order_by(EventSource.trust_tier, EventSource.id)
    ):
        out.setdefault(s.event_id, s)
    return out


# --- feed --------------------------------------------------------------------------------------


class FeedRow(BaseModel):
    event_id: int
    headline: str
    event_type: EventType
    event_time: datetime
    verification_status: VerificationStatus
    confidence: float
    salience: float
    components: dict[str, float]
    source_url: str
    span: str
    trust_tier: TrustTier


def feed(
    session: Session, limit: int = 50, *, now: datetime | None = None,
    settings: Settings | None = None,
) -> list[FeedRow]:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    heads = list(
        session.scalars(
            select(HeadEvent).where(
                HeadEvent.event_time >= now - timedelta(days=settings.feed_window_days),
                HeadEvent.event_time <= now,
            )
        )
    )
    ids = [h.id for h in heads]
    if not ids:
        return []

    incumbent_ids = sal.incumbents(session)
    importance: dict[int, float] = {}
    for event_id, ent in session.execute(
        select(EventEntity.event_id, Entity)
        .join(Entity, Entity.id == EventEntity.entity_id)
        .where(EventEntity.event_id.in_(ids))
    ):
        imp = sal.entity_importance(ent, incumbent_ids, settings)
        importance[event_id] = max(importance.get(event_id, 0.0), imp)

    election: dict[int, float] = {}
    for event_id, confidence, cycle in session.execute(
        select(EventRaceEdge.event_id, EventRaceEdge.confidence, Race.cycle)
        .join(Race, Race.id == EventRaceEdge.race_id)
        .where(EventRaceEdge.event_id.in_(ids))
    ):
        p = sal.election_proximity(confidence, cycle, now, settings.salience_election_tau_days)
        election[event_id] = max(election.get(event_id, 0.0), p)

    sources = top_sources(session, ids)
    rows = []
    for h in heads:
        src = sources.get(h.id)
        if src is None:
            continue
        s = sal.salience(
            event_time=h.event_time, now=now,
            independent_sources=int(h.verification.get("independent_sources", 1)),
            importance=importance.get(h.id, 0.0), verification_status=h.verification_status,
            election=election.get(h.id, 0.0), settings=settings,
        )
        rows.append(FeedRow(
            event_id=h.id, headline=h.headline, event_type=h.event_type,
            event_time=h.event_time, verification_status=h.verification_status,
            confidence=h.confidence, salience=round(s.total, 6), components=s.components(),
            source_url=src.url, span=src.span, trust_tier=src.trust_tier,
        ))
    rows.sort(key=lambda r: (-r.salience, -r.event_time.timestamp(), r.event_id))
    return rows[:limit]


# --- stance flips ------------------------------------------------------------------------------


class StanceFlip(BaseModel):
    """The earlier stance a stance row reverses (marked by verify on the head's stance row)."""

    prior_event_id: int
    prior_event_time: datetime
    prior_stance: Stance
    prior_span: str
    prior_source_url: str | None


def _flip(raw: dict[str, Any] | None) -> StanceFlip | None:
    return StanceFlip.model_validate(raw) if raw else None


# --- event object ------------------------------------------------------------------------------


class AffectedElection(BaseModel):
    race_id: str
    rating: RaceRating | None
    confidence: float
    rationale: str
    matched_topics: list[str]


class ReactionView(Reaction):
    flip: StanceFlip | None


class EventObjectView(EventObject):
    political_reactions: list[ReactionView]  # type: ignore[assignment]
    affected_elections: list[AffectedElection]
    verification: dict[str, Any]


def affected_elections(session: Session, head_id: int) -> list[AffectedElection]:
    return [
        AffectedElection(
            race_id=edge.race_id, rating=rating, confidence=edge.confidence,
            rationale=edge.rationale, matched_topics=edge.matched_topics,
        )
        for edge, rating in session.execute(
            select(EventRaceEdge, Race.rating)
            .join(Race, Race.id == EventRaceEdge.race_id)
            .where(EventRaceEdge.event_id == head_id)
            .order_by(EventRaceEdge.confidence.desc(), EventRaceEdge.race_id)
        )
    ]


def event_object(session: Session, head_id: int) -> EventObjectView:
    obj = load_event_object(session, head_id)
    head = session.get(Event, head_id)
    assert head is not None
    flips: dict[tuple[int, str], StanceFlip] = {}
    for entity_id, topic, raw in session.execute(
        select(EventEntity.entity_id, EventEntity.topic, EventEntity.stance_flip).where(
            EventEntity.event_id == head_id, EventEntity.stance_flip.is_not(None)
        )
    ):
        if (f := _flip(raw)) is not None:
            flips[(entity_id, topic)] = f
    fields = obj.model_dump(exclude={"political_reactions"})
    return EventObjectView(
        **fields,
        political_reactions=[
            ReactionView(**r.model_dump(), flip=flips.get((r.entity_id, r.topic)))
            for r in obj.political_reactions
        ],
        affected_elections=affected_elections(session, head_id),
        verification=head.verification,
    )


# --- stances -----------------------------------------------------------------------------------


class StanceRow(BaseModel):
    event_id: int
    event_time: datetime
    entity_id: int
    topic: str
    stance: Stance
    intensity: float | None
    confidence: float
    span: str
    source_url: str
    trust_tier: TrustTier
    verification_status: VerificationStatus
    flip: StanceFlip | None  # set when this stance reverses the entity's previous one


def _stance_rows(session: Session, entity_id: int, topic: str | None) -> list[StanceRow]:
    """The head stance rows, each sourced from the member that carried that exact span."""
    member = aliased(Event)
    member_ee = aliased(EventEntity)
    q = (
        select(EventEntity, HeadEvent.event_time, HeadEvent.verification_status, EventSource)
        .join(HeadEvent, HeadEvent.id == EventEntity.event_id)
        .join(member, and_(member.cluster_id == HeadEvent.id, member.id != HeadEvent.id))
        .join(member_ee, and_(
            member_ee.event_id == member.id, member_ee.entity_id == EventEntity.entity_id,
            member_ee.role == EventEntity.role, member_ee.topic == EventEntity.topic,
            member_ee.span == EventEntity.span,
        ))
        .join(EventSource, EventSource.event_id == member.id)
        .where(EventEntity.entity_id == entity_id, EventEntity.stance.is_not(None))
        .order_by(
            HeadEvent.event_time, HeadEvent.id, EventEntity.topic, EventEntity.role,
            EventSource.trust_tier, EventSource.id,
        )
    )
    if topic is not None:
        q = q.where(EventEntity.topic == topic)
    seen: set[tuple[int, str, str]] = set()
    out = []
    for ee, t, status, src in session.execute(q):
        key = (ee.event_id, ee.topic, ee.role)
        if key in seen:
            continue
        seen.add(key)
        assert ee.stance is not None
        out.append(StanceRow(
            event_id=ee.event_id, event_time=t, entity_id=ee.entity_id, topic=ee.topic,
            stance=ee.stance, intensity=ee.intensity, confidence=ee.confidence, span=ee.span,
            source_url=src.url, trust_tier=src.trust_tier, verification_status=status,
            flip=_flip(ee.stance_flip),
        ))
    return out


def stance_timeline(session: Session, entity_id: int, topic: str) -> list[StanceRow]:
    """Grounded stances of one entity on one topic, oldest first."""
    return _stance_rows(session, entity_id, topic)


# --- entity dossier ----------------------------------------------------------------------------


class EntityInfo(BaseModel):
    entity_id: int
    canonical_id: str
    name: str
    entity_type: str


class RecentEvent(BaseModel):
    event_id: int
    headline: str
    event_type: EventType
    event_time: datetime
    roles: list[str]
    verification_status: VerificationStatus
    source_url: str
    span: str
    trust_tier: TrustTier


class EntityDossier(BaseModel):
    entity: EntityInfo
    stances: list[StanceRow]  # latest per topic
    recent_events: list[RecentEvent]
    relationships: list[Neighbor]


def entity_dossier(session: Session, entity_id: int, *, recent: int = 20) -> EntityDossier:
    ent = session.get(Entity, entity_id)
    if ent is None:
        raise ValueError(f"no entity {entity_id}")
    latest: dict[str, StanceRow] = {}
    for row in _stance_rows(session, entity_id, None):
        latest[row.topic] = row  # rows are oldest first

    roles: dict[int, set[str]] = {}
    heads: dict[int, Event] = {}
    for role, h in session.execute(
        select(EventEntity.role, HeadEvent)
        .join(HeadEvent, HeadEvent.id == EventEntity.event_id)
        .where(EventEntity.entity_id == entity_id)
    ):
        roles.setdefault(h.id, set()).add(role)
        heads[h.id] = h
    ordered = sorted(heads.values(), key=lambda h: (h.event_time, h.id), reverse=True)[:recent]
    sources = top_sources(session, [h.id for h in ordered])
    recent_events = [
        RecentEvent(
            event_id=h.id, headline=h.headline, event_type=h.event_type,
            event_time=h.event_time, roles=sorted(roles[h.id]),
            verification_status=h.verification_status, source_url=src.url, span=src.span,
            trust_tier=src.trust_tier,
        )
        for h in ordered
        if (src := sources.get(h.id)) is not None
    ]
    return EntityDossier(
        entity=EntityInfo(
            entity_id=ent.id, canonical_id=ent.canonical_id, name=ent.name,
            entity_type=ent.entity_type,
        ),
        stances=sorted(latest.values(), key=lambda r: r.topic),
        recent_events=recent_events,
        relationships=neighborhood(session, entity_id),
    )


# --- race dossier ------------------------------------------------------------------------------


class RatingRow(BaseModel):
    rater: str
    rating: RaceRating
    asof: date
    source_url: str


class CandidateRow(BaseModel):
    fec_candidate_id: str
    entity_id: int | None
    canonical_id: str | None
    name: str | None
    finance: dict[str, Any] | None


class PollRow(BaseModel):
    value: Decimal
    asof: date
    source_url: str
    meta: dict[str, Any]


class LinkedEvent(BaseModel):
    event_id: int
    headline: str
    event_time: datetime
    verification_status: VerificationStatus
    confidence: float  # the link's confidence
    rationale: str
    matched_topics: list[str]
    source_url: str
    span: str
    trust_tier: TrustTier


class RaceDossier(BaseModel):
    race_id: str
    state_fips: str
    office: str
    cycle: int
    election_day: date
    rating: RaceRating | None
    rating_history: list[RatingRow]  # newest first
    incumbent: EntityInfo | None
    candidates: list[CandidateRow]
    finance_asof: str | None
    finance_source_url: str | None
    poll_average: PollRow | None
    linked_events: list[LinkedEvent]


def _entity_info(e: Entity) -> EntityInfo:
    return EntityInfo(
        entity_id=e.id, canonical_id=e.canonical_id, name=e.name, entity_type=e.entity_type
    )


def race_dossier(session: Session, race_id: str, *, events: int = 20) -> RaceDossier:
    race = session.get(Race, race_id)
    if race is None:
        raise ValueError(f"no race {race_id}")
    history = [
        RatingRow(rater=r.rater, rating=r.rating, asof=r.asof, source_url=r.source_url)
        for r in session.scalars(
            select(RaceRatingHistory)
            .where(RaceRatingHistory.race_id == race_id)
            .order_by(RaceRatingHistory.asof.desc(), RaceRatingHistory.rater)
        )
    ]

    incumbent = None
    if bioguide := race.meta.get("incumbent_bioguide"):
        e = session.scalar(
            select(Entity).where(Entity.canonical_id == make(Namespace.BIOGUIDE, bioguide))
        )
        incumbent = _entity_info(e) if e else None

    finance = race.meta.get("finance") or {}
    candidates = []
    for fec_id in race.fec_candidate_ids:
        e = session.scalars(
            select(Entity)
            .where(
                (Entity.canonical_id == make(Namespace.FEC, fec_id))
                | Entity.aliases.contains([fec_id])
            )
            .order_by(Entity.id)
            .limit(1)
        ).first()
        info = (finance.get("candidates") or {}).get(fec_id)
        candidates.append(CandidateRow(
            fec_candidate_id=fec_id, entity_id=e.id if e else None,
            canonical_id=e.canonical_id if e else None,
            name=e.name if e else (info or {}).get("name"), finance=info,
        ))

    poll = session.scalars(
        select(PollAverage)
        .where(PollAverage.race_id == race_id)
        .order_by(PollAverage.asof.desc(), PollAverage.id.desc())
        .limit(1)
    ).first()

    links = session.execute(
        select(EventRaceEdge, HeadEvent)
        .join(HeadEvent, HeadEvent.id == EventRaceEdge.event_id)
        .where(EventRaceEdge.race_id == race_id)
        .order_by(
            EventRaceEdge.confidence.desc(), HeadEvent.event_time.desc(), HeadEvent.id.desc()
        )
        .limit(events)
    ).all()
    sources = top_sources(session, [h.id for _, h in links])
    linked = [
        LinkedEvent(
            event_id=h.id, headline=h.headline, event_time=h.event_time,
            verification_status=h.verification_status, confidence=edge.confidence,
            rationale=edge.rationale, matched_topics=edge.matched_topics, source_url=src.url,
            span=src.span, trust_tier=src.trust_tier,
        )
        for edge, h in links
        if (src := sources.get(h.id)) is not None
    ]

    return RaceDossier(
        race_id=race.id, state_fips=race.state_fips, office=race.office, cycle=race.cycle,
        election_day=sal.election_day(race.cycle), rating=race.rating, rating_history=history,
        incumbent=incumbent, candidates=candidates, finance_asof=finance.get("asof"),
        finance_source_url=finance.get("source_url"),
        poll_average=(
            PollRow(value=poll.value, asof=poll.asof, source_url=poll.source_url, meta=poll.meta)
            if poll else None
        ),
        linked_events=linked,
    )
