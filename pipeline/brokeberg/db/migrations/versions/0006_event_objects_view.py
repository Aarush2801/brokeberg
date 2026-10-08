"""event_objects: the read path for event objects (cluster heads only)

Revision ID: 0006_event_objects_view
Revises: 0005_cluster
Create Date: 2026-10-07

`events` holds both cluster heads (`id = cluster_id`, the event object) and their members (one per
extracted raw item). Readers (verification, graph, UI) query `event_objects`, never `events`, so
they see exactly one row per happening. Postgres expands `e.*` at creation: a new `events` column
needs the view recreated in that column's migration.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_event_objects_view"
down_revision: str | None = "0005_cluster"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE VIEW event_objects AS SELECT e.* FROM events e WHERE e.id = e.cluster_id")


def downgrade() -> None:
    op.execute("DROP VIEW event_objects")
