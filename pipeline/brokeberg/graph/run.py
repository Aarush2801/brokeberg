"""Edges -> verify -> election links, for every event object.

`python -m brokeberg.graph.run`

Heads go oldest first, so the stance-flip check sees every earlier stance. Each step rebuilds
its own rows for the head, so re-running is idempotent. One transaction per head, so one failure
never sinks the batch.
"""

import argparse
import logging
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.config import Settings, get_settings
from brokeberg.db.models import Event, HeadEvent
from brokeberg.db.session import session_scope
from brokeberg.graph.edges import rollup_edges
from brokeberg.graph.elections import link_races
from brokeberg.verify.run import verify_head

log = logging.getLogger("brokeberg.graph")


def head_ids(session: Session) -> list[int]:
    return list(session.scalars(select(HeadEvent.id).order_by(HeadEvent.event_time, HeadEvent.id)))


def process_head(session: Session, head: Event, settings: Settings) -> tuple[str, int, int]:
    edges = rollup_edges(session, head.id)
    status = verify_head(session, head, settings)
    races = link_races(session, head, settings)
    return status, edges, races


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()

    with session_scope() as session:
        ids = head_ids(session)
    statuses: Counter[str] = Counter()
    edges = races = failed = 0
    for head_id in ids:
        try:
            with session_scope() as session:
                head = session.get(Event, head_id)
                assert head is not None
                status, n_edges, n_races = process_head(session, head, settings)
        except Exception as e:  # noqa: BLE001 - one bad head never sinks the batch
            log.warning("graph pass on head %s failed: %s", head_id, e)
            failed += 1
            continue
        statuses[str(status)] += 1
        edges += n_edges
        races += n_races
        print(f"head {head_id:<6} {status:<14} edges={n_edges:<3} races={n_races}")
    print(f"heads: {len(ids)}; {dict(statuses)}; edges: {edges}; race links: {races}; "
          f"failed: {failed}")


if __name__ == "__main__":
    main()
