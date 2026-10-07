"""The `raw_items` writer: content hash, dedup, insert. Connectors never write it directly."""

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brokeberg.db.models import RawItem
from brokeberg.ingest.base import RawRecord, RawSource, Stats


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(source: str, url: str, payload: Any) -> str:
    """Stable over (source, url, payload). Resolution results are excluded on purpose, so
    improving the resolver never makes an old item look new."""
    digest = hashlib.sha256()
    for part in (source, url, canonical_json(payload)):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def raw_item_row(source: str, connector: RawSource, record: RawRecord) -> dict[str, Any]:
    return {
        "source": source,
        "source_type": connector.source_type,
        "content_hash": content_hash(source, record.url, record.raw_payload),
        "url": record.url,
        "event_time": record.event_time,
        "payload_jsonb": {
            "text": record.text,
            "raw": record.raw_payload,
            "_resolved": sorted(set(record.entity_ids)),
            "_unresolved": sorted(set(record.unresolved)),
        },
    }


def write_raw(session: Session, connector: RawSource, records: Iterable[RawRecord]) -> Stats:
    """Insert records, skipping any whose content hash is already stored (or repeated in-batch)."""
    stats = Stats(source=connector.source)
    seen: set[str] = set()
    for record in records:
        stats.fetched += 1
        row = raw_item_row(connector.source, connector, record)
        if row["content_hash"] in seen:
            stats.skipped += 1
            continue
        seen.add(row["content_hash"])
        result = session.execute(
            insert(RawItem)
            .values(row)
            .on_conflict_do_nothing(index_elements=[RawItem.content_hash])
            .returning(RawItem.id)
        )
        if result.scalar_one_or_none() is None:
            stats.skipped += 1
        else:
            stats.inserted += 1
    return stats
