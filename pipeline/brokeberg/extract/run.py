"""Chain passes 0-5 over raw items and persist the result with provenance.

`python -m brokeberg.extract.run [--limit N] [--source x] [--raw-item-id ID]`

Idempotent: an item with an `extraction_runs` row is skipped unless that run failed. Each item
runs in its own savepoint, so one bad item never sinks the batch.
"""

import argparse
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brokeberg.db.models import (
    NO_TOPIC,
    Edge,
    Event,
    EventEntity,
    EventSource,
    ExtractionRun,
    ExtractionStatus,
    RawItem,
    ReviewQueue,
    ReviewStatus,
)
from brokeberg.db.session import session_scope
from brokeberg.extract.classify import Classification, classify
from brokeberg.extract.doc import (
    PROMPT_VERSION,
    REVIEW_THRESHOLD,
    ExtractState,
    ReviewItem,
    SourceDoc,
)
from brokeberg.extract.entities import EntitiesResult, entities
from brokeberg.extract.event_core import EventCore, event_core
from brokeberg.extract.gate import GateResult, gate
from brokeberg.extract.relationships import RelationshipsResult, relationships
from brokeberg.extract.stance import StancesResult, stance
from brokeberg.taxonomy import SOURCE_TRUST

log = logging.getLogger("brokeberg.extract")

Pass = Callable[[SourceDoc, ExtractState], BaseModel]

PASSES: tuple[tuple[str, Pass], ...] = (
    ("gate", gate),
    ("event_core", event_core),
    ("entities", entities),
    ("classify", classify),
    ("stance", stance),
    ("relationships", relationships),
)


@dataclass
class Extraction:
    status: ExtractionStatus
    state: ExtractState
    dropped_reason: str | None = None
    error: str | None = None

    def pass_outputs(self) -> dict[str, Any]:
        return {k: v.model_dump(mode="json") for k, v in self.state.outputs.items()}


def run_passes(session: Session, doc: SourceDoc) -> Extraction:
    """Run 0 -> 5 without persisting (the eval harness calls this directly).

    The only write is `entities` minting a Policy_Bill node from a structured bill ID.
    """
    state = ExtractState(session=session)
    for name, fn in PASSES:
        try:
            out = fn(doc, state)
        except Exception as e:  # noqa: BLE001 - any pass failure marks the item, never the batch
            log.warning("pass %s failed on %s: %s", name, doc.url, e)
            return Extraction(ExtractionStatus.FAILED, state, error=f"{name}: {e}")
        state.outputs[name] = out
        if isinstance(out, GateResult) and not out.relevant:
            if out.confidence < REVIEW_THRESHOLD:
                state.flag_low_confidence("gate", doc.url, out.confidence, out.model_dump())
            return Extraction(ExtractionStatus.DROPPED, state, dropped_reason=out.reason)
    return Extraction(ExtractionStatus.EXTRACTED, state)


def persist(session: Session, item: RawItem, doc: SourceDoc, state: ExtractState) -> int:
    """Write the event, its provenance, entity/stance rows, and edges. Returns the event id."""
    core = state.get("event_core", EventCore)
    cls = state.get("classify", Classification)
    ents = state.get("entities", EntitiesResult)
    stances = state.get("stance", StancesResult)
    rels = state.get("relationships", RelationshipsResult)

    what = " ".join(p for p in (core.actor_mention, core.action, core.object) if p)
    event = Event(
        event_type=core.event_type,
        headline=core.headline,
        what_happened=what or None,
        event_time=core.event_time or item.fetched_at,
        confidence=core.confidence,
        topics=[str(t) for t in cls.topics],
        policy_areas=[str(t) for t in cls.policy_areas],
        jurisdiction=core.jurisdiction_id,
    )
    session.add(event)
    session.flush()

    session.add(
        EventSource(
            event_id=event.id,
            raw_item_id=item.id,
            url=item.url,
            span=core.span,
            trust_tier=SOURCE_TRUST[item.source_type],
            claim=core.headline,
        )
    )
    for e in ents.resolved:
        assert e.entity_id is not None
        session.add(
            EventEntity(
                event_id=event.id, entity_id=e.entity_id, role=e.role, topic=NO_TOPIC,
                span=e.span, confidence=e.confidence,
            )
        )
    for s in stances.stances:
        session.add(
            EventEntity(
                event_id=event.id, entity_id=s.entity_id, role="actor", topic=str(s.topic),
                stance=s.position, intensity=s.intensity, span=s.verbatim_span,
                confidence=s.confidence,
            )
        )
    for r in rels.relations:
        session.add(
            Edge(
                src_entity=r.src_entity, relation=r.relation, dst_entity=r.dst_entity,
                rationale=r.rationale, confidence=r.confidence, event_id=event.id,
            )
        )
    session.flush()
    return event.id


def write_review(session: Session, raw_item_id: int, items: list[ReviewItem]) -> None:
    for r in items:
        session.execute(
            insert(ReviewQueue)
            .values(raw_item_id=raw_item_id, **r.model_dump())
            .on_conflict_do_nothing(constraint="uq_review_queue_item_kind_mention_field")
        )


def _record_run(session: Session, item: RawItem, ex: Extraction, event_id: int | None) -> None:
    values = {
        "raw_item_id": item.id,
        "content_hash": item.content_hash,
        "status": ex.status,
        "dropped_reason": ex.dropped_reason,
        "error": ex.error,
        "pass_outputs": ex.pass_outputs(),
        "prompt_version": PROMPT_VERSION,
        "event_id": event_id,
    }
    stmt = insert(ExtractionRun).values(values)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[ExtractionRun.raw_item_id],
            set_={k: stmt.excluded[k] for k in values if k != "raw_item_id"},
        )
    )


def extract_item(session: Session, item: RawItem) -> ExtractionStatus | None:
    """Extract and persist one raw item. None if it was already done (idempotent skip)."""
    prior = session.scalar(
        select(ExtractionRun.status).where(ExtractionRun.raw_item_id == item.id)
    )
    if prior is not None and prior != ExtractionStatus.FAILED:
        return None

    doc = SourceDoc.from_raw_item(item)
    savepoint = session.begin_nested()
    ex = run_passes(session, doc)
    event_id = None
    try:
        if ex.status == ExtractionStatus.EXTRACTED:
            event_id = persist(session, item, doc, ex.state)
        if ex.status != ExtractionStatus.FAILED:
            write_review(session, item.id, ex.state.review)
        savepoint.commit()
    except Exception as e:  # noqa: BLE001 - a persist failure marks the item, never the batch
        savepoint.rollback()
        log.warning("persist failed on %s: %s", item.url, e)
        ex = Extraction(ExtractionStatus.FAILED, ex.state, error=f"persist: {e}")
        event_id = None
    _record_run(session, item, ex, event_id)
    return ex.status


def pending(
    session: Session, *, source: str | None, raw_item_id: int | None, limit: int | None
) -> list[RawItem]:
    q = (
        select(RawItem)
        .outerjoin(ExtractionRun, ExtractionRun.raw_item_id == RawItem.id)
        .where(or_(ExtractionRun.id.is_(None), ExtractionRun.status == ExtractionStatus.FAILED))
        .order_by(RawItem.id)
    )
    if source:
        q = q.where(RawItem.source == source)
    if raw_item_id is not None:
        q = q.where(RawItem.id == raw_item_id)
    if limit:
        q = q.limit(limit)
    return list(session.scalars(q))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--source", default=None)
    parser.add_argument("--raw-item-id", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with session_scope() as session:
        ids = [
            i.id
            for i in pending(
                session, source=args.source, raw_item_id=args.raw_item_id, limit=args.limit
            )
        ]
    counts: dict[str, int] = {}
    for raw_id in ids:
        with session_scope() as session:  # one transaction per item
            item = session.get(RawItem, raw_id)
            assert item is not None
            status = extract_item(session, item)
        key = status.value if status else "skipped"
        counts[key] = counts.get(key, 0) + 1
        print(f"raw_item {raw_id:<6} {key}")
    with session_scope() as session:
        review_open = session.scalar(
            select(func.count())
            .select_from(ReviewQueue)
            .where(ReviewQueue.status == ReviewStatus.OPEN)
        )
    print(f"done: {counts or 'nothing pending'}; open review_queue rows: {review_open}")


if __name__ == "__main__":
    main()
