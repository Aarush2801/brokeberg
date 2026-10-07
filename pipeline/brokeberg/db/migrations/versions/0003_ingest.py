"""ingest: pure tossup rating, source in the indicators key, poll_averages idempotency hash

Revision ID: 0003_ingest
Revises: 0002_schema_spine
Create Date: 2026-10-07

Enum values are frozen literals, as in 0002.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_ingest"
down_revision: str | None = "0002_schema_spine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RACE_RATING_OLD = (
    "safe_d", "likely_d", "lean_d", "tossup_d", "tossup_r", "lean_r", "likely_r", "safe_r",
)
RACE_RATING_NEW = (
    "safe_d", "likely_d", "lean_d", "tossup_d", "tossup", "tossup_r", "lean_r", "likely_r",
    "safe_r",
)
RATING_TABLES = ("races", "race_ratings_history")


def _swap_rating_check(values: tuple[str, ...]) -> None:
    allowed = ", ".join(f"'{v}'" for v in values)
    for table in RATING_TABLES:
        name = f"ck_{table}_race_rating"
        op.drop_constraint(op.f(name), table, type_="check")
        op.create_check_constraint(op.f(name), table, f"rating IN ({allowed})")


def upgrade() -> None:
    _swap_rating_check(RACE_RATING_NEW)

    op.drop_constraint(op.f("pk_indicators"), "indicators", type_="primary")
    op.create_primary_key(op.f("pk_indicators"), "indicators", ["series_id", "asof", "source"])

    op.add_column("poll_averages", sa.Column("content_hash", sa.Text(), nullable=False))
    op.create_unique_constraint(
        op.f("uq_poll_averages_content_hash"), "poll_averages", ["content_hash"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_poll_averages_content_hash"), "poll_averages", type_="unique")
    op.drop_column("poll_averages", "content_hash")

    op.drop_constraint(op.f("pk_indicators"), "indicators", type_="primary")
    op.create_primary_key(op.f("pk_indicators"), "indicators", ["series_id", "asof"])

    # Fails loudly if any 'tossup' rows exist; there is no lossless mapping back.
    _swap_rating_check(RACE_RATING_OLD)
