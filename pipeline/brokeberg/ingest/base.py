"""The common connector interfaces. The rest of the system never needs to know which source it is.

Two kinds of source:
- `Connector`: unstructured items (bills, votes, posts, filings) -> `RawRecord` -> `raw_items`,
  written by `pipeline.write_raw` (which owns hashing and dedup).
- `StructuredLoader`: already-structured data (indicator observations, polls, ratings, FEC
  candidate lists) written straight to their typed tables, idempotently.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from brokeberg.taxonomy import SourceType


class RawRecord(BaseModel):
    url: str = Field(min_length=1)
    text: str
    event_time: datetime | None
    raw_payload: dict[str, Any]
    # Canonical IDs the connector resolved cheaply (exact registry lookups only).
    entity_ids: list[str] = Field(default_factory=list)
    # Mentions it could not resolve; they go to the review queue, never to a new node.
    unresolved: list[str] = Field(default_factory=list)


@dataclass
class Stats:
    source: str
    fetched: int = 0
    inserted: int = 0
    skipped: int = 0
    note: str = ""

    def __str__(self) -> str:
        line = (
            f"{self.source:<12} fetched={self.fetched:<5} inserted={self.inserted:<5} "
            f"skipped={self.skipped}"
        )
        return f"{line}  {self.note}" if self.note else line


class RawSource(Protocol):
    """What `pipeline.write_raw` needs to label rows."""

    source: str
    source_type: SourceType


class Connector(RawSource, Protocol):
    def fetch(self, session: Session, since: datetime) -> Iterable[RawRecord]: ...


class StructuredLoader(Protocol):
    source: str

    def load(self, session: Session, since: datetime) -> Stats: ...
