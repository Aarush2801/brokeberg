"""The DB spine. Every controlled-vocabulary column is constrained to the enums in `taxonomy`.

Enums are stored as varchar + a CHECK constraint (not native PG enums), so adding a taxonomy value
is a one-line constraint swap in a migration. `tests/test_migrations.py` fails if the CHECK
constraints in the DB drift from `taxonomy.py`.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CHAR, JSONB
from sqlalchemy.orm import Mapped, aliased, mapped_column

from brokeberg.db.base import Base
from brokeberg.taxonomy import (
    EdgeType,
    EntityType,
    EventLinkType,
    EventType,
    RaceRating,
    RaceType,
    SourceType,
    Stance,
    Topic,
    TrustTier,
    VerificationStatus,
)

EMBED_DIM = 1024  # pgvector column width; dev (bge-large) and prod (Titan v2) both emit 1024.
ENUM_LENGTH = 64


# Pipeline workflow states. Not domain vocabulary, so they live here rather than in `taxonomy`.
class ReviewKind(StrEnum):
    UNRESOLVED_MENTION = "unresolved_mention"
    LOW_CONFIDENCE = "low_confidence"
    VERIFICATION = "verification"


class ReviewStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ExtractionStatus(StrEnum):
    DROPPED = "dropped"
    EXTRACTED = "extracted"
    FAILED = "failed"


# CHECK names (after the `ck_<table>_` prefix) for each enum, used by migrations and the drift test.
ENUM_CHECKS: dict[str, type[StrEnum]] = {
    "source_type": SourceType,
    "entity_type": EntityType,
    "event_type": EventType,
    "verification_status": VerificationStatus,
    "trust_tier": TrustTier,
    "stance": Stance,
    "edge_type": EdgeType,
    "event_link_type": EventLinkType,
    "race_type": RaceType,
    "race_rating": RaceRating,
    "review_kind": ReviewKind,
    "review_status": ReviewStatus,
    "extraction_status": ExtractionStatus,
}

# `event_entities.topic`: '' for a plain mention row, else the Topic a stance row is about.
NO_TOPIC = ""
TOPIC_CHECK = "topic = '' OR topic IN ({})".format(", ".join(f"'{t.value}'" for t in Topic))


def _enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=ENUM_LENGTH,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


def _unit_range(col: str) -> CheckConstraint:
    return CheckConstraint(f"{col} >= 0 AND {col} <= 1", name=f"{col}_range")


def _non_empty(col: str) -> CheckConstraint:
    return CheckConstraint(f"length(btrim({col})) > 0", name=f"{col}_non_empty")


def _pk() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RawItem(Base):
    """One fetched source item. `content_hash` is the idempotency key."""

    __tablename__ = "raw_items"

    id: Mapped[int] = _pk()
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        _enum(SourceType, "source_type"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    payload_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = _created_at()
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Entity(Base):
    """A graph node keyed by a namespaced canonical ID (see `brokeberg.ids.canonical`)."""

    __tablename__ = "entities"
    __table_args__ = (
        Index("ix_entities_aliases", "aliases", postgresql_using="gin"),
        CheckConstraint("jsonb_typeof(aliases) = 'array'", name="aliases_is_array"),
    )

    id: Mapped[int] = _pk()
    entity_type: Mapped[EntityType] = mapped_column(
        _enum(EntityType, "entity_type"), nullable=False, index=True
    )
    canonical_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    importance: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Event(Base):
    """A member event (one per extracted raw item) or a cluster head (the event object).

    A head has `cluster_id = id`; a member points `cluster_id` at its head; NULL = unclustered.
    """

    __tablename__ = "events"
    __table_args__ = (
        _unit_range("confidence"),
        Index("ix_events_topics", "topics", postgresql_using="gin"),
        Index("ix_events_policy_areas", "policy_areas", postgresql_using="gin"),
        Index("ix_events_event_time", text("event_time DESC")),
    )

    id: Mapped[int] = _pk()
    cluster_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("events.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[EventType] = mapped_column(_enum(EventType, "event_type"), nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    what_happened: Mapped[str | None] = mapped_column(Text)
    why_it_matters: Mapped[str | None] = mapped_column(Text)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingest_time: Mapped[datetime] = _created_at()
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        _enum(VerificationStatus, "verification_status"),
        nullable=False,
        server_default=VerificationStatus.UNVERIFIED.value,
    )
    topics: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    policy_areas: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    # A jurisdiction canonical ID (`fips:13`) or 'federal'.
    jurisdiction: Mapped[str | None] = mapped_column(Text)
    # Heads only: hash of member ids + synthesis version; unchanged -> skip re-materializing.
    cluster_hash: Mapped[str | None] = mapped_column(Text)
    # Heads only: the verify pass's factual evidence (source count, numeric checks).
    verification: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class EventSource(Base):
    """Provenance: no verbatim span, no claim."""

    __tablename__ = "event_sources"
    __table_args__ = (_non_empty("span"),)

    id: Mapped[int] = _pk()
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raw_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_items.id", ondelete="SET NULL"), index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    span: Mapped[str] = mapped_column(Text, nullable=False)
    trust_tier: Mapped[TrustTier] = mapped_column(_enum(TrustTier, "trust_tier"), nullable=False)
    claim: Mapped[str | None] = mapped_column(Text)


class EventEntity(Base):
    """A mention (`topic=''`) or a per-topic stance of an entity in an event."""

    __tablename__ = "event_entities"
    __table_args__ = (
        _unit_range("intensity"),
        _unit_range("confidence"),
        _non_empty("span"),
        CheckConstraint(TOPIC_CHECK, name="topic_valid"),
    )

    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic: Mapped[str] = mapped_column(
        String(64), primary_key=True, server_default=text("''")
    )
    stance: Mapped[Stance | None] = mapped_column(_enum(Stance, "stance"))
    intensity: Mapped[float | None] = mapped_column(Float)
    span: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # Head stance rows only: the earlier stance this one reverses (set by verify; NULL = none).
    stance_flip: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Edge(Base):
    """A typed relationship between two entities. There is no CAUSES edge type, by design."""

    __tablename__ = "edges"
    __table_args__ = (
        _unit_range("confidence"),
        CheckConstraint("src_entity <> dst_entity", name="no_self_loop"),
        UniqueConstraint(
            "src_entity", "relation", "dst_entity", "event_id",
            name="uq_edges_src_relation_dst_event",
        ),
    )

    id: Mapped[int] = _pk()
    src_entity: Mapped[int] = mapped_column(
        ForeignKey("entities.id"), nullable=False, index=True
    )
    relation: Mapped[EdgeType] = mapped_column(_enum(EdgeType, "edge_type"), nullable=False)
    dst_entity: Mapped[int] = mapped_column(
        ForeignKey("entities.id"), nullable=False, index=True
    )
    rationale: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = _created_at()


class Indicator(Base):
    """One observation of an economic series (FRED series ID, un-namespaced).

    `source` is part of the key: BLS values are stored under the matching FRED series ID as a
    verification reference, alongside FRED's own value for the same date.
    """

    __tablename__ = "indicators"

    series_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    asof: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class Race(Base):
    """A contest, keyed by `STATE-OFFICE-CYCLE` (e.g. 'GA-SEN-2026')."""

    __tablename__ = "races"
    __table_args__ = (
        CheckConstraint("id ~ '^[A-Z]{2}-[A-Z]+-[0-9]{4}$'", name="id_format"),
        CheckConstraint("state_fips ~ '^[0-9]{2}$'", name="state_fips_format"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    state_fips: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    office: Mapped[RaceType] = mapped_column(_enum(RaceType, "race_type"), nullable=False)
    cycle: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Current rating; only ever written from a sourced `race_ratings_history` row.
    rating: Mapped[RaceRating | None] = mapped_column(_enum(RaceRating, "race_rating"))
    salient_topics: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    fec_candidate_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    ballotpedia_slug: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class RaceRatingHistory(Base):
    __tablename__ = "race_ratings_history"
    __table_args__ = (
        UniqueConstraint(
            "race_id", "rater", "asof", name="uq_race_ratings_history_race_rater_asof"
        ),
    )

    id: Mapped[int] = _pk()
    race_id: Mapped[str] = mapped_column(
        ForeignKey("races.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rater: Mapped[str] = mapped_column(String(64), nullable=False)
    rating: Mapped[RaceRating] = mapped_column(_enum(RaceRating, "race_rating"), nullable=False)
    asof: Mapped[date] = mapped_column(Date, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)


class PollAverage(Base):
    __tablename__ = "poll_averages"

    id: Mapped[int] = _pk()
    race_id: Mapped[str] = mapped_column(
        ForeignKey("races.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    asof: Mapped[date] = mapped_column(Date, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    # Idempotency key over the source row, so re-ingesting a poll file never double-inserts.
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


class EventEmbedding(Base):
    """One vector per member event. Heads are never embedded; similarity runs over members.

    HNSW (cosine), not ivfflat: HNSW needs no training pass, so it is correct on an empty and
    growing table, and has better recall/latency. ivfflat's `lists` must be tuned on existing data.
    """

    __tablename__ = "event_embeddings"
    __table_args__ = (
        Index(
            "ix_event_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM), nullable=False)
    # NULL / a different model than configured -> stale, re-embedded.
    embed_model: Mapped[str | None] = mapped_column(Text)
    text_hash: Mapped[str | None] = mapped_column(Text)


class EventLink(Base):
    """A link between two cluster heads: `src` came after `dst`. Never causal."""

    __tablename__ = "event_links"
    __table_args__ = (
        _unit_range("confidence"),
        CheckConstraint("src_event <> dst_event", name="no_self_loop"),
        UniqueConstraint(
            "src_event", "relation", "dst_event", name="uq_event_links_src_relation_dst"
        ),
    )

    id: Mapped[int] = _pk()
    src_event: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation: Mapped[EventLinkType] = mapped_column(
        _enum(EventLinkType, "event_link_type"), nullable=False
    )
    dst_event: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rationale: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class EventRaceEdge(Base):
    """event -AFFECTS-> race. Never a bare link: every row carries the rule's rationale."""

    __tablename__ = "event_race_edges"
    __table_args__ = (
        _unit_range("confidence"),
        _non_empty("rationale"),
        CheckConstraint("relation = 'AFFECTS'", name="relation_affects"),
        UniqueConstraint("event_id", "race_id", name="uq_event_race_edges_event_race"),
    )

    id: Mapped[int] = _pk()
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    race_id: Mapped[str] = mapped_column(
        ForeignKey("races.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation: Mapped[EdgeType] = mapped_column(_enum(EdgeType, "edge_type"), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    matched_topics: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = _created_at()


class ReviewQueue(Base):
    """Everything a human must look at: unresolved mentions and low-confidence extractions.

    A mention that cannot be linked to a canonical ID lands here, never in `entities`.
    """

    __tablename__ = "review_queue"
    __table_args__ = (
        _unit_range("confidence"),
        UniqueConstraint(
            "raw_item_id", "kind", "mention", "field",
            name="uq_review_queue_item_kind_mention_field",
        ),
    )

    id: Mapped[int] = _pk()
    raw_item_id: Mapped[int] = mapped_column(
        ForeignKey("raw_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ReviewKind] = mapped_column(_enum(ReviewKind, "review_kind"), nullable=False)
    mention: Mapped[str] = mapped_column(Text, nullable=False)
    # Which extraction field this is about, e.g. 'entities' or 'stance:healthcare'.
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type_hint: Mapped[EntityType | None] = mapped_column(_enum(EntityType, "entity_type"))
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[ReviewStatus] = mapped_column(
        _enum(ReviewStatus, "review_status"),
        nullable=False,
        server_default=ReviewStatus.OPEN.value,
        index=True,
    )
    created_at: Mapped[datetime] = _created_at()


class ExtractionRun(Base):
    """One extraction attempt per raw item: the idempotency record and the per-pass partials."""

    __tablename__ = "extraction_runs"

    id: Mapped[int] = _pk()
    raw_item_id: Mapped[int] = mapped_column(
        ForeignKey("raw_items.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ExtractionStatus] = mapped_column(
        _enum(ExtractionStatus, "extraction_status"), nullable=False
    )
    dropped_reason: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    pass_outputs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created_at()


# The `event_objects` view (cluster heads only), mapped onto `Event` so readers get ORM rows from
# the view, never from `events`. Its own MetaData: it is a view, not a table migrations manage.
event_objects_view = Table(
    "event_objects",
    MetaData(),
    *(Column(c.name, c.type, primary_key=c.primary_key) for c in Event.__table__.columns),
)
HeadEvent = aliased(Event, event_objects_view, adapt_on_names=True)
