from typing import Any

from extract_docs import x_post
from sqlalchemy import func, select
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
)
from brokeberg.extract.classify import Classification
from brokeberg.extract.doc import SourceDoc
from brokeberg.extract.entities import MentionLLM, MentionsLLM
from brokeberg.extract.event_core import EventCoreLLM
from brokeberg.extract.gate import GateResult
from brokeberg.extract.relationships import RelationsLLM
from brokeberg.extract.run import extract_item
from brokeberg.extract.stance import StanceLLM, StancesResult
from brokeberg.ingest.base import RawRecord
from brokeberg.ingest.pipeline import write_raw
from brokeberg.taxonomy import SourceType, Stance, Topic, TrustTier


class _X:
    source = "x"
    source_type = SourceType.SOCIAL_POST


def _raw_item(db: Session, doc: SourceDoc) -> RawItem:
    write_raw(
        db, _X(),
        [RawRecord(url=doc.url, text=doc.body, event_time=doc.event_time, raw_payload=doc.raw,
                   entity_ids=doc.resolved)],
    )
    item = db.scalar(select(RawItem).where(RawItem.url == doc.url))
    assert item is not None
    return item


def _script(fake_llm: Any, author_id: int) -> None:
    fake_llm.set(GateResult, GateResult(relevant=True, reason="tariffs", confidence=0.95))
    fake_llm.set(
        EventCoreLLM,
        EventCoreLLM(
            event_type="statement", headline="Murkowski to vote against lumber tariff extension",
            actor_mention="@LisaMurkowski", action="will vote against",
            object="extending lumber tariffs", event_time=None, jurisdiction="federal",
            span="I will vote against extending them.", confidence=0.9,
        ),
    )
    fake_llm.set(
        MentionsLLM,
        MentionsLLM(
            mentions=[
                MentionLLM(mention="Sen. Chuck Schumer", entity_type="Politician",
                           role="target", span="Sen. Chuck Schumer", confidence=0.9),
                MentionLLM(mention="Sen. Nobody Fakename", entity_type="Politician",
                           role="mentioned", span="Sen. Nobody Fakename", confidence=0.9),
            ]
        ),
    )
    fake_llm.set(
        Classification,
        Classification(topics=[Topic.TRADE_TARIFFS, Topic.HOUSING], policy_areas=[],
                       jurisdiction_level="federal", election_relevance=0.2, confidence=0.9),
    )
    fake_llm.set(
        StancesResult,
        StancesResult(
            stances=[
                StanceLLM(entity_id=author_id, topic=Topic.TRADE_TARIFFS,
                          position=Stance.STRONGLY_OPPOSE, intensity=0.8,
                          verbatim_span="Tariffs on Canadian lumber are a tax on Alaska families",
                          confidence=0.85),
                StanceLLM(entity_id=author_id, topic=Topic.HOUSING, position=Stance.LEAN_SUPPORT,
                          intensity=0.3, verbatim_span="Alaska families building homes",
                          confidence=0.5),
            ]
        ),
    )
    fake_llm.set(RelationsLLM, RelationsLLM(relations=[]))


def _author_id(db: Session) -> int:
    from brokeberg.ids import bioguide

    e = bioguide.by_bioguide(db, "M001153")
    assert e is not None
    return e.id


def test_full_chain_persists_grounded_records(seeded_db: Session, fake_llm: Any) -> None:
    doc = SourceDoc.build(
        source="x", source_type=SourceType.SOCIAL_POST, url=x_post().url,
        body=x_post().body.replace("Schumer", "Schumer and Sen. Nobody Fakename"),
        event_time=x_post().event_time, raw=x_post().raw, resolved=x_post().resolved,
    )
    item = _raw_item(seeded_db, doc)
    author = _author_id(seeded_db)
    _script(fake_llm, author)

    assert extract_item(seeded_db, item) == ExtractionStatus.EXTRACTED
    run = seeded_db.scalar(select(ExtractionRun).where(ExtractionRun.raw_item_id == item.id))
    assert run is not None and run.event_id is not None
    assert set(run.pass_outputs) == {
        "gate", "event_core", "entities", "classify", "stance", "relationships"
    }

    event = seeded_db.get(Event, run.event_id)
    assert event is not None and event.jurisdiction == "federal"
    assert event.topics == ["trade_tariffs", "housing"]
    src = seeded_db.scalars(select(EventSource).where(EventSource.event_id == event.id)).one()
    assert src.span == "I will vote against extending them." and src.trust_tier == TrustTier.T4

    rows = seeded_db.scalars(select(EventEntity).where(EventEntity.event_id == event.id)).all()
    mentions = {(r.entity_id, r.role) for r in rows if r.topic == NO_TOPIC}
    assert (author, "author") in mentions and len(mentions) == 2  # author + Schumer
    stances = {(r.topic, r.stance) for r in rows if r.topic != NO_TOPIC}
    assert stances == {
        ("trade_tariffs", Stance.STRONGLY_OPPOSE), ("housing", Stance.LEAN_SUPPORT)
    }
    assert all(r.span and 0 <= r.confidence <= 1 for r in rows)

    review = seeded_db.scalars(
        select(ReviewQueue).where(ReviewQueue.raw_item_id == item.id)
    ).all()
    assert {(r.kind.value, r.field) for r in review} == {
        ("unresolved_mention", "entities"),  # Nobody Fakename
        ("low_confidence", "stance:housing"),  # 0.5 < threshold
    }


def _counts(db: Session) -> tuple[int, ...]:
    return tuple(
        db.scalar(select(func.count()).select_from(m)) or 0
        for m in (Event, EventSource, EventEntity, Edge, ReviewQueue, ExtractionRun)
    )


def test_second_run_is_a_noop(seeded_db: Session, fake_llm: Any) -> None:
    item = _raw_item(seeded_db, x_post())
    _script(fake_llm, _author_id(seeded_db))
    assert extract_item(seeded_db, item) == ExtractionStatus.EXTRACTED
    before, calls = _counts(seeded_db), len(fake_llm.calls)
    assert extract_item(seeded_db, item) is None
    assert _counts(seeded_db) == before
    assert len(fake_llm.calls) == calls  # no LLM spend on a re-run


def test_failed_pass_is_recorded_then_retried(seeded_db: Session, fake_llm: Any) -> None:
    item = _raw_item(seeded_db, x_post())
    _script(fake_llm, _author_id(seeded_db))
    fake_llm.set(MentionsLLM, lambda _prompt: (_ for _ in ()).throw(RuntimeError("boom")))
    assert extract_item(seeded_db, item) == ExtractionStatus.FAILED
    run = seeded_db.scalar(select(ExtractionRun).where(ExtractionRun.raw_item_id == item.id))
    assert run is not None and run.error == "entities: boom" and run.event_id is None
    assert seeded_db.scalar(select(func.count()).select_from(Event)) == 0

    _script(fake_llm, _author_id(seeded_db))
    assert extract_item(seeded_db, item) == ExtractionStatus.EXTRACTED
