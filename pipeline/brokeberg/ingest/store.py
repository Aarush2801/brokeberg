"""Idempotent writers for structured tables (indicators). Raw items go through `pipeline`."""

from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brokeberg.db.models import Indicator


class Observation(NamedTuple):
    series_id: str  # FRED series ID, un-namespaced
    asof: date
    value: Decimal


def upsert_indicators(session: Session, source: str, observations: list[Observation]) -> int:
    """Insert new observations and apply revisions. Returns rows written (new or revised);
    unchanged rows are not touched."""
    if not observations:
        return 0
    rows = [
        {"series_id": o.series_id, "asof": o.asof, "source": source, "value": o.value}
        for o in observations
    ]
    base = insert(Indicator).values(rows)
    stmt = base.on_conflict_do_update(
        index_elements=[Indicator.series_id, Indicator.asof, Indicator.source],
        set_={"value": base.excluded.value},
        where=Indicator.value.is_distinct_from(base.excluded.value),
    ).returning(Indicator.series_id)
    return len(session.execute(stmt).all())
