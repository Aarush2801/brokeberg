"""Typed entity edges on event objects, and one-hop neighborhood queries.

Pass 5 writes edges on member events (raw extraction output, like member `event_sources`). The
graph's edges live on the cluster head: one per (src, relation, dst) per head, the best-confidence
member's rationale, `event_id` = the head, whose sources are the edge's provenance.
"""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brokeberg.db.models import Edge, Entity, Event, EventSource, HeadEvent
from brokeberg.taxonomy import EdgeType, TrustTier


def rollup_edges(session: Session, head_id: int) -> int:
    """Rebuild the head's edges from its members. Returns the number of edges."""
    session.execute(delete(Edge).where(Edge.event_id == head_id))
    best: dict[tuple[int, EdgeType, int], Edge] = {}
    for e in session.scalars(
        select(Edge)
        .join(Event, Event.id == Edge.event_id)
        .where(Event.cluster_id == head_id, Event.id != head_id)
        .order_by(Edge.id)
    ):
        key = (e.src_entity, e.relation, e.dst_entity)
        if key not in best or e.confidence > best[key].confidence:
            best[key] = e
    for (src, relation, dst), e in best.items():
        session.execute(
            insert(Edge)
            .values(
                src_entity=src, relation=relation, dst_entity=dst, rationale=e.rationale,
                confidence=e.confidence, event_id=head_id,
            )
            .on_conflict_do_nothing(constraint="uq_edges_src_relation_dst_event")
        )
    session.flush()
    return len(best)


class Neighbor(BaseModel):
    """One (direction, relation, neighbor) group, with its latest supporting event's provenance."""

    entity_id: int
    canonical_id: str
    name: str
    entity_type: str
    relation: EdgeType
    direction: str  # "out": entity -> neighbor; "in": neighbor -> entity
    edge_count: int
    confidence: float
    rationale: str | None
    event_id: int
    event_time: datetime
    source_url: str
    span: str
    trust_tier: TrustTier


def neighborhood(session: Session, entity_id: int) -> list[Neighbor]:
    """One-hop relationships of an entity, over head edges only (members never double-count)."""
    rows = session.execute(
        select(Edge, HeadEvent.event_time)
        .join(HeadEvent, HeadEvent.id == Edge.event_id)
        .where(or_(Edge.src_entity == entity_id, Edge.dst_entity == entity_id))
        .order_by(HeadEvent.event_time.desc(), Edge.id.desc())
    ).all()
    groups: dict[tuple[str, EdgeType, int], list[tuple[Edge, datetime]]] = {}
    for edge, t in rows:
        out = edge.src_entity == entity_id
        other = edge.dst_entity if out else edge.src_entity
        groups.setdefault(("out" if out else "in", edge.relation, other), []).append((edge, t))
    if not groups:
        return []

    others = {k[2] for k in groups}
    ents = {e.id: e for e in session.scalars(select(Entity).where(Entity.id.in_(others)))}
    latest_events = {g[0][0].event_id for g in groups.values() if g[0][0].event_id is not None}
    source: dict[int, EventSource] = {}
    for s in session.scalars(
        select(EventSource)
        .where(EventSource.event_id.in_(latest_events))
        .order_by(EventSource.trust_tier, EventSource.id)
    ):
        source.setdefault(s.event_id, s)

    result = []
    for (direction, relation, other), edges in groups.items():
        latest, t = edges[0]
        src = source.get(latest.event_id) if latest.event_id is not None else None
        if src is None or latest.event_id is None:  # no provenance, no claim
            continue
        strongest = max(edges, key=lambda et: et[0].confidence)[0]
        ent = ents[other]
        result.append(Neighbor(
            entity_id=ent.id, canonical_id=ent.canonical_id, name=ent.name,
            entity_type=ent.entity_type, relation=relation, direction=direction,
            edge_count=len(edges), confidence=strongest.confidence,
            rationale=strongest.rationale, event_id=latest.event_id, event_time=t,
            source_url=src.url, span=src.span, trust_tier=src.trust_tier,
        ))
    return sorted(result, key=lambda n: (-n.confidence, -n.edge_count, n.name, n.relation))
