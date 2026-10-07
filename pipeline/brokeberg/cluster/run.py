"""Embed -> cluster -> materialize event objects (and their related-event links).

`python -m brokeberg.cluster.run [--limit N] [--force]`

Idempotent: clustered members are never re-placed, and a head is only re-materialized when its
membership (or SYNTH_VERSION) changed. One transaction per member and per head, so one failure
never sinks the batch.
"""

import argparse
import logging

from brokeberg.cluster import cluster, embed_events, event_object
from brokeberg.config import get_settings
from brokeberg.db.models import Event
from brokeberg.db.session import session_scope

log = logging.getLogger("brokeberg.cluster")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="re-materialize every head")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with session_scope() as session:
        embedded = embed_events.embed_pending(session, args.limit)
    print(f"embedded: {embedded}")

    settings = get_settings()
    counts = {"new": 0, "attached": 0, "tiebreaks": 0, "failed": 0}
    with session_scope() as session:
        pending = cluster.pending(session, args.limit)
    for event_id in pending:
        try:
            with session_scope() as session:
                event = session.get(Event, event_id)
                assert event is not None
                placed = cluster.cluster_event(session, event, settings)
        except Exception as e:  # noqa: BLE001 - one bad member never sinks the batch
            log.warning("clustering event %s failed: %s", event_id, e)
            counts["failed"] += 1
            continue
        counts["new" if placed.opened else "attached"] += 1
        counts["tiebreaks"] += placed.decision == cluster.Decision.TIEBREAK
        print(f"event {event_id:<6} {placed.decision.value:<8} -> head {placed.head_id}")
    print(f"clustered: {counts}")

    with session_scope() as session:
        lexicon = event_object.load_lexicon(session)
        heads = event_object.heads(session)
    refreshed = failed = 0
    for head_id in heads:
        try:
            with session_scope() as session:
                head = session.get(Event, head_id)
                assert head is not None
                refreshed += event_object.materialize(session, head, lexicon, force=args.force)
        except Exception as e:  # noqa: BLE001
            log.warning("materializing head %s failed: %s", head_id, e)
            failed += 1
    print(f"heads: {len(heads)}; materialized: {refreshed}; failed: {failed}")


if __name__ == "__main__":
    main()
