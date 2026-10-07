"""Fixture corpus for clustering tests: member events inserted directly (no extraction run).

Three reports of the August CPI release (BLS, a news story, a senator's reaction), plus an
unrelated nomination vote. `unit_vec` builds controlled embeddings: `unit_vec(s, k)` has cosine
`s` with the base axis, and two such vectors on different `k` have cosine `s1 * s2`.
"""

import hashlib
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.db.models import (
    EMBED_DIM,
    NO_TOPIC,
    Entity,
    Event,
    EventEntity,
    EventSource,
    RawItem,
)
from brokeberg.taxonomy import SOURCE_TRUST, EventType, SourceType, Stance, Topic

T0 = datetime(2026, 9, 10, 12, 30, tzinfo=UTC)

CPI = "fred:CPIAUCSL"
MURKOWSKI = "bioguide:M001153"
SULLIVAN = "bioguide:S001198"


def unit_vec(sim_to_base: float, axis: int) -> list[float]:
    assert axis > 0, "axis 0 is the base"
    v = [0.0] * EMBED_DIM
    v[0] = sim_to_base
    v[axis] = math.sqrt(max(0.0, 1 - sim_to_base**2))
    return v


@dataclass
class Item:
    headline: str
    span: str
    url: str
    source_type: SourceType
    event_type: EventType
    event_time: datetime
    entities: list[tuple[str, str, str]]  # (canonical_id, role, span)
    topics: list[Topic] = field(default_factory=list)
    stances: list[tuple[str, Topic, Stance, str]] = field(default_factory=list)
    confidence: float = 0.9


CPI_BLS = Item(
    headline="CPI rose 0.4 percent in August",
    span="The Consumer Price Index for All Urban Consumers increased 0.4 percent on a seasonally "
    "adjusted basis in August",
    url="https://www.bls.gov/news.release/cpi.nr0.htm",
    source_type=SourceType.DATA_RELEASE,
    event_type=EventType.ECONOMIC_RELEASE,
    event_time=T0,
    entities=[(CPI, "subject", "The Consumer Price Index for All Urban Consumers")],
    topics=[Topic.INFLATION_COST_OF_LIVING],
    confidence=0.95,
)
CPI_NEWS = Item(
    headline="Consumer prices climbed 0.4% in August, hotter than forecast",
    span="Consumer prices rose 0.4% in August from July, above the 0.3% economists expected",
    url="https://www.nytimes.com/2026/09/10/business/cpi-inflation-august.html",
    source_type=SourceType.NEWS,
    event_type=EventType.ECONOMIC_RELEASE,
    event_time=T0.replace(hour=13),
    entities=[(CPI, "subject", "Consumer prices")],
    topics=[Topic.INFLATION_COST_OF_LIVING, Topic.MONETARY_POLICY],
    confidence=0.85,
)
CPI_REACTION = Item(
    headline="Murkowski says August CPI shows families still squeezed",
    span="Today's CPI report shows prices up 0.4% again. Alaska families are still squeezed.",
    url="https://x.com/LisaMurkowski/status/1966000000000000001",
    source_type=SourceType.SOCIAL_POST,
    event_type=EventType.STATEMENT,
    event_time=T0.replace(hour=15),
    entities=[(CPI, "subject", "CPI"), (MURKOWSKI, "actor", "@LisaMurkowski")],
    topics=[Topic.INFLATION_COST_OF_LIVING],
    stances=[(MURKOWSKI, Topic.INFLATION_COST_OF_LIVING, Stance.OPPOSE,
              "Alaska families are still squeezed.")],
    confidence=0.8,
)
NOMINATION = Item(
    headline="Senate confirms ambassador to Japan, 68-30",
    span="The Senate voted 68-30 to confirm the nominee as ambassador to Japan",
    url="https://www.senate.gov/legislative/LIS/roll_call_votes/vote1192/vote_119_2_00250.htm",
    source_type=SourceType.GOVERNMENT_PRIMARY,
    event_type=EventType.NOMINATION,
    event_time=T0.replace(hour=16),
    entities=[(SULLIVAN, "voter", "Sullivan (R-AK), Yea")],
    topics=[Topic.FOREIGN_POLICY_DEFENSE],
)


def entity_id(db: Session, canonical_id: str) -> int:
    eid = db.scalar(select(Entity.id).where(Entity.canonical_id == canonical_id))
    assert eid is not None, f"{canonical_id} not seeded"
    return eid


def add_member(db: Session, item: Item, **overrides: Any) -> Event:
    """Insert one extracted member event (raw item + event + provenance + entity/stance rows)."""
    if overrides:
        item = Item(**{**item.__dict__, **overrides})
    raw = RawItem(
        source="fixture",
        source_type=item.source_type,
        content_hash=hashlib.sha256(f"{item.url}|{item.headline}".encode()).hexdigest(),
        url=item.url,
        payload_jsonb={"text": item.span},
        event_time=item.event_time,
    )
    db.add(raw)
    event = Event(
        event_type=item.event_type,
        headline=item.headline,
        what_happened=item.span,
        event_time=item.event_time,
        confidence=item.confidence,
        topics=[str(t) for t in item.topics],
        policy_areas=[str(t) for t in item.topics],
        jurisdiction="federal",
    )
    db.add(event)
    db.flush()
    db.add(
        EventSource(
            event_id=event.id, raw_item_id=raw.id, url=item.url, span=item.span,
            trust_tier=SOURCE_TRUST[item.source_type], claim=item.headline,
        )
    )
    for cid, role, span in item.entities:
        db.add(
            EventEntity(
                event_id=event.id, entity_id=entity_id(db, cid), role=role, topic=NO_TOPIC,
                span=span, confidence=0.9,
            )
        )
    for cid, topic, stance, span in item.stances:
        db.add(
            EventEntity(
                event_id=event.id, entity_id=entity_id(db, cid), role="actor", topic=str(topic),
                stance=stance, intensity=0.6, span=span, confidence=0.85,
            )
        )
    db.flush()
    return event


class FakeEmbedder:
    """Stands in for `embed()`: the vector is chosen by the text's first line (the headline)."""

    def __init__(self) -> None:
        self.vectors: dict[str, list[float]] = {}
        self.calls = 0

    def set(self, headline: str, vector: list[float]) -> None:
        self.vectors[headline] = vector

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self.vectors[t.split("\n", 1)[0]] for t in texts]
