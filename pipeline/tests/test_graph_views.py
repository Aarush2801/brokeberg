from datetime import date, timedelta
from decimal import Decimal

import pytest
from cluster_corpus import (
    CPI,
    CPI_BLS,
    CPI_NEWS,
    CPI_REACTION,
    MURKOWSKI,
    T0,
    entity_id,
)
from graph_corpus import GA, MURKOWSKI_EARLIER, build_graph
from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.config import get_settings
from brokeberg.db.models import Edge, Event, Indicator, Race
from brokeberg.graph import views
from brokeberg.graph.edges import neighborhood
from brokeberg.graph.run import head_ids, process_head
from brokeberg.graph.salience import election_day
from brokeberg.taxonomy import EdgeType, RaceRating, Stance, Topic, VerificationStatus

NOW = T0 + timedelta(hours=6)


@pytest.fixture
def graph(seeded_db: Session) -> dict[str, Event]:
    return build_graph(seeded_db)


def test_feed_is_salience_ranked_and_sourced(seeded_db: Session, graph: dict[str, Event]) -> None:
    rows = views.feed(seeded_db, now=NOW)
    ids = [r.event_id for r in rows]
    assert graph["stale"].id not in ids  # outside the window
    assert ids[0] == graph["cpi"].id  # fresh, 3 sources, fact-checked, race-linked
    assert set(ids) == {graph["cpi"].id, graph["nomination"].id, graph["earlier"].id}
    assert [r.salience for r in rows] == sorted((r.salience for r in rows), reverse=True)
    for r in rows:
        assert r.source_url and r.span
    top = rows[0]
    assert top.components["election"] > 0
    assert top.source_count == 3 and Topic.INFLATION_COST_OF_LIVING in top.topics
    assert top.source_url == CPI_BLS.url  # best-trust source first
    assert views.feed(seeded_db, limit=1, now=NOW)[0].event_id == top.event_id


def test_feed_never_shows_future_events(seeded_db: Session, graph: dict[str, Event]) -> None:
    rows = views.feed(seeded_db, now=T0 - timedelta(days=1))
    assert [r.event_id for r in rows] == [graph["earlier"].id]


def test_event_object_has_elections_sources_verification(
    seeded_db: Session, graph: dict[str, Event]
) -> None:
    obj = views.event_object(seeded_db, graph["cpi"].id)
    # Murkowski's reaction in this cluster flips her earlier stance: that shows on her reaction,
    # while the event's status reflects only its facts.
    assert obj.verification_status == VerificationStatus.FACT_CHECKED
    assert {c["result"] for c in obj.verification["numeric"]} == {"match"}
    [reaction] = obj.political_reactions
    assert reaction.canonical_id == MURKOWSKI and reaction.stance == Stance.OPPOSE
    assert reaction.flip is not None
    assert (reaction.flip.prior_event_id, reaction.flip.prior_stance) == (
        graph["earlier"].id, Stance.SUPPORT
    )
    assert reaction.flip.prior_source_url == MURKOWSKI_EARLIER.url
    assert obj.verification["independent_sources"] == 3
    assert {s.url for s in obj.sources} == {CPI_BLS.url, CPI_NEWS.url, CPI_REACTION.url}
    [ga] = [e for e in obj.affected_elections if e.race_id == GA]
    assert ga.rating == RaceRating.TOSSUP
    assert ga.rationale and ga.matched_topics == [Topic.INFLATION_COST_OF_LIVING]


def test_race_dossier(seeded_db: Session, graph: dict[str, Event]) -> None:
    d = views.race_dossier(seeded_db, GA)
    race = seeded_db.get(Race, GA)
    assert race is not None
    assert d.rating == RaceRating.TOSSUP
    assert d.election_day == date(2026, 11, 3)
    [h] = d.rating_history
    assert h.source_url.startswith("https://www.cookpolitical.com/")
    assert d.incumbent is not None
    assert d.incumbent.canonical_id == f"bioguide:{race.meta['incumbent_bioguide']}"
    assert d.poll_average is not None and d.poll_average.source_url
    # Both federal inflation events link; the nomination (foreign policy) does not.
    assert {e.event_id for e in d.linked_events} == {graph["cpi"].id, graph["earlier"].id}
    assert [e.confidence for e in d.linked_events] == sorted(
        (e.confidence for e in d.linked_events), reverse=True
    )
    for e in d.linked_events:
        assert e.rationale and e.source_url and e.span
    cpi = next(e for e in d.linked_events if e.event_id == graph["cpi"].id)
    assert cpi.source_url == CPI_BLS.url


def test_entity_dossier(seeded_db: Session, graph: dict[str, Event]) -> None:
    murkowski = entity_id(seeded_db, MURKOWSKI)
    d = views.entity_dossier(seeded_db, murkowski)
    assert d.entity.canonical_id == MURKOWSKI
    [stance] = d.stances  # latest on the topic: the CPI reaction
    assert (stance.event_id, stance.stance) == (graph["cpi"].id, Stance.OPPOSE)
    assert stance.source_url == CPI_REACTION.url
    assert stance.flip is not None
    assert [e.event_id for e in d.recent_events] == [graph["cpi"].id, graph["earlier"].id]
    assert all(e.source_url and e.span for e in d.recent_events)
    [rel] = d.relationships
    assert (rel.canonical_id, rel.relation, rel.direction) == (CPI, EdgeType.RESPONDS_TO, "out")
    assert rel.event_id == graph["cpi"].id and rel.source_url and rel.span


def test_stance_timeline(seeded_db: Session, graph: dict[str, Event]) -> None:
    rows = views.stance_timeline(
        seeded_db, entity_id(seeded_db, MURKOWSKI), Topic.INFLATION_COST_OF_LIVING
    )
    assert [(r.event_id, r.stance) for r in rows] == [
        (graph["earlier"].id, Stance.SUPPORT), (graph["cpi"].id, Stance.OPPOSE),
    ]
    assert [r.source_url for r in rows] == [MURKOWSKI_EARLIER.url, CPI_REACTION.url]
    assert rows[1].verification_status == VerificationStatus.FACT_CHECKED
    assert rows[0].flip is None
    assert rows[1].flip is not None and rows[1].flip.prior_event_id == graph["earlier"].id
    assert rows[1].flip.prior_span == MURKOWSKI_EARLIER.span
    assert all(r.span and r.intensity is not None for r in rows)
    assert views.stance_timeline(seeded_db, entity_id(seeded_db, MURKOWSKI), "healthcare") == []


def test_head_edges_dedupe_member_edges(seeded_db: Session, graph: dict[str, Event]) -> None:
    head_edges = seeded_db.scalars(
        select(Edge).where(Edge.event_id == graph["cpi"].id)
    ).all()
    assert len(head_edges) == 1
    assert head_edges[0].confidence == 0.8  # the stronger member's edge
    [n] = neighborhood(seeded_db, entity_id(seeded_db, CPI))
    assert (n.canonical_id, n.direction, n.edge_count) == (MURKOWSKI, "in", 1)


def test_graph_pass_is_idempotent(seeded_db: Session, graph: dict[str, Event]) -> None:
    before = [r.model_dump() for r in views.feed(seeded_db, now=NOW)]
    settings = get_settings()
    for hid in head_ids(seeded_db):
        head = seeded_db.get(Event, hid)
        assert head is not None
        process_head(seeded_db, head, settings)
    assert [r.model_dump() for r in views.feed(seeded_db, now=NOW)] == before


def test_election_day() -> None:
    assert election_day(2026) == date(2026, 11, 3)
    assert election_day(2028) == date(2028, 11, 7)


def test_ticker_yoy_level_and_sparse(seeded_db: Session) -> None:
    db = seeded_db
    obs = [
        # FRED has too little CPI history for YoY; BLS has the year-earlier months.
        ("CPIAUCSL", "fred", date(2026, 8, 1), "321.28"),
        ("CPIAUCSL", "bls", date(2025, 7, 1), "310.00"),
        ("CPIAUCSL", "bls", date(2025, 8, 1), "312.00"),
        ("CPIAUCSL", "bls", date(2026, 7, 1), "320.00"),
        ("CPIAUCSL", "bls", date(2026, 8, 1), "321.28"),
        ("UNRATE", "fred", date(2026, 8, 1), "4.1"),
        ("UNRATE", "fred", date(2026, 9, 1), "4.2"),
        ("PAYEMS", "fred", date(2026, 9, 1), "159044"),  # one level: no change to report
    ]
    for series_id, source, asof, value in obs:
        db.add(Indicator(series_id=series_id, asof=asof, source=source, value=Decimal(value)))
    db.flush()

    rows = {r.series_id: r for r in views.ticker(db)}
    assert set(rows) == {"CPIAUCSL", "UNRATE"}
    cpi = rows["CPIAUCSL"]
    assert (cpi.source, cpi.asof, cpi.transform) == ("bls", date(2026, 8, 1), "yoy")
    assert cpi.value == pytest.approx(round((321.28 / 312 - 1) * 100, 4))
    assert cpi.delta == pytest.approx(cpi.value - (320 / 310 - 1) * 100, abs=1e-3)
    assert cpi.source_url == "https://data.bls.gov/timeseries/CUSR0000SA0"
    assert "2025-08-01 = 312.00" in cpi.span
    un = rows["UNRATE"]
    assert (un.value, un.delta, un.source) == (4.2, pytest.approx(0.1), "fred")
    assert un.source_url == "https://fred.stlouisfed.org/series/UNRATE"
