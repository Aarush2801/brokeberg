"""schema spine: raw items, entities, events, provenance, edges, indicators, races, embeddings

Revision ID: 0002_schema_spine
Revises: 0001_baseline
Create Date: 2026-10-07

Enum values are frozen literals (a migration is a snapshot, not a view of today's taxonomy).
`tests/test_migrations.py` fails if `taxonomy.py` drifts from these CHECK constraints.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002_schema_spine"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_TYPE = (
    "government_primary", "official_statement", "data_release", "press_release", "poll", "news",
    "social_post",
)
ENTITY_TYPE = (
    "Politician", "Agency", "Committee", "Party", "Candidate", "Race", "Office", "Jurisdiction",
    "EconomicIndicator", "Industry", "Company", "InterestGroup_PAC", "Country", "Policy_Bill",
)
EVENT_TYPE = (
    "legislative_action", "executive_action", "statement", "economic_release", "judicial_action",
    "poll_release", "campaign_finance_filing", "election_result", "controversy", "nomination",
    "regulatory_action", "geopolitical",
)
VERIFICATION_STATUS = (
    "unverified", "single_source", "corroborated", "contradicted", "fact_checked",
)
TRUST_TIER = ("T1", "T2", "T3", "T4")
STANCE = (
    "strongly_support", "support", "lean_support", "neutral_unclear", "lean_oppose", "oppose",
    "strongly_oppose",
)
EDGE_TYPE = (
    "SUPPORTS", "OPPOSES", "PROPOSES", "VOTED_FOR", "VOTED_AGAINST", "AFFECTS", "EXPOSED_TO",
    "LOCATED_IN", "COMPETES_IN", "ENDORSES", "FUNDED_BY", "RESPONDS_TO", "CORRELATES_WITH",
)
RACE_TYPE = ("Senate", "House", "Governor", "President", "ballot_measure")
RACE_RATING = (
    "safe_d", "likely_d", "lean_d", "tossup_d", "tossup_r", "lean_r", "likely_r", "safe_r",
)


def _enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    # varchar(64) + CHECK, named ck_<table>_<name> by the metadata naming convention.
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=64)


def _pk() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True)


def _now(name: str) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _jsonb(name: str, default: str) -> sa.Column:
    return sa.Column(
        name, postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text(default),
        nullable=False,
    )


def _text_array(name: str) -> sa.Column:
    return sa.Column(
        name, postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
    )


def _unit_range(col: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{col} >= 0 AND {col} <= 1", name=f"{col}_range")


def _non_empty(col: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"length(btrim({col})) > 0", name=f"{col}_non_empty")


def upgrade() -> None:
    op.create_table(
        "raw_items",
        _pk(),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_type", _enum("source_type", SOURCE_TYPE), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("payload_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _now("fetched_at"),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "entities",
        _pk(),
        sa.Column("entity_type", _enum("entity_type", ENTITY_TYPE), nullable=False),
        sa.Column("canonical_id", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        _jsonb("aliases", "'[]'::jsonb"),
        sa.Column("importance", sa.Float(), server_default=sa.text("0"), nullable=False),
        _jsonb("meta", "'{}'::jsonb"),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint("jsonb_typeof(aliases) = 'array'", name="aliases_is_array"),
    )
    op.create_index("ix_entities_entity_type", "entities", ["entity_type"])
    op.create_index("ix_entities_aliases", "entities", ["aliases"], postgresql_using="gin")

    op.create_table(
        "events",
        _pk(),
        sa.Column("cluster_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", _enum("event_type", EVENT_TYPE), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("what_happened", sa.Text(), nullable=True),
        sa.Column("why_it_matters", sa.Text(), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        _now("ingest_time"),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "verification_status",
            _enum("verification_status", VERIFICATION_STATUS),
            server_default="unverified",
            nullable=False,
        ),
        _text_array("topics"),
        _text_array("policy_areas"),
        sa.Column("jurisdiction", sa.Text(), nullable=True),
        _unit_range("confidence"),
    )
    op.create_index("ix_events_cluster_id", "events", ["cluster_id"])
    op.create_index("ix_events_event_time", "events", [sa.literal_column("event_time DESC")])
    op.create_index("ix_events_topics", "events", ["topics"], postgresql_using="gin")
    op.create_index("ix_events_policy_areas", "events", ["policy_areas"], postgresql_using="gin")

    op.create_table(
        "event_sources",
        _pk(),
        sa.Column(
            "event_id", sa.BigInteger(), sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "raw_item_id", sa.BigInteger(), sa.ForeignKey("raw_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("span", sa.Text(), nullable=False),
        sa.Column("trust_tier", _enum("trust_tier", TRUST_TIER), nullable=False),
        sa.Column("claim", sa.Text(), nullable=True),
        _non_empty("span"),
    )
    op.create_index("ix_event_sources_event_id", "event_sources", ["event_id"])
    op.create_index("ix_event_sources_raw_item_id", "event_sources", ["raw_item_id"])

    op.create_table(
        "event_entities",
        sa.Column(
            "event_id", sa.BigInteger(), sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("entity_id", sa.BigInteger(), sa.ForeignKey("entities.id"), primary_key=True),
        sa.Column("role", sa.String(64), primary_key=True),
        sa.Column("stance", _enum("stance", STANCE), nullable=True),
        sa.Column("intensity", sa.Float(), nullable=True),
        sa.Column("span", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        _unit_range("intensity"),
        _unit_range("confidence"),
        _non_empty("span"),
    )
    op.create_index("ix_event_entities_entity_id", "event_entities", ["entity_id"])

    op.create_table(
        "edges",
        _pk(),
        sa.Column("src_entity", sa.BigInteger(), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("relation", _enum("edge_type", EDGE_TYPE), nullable=False),
        sa.Column("dst_entity", sa.BigInteger(), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "event_id", sa.BigInteger(), sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=True,
        ),
        _now("created_at"),
        _unit_range("confidence"),
        sa.CheckConstraint("src_entity <> dst_entity", name="no_self_loop"),
    )
    op.create_index("ix_edges_src_entity", "edges", ["src_entity"])
    op.create_index("ix_edges_dst_entity", "edges", ["dst_entity"])
    op.create_index("ix_edges_event_id", "edges", ["event_id"])

    op.create_table(
        "indicators",
        sa.Column("series_id", sa.String(32), primary_key=True),
        sa.Column("asof", sa.Date(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
    )

    op.create_table(
        "races",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("state_fips", sa.CHAR(2), nullable=False),
        sa.Column("office", _enum("race_type", RACE_TYPE), nullable=False),
        sa.Column("cycle", sa.SmallInteger(), nullable=False),
        sa.Column("rating", _enum("race_rating", RACE_RATING), nullable=True),
        _text_array("salient_topics"),
        _text_array("fec_candidate_ids"),
        sa.Column("ballotpedia_slug", sa.Text(), nullable=True),
        _jsonb("meta", "'{}'::jsonb"),
        sa.CheckConstraint("id ~ '^[A-Z]{2}-[A-Z]+-[0-9]{4}$'", name="id_format"),
        sa.CheckConstraint("state_fips ~ '^[0-9]{2}$'", name="state_fips_format"),
    )

    op.create_table(
        "race_ratings_history",
        _pk(),
        sa.Column(
            "race_id", sa.String(32), sa.ForeignKey("races.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rater", sa.String(64), nullable=False),
        sa.Column("rating", _enum("race_rating", RACE_RATING), nullable=False),
        sa.Column("asof", sa.Date(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "race_id", "rater", "asof", name="uq_race_ratings_history_race_rater_asof"
        ),
    )
    op.create_index("ix_race_ratings_history_race_id", "race_ratings_history", ["race_id"])

    op.create_table(
        "poll_averages",
        _pk(),
        sa.Column(
            "race_id", sa.String(32), sa.ForeignKey("races.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(), nullable=False),
        _jsonb("meta", "'{}'::jsonb"),
        sa.Column("asof", sa.Date(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
    )
    op.create_index("ix_poll_averages_race_id", "poll_averages", ["race_id"])

    op.create_table(
        "event_embeddings",
        sa.Column(
            "event_id", sa.BigInteger(), sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("embedding", Vector(1024), nullable=False),
    )


def downgrade() -> None:
    # Indexes and constraints go with their tables. The `vector` extension belongs to 0001.
    for table in (
        "event_embeddings",
        "poll_averages",
        "race_ratings_history",
        "races",
        "indicators",
        "edges",
        "event_entities",
        "event_sources",
        "events",
        "entities",
        "raw_items",
    ):
        op.drop_table(table)
