"""Fixture corpus for verification / graph tests: clustered heads, indicator data, race ratings.

Heads are built through the real `new_head` + `rollup` path (no LLM), so their sources and
stance rows are exactly what clustering would roll up from the members.
"""

from datetime import date, timedelta
from decimal import Decimal

from cluster_corpus import (
    CPI,
    CPI_BLS,
    CPI_NEWS,
    CPI_REACTION,
    MURKOWSKI,
    NOMINATION,
    T0,
    Item,
    add_member,
    entity_id,
)
from sqlalchemy.orm import Session

from brokeberg.cluster.cluster import new_head
from brokeberg.cluster.event_object import rollup
from brokeberg.config import get_settings
from brokeberg.db.models import Edge, Event, Indicator, PollAverage, Race, RaceRatingHistory
from brokeberg.graph.run import head_ids, process_head
from brokeberg.taxonomy import EdgeType, EventType, RaceRating, SourceType, Stance, Topic

JUL, AUG = date(2026, 7, 1), date(2026, 8, 1)
# 320.000 -> 321.280 is +0.4% m/m: what the BLS/news/senator spans in `cluster_corpus` claim.
CPI_JUL, CPI_AUG = Decimal("320.000"), Decimal("321.280")

WRONG_CPI_POST = Item(
    headline="CPI jumped 0.9% in August",
    span="BREAKING: CPI jumped 0.9% in August, the worst reading in years",
    url="https://x.com/econ_hot_takes/status/1966000000000000099",
    source_type=SourceType.SOCIAL_POST,
    event_type=EventType.STATEMENT,
    event_time=T0.replace(hour=14),
    entities=[(CPI, "subject", "CPI")],
    topics=[Topic.INFLATION_COST_OF_LIVING],
    confidence=0.7,
)
MURKOWSKI_EARLIER = Item(
    headline="Murkowski backs administration plan on prices",
    span="I support the administration's plan to bring down grocery prices",
    url="https://www.murkowski.senate.gov/press/release/prices-plan",
    source_type=SourceType.OFFICIAL_STATEMENT,
    event_type=EventType.STATEMENT,
    event_time=T0 - timedelta(days=5),
    entities=[(MURKOWSKI, "actor", "Murkowski")],
    topics=[Topic.INFLATION_COST_OF_LIVING],
    stances=[(MURKOWSKI, Topic.INFLATION_COST_OF_LIVING, Stance.SUPPORT,
              "I support the administration's plan to bring down grocery prices")],
)


def make_head(db: Session, *ms: Event) -> Event:
    """Cluster the given members under one head and roll them up."""
    head = new_head(db, ms[0])
    for m in ms[1:]:
        m.cluster_id = head.id
    db.flush()
    rollup(db, head, list(ms))
    return head


def cluster_of(
    db: Session, *items: Item, jurisdiction: str | None = None, **overrides: object
) -> Event:
    """One cluster of fresh members; `jurisdiction` replaces the fixture default ('federal')."""
    ms = [add_member(db, it, **overrides) for it in items]
    if jurisdiction is not None:
        for m in ms:
            m.jurisdiction = jurisdiction
    return make_head(db, *ms)


def seed_cpi(
    db: Session, *, jul: Decimal = CPI_JUL, aug: Decimal = CPI_AUG, bls_aug: Decimal | None = None
) -> None:
    for source in ("fred", "bls"):
        db.add(Indicator(series_id="CPIAUCSL", asof=JUL, source=source, value=jul))
        value = bls_aug if source == "bls" and bls_aug is not None else aug
        db.add(Indicator(series_id="CPIAUCSL", asof=AUG, source=source, value=value))
    db.flush()


def rate(db: Session, race_id: str, rating: RaceRating, asof: date = date(2026, 9, 30)) -> None:
    """A sourced rating row, and the race's current rating from it (as the ratings loader does)."""
    db.add(RaceRatingHistory(
        race_id=race_id, rater="cook", rating=rating, asof=asof,
        source_url=f"https://www.cookpolitical.com/ratings/senate/{race_id}",
    ))
    race = db.get(Race, race_id)
    assert race is not None
    race.rating = rating
    db.flush()


def add_member_edge(
    db: Session, member: Event, src: str, relation: EdgeType, dst: str, confidence: float
) -> None:
    """A pass-5 edge on a member event."""
    db.add(Edge(
        src_entity=entity_id(db, src), relation=relation, dst_entity=entity_id(db, dst),
        rationale=f"fixture {relation}", confidence=confidence, event_id=member.id,
    ))
    db.flush()


GA = "GA-SEN-2026"


def build_graph(db: Session) -> dict[str, Event]:
    """CPI cluster (3 sources, linked to GA), a nomination, Murkowski's earlier stance, a stale
    event outside the feed window; then the full graph pass over every head."""
    seed_cpi(db)
    rate(db, GA, RaceRating.TOSSUP)
    db.add(PollAverage(
        race_id=GA, value=1.5, asof=date(2026, 9, 28),
        source_url="https://example.org/polls/ga-sen-2026", meta={"leader": "D"},
        content_hash="ga-poll-1",
    ))

    cpi_members = [add_member(db, it) for it in (CPI_BLS, CPI_NEWS, CPI_REACTION)]
    # Pass 5 found the same edge in two members: the head must carry it once.
    for m, conf in ((cpi_members[1], 0.6), (cpi_members[2], 0.8)):
        add_member_edge(db, m, MURKOWSKI, EdgeType.RESPONDS_TO, CPI, conf)
    out = {
        "earlier": make_head(db, add_member(db, MURKOWSKI_EARLIER)),
        "cpi": make_head(db, *cpi_members),
        "nomination": make_head(db, add_member(db, NOMINATION)),
        "stale": make_head(db, add_member(
            db, NOMINATION, headline="An old vote", event_time=T0 - timedelta(days=40)
        )),
    }
    settings = get_settings()
    for hid in head_ids(db):
        head = db.get(Event, hid)
        assert head is not None
        process_head(db, head, settings)
    return out
