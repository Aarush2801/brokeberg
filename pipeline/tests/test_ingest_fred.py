from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.db.models import Indicator
from brokeberg.db.seed_data.fred_series import SERIES
from brokeberg.ingest.replay import REPLAY_SINCE, cassette
from brokeberg.ingest.sources.fred import FredLoader, parse_observations


def test_parse_skips_missing_values() -> None:
    obs = parse_observations(
        "DGS10",
        {"observations": [{"date": "2026-09-01", "value": "4.1"},
                          {"date": "2026-09-02", "value": "."}]},
    )
    assert [(o.series_id, o.asof.isoformat(), o.value) for o in obs] == [
        ("DGS10", "2026-09-01", Decimal("4.1"))
    ]


def test_fred_loads_every_seeded_series_idempotently(db_session: Session) -> None:
    with cassette("fred"):
        first = FredLoader().load(db_session, REPLAY_SINCE)
    assert first.inserted > 0 and first.inserted == first.fetched

    rows = db_session.scalars(select(Indicator).where(Indicator.source == "fred")).all()
    assert {r.series_id for r in rows} == {s.series_id for s in SERIES}
    assert all(r.series_id == r.series_id.upper() for r in rows)  # FRED IDs, un-namespaced

    with cassette("fred"):
        again = FredLoader().load(db_session, REPLAY_SINCE)
    assert (again.inserted, again.skipped) == (0, first.fetched)
