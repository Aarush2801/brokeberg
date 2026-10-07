"""Member of Congress mention/handle -> bioguide ID (via seeded Politician entities)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.db.models import Entity
from brokeberg.ids.canonical import Namespace, is_valid, make
from brokeberg.ids.resolve import ResolveResult, resolve
from brokeberg.taxonomy import EntityType


def resolve_member(session: Session, mention: str) -> ResolveResult:
    """'Sen. Jon Ossoff' | '@ossoff' | 'Ossoff (D-GA)' -> the member's entity, or None."""
    return resolve(session, mention, EntityType.POLITICIAN)


def by_bioguide(session: Session, bioguide_id: str) -> Entity | None:
    """Exact lookup by raw bioguide ID ('O000174')."""
    raw = bioguide_id.strip().upper()
    if not is_valid(Namespace.BIOGUIDE, raw):
        return None
    cid = make(Namespace.BIOGUIDE, raw)
    return session.scalar(select(Entity).where(Entity.canonical_id == cid))
