"""verify + graph: events.verification, event->race edges, edge dedupe, verification review kind

Revision ID: 0007_verify_graph
Revises: 0006_event_objects_view
Create Date: 2026-10-07

`event_objects` expands `e.*` at creation, so it is dropped and recreated around the new
`events.verification` column. `event_race_edges` is its own table: `edges` is entity -> entity and
an event is not an entity node. Enum values are frozen literals, as in 0002.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_verify_graph"
down_revision: str | None = "0006_event_objects_view"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EDGE_TYPE = (
    "SUPPORTS", "OPPOSES", "PROPOSES", "VOTED_FOR", "VOTED_AGAINST", "AFFECTS", "EXPOSED_TO",
    "LOCATED_IN", "COMPETES_IN", "ENDORSES", "FUNDED_BY", "RESPONDS_TO", "CORRELATES_WITH",
)
REVIEW_KIND_OLD = ("unresolved_mention", "low_confidence")
REVIEW_KIND_NEW = (*REVIEW_KIND_OLD, "verification")

VIEW = "CREATE VIEW event_objects AS SELECT e.* FROM events e WHERE e.id = e.cluster_id"


def _review_kind_check(values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_review_queue_review_kind"), "review_queue", type_="check")
    allowed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(
        op.f("ck_review_queue_review_kind"), "review_queue", f"kind IN ({allowed})"
    )


def upgrade() -> None:
    op.execute("DROP VIEW event_objects")
    op.add_column(
        "events",
        sa.Column(
            "verification", postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
    )
    op.execute(VIEW)

    op.create_unique_constraint(
        "uq_edges_src_relation_dst_event", "edges",
        ["src_entity", "relation", "dst_entity", "event_id"],
    )

    op.create_table(
        "event_race_edges",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "event_id", sa.BigInteger(), sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "race_id", sa.String(32), sa.ForeignKey("races.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "relation",
            sa.Enum(
                *EDGE_TYPE, name="edge_type", native_enum=False, create_constraint=True,
                length=64,
            ),
            nullable=False,
        ),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "matched_topics", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.CheckConstraint("length(btrim(rationale)) > 0", name="rationale_non_empty"),
        sa.CheckConstraint("relation = 'AFFECTS'", name="relation_affects"),
        sa.UniqueConstraint("event_id", "race_id", name="uq_event_race_edges_event_race"),
    )
    op.create_index("ix_event_race_edges_event_id", "event_race_edges", ["event_id"])
    op.create_index("ix_event_race_edges_race_id", "event_race_edges", ["race_id"])

    _review_kind_check(REVIEW_KIND_NEW)


def downgrade() -> None:
    op.execute("DELETE FROM review_queue WHERE kind = 'verification'")
    _review_kind_check(REVIEW_KIND_OLD)
    op.drop_table("event_race_edges")
    op.drop_constraint("uq_edges_src_relation_dst_event", "edges", type_="unique")
    op.execute("DROP VIEW event_objects")
    op.drop_column("events", "verification")
    op.execute(VIEW)
