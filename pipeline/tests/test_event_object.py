import re
from datetime import timedelta
from typing import Any

import pytest
from cluster_corpus import (
    CPI,
    CPI_BLS,
    CPI_NEWS,
    CPI_REACTION,
    MURKOWSKI,
    NOMINATION,
    T0,
    FakeEmbedder,
    add_member,
    entity_id,
    unit_vec,
)
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from brokeberg.cluster import embed_events
from brokeberg.cluster.cluster import cluster_entity_ids, cluster_pending
from brokeberg.cluster.embed_events import embed_pending
from brokeberg.cluster.event_object import (
    Synthesis,
    check_grounded,
    cluster_spans,
    heads,
    load_event_object,
    load_lexicon,
    materialize,
    mentioned_entities,
    numbers,
    synthesis_text,
)
from brokeberg.db.models import Event, EventEntity, EventLink, EventSource, ReviewQueue
from brokeberg.taxonomy import EventLinkType, EventType, Stance, Topic, TrustTier

JULY_CPI = "CPI rose 0.2 percent in July"
SENATOR_LATER = "Murkowski presses on prices after CPI report"


def echo_synthesis(prompt: str) -> Synthesis:
    """A well-behaved model: restates excerpt [1] verbatim."""
    first = re.search(r"^\[1\] (.+)$", prompt, re.M)
    assert first is not None
    return Synthesis(
        headline=first.group(1)[:80], what_happened=first.group(1), why_it_matters=None, cited=[1]
    )


@pytest.fixture
def corpus(
    seeded_db: Session, monkeypatch: pytest.MonkeyPatch, fake_llm: Any
) -> dict[str, Event]:
    """Clustered: Aug CPI (3 members), nomination, July CPI (prior), a later senator statement."""
    fake = FakeEmbedder()
    monkeypatch.setattr(embed_events, "embed", fake)
    fake.set(CPI_BLS.headline, unit_vec(1.0, 9))
    fake.set(CPI_NEWS.headline, unit_vec(0.95, 1))
    fake.set(CPI_REACTION.headline, unit_vec(0.90, 2))
    fake.set(NOMINATION.headline, unit_vec(0.0, 5))
    fake.set(JULY_CPI, unit_vec(0.90, 3))
    fake.set(SENATOR_LATER, unit_vec(0.80, 4))
    events = {
        "bls": add_member(seeded_db, CPI_BLS),
        "news": add_member(seeded_db, CPI_NEWS),
        "reaction": add_member(seeded_db, CPI_REACTION),
        "nomination": add_member(seeded_db, NOMINATION),
        "july": add_member(
            seeded_db, CPI_BLS, headline=JULY_CPI, url="https://www.bls.gov/july",
            span="The Consumer Price Index for All Urban Consumers increased 0.2 percent in July",
            event_time=T0 - timedelta(days=28),
        ),
        "later": add_member(
            seeded_db, CPI_REACTION, headline=SENATOR_LATER, url="https://x.com/later",
            span="Prices are still too high for Alaska families.", stances=[],
            event_time=T0 + timedelta(days=3),
        ),
    }
    embed_pending(seeded_db)
    cluster_pending(seeded_db)
    fake_llm.set(Synthesis, echo_synthesis)
    return events


def _materialize_all(db: Session) -> int:
    lexicon = load_lexicon(db)
    return sum(materialize(db, db.get(Event, h), lexicon) for h in heads(db))  # type: ignore[arg-type]


def test_rollup(seeded_db: Session, corpus: dict[str, Event]) -> None:
    _materialize_all(seeded_db)
    head = seeded_db.get(Event, corpus["bls"].cluster_id)
    assert head is not None

    sources = seeded_db.scalars(
        select(EventSource).where(EventSource.event_id == head.id).order_by(EventSource.id)
    ).all()
    assert {s.url for s in sources} == {CPI_BLS.url, CPI_NEWS.url, CPI_REACTION.url}
    assert sources[0].trust_tier == TrustTier.T1  # best trust first
    cpi_rows = seeded_db.scalars(
        select(EventEntity).where(
            EventEntity.event_id == head.id, EventEntity.entity_id == entity_id(seeded_db, CPI)
        )
    ).all()
    assert len(cpi_rows) == 1  # three members' CPI mentions deduped
    assert head.topics == sorted([Topic.INFLATION_COST_OF_LIVING, Topic.MONETARY_POLICY])
    assert head.event_time == T0
    assert head.event_type == EventType.ECONOMIC_RELEASE  # 2 of 3 members
    # trust-weighted mean: (1.0*0.95 + 0.6*0.85 + 0.4*0.8) / 2.0
    assert head.confidence == pytest.approx(0.89)


def test_grounded_synthesis_is_accepted(seeded_db: Session, corpus: dict[str, Event]) -> None:
    _materialize_all(seeded_db)
    head = seeded_db.get(Event, corpus["bls"].cluster_id)
    assert head is not None

    members = [corpus[k].id for k in ("bls", "news", "reaction")]
    spans = cluster_spans(seeded_db, members)
    assert head.headline == spans[0][:80]
    # The synthesis adds no number and no known entity absent from the cluster's spans.
    text = "\n".join(filter(None, (head.headline, head.what_happened, head.why_it_matters)))
    corpus_text = "\n".join(spans)
    assert numbers(text) <= numbers(corpus_text)
    ents = cluster_entity_ids(seeded_db, head.id)
    for surface, eid in mentioned_entities(text, load_lexicon(seeded_db)):
        assert eid in ents or surface in corpus_text
    assert seeded_db.scalar(select(func.count()).select_from(ReviewQueue)) == 0


@pytest.mark.parametrize(
    ("bad", "problem"),
    [
        (Synthesis(headline="CPI rose 0.6% in August", what_happened="CPI rose.",
                   why_it_matters=None, cited=[1]), "numbers not in spans"),
        (Synthesis(headline="Dan Sullivan reacts to CPI", what_happened="CPI rose.",
                   why_it_matters=None, cited=[1]), "entity not in cluster"),
        (Synthesis(headline="CPI rose", what_happened="CPI rose.", why_it_matters=None,
                   cited=[99]), "cited excerpts that do not exist"),
    ],
)
def test_ungrounded_synthesis_falls_back(
    seeded_db: Session, corpus: dict[str, Event], fake_llm: Any, bad: Synthesis, problem: str
) -> None:
    fake_llm.set(Synthesis, bad)
    head = seeded_db.get(Event, corpus["bls"].cluster_id)
    assert head is not None
    lexicon = load_lexicon(seeded_db)

    spans = cluster_spans(seeded_db, [corpus[k].id for k in ("bls", "news", "reaction")])
    problems = check_grounded(bad, spans, cluster_entity_ids(seeded_db, head.id), lexicon)
    assert any(problem in p for p in problems)

    materialize(seeded_db, head, lexicon)

    # Extractive fallback: the best-trust member's own fields, no why_it_matters.
    assert head.headline == CPI_BLS.headline
    assert head.what_happened == CPI_BLS.span
    assert head.why_it_matters is None
    assert synthesis_text(bad) not in (head.headline, head.what_happened)
    review = seeded_db.scalars(select(ReviewQueue).where(ReviewQueue.field == "event_object")).one()
    assert any(problem in p for p in review.payload["problems"])


def test_event_object_has_reactions_related_and_provenance(
    seeded_db: Session, corpus: dict[str, Event]
) -> None:
    _materialize_all(seeded_db)
    obj = load_event_object(seeded_db, corpus["bls"].cluster_id)  # type: ignore[arg-type]

    assert sorted(obj.member_event_ids) == sorted(corpus[k].id for k in ("bls", "news", "reaction"))
    assert {e.canonical_id for e in obj.entities} == {CPI, MURKOWSKI}
    assert len(obj.sources) == 3 and all(s.span and s.url for s in obj.sources)

    [reaction] = obj.political_reactions
    assert (reaction.canonical_id, reaction.topic, reaction.stance) == (
        MURKOWSKI, Topic.INFLATION_COST_OF_LIVING, Stance.OPPOSE,
    )
    assert reaction.span == "Alaska families are still squeezed."
    assert reaction.source_url == CPI_REACTION.url

    related = {(r.event_id, r.relation, r.direction) for r in obj.related_events}
    assert related == {
        (corpus["july"].cluster_id, EventLinkType.FOLLOWS, "prior"),
        (corpus["later"].cluster_id, EventLinkType.RESPONDS_TO, "later"),
    }
    # The unrelated nomination shares no entity: no link.
    assert corpus["nomination"].cluster_id not in {r.event_id for r in obj.related_events}


def test_rematerialize_is_idempotent(
    seeded_db: Session, corpus: dict[str, Event], fake_llm: Any
) -> None:
    assert _materialize_all(seeded_db) == 4
    counts = [
        seeded_db.scalar(select(func.count()).select_from(t))
        for t in (EventSource, EventEntity, EventLink)
    ]
    llm_calls = len(fake_llm.calls)

    assert _materialize_all(seeded_db) == 0
    assert len(fake_llm.calls) == llm_calls  # unchanged membership: no re-synthesis
    assert counts == [
        seeded_db.scalar(select(func.count()).select_from(t))
        for t in (EventSource, EventEntity, EventLink)
    ]


def test_new_member_rematerializes_only_its_head(
    seeded_db: Session, corpus: dict[str, Event], monkeypatch: pytest.MonkeyPatch
) -> None:
    _materialize_all(seeded_db)
    fake = FakeEmbedder()
    fake.set("Another CPI story", unit_vec(0.97, 6))
    monkeypatch.setattr(embed_events, "embed", fake)
    add_member(seeded_db, CPI_NEWS, headline="Another CPI story", url="https://ex.com/5")
    embed_pending(seeded_db)
    cluster_pending(seeded_db)

    assert _materialize_all(seeded_db) == 1
    obj = load_event_object(seeded_db, corpus["bls"].cluster_id)  # type: ignore[arg-type]
    assert len(obj.member_event_ids) == 4 and len(obj.sources) == 4
    links = seeded_db.scalar(select(func.count()).select_from(EventLink))
    assert links == 2  # relinking replaced, never duplicated


def test_one_event_object_per_cluster_with_all_member_sources(
    seeded_db: Session, corpus: dict[str, Event]
) -> None:
    _materialize_all(seeded_db)

    cluster_ids = set(
        seeded_db.scalars(select(Event.cluster_id).where(Event.cluster_id.is_not(None)))
    )
    per_cluster = dict(
        seeded_db.execute(
            text("SELECT cluster_id, count(*) FROM event_objects GROUP BY cluster_id")
        ).all()
    )
    assert per_cluster == {cid: 1 for cid in cluster_ids}  # exactly one head per cluster

    for head_id in cluster_ids:
        member_sources = set(
            seeded_db.execute(
                select(EventSource.url, EventSource.span)
                .join(Event, Event.id == EventSource.event_id)
                .where(Event.cluster_id == head_id, Event.id != head_id)
            ).all()
        )
        head_sources = set(
            seeded_db.execute(
                select(EventSource.url, EventSource.span).where(EventSource.event_id == head_id)
            ).all()
        )
        assert member_sources and head_sources == member_sources
