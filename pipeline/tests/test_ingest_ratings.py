import json
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.db.models import Race, RaceRatingHistory
from brokeberg.db.seed import seed
from brokeberg.ingest import http
from brokeberg.ingest.replay import REPLAY_SINCE, cassette
from brokeberg.ingest.sources.ratings import Page, RatingsLoader, parse_inside_elections
from brokeberg.taxonomy import RaceRating


def test_inside_elections_labels_map_explicitly() -> None:
    body = json.dumps({"ratings": [
        {"district": "TX", "rating": "Tilt Republican", "date": "2026-10-01T13:23:00-05:00"},
        {"district": "ME", "rating": "Toss-up", "date": "2026-09-01T10:00:00-05:00"},
        {"district": "GA", "rating": "Something New", "date": "2026-09-01T10:00:00-05:00"},
    ]})
    out = parse_inside_elections(Page(body, datetime.now(UTC)))
    assert [(r.state, r.rating, r.asof) for r in out] == [
        ("TX", RaceRating.TOSSUP_R, date(2026, 10, 1)),
        ("ME", RaceRating.TOSSUP, date(2026, 9, 1)),
    ]  # the unknown label is skipped, not guessed


def test_ratings_load_sourced_history_and_current_rating(
    db_session: Session, tmp_path: Path
) -> None:
    seed(db_session)
    http.clear_robots_cache()
    with cassette("ratings"):
        first = RatingsLoader(cache_dir=tmp_path).load(db_session, REPLAY_SINCE)
    assert first.inserted > 0
    assert "sabato" in first.note  # refused by robots.txt (bot challenge), skipped

    rows = db_session.scalars(select(RaceRatingHistory)).all()
    assert {r.rater for r in rows} == {"cook", "inside_elections"}
    assert all(r.source_url.startswith("https://") for r in rows)
    # Only the 10 MVP races are kept, each rated by both raters.
    assert len({r.race_id for r in rows}) == 10

    # Every current rating comes from a sourced history row.
    for race in db_session.scalars(select(Race)):
        assert race.rating in {r.rating for r in rows if r.race_id == race.id}

    # Second run is served from the on-disk cache (no cassette needed) and writes nothing.
    again = RatingsLoader(cache_dir=tmp_path).load(db_session, REPLAY_SINCE)
    assert (again.inserted, again.skipped) == (0, first.fetched)
