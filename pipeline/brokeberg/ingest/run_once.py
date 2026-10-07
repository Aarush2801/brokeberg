"""Run one ingestion cycle over every source: `python -m brokeberg.ingest.run_once [--replay]`.

Each source runs in its own transaction, so one failing source is logged and the rest still land.
`--replay` serves every HTTP call from the recorded cassettes (no network, no keys needed beyond
what `require()` checks) and pins `since` to the recording date.
"""

import argparse
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from brokeberg.db.session import session_scope
from brokeberg.ingest.base import Stats
from brokeberg.ingest.pipeline import write_raw
from brokeberg.ingest.replay import REPLAY_SINCE, cassette
from brokeberg.ingest.sources.bls import BlsLoader
from brokeberg.ingest.sources.congress import CongressConnector, SenateVotesConnector
from brokeberg.ingest.sources.fec import FecLoader
from brokeberg.ingest.sources.fred import FredLoader
from brokeberg.ingest.sources.ratings import RatingsLoader
from brokeberg.ingest.sources.x import RECORDED_ACCOUNTS, RECORDED_MAX_RESULTS, XConnector

log = logging.getLogger("brokeberg.ingest")

Job = Callable[[Session, datetime], Stats]


def _connector_job(connector: Any) -> Job:
    return lambda session, since: write_raw(session, connector, connector.fetch(session, since))


def jobs(replay: bool) -> dict[str, Job]:
    x = (
        XConnector(max_accounts=RECORDED_ACCOUNTS, max_results=RECORDED_MAX_RESULTS)
        if replay
        else XConnector()
    )
    return {
        "fred": FredLoader().load,
        "bls": BlsLoader().load,
        "congress": _connector_job(CongressConnector()),
        "senate_votes": _connector_job(SenateVotesConnector()),
        "fec": FecLoader().load,
        # Replay must hit the cassette, not a warm on-disk cache.
        "ratings": (RatingsLoader(cache_dir=None) if replay else RatingsLoader()).load,
        "x": _connector_job(x),
    }


def run(since: datetime, replay: bool = False, only: list[str] | None = None) -> list[Stats]:
    results = []
    for name, job in jobs(replay).items():
        if only and name not in only:
            continue
        ctx: AbstractContextManager[Any] = cassette(name) if replay else nullcontext()
        try:
            with ctx, session_scope() as session:
                stats = job(session, since)
        except Exception as exc:
            log.exception("ingest: %s failed", name)
            stats = Stats(source=name, note=f"FAILED: {type(exc).__name__}: {exc}"[:200])
        print(stats)
        results.append(stats)
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", action="store_true", help="serve HTTP from cassettes")
    parser.add_argument("--since", help="ISO date; default 7 days ago (replay: recording date)")
    parser.add_argument("--only", nargs="*", help="run only these sources")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.replay:
        since = REPLAY_SINCE
    elif args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
    else:
        since = datetime.now(UTC) - timedelta(days=7)
    run(since, replay=args.replay, only=args.only)


if __name__ == "__main__":
    main()
