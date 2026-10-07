from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.db.models import Indicator
from brokeberg.ingest.replay import REPLAY_SINCE, cassette
from brokeberg.ingest.sources.bls import BLS_TO_FRED, BlsLoader, parse_series


def test_parse_maps_to_fred_ids_and_skips_annual() -> None:
    payload = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {"series": [{"seriesID": "LNS14000000", "data": [
            {"year": "2026", "period": "M08", "value": "4.3"},
            {"year": "2025", "period": "M13", "value": "4.1"},
            {"year": "2026", "period": "M07", "value": "-"},
        ]}]},
    }
    [obs] = parse_series(payload)
    assert (obs.series_id, obs.asof) == ("UNRATE", date(2026, 8, 1))


def test_bls_loads_under_fred_ids_idempotently(db_session: Session) -> None:
    with cassette("bls"):
        first = BlsLoader().load(db_session, REPLAY_SINCE)
    assert first.inserted > 0

    rows = db_session.scalars(select(Indicator).where(Indicator.source == "bls")).all()
    assert {r.series_id for r in rows} == set(BLS_TO_FRED.values())

    with cassette("bls"):
        again = BlsLoader().load(db_session, REPLAY_SINCE)
    assert again.inserted == 0
