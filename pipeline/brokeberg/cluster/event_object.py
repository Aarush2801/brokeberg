"""Materialize a cluster head into the event object the terminal renders.

Rollups (sources, entities, topics, type, time, confidence) and related-event links are code.
The LLM writes only headline / what_happened / why_it_matters, over the cluster's stored spans,
and `check_grounded` rejects any output carrying a number or a known entity the spans do not.
"""

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from brokeberg import llm
from brokeberg.cluster.cluster import cluster_entity_ids, members, review_raw_item
from brokeberg.config import Settings, get_settings
from brokeberg.db.models import (
    EMBED_DIM,
    Entity,
    Event,
    EventEmbedding,
    EventEntity,
    EventLink,
    EventSource,
    ReviewKind,
)
from brokeberg.extract.doc import SYSTEM, ReviewItem
from brokeberg.extract.run import write_review
from brokeberg.taxonomy import EventLinkType, EventType, TrustTier, VerificationStatus

# Bump when the synthesis prompt/schema or the rollup rules change: every head re-materializes.
SYNTH_VERSION = "day4-v2"
TRUST_WEIGHT: dict[TrustTier, float] = {
    TrustTier.T1: 1.0, TrustTier.T2: 0.8, TrustTier.T3: 0.6, TrustTier.T4: 0.4,
}
MAX_SPANS = 40


def _rank(tier: TrustTier) -> int:
    return int(tier.value[1:])


def cluster_hash(member_ids: list[int]) -> str:
    key = SYNTH_VERSION + ":" + ",".join(str(i) for i in sorted(member_ids))
    return hashlib.sha256(key.encode()).hexdigest()


# --- rollup ------------------------------------------------------------------------------------


def member_tiers(session: Session, member_ids: list[int]) -> dict[int, TrustTier]:
    """Each member's best (lowest-numbered) source tier; T4 if it somehow has none."""
    tiers: dict[int, TrustTier] = {m: TrustTier.T4 for m in member_ids}
    for event_id, tier in session.execute(
        select(EventSource.event_id, EventSource.trust_tier).where(
            EventSource.event_id.in_(member_ids)
        )
    ):
        if _rank(tier) < _rank(tiers[event_id]):
            tiers[event_id] = tier
    return tiers


def rollup(session: Session, head: Event, ms: list[Event]) -> None:
    """Rebuild the head's provenance, entities and summary fields from its members."""
    ids = [m.id for m in ms]
    tiers = member_tiers(session, ids)

    session.execute(delete(EventSource).where(EventSource.event_id == head.id))
    session.execute(delete(EventEntity).where(EventEntity.event_id == head.id))
    session.flush()

    seen: set[tuple[str, str]] = set()
    for s in session.scalars(
        select(EventSource)
        .where(EventSource.event_id.in_(ids))
        .order_by(EventSource.trust_tier, EventSource.id)
    ):
        if (s.url, s.span) in seen:
            continue
        seen.add((s.url, s.span))
        session.add(
            EventSource(
                event_id=head.id, raw_item_id=s.raw_item_id, url=s.url, span=s.span,
                trust_tier=s.trust_tier, claim=s.claim,
            )
        )

    best: dict[tuple[int, str, str], EventEntity] = {}
    for ee in session.scalars(
        select(EventEntity)
        .where(EventEntity.event_id.in_(ids))
        .order_by(EventEntity.event_id, EventEntity.entity_id)
    ):
        key = (ee.entity_id, ee.role, ee.topic)
        if key not in best or ee.confidence > best[key].confidence:
            best[key] = ee
    for ee in best.values():
        session.add(
            EventEntity(
                event_id=head.id, entity_id=ee.entity_id, role=ee.role, topic=ee.topic,
                stance=ee.stance, intensity=ee.intensity, span=ee.span, confidence=ee.confidence,
            )
        )

    head.topics = sorted({t for m in ms for t in m.topics})
    head.policy_areas = sorted({t for m in ms for t in m.policy_areas})
    head.event_time = min(m.event_time for m in ms)
    # Most common type; ties go to the type with the best-trust member, then first seen.
    types = Counter(m.event_type for m in ms)
    head.event_type = max(
        types, key=lambda t: (types[t], -min(_rank(tiers[m.id]) for m in ms if m.event_type == t))
    )
    jurisdictions = Counter(m.jurisdiction for m in ms if m.jurisdiction)
    head.jurisdiction = jurisdictions.most_common(1)[0][0] if jurisdictions else None
    head.confidence = rolled_confidence(tiers, ms)
    session.flush()


def rolled_confidence(tiers: dict[int, TrustTier], ms: list[Event]) -> float:
    """Trust-weighted mean of member confidences: the head's pre-verification confidence."""
    weights = [TRUST_WEIGHT[tiers[m.id]] for m in ms]
    return sum(w * m.confidence for w, m in zip(weights, ms, strict=True)) / sum(weights)


# --- synthesis ---------------------------------------------------------------------------------


class Synthesis(BaseModel):
    headline: str = Field(min_length=1)
    what_happened: str = Field(min_length=1)
    why_it_matters: str | None
    cited: list[int]


SYNTH_PROMPT = """Write the summary of one real-world event using ONLY the numbered excerpts below.
They are verbatim from the event's sources.

Rules:
- Every fact, name and number you write must appear in the excerpts. No background, no outside
  knowledge. Copy numbers exactly as the excerpts write them.
- No causal claims: never say X caused, drove, or led to Y. Report what happened and who said what.
- Write about the event, never about the excerpts: do not mention excerpts, their numbers, or
  document metadata.
- headline: neutral, under 15 words.
- what_happened: 1-3 sentences.
- why_it_matters: 1-2 sentences, only as far as the excerpts themselves state stakes or reactions;
  null if they do not.
- cited: the numbers of the excerpts you used.

<excerpts>
{excerpts}
</excerpts>"""


def cluster_spans(session: Session, member_ids: list[int]) -> list[str]:
    """Distinct stored spans: sources (best trust first), then entity/stance spans."""
    spans = list(
        session.scalars(
            select(EventSource.span)
            .where(EventSource.event_id.in_(member_ids))
            .order_by(EventSource.trust_tier, EventSource.id)
        )
    )
    spans += session.scalars(
        select(EventEntity.span)
        .where(EventEntity.event_id.in_(member_ids))
        .order_by(EventEntity.event_id, EventEntity.entity_id, EventEntity.role, EventEntity.topic)
    ).all()
    return list(dict.fromkeys(spans))[:MAX_SPANS]


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)}


@dataclass(frozen=True)
class Lexicon:
    """Proper-name surfaces (entity names + aliases with a capital letter) -> entity id."""

    surfaces: tuple[tuple[str, int], ...]


def load_lexicon(session: Session) -> Lexicon:
    out: list[tuple[str, int]] = []
    for entity_id, name, aliases in session.execute(
        select(Entity.id, Entity.name, Entity.aliases)
    ):
        for surface in dict.fromkeys([name, *aliases]):
            if len(surface) >= 3 and any(c.isupper() for c in surface):
                out.append((surface, entity_id))
    return Lexicon(tuple(out))


def mentioned_entities(text: str, lexicon: Lexicon) -> list[tuple[str, int]]:
    return [
        (surface, entity_id)
        for surface, entity_id in lexicon.surfaces
        if surface in text and re.search(rf"(?<!\w){re.escape(surface)}(?!\w)", text)
    ]


def synthesis_text(s: Synthesis) -> str:
    return "\n".join(p for p in (s.headline, s.what_happened, s.why_it_matters) if p)


def check_grounded(
    s: Synthesis, spans: list[str], cluster_entities: set[int], lexicon: Lexicon
) -> list[str]:
    """Every problem that makes `s` ungrounded; empty means accept."""
    problems = []
    if not s.cited:
        problems.append("no citations")
    if bad := [c for c in s.cited if not 1 <= c <= len(spans)]:
        problems.append(f"cited excerpts that do not exist: {bad}")
    text = synthesis_text(s)
    corpus = "\n".join(spans)
    if extra := sorted(numbers(text) - numbers(corpus)):
        problems.append(f"numbers not in spans: {extra}")
    for surface, entity_id in mentioned_entities(text, lexicon):
        if entity_id not in cluster_entities and surface not in corpus:
            problems.append(f"entity not in cluster: {surface!r}")
    return problems


def synthesize(spans: list[str]) -> Synthesis:
    excerpts = "\n".join(f"[{i}] {s}" for i, s in enumerate(spans, 1))
    return llm.complete(
        SYNTH_PROMPT.format(excerpts=excerpts), schema=Synthesis, system=SYSTEM
    )


def _best_member(session: Session, ms: list[Event]) -> Event:
    tiers = member_tiers(session, [m.id for m in ms])
    return min(ms, key=lambda m: (_rank(tiers[m.id]), -m.confidence, m.id))


def write_prose(session: Session, head: Event, ms: list[Event], lexicon: Lexicon) -> bool:
    """LLM prose if grounded, else the best member's extractive fields. True if LLM prose used."""
    ids = [m.id for m in ms]
    spans = cluster_spans(session, ids)
    entities = cluster_entity_ids(session, head.id)
    try:
        s = synthesize(spans)
        problems = check_grounded(s, spans, entities, lexicon)
    except llm.LLMOutputError as e:
        s, problems = None, [f"invalid output: {e}"]
    if s is not None and not problems:
        head.headline, head.what_happened, head.why_it_matters = (
            s.headline, s.what_happened, s.why_it_matters,
        )
        return True

    best = _best_member(session, ms)
    head.headline, head.what_happened, head.why_it_matters = (
        best.headline, best.what_happened, None,
    )
    raw_item_id = review_raw_item(session, best)
    if raw_item_id is not None:
        write_review(
            session, raw_item_id,
            [ReviewItem(
                kind=ReviewKind.LOW_CONFIDENCE, mention=best.headline, field="event_object",
                payload={
                    "head_id": head.id, "problems": problems,
                    "synthesis": s.model_dump() if s else None,
                },
            )],
        )
    return False


# --- related events ----------------------------------------------------------------------------


def _centroids(session: Session, head_ids: list[int]) -> dict[int, list[float]]:
    rows = session.execute(
        select(Event.cluster_id, func.avg(EventEmbedding.embedding, type_=Vector(EMBED_DIM)))
        .join(EventEmbedding, EventEmbedding.event_id == Event.id)
        .where(Event.cluster_id.in_(head_ids), Event.id != Event.cluster_id)
        .group_by(Event.cluster_id)
    ).all()
    return {cid: [float(x) for x in vec] for cid, vec in rows}


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def link_related(session: Session, head: Event, settings: Settings) -> int:
    """Recompute every link touching `head`: heads within the window that share an entity and
    whose centroids are similar. Later head -> earlier head; a statement following a
    non-statement is RESPONDS_TO, anything else FOLLOWS. Returns the number of links."""
    session.execute(
        delete(EventLink).where(or_(EventLink.src_event == head.id, EventLink.dst_event == head.id))
    )
    mine = cluster_entity_ids(session, head.id)
    if not mine:
        return 0
    window = timedelta(days=settings.related_window_days)
    other = aliased(Event)
    others = list(
        session.scalars(
            select(other)
            .join(Event, Event.cluster_id == other.id)
            .join(EventEntity, EventEntity.event_id == Event.id)
            .where(
                other.id == other.cluster_id,
                other.id != head.id,
                Event.id != other.id,
                EventEntity.entity_id.in_(mine),
                other.event_time.between(head.event_time - window, head.event_time + window),
            )
            .distinct()
        )
    )
    centroids = _centroids(session, [head.id, *(o.id for o in others)])
    if head.id not in centroids:
        return 0
    names = {
        eid: cid
        for eid, cid in session.execute(
            select(Entity.id, Entity.canonical_id).where(Entity.id.in_(mine))
        )
    }

    n = 0
    for o in others:
        if o.id not in centroids:
            continue
        sim = _cosine(centroids[head.id], centroids[o.id])
        if sim < settings.related_min_sim:
            continue
        src, dst = (head, o) if (head.event_time, head.id) > (o.event_time, o.id) else (o, head)
        relation = (
            EventLinkType.RESPONDS_TO
            if src.event_type == EventType.STATEMENT and dst.event_type != EventType.STATEMENT
            else EventLinkType.FOLLOWS
        )
        shared = sorted(names[e] for e in mine & cluster_entity_ids(session, o.id))
        session.execute(
            insert(EventLink)
            .values(
                src_event=src.id, relation=relation, dst_event=dst.id,
                rationale=f"centroid cosine {sim:.2f}; shared entities: {', '.join(shared)}",
                confidence=min(max(sim, 0.0), 1.0),
            )
            .on_conflict_do_nothing(constraint="uq_event_links_src_relation_dst")
        )
        n += 1
    session.flush()
    return n


# --- materialize -------------------------------------------------------------------------------


def materialize(session: Session, head: Event, lexicon: Lexicon, *, force: bool = False) -> bool:
    """Refresh one head if its membership (or SYNTH_VERSION) changed. True if it was refreshed."""
    ms = members(session, head.id)
    if not ms:
        return False
    h = cluster_hash([m.id for m in ms])
    if head.cluster_hash == h and not force:
        return False
    rollup(session, head, ms)
    write_prose(session, head, ms, lexicon)
    head.cluster_hash = h
    link_related(session, head, get_settings())
    session.flush()
    return True


def heads(session: Session) -> list[int]:
    return list(
        session.scalars(select(Event.id).where(Event.id == Event.cluster_id).order_by(Event.id))
    )


# --- the event object --------------------------------------------------------------------------


class EntityRef(BaseModel):
    entity_id: int
    canonical_id: str
    name: str
    entity_type: str
    roles: list[str]


class Reaction(BaseModel):
    entity_id: int
    canonical_id: str
    name: str
    topic: str
    stance: str
    intensity: float | None
    span: str
    source_url: str
    trust_tier: TrustTier
    confidence: float


class RelatedEvent(BaseModel):
    event_id: int
    relation: EventLinkType
    direction: str  # "prior": this event follows it; "later": it follows this event
    headline: str
    event_time: datetime
    confidence: float


class SourceRef(BaseModel):
    url: str
    span: str
    trust_tier: TrustTier
    raw_item_id: int | None


class EventObject(BaseModel):
    id: int
    event_type: EventType
    headline: str
    what_happened: str | None
    why_it_matters: str | None
    event_time: datetime
    ingest_time: datetime
    confidence: float
    verification_status: VerificationStatus
    topics: list[str]
    policy_areas: list[str]
    jurisdiction: str | None
    member_event_ids: list[int]
    entities: list[EntityRef]
    political_reactions: list[Reaction]
    related_events: list[RelatedEvent]
    sources: list[SourceRef]


def _reactions(session: Session, member_ids: list[int]) -> list[Reaction]:
    """Stance rows from members, each with its member's source; one per (entity, topic)."""
    source: dict[int, EventSource] = {}
    for s in session.scalars(
        select(EventSource)
        .where(EventSource.event_id.in_(member_ids))
        .order_by(EventSource.trust_tier, EventSource.id)
    ):
        source.setdefault(s.event_id, s)
    rows = session.execute(
        select(EventEntity, Entity)
        .join(Entity, Entity.id == EventEntity.entity_id)
        .where(EventEntity.event_id.in_(member_ids), EventEntity.stance.is_not(None))
    ).all()
    best: dict[tuple[int, str], Reaction] = {}
    for ee, ent in rows:
        src = source.get(ee.event_id)
        if src is None:  # no provenance, no claim
            continue
        r = Reaction(
            entity_id=ent.id, canonical_id=ent.canonical_id, name=ent.name, topic=ee.topic,
            stance=ee.stance, intensity=ee.intensity, span=ee.span, source_url=src.url,
            trust_tier=src.trust_tier, confidence=ee.confidence,
        )
        key = (ent.id, ee.topic)
        cur = best.get(key)
        if cur is None or (_rank(r.trust_tier), -r.confidence) < (
            _rank(cur.trust_tier), -cur.confidence
        ):
            best[key] = r
    return sorted(best.values(), key=lambda r: (r.name, r.topic))


def _related(session: Session, head_id: int) -> list[RelatedEvent]:
    out = []
    for link in session.scalars(
        select(EventLink).where(
            or_(EventLink.src_event == head_id, EventLink.dst_event == head_id)
        )
    ):
        prior = link.src_event == head_id
        ev = session.get(Event, link.dst_event if prior else link.src_event)
        assert ev is not None
        out.append(
            RelatedEvent(
                event_id=ev.id, relation=link.relation, direction="prior" if prior else "later",
                headline=ev.headline, event_time=ev.event_time, confidence=link.confidence,
            )
        )
    return sorted(out, key=lambda r: (r.event_time, r.event_id))


def load_event_object(session: Session, head_id: int) -> EventObject:
    head = session.get(Event, head_id)
    if head is None or head.cluster_id != head.id:
        raise ValueError(f"event {head_id} is not a cluster head")
    member_ids = [m.id for m in members(session, head.id)]

    roles: dict[int, set[str]] = {}
    ents: dict[int, Entity] = {}
    for ee, ent in session.execute(
        select(EventEntity, Entity)
        .join(Entity, Entity.id == EventEntity.entity_id)
        .where(EventEntity.event_id == head.id)
    ):
        roles.setdefault(ent.id, set()).add(ee.role)
        ents[ent.id] = ent
    entities = [
        EntityRef(
            entity_id=e.id, canonical_id=e.canonical_id, name=e.name,
            entity_type=e.entity_type, roles=sorted(roles[e.id]),
        )
        for e in sorted(ents.values(), key=lambda e: e.name)
    ]
    sources = [
        SourceRef(url=s.url, span=s.span, trust_tier=s.trust_tier, raw_item_id=s.raw_item_id)
        for s in session.scalars(
            select(EventSource)
            .where(EventSource.event_id == head.id)
            .order_by(EventSource.trust_tier, EventSource.id)
        )
    ]
    fields: dict[str, Any] = {
        k: getattr(head, k)
        for k in (
            "id", "event_type", "headline", "what_happened", "why_it_matters", "event_time",
            "ingest_time", "confidence", "verification_status", "topics", "policy_areas",
            "jurisdiction",
        )
    }
    return EventObject(
        **fields,
        member_event_ids=member_ids,
        entities=entities,
        political_reactions=_reactions(session, member_ids),
        related_events=_related(session, head.id),
        sources=sources,
    )
