"""Assign each member event to a cluster. Deterministic except for one LLM tiebreak.

Candidates = members already clustered, within ±window of the event's time, ranked by cosine
similarity, keeping only clusters that share >= `cluster_min_entity_overlap` resolved entities.
The top candidate decides: >= t_high attaches, < t_low (or none) starts a new cluster, and the band
between gets exactly one "same underlying event?" LLM call.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg import llm
from brokeberg.config import Settings, get_settings
from brokeberg.db.models import Event, EventEmbedding, EventEntity, EventSource, ReviewKind
from brokeberg.extract.doc import REVIEW_THRESHOLD, SYSTEM, ReviewItem
from brokeberg.extract.run import write_review

# How many members of the candidate cluster the tiebreak prompt shows.
TIEBREAK_MEMBERS = 3


class Decision(StrEnum):
    NEW = "new"
    ATTACH = "attach"
    TIEBREAK = "tiebreak"


@dataclass(frozen=True)
class Candidate:
    cluster_id: int
    similarity: float  # max cosine over the cluster's members
    overlap: int  # shared resolved entities


@dataclass
class ClusterStats:
    new: int = 0
    attached: int = 0
    tiebreaks: int = 0
    heads: set[int] = field(default_factory=set)


def decide(top: Candidate | None, settings: Settings) -> Decision:
    """The band rule. Candidates already passed the entity-overlap filter."""
    if top is None or top.similarity < settings.cluster_t_low:
        return Decision.NEW
    if top.similarity >= settings.cluster_t_high:
        return Decision.ATTACH
    return Decision.TIEBREAK


def entity_ids(session: Session, event_ids: list[int]) -> set[int]:
    return set(
        session.scalars(
            select(EventEntity.entity_id).where(EventEntity.event_id.in_(event_ids)).distinct()
        )
    )


def cluster_entity_ids(session: Session, cluster_id: int) -> set[int]:
    """Resolved entities across a cluster's members."""
    return set(
        session.scalars(
            select(EventEntity.entity_id)
            .join(Event, Event.id == EventEntity.event_id)
            .where(Event.cluster_id == cluster_id, Event.id != cluster_id)
            .distinct()
        )
    )


def members(session: Session, cluster_id: int) -> list[Event]:
    return list(
        session.scalars(
            select(Event)
            .where(Event.cluster_id == cluster_id, Event.id != cluster_id)
            .order_by(Event.event_time, Event.id)
        )
    )


def find_candidates(session: Session, event: Event, settings: Settings) -> list[Candidate]:
    """Clusters near `event` in time and embedding space that share a resolved entity."""
    vector = session.scalar(
        select(EventEmbedding.embedding).where(EventEmbedding.event_id == event.id)
    )
    if vector is None:
        return []
    window = timedelta(hours=settings.cluster_window_hours)
    distance = EventEmbedding.embedding.cosine_distance(vector)
    rows = session.execute(
        select(Event.cluster_id, (1 - distance).label("sim"))
        .join(EventEmbedding, EventEmbedding.event_id == Event.id)
        .where(
            Event.cluster_id.is_not(None),
            Event.cluster_id != Event.id,
            Event.id != event.id,
            Event.event_time.between(event.event_time - window, event.event_time + window),
        )
        .order_by(distance)
        .limit(settings.cluster_knn)
    ).all()

    best: dict[int, float] = {}
    for cluster_id, sim in rows:
        best[cluster_id] = max(best.get(cluster_id, -1.0), float(sim))
    if not best:
        return []

    mine = entity_ids(session, [event.id])
    out = []
    for cluster_id, sim in best.items():
        overlap = len(mine & cluster_entity_ids(session, cluster_id))
        if overlap >= settings.cluster_min_entity_overlap:
            out.append(Candidate(cluster_id, sim, overlap))
    return sorted(out, key=lambda c: (-c.similarity, c.cluster_id))


class SameEvent(BaseModel):
    same: bool
    reason: str
    confidence: float = Field(ge=0, le=1)


TIEBREAK_PROMPT = """Do these two reports describe the same underlying real-world event (the same
release, vote, statement, filing, or action), not merely the same topic? Answer from the text only.

<new_report>
{new}
</new_report>

<existing_cluster>
{cluster}
</existing_cluster>

same: true only if they are the same event. reason: one sentence. confidence: 0-1."""


def _describe(session: Session, event: Event) -> str:
    spans = session.scalars(
        select(EventSource.span).where(EventSource.event_id == event.id).order_by(EventSource.id)
    ).all()
    lines = [f"Headline: {event.headline}", f"Time: {event.event_time.isoformat()}"]
    lines += [f"Excerpt: {s}" for s in spans]
    return "\n".join(lines)


def review_raw_item(session: Session, event: Event) -> int | None:
    return session.scalar(
        select(EventSource.raw_item_id)
        .where(EventSource.event_id == event.id, EventSource.raw_item_id.is_not(None))
        .order_by(EventSource.id)
        .limit(1)
    )


def tiebreak(session: Session, event: Event, candidate: Candidate) -> bool:
    """The only LLM use in clustering. Low confidence splits (and goes to review)."""
    shown = members(session, candidate.cluster_id)[:TIEBREAK_MEMBERS]
    out = llm.complete(
        TIEBREAK_PROMPT.format(
            new=_describe(session, event),
            cluster="\n\n".join(_describe(session, m) for m in shown),
        ),
        schema=SameEvent,
        system=SYSTEM,
        model=get_settings().llm_model_cheap,
        max_tokens=1024,
    )
    if out.confidence < REVIEW_THRESHOLD:
        raw_item_id = review_raw_item(session, event)
        if raw_item_id is not None:
            write_review(
                session, raw_item_id,
                [ReviewItem(
                    kind=ReviewKind.LOW_CONFIDENCE, mention=event.headline, field="cluster",
                    payload={
                        "event_id": event.id, "cluster_id": candidate.cluster_id,
                        "similarity": candidate.similarity, **out.model_dump(),
                    },
                    confidence=out.confidence,
                )],
            )
        return False
    return out.same


def new_head(session: Session, member: Event) -> Event:
    """Open a cluster: a head row seeded from its first member, `cluster_id = id`."""
    head = Event(
        event_type=member.event_type,
        headline=member.headline,
        what_happened=member.what_happened,
        event_time=member.event_time,
        confidence=member.confidence,
        topics=list(member.topics),
        policy_areas=list(member.policy_areas),
        jurisdiction=member.jurisdiction,
    )
    session.add(head)
    session.flush()
    head.cluster_id = head.id
    member.cluster_id = head.id
    session.flush()
    return head


@dataclass(frozen=True)
class Placement:
    decision: Decision
    head_id: int
    opened: bool  # True if this event started a new cluster


def cluster_event(session: Session, event: Event, settings: Settings) -> Placement:
    """Place one unclustered member into an existing cluster or a new one."""
    candidates = find_candidates(session, event, settings)
    top = candidates[0] if candidates else None
    decision = decide(top, settings)
    if top is None or decision == Decision.NEW or (
        decision == Decision.TIEBREAK and not tiebreak(session, event, top)
    ):
        return Placement(decision, new_head(session, event).id, opened=True)
    event.cluster_id = top.cluster_id
    session.flush()
    return Placement(decision, top.cluster_id, opened=False)


def pending(session: Session, limit: int | None = None) -> list[int]:
    """Unclustered members that have an embedding, oldest first (deterministic)."""
    q = (
        select(Event.id)
        .join(EventEmbedding, EventEmbedding.event_id == Event.id)
        .where(Event.cluster_id.is_(None))
        .order_by(Event.event_time, Event.id)
    )
    if limit:
        q = q.limit(limit)
    return list(session.scalars(q))


def cluster_pending(session: Session, limit: int | None = None) -> ClusterStats:
    """Cluster every pending member in one session. Already-clustered members are never touched."""
    settings = get_settings()
    stats = ClusterStats()
    for event_id in pending(session, limit):
        event = session.get(Event, event_id)
        assert event is not None
        placed = cluster_event(session, event, settings)
        stats.heads.add(placed.head_id)
        stats.tiebreaks += placed.decision == Decision.TIEBREAK
        if placed.opened:
            stats.new += 1
        else:
            stats.attached += 1
    return stats
