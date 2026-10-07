"""Candidate / committee mention -> FEC-linked entity.

An incumbent is one node: their entity is a Politician keyed by bioguide, with FEC candidate IDs
in `aliases` and `meta.fec_ids`. So candidate resolution searches Candidate and Politician nodes.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.db.models import Entity
from brokeberg.ids.canonical import Namespace, is_valid, make
from brokeberg.ids.resolve import ResolveResult, resolve
from brokeberg.taxonomy import EntityType


def resolve_candidate(session: Session, mention: str) -> ResolveResult:
    return resolve(session, mention, [EntityType.CANDIDATE, EntityType.POLITICIAN])


def resolve_committee(session: Session, mention: str) -> ResolveResult:
    return resolve(session, mention, [EntityType.COMMITTEE, EntityType.INTEREST_GROUP_PAC])


def by_fec_id(session: Session, fec_id: str) -> Entity | None:
    """Exact lookup by FEC candidate/committee ID: its own node, else the incumbent holding it."""
    raw = fec_id.strip().upper()
    if not is_valid(Namespace.FEC, raw):
        return None
    own = session.scalar(select(Entity).where(Entity.canonical_id == make(Namespace.FEC, raw)))
    if own is not None:
        return own
    return session.scalar(
        select(Entity).where(Entity.meta["fec_ids"].contains([raw])).limit(1)
    )
