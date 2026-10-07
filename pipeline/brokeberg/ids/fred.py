"""FRED series IDs: normalize, validate, and check against the registered set."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.db.models import Entity
from brokeberg.ids.canonical import Namespace, is_valid, make


def normalize(series_id: str) -> str | None:
    """' cpiaucsl ' -> 'CPIAUCSL'; malformed -> None."""
    sid = series_id.strip().upper()
    return sid if is_valid(Namespace.FRED, sid) else None


def canonical(series_id: str) -> str | None:
    sid = normalize(series_id)
    return make(Namespace.FRED, sid) if sid else None


def is_registered(session: Session, series_id: str) -> bool:
    """True if the series was seeded as an EconomicIndicator entity."""
    cid = canonical(series_id)
    if cid is None:
        return False
    return session.scalar(select(Entity.id).where(Entity.canonical_id == cid)) is not None
