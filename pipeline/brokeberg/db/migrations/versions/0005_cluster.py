"""cluster: head/member events, embedding HNSW index, event links

Revision ID: 0005_cluster
Revises: 0004_extract
Create Date: 2026-10-07

A cluster head is an `events` row with `cluster_id = id`; members point at it. The ANN index is
HNSW with cosine ops: it needs no training data (works on an empty, growing table) and beats
ivfflat on recall/latency; ivfflat's `lists` would have to be tuned on data we do not have yet.
Enum values are frozen literals, as in 0002.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_cluster"
down_revision: str | None = "0004_extract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_LINK_TYPE = ("FOLLOWS", "RESPONDS_TO")


def upgrade() -> None:
    op.create_foreign_key(
        op.f("fk_events_cluster_id_events"), "events", "events", ["cluster_id"], ["id"],
        ondelete="SET NULL",
    )
    op.add_column("events", sa.Column("cluster_hash", sa.Text(), nullable=True))

    op.add_column("event_embeddings", sa.Column("embed_model", sa.Text(), nullable=True))
    op.add_column("event_embeddings", sa.Column("text_hash", sa.Text(), nullable=True))
    op.create_index(
        "ix_event_embeddings_embedding_hnsw",
        "event_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "event_links",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "src_event", sa.BigInteger(), sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "relation",
            sa.Enum(
                *EVENT_LINK_TYPE, name="event_link_type", native_enum=False,
                create_constraint=True, length=64,
            ),
            nullable=False,
        ),
        sa.Column(
            "dst_event", sa.BigInteger(), sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.CheckConstraint("src_event <> dst_event", name="no_self_loop"),
        sa.UniqueConstraint(
            "src_event", "relation", "dst_event", name="uq_event_links_src_relation_dst"
        ),
    )
    op.create_index("ix_event_links_src_event", "event_links", ["src_event"])
    op.create_index("ix_event_links_dst_event", "event_links", ["dst_event"])


def downgrade() -> None:
    op.drop_table("event_links")
    op.drop_index("ix_event_embeddings_embedding_hnsw", table_name="event_embeddings")
    op.drop_column("event_embeddings", "text_hash")
    op.drop_column("event_embeddings", "embed_model")
    op.drop_column("events", "cluster_hash")
    op.drop_constraint(op.f("fk_events_cluster_id_events"), "events", type_="foreignkey")
