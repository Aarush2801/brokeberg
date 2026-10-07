"""Embed each member event (headline + key spans) into `event_embeddings`."""

import hashlib

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brokeberg.config import get_settings
from brokeberg.db.models import Event, EventEmbedding, EventEntity, EventSource
from brokeberg.embed import embed

# bge-large truncates at 512 tokens; the headline and the core span come first, so they survive.
MAX_CHARS = 2000
BATCH = 32


def is_member() -> ColumnElement[bool]:
    """SQL predicate: not a cluster head (unclustered, or pointing at another row)."""
    return or_(Event.cluster_id.is_(None), Event.cluster_id != Event.id)


def embed_text(session: Session, event: Event) -> str:
    """Headline, then the event's source spans, then distinct entity spans; deterministic order."""
    parts = [event.headline]
    parts += session.scalars(
        select(EventSource.span).where(EventSource.event_id == event.id).order_by(EventSource.id)
    ).all()
    parts += session.scalars(
        select(EventEntity.span)
        .where(EventEntity.event_id == event.id)
        .order_by(EventEntity.entity_id, EventEntity.role, EventEntity.topic)
    ).all()
    return "\n".join(dict.fromkeys(parts))[:MAX_CHARS]


def text_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


def embed_pending(session: Session, limit: int | None = None) -> int:
    """Embed member events with no embedding, or one from a different model. Returns the count."""
    model = get_settings().embed_model
    q = (
        select(Event)
        .outerjoin(EventEmbedding, EventEmbedding.event_id == Event.id)
        .where(
            is_member(),
            or_(
                EventEmbedding.event_id.is_(None),
                EventEmbedding.embed_model.is_distinct_from(model),
            ),
        )
        .order_by(Event.id)
    )
    if limit:
        q = q.limit(limit)
    events = list(session.scalars(q))
    for i in range(0, len(events), BATCH):
        batch = events[i : i + BATCH]
        texts = [embed_text(session, e) for e in batch]
        for event, text, vector in zip(batch, texts, embed(texts), strict=True):
            stmt = insert(EventEmbedding).values(
                event_id=event.id, embedding=vector, embed_model=model,
                text_hash=text_hash(model, text),
            )
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[EventEmbedding.event_id],
                    set_={
                        "embedding": stmt.excluded.embedding,
                        "embed_model": stmt.excluded.embed_model,
                        "text_hash": stmt.excluded.text_hash,
                    },
                )
            )
    session.flush()
    return len(events)
