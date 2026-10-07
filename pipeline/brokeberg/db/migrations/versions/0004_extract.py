"""extract: review queue, extraction runs, per-topic stance rows in event_entities

Revision ID: 0004_extract
Revises: 0003_ingest
Create Date: 2026-10-07

Enum values are frozen literals, as in 0002.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_extract"
down_revision: str | None = "0003_ingest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTITY_TYPE = (
    "Politician", "Agency", "Committee", "Party", "Candidate", "Race", "Office", "Jurisdiction",
    "EconomicIndicator", "Industry", "Company", "InterestGroup_PAC", "Country", "Policy_Bill",
)
TOPIC = (
    "inflation_cost_of_living", "taxation", "trade_tariffs", "immigration", "healthcare",
    "energy_climate", "labor_jobs", "housing", "monetary_policy", "fiscal_debt",
    "foreign_policy_defense", "social_abortion", "crime_justice", "tech_ai_regulation", "education",
    "agriculture",
)
REVIEW_KIND = ("unresolved_mention", "low_confidence")
REVIEW_STATUS = ("open", "accepted", "rejected")
EXTRACTION_STATUS = ("dropped", "extracted", "failed")


def _enum(name: str, values: tuple[str, ...]) -> sa.Enum:
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


def upgrade() -> None:
    op.create_table(
        "review_queue",
        _pk(),
        sa.Column(
            "raw_item_id", sa.BigInteger(), sa.ForeignKey("raw_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", _enum("review_kind", REVIEW_KIND), nullable=False),
        sa.Column("mention", sa.Text(), nullable=False),
        sa.Column("field", sa.String(64), nullable=False),
        sa.Column("entity_type_hint", _enum("entity_type", ENTITY_TYPE), nullable=True),
        _jsonb("candidates", "'[]'::jsonb"),
        _jsonb("payload", "'{}'::jsonb"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "status", _enum("review_status", REVIEW_STATUS), server_default="open", nullable=False
        ),
        _now("created_at"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.UniqueConstraint(
            "raw_item_id", "kind", "mention", "field",
            name="uq_review_queue_item_kind_mention_field",
        ),
    )
    op.create_index("ix_review_queue_raw_item_id", "review_queue", ["raw_item_id"])
    op.create_index("ix_review_queue_status", "review_queue", ["status"])

    op.create_table(
        "extraction_runs",
        _pk(),
        sa.Column(
            "raw_item_id", sa.BigInteger(), sa.ForeignKey("raw_items.id", ondelete="CASCADE"),
            nullable=False, unique=True,
        ),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("status", _enum("extraction_status", EXTRACTION_STATUS), nullable=False),
        sa.Column("dropped_reason", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _jsonb("pass_outputs", "'{}'::jsonb"),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column(
            "event_id", sa.BigInteger(), sa.ForeignKey("events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _now("created_at"),
    )

    # One stance row per (entity, topic): topic joins the primary key; '' marks a plain mention.
    op.add_column(
        "event_entities",
        sa.Column("topic", sa.String(64), server_default=sa.text("''"), nullable=False),
    )
    allowed = ", ".join(f"'{t}'" for t in TOPIC)
    op.create_check_constraint(
        op.f("ck_event_entities_topic_valid"), "event_entities",
        f"topic = '' OR topic IN ({allowed})",
    )
    op.drop_constraint(op.f("pk_event_entities"), "event_entities", type_="primary")
    op.create_primary_key(
        op.f("pk_event_entities"), "event_entities", ["event_id", "entity_id", "role", "topic"]
    )


def downgrade() -> None:
    # Fails loudly if an actor holds stances on several topics in one event; no lossless mapping.
    op.drop_constraint(op.f("pk_event_entities"), "event_entities", type_="primary")
    op.create_primary_key(
        op.f("pk_event_entities"), "event_entities", ["event_id", "entity_id", "role"]
    )
    op.drop_constraint(op.f("ck_event_entities_topic_valid"), "event_entities", type_="check")
    op.drop_column("event_entities", "topic")

    op.drop_table("extraction_runs")
    op.drop_table("review_queue")
