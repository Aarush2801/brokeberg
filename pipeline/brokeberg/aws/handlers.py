"""Lambda entry points. Config comes from Secrets Manager; the work is the same `run()` functions
the CLIs call.

- `ingest`: one function per connector (env SOURCE), fired by EventBridge Scheduler. Writes
  raw_items (+ S3 archive) and, if anything new landed, enqueues one message for `process`.
- `process`: triggered by a FIFO queue with a single message group (one run at a time).
  Extracts pending raw items up to EXTRACT_DAILY_CAP per UTC day (the Bedrock spend guard), then
  clusters and runs the graph pass.
  Items over the cap stay pending for the next day's run.
"""

import json
import logging
import os
from dataclasses import asdict
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brokeberg.aws import secrets

log = logging.getLogger("brokeberg.aws")

DEFAULT_DAILY_CAP = 30
PROCESS_GROUP = "process"

_loaded = False


def _cold_start() -> None:
    global _loaded
    if not _loaded:
        logging.getLogger().setLevel(logging.INFO)
        # httpx logs full request URLs at INFO, and FRED/Congress/FEC put the API key in the
        # query string, so it would land in CloudWatch.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        secrets.load()
        _loaded = True


def extracted_today(session: Session, now: datetime) -> int:
    from brokeberg.db.models import ExtractionRun

    midnight = datetime.combine(now.date(), time.min, tzinfo=UTC)
    return int(
        session.scalar(
            select(func.count()).select_from(ExtractionRun).where(
                ExtractionRun.created_at >= midnight
            )
        )
        or 0
    )


def ingest(event: dict[str, Any], context: Any = None, *, sqs: Any = None) -> dict[str, Any]:
    _cold_start()
    from brokeberg.ingest import run_once

    source = os.environ["SOURCE"]
    since = datetime.now(UTC) - timedelta(days=float(os.environ.get("INGEST_SINCE_DAYS", "7")))
    [stats] = run_once.run(since, only=[source])
    result = asdict(stats)
    log.info(json.dumps({"stage": "ingest", **result}))
    if stats.note.startswith("FAILED"):
        raise RuntimeError(stats.note)
    if stats.inserted:
        if sqs is None:
            import boto3

            sqs = boto3.client("sqs")
        # FIFO with one message group: `process` runs one batch at a time, so clustering never
        # races itself.
        sqs.send_message(
            QueueUrl=os.environ["PROCESS_QUEUE_URL"],
            MessageBody=json.dumps({"source": source, "inserted": stats.inserted}),
            MessageGroupId=PROCESS_GROUP,
            MessageDeduplicationId=f"{source}-{datetime.now(UTC):%Y%m%dT%H%M%S}",
        )
    return result


def process(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    _cold_start()
    from brokeberg.cluster import run as cluster_run
    from brokeberg.db.session import session_scope
    from brokeberg.extract import run as extract_run
    from brokeberg.graph import run as graph_run

    cap = int(os.environ.get("EXTRACT_DAILY_CAP", DEFAULT_DAILY_CAP))
    with session_scope() as session:
        used = extracted_today(session, datetime.now(UTC))
    remaining = max(cap - used, 0)
    extracted = extract_run.run(limit=remaining) if remaining else {}
    log.info(json.dumps({"stage": "extract", "cap": cap, "used": used, **extracted}))
    clustered = cluster_run.run()
    log.info(json.dumps({"stage": "cluster", **clustered}))
    graphed = graph_run.run()
    log.info(json.dumps({"stage": "graph", **graphed}))
    return {"extract": extracted, "cluster": clustered, "graph": graphed}
