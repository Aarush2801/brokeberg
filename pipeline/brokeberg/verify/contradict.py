"""Stance flips: a head's stance on (entity, topic) against that entity's latest earlier stance.

A flip is a property of the entity's stance, not of the event's facts: it is marked on the head's
stance row (`event_entities.stance_flip`) and never touches `verification_status`. A material
flip crosses from the support side to the oppose side (or back), with both stances held at
confidence >= `verify_stance_min_conf`. Neutral is neither side, so drifting to or from it is not
a flip. Both stances stay stored; nothing is overwritten.
"""

from typing import Any

from sqlalchemy import and_, select, tuple_
from sqlalchemy.orm import Session, aliased

from brokeberg.config import Settings
from brokeberg.db.models import Event, EventEntity, EventSource, HeadEvent
from brokeberg.taxonomy import Stance

SUPPORT = frozenset({Stance.STRONGLY_SUPPORT, Stance.SUPPORT, Stance.LEAN_SUPPORT})
OPPOSE = frozenset({Stance.LEAN_OPPOSE, Stance.OPPOSE, Stance.STRONGLY_OPPOSE})


def side(stance: Stance | None) -> int:
    return 1 if stance in SUPPORT else -1 if stance in OPPOSE else 0


def is_flip(prior: Stance | None, new: Stance | None) -> bool:
    a, b = side(prior), side(new)
    return a != 0 and b != 0 and a != b


def stance_source(session: Session, row: EventEntity) -> EventSource | None:
    """The source of a head stance row: the best source of the member that carried its span."""
    member = aliased(Event)
    member_ee = aliased(EventEntity)
    return session.scalars(
        select(EventSource)
        .join(member, member.id == EventSource.event_id)
        .join(member_ee, and_(
            member_ee.event_id == member.id, member_ee.entity_id == row.entity_id,
            member_ee.role == row.role, member_ee.topic == row.topic, member_ee.span == row.span,
        ))
        .where(member.cluster_id == row.event_id, member.id != row.event_id)
        .order_by(EventSource.trust_tier, EventSource.id)
        .limit(1)
    ).first()


def _prior(session: Session, head: Event, row: EventEntity) -> tuple[EventEntity, Any] | None:
    found = session.execute(
        select(EventEntity, HeadEvent.event_time)
        .join(HeadEvent, HeadEvent.id == EventEntity.event_id)
        .where(
            EventEntity.entity_id == row.entity_id,
            EventEntity.topic == row.topic,
            EventEntity.stance.is_not(None),
            tuple_(HeadEvent.event_time, HeadEvent.id) < tuple_(head.event_time, head.id),
        )
        .order_by(HeadEvent.event_time.desc(), HeadEvent.id.desc())
        .limit(1)
    ).first()
    return (found[0], found[1]) if found else None


def mark_flips(session: Session, head: Event, settings: Settings) -> list[dict[str, Any]]:
    """Recompute `stance_flip` on every stance row of the head. Returns the flips marked."""
    flips = []
    for row in session.scalars(
        select(EventEntity)
        .where(EventEntity.event_id == head.id, EventEntity.stance.is_not(None))
        .order_by(EventEntity.entity_id, EventEntity.topic, EventEntity.role)
    ):
        flip = None
        if row.confidence >= settings.verify_stance_min_conf and side(row.stance) != 0:
            prior = _prior(session, head, row)
            if prior is not None:
                p, p_time = prior
                if p.confidence >= settings.verify_stance_min_conf and is_flip(
                    p.stance, row.stance
                ):
                    src = stance_source(session, p)
                    flip = {
                        "prior_event_id": p.event_id, "prior_event_time": p_time.isoformat(),
                        "prior_stance": p.stance, "prior_span": p.span,
                        "prior_source_url": src.url if src else None,
                    }
                    flips.append({
                        "entity_id": row.entity_id, "topic": row.topic, "stance": row.stance,
                        "span": row.span, **flip,
                    })
        if row.stance_flip != flip:
            row.stance_flip = flip
    session.flush()
    return flips
