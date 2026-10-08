"""stance flips live on the stance row, not on the event

Revision ID: 0008_stance_flip
Revises: 0007_verify_graph
Create Date: 2026-10-07

`event_entities.stance_flip` (head stance rows only): the prior stance this row reverses, with its
event, span and source. An event's `verification_status` reflects only its factual checks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_stance_flip"
down_revision: str | None = "0007_verify_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event_entities",
        sa.Column("stance_flip", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Statuses written under the old rule (a flip marked the whole event 'contradicted') are
    # re-derived by the next `make graph`.


def downgrade() -> None:
    op.drop_column("event_entities", "stance_flip")
