from cluster_corpus import CPI_BLS, CPI_REACTION, NOMINATION
from graph_corpus import cluster_of, rate
from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.config import get_settings
from brokeberg.db.models import Event, EventRaceEdge
from brokeberg.graph.elections import link_races
from brokeberg.taxonomy import EdgeType, RaceRating, Topic

GA, ME, NC, MI, AK = "GA-SEN-2026", "ME-SEN-2026", "NC-SEN-2026", "MI-SEN-2026", "AK-SEN-2026"


def _links(db: Session, head: Event) -> dict[str, EventRaceEdge]:
    link_races(db, head, get_settings())
    return {
        e.race_id: e
        for e in db.scalars(select(EventRaceEdge).where(EventRaceEdge.event_id == head.id))
    }


def test_inflation_event_in_tossup_state_links_with_rationale(seeded_db: Session) -> None:
    rate(seeded_db, GA, RaceRating.TOSSUP)
    head = cluster_of(seeded_db, CPI_BLS, jurisdiction="fips:13")
    links = _links(seeded_db, head)
    assert set(links) == {GA}
    edge = links[GA]
    assert edge.relation == EdgeType.AFFECTS
    assert edge.matched_topics == [Topic.INFLATION_COST_OF_LIVING]
    assert "inflation_cost_of_living salient in GA-SEN-2026" in edge.rationale
    assert "tossup" in edge.rationale and "cook 2026-09-30" in edge.rationale
    assert "event jurisdiction fips:13" in edge.rationale
    assert edge.confidence == head.confidence  # tossup 1.0 x direct state 1.0


def test_safe_seat_state_does_not_link(seeded_db: Session) -> None:
    rate(seeded_db, ME, RaceRating.SAFE_D)
    head = cluster_of(seeded_db, CPI_BLS, jurisdiction="fips:23")
    assert _links(seeded_db, head) == {}


def test_non_salient_topic_does_not_link(seeded_db: Session) -> None:
    rate(seeded_db, GA, RaceRating.TOSSUP)
    head = cluster_of(seeded_db, NOMINATION, jurisdiction="fips:13")  # foreign policy
    assert _links(seeded_db, head) == {}


def test_federal_event_links_only_competitive_races(seeded_db: Session) -> None:
    rate(seeded_db, GA, RaceRating.TOSSUP)
    rate(seeded_db, NC, RaceRating.LEAN_R)
    rate(seeded_db, ME, RaceRating.SAFE_D)  # MI stays unrated
    head = cluster_of(seeded_db, CPI_BLS)  # jurisdiction 'federal'
    links = _links(seeded_db, head)
    assert set(links) == {GA, NC}
    s = get_settings()
    assert links[NC].confidence == head.confidence * s.race_rating_weight["lean"] * (
        s.race_match_weight["federal"]
    )
    assert "federal event" in links[GA].rationale


def test_politician_home_state_links(seeded_db: Session) -> None:
    rate(seeded_db, AK, RaceRating.LEAN_R)
    head = cluster_of(seeded_db, CPI_REACTION)  # Murkowski (AK), federal jurisdiction
    links = _links(seeded_db, head)
    assert "involves bioguide:M001153" in links[AK].rationale  # beats the federal match


def test_relink_is_idempotent(seeded_db: Session) -> None:
    rate(seeded_db, GA, RaceRating.TOSSUP)
    head = cluster_of(seeded_db, CPI_BLS, jurisdiction="fips:13")
    first = {k: (v.rationale, v.confidence) for k, v in _links(seeded_db, head).items()}
    second = {k: (v.rationale, v.confidence) for k, v in _links(seeded_db, head).items()}
    assert first == second
    rows = seeded_db.scalars(
        select(EventRaceEdge.id).where(EventRaceEdge.event_id == head.id)
    ).all()
    assert len(rows) == 1
