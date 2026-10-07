"""The document every pass reads, span grounding, and the state threaded through the DAG.

The LLM sees `SourceDoc.text`: a short header built in code from structured payload fields
(author handle, bill sponsors) followed by the item's own text. The header lets a span point at
a fact the source states in a field rather than in prose; it never adds anything not in the payload.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from brokeberg.db.models import RawItem, ReviewKind
from brokeberg.taxonomy import EntityType, SourceType

# Below this, an extracted field also goes to the review queue. Code, not judgment.
REVIEW_THRESHOLD = 0.6
# Bump when any pass's prompt or schema changes; stored on every extraction run.
PROMPT_VERSION = "day3-v2"

HEADER_END = "---"

SYSTEM = (
    "You are the structuring layer of a political-economic intelligence pipeline. You extract "
    "only what the document states. You never add outside knowledge, never guess identities, and "
    "never assert causation. Every span you return must be copied character-for-character from "
    "the document. If you cannot ground a field in the text, omit it or give it low confidence."
)


@dataclass(frozen=True)
class SourceDoc:
    source: str
    source_type: SourceType
    url: str
    body: str
    event_time: datetime | None
    raw: dict[str, Any]
    resolved: list[str]  # canonical IDs the connector resolved by exact registry lookup
    header: list[str]
    raw_item_id: int | None = None

    @property
    def kind(self) -> str | None:
        """'bill' | 'vote' for congress payloads, else None."""
        kind = self.raw.get("kind")
        return str(kind) if kind else None

    @property
    def text(self) -> str:
        if not self.header:
            return self.body
        return "\n".join([*self.header, HEADER_END, self.body])

    @classmethod
    def build(
        cls,
        *,
        source: str,
        source_type: SourceType,
        url: str,
        body: str,
        event_time: datetime | None,
        raw: dict[str, Any],
        resolved: list[str],
        raw_item_id: int | None = None,
    ) -> "SourceDoc":
        return cls(
            source=source,
            source_type=source_type,
            url=url,
            body=body,
            event_time=event_time,
            raw=raw,
            resolved=resolved,
            header=_header(raw),
            raw_item_id=raw_item_id,
        )

    @classmethod
    def from_raw_item(cls, item: RawItem) -> "SourceDoc":
        payload = item.payload_jsonb
        return cls.build(
            source=item.source,
            source_type=item.source_type,
            url=item.url,
            body=str(payload.get("text") or ""),
            event_time=item.event_time,
            raw=payload.get("raw") or {},
            resolved=list(payload.get("_resolved") or []),
            raw_item_id=item.id,
        )


def _header(raw: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    author = raw.get("author")
    if isinstance(author, dict) and author.get("handle"):
        lines.append(f"Author: @{author['handle']}")
    for sponsor in raw.get("sponsors") or []:
        if sponsor.get("fullName"):
            lines.append(f"Sponsor: {sponsor['fullName']}")
    return lines


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    return re.sub(r"\s+", " ", text).strip()


class UngroundedError(ValueError):
    """A pass's required claim could not be grounded in a verbatim span."""


def ground(span: str | None, doc: SourceDoc) -> bool:
    """True iff `span` occurs verbatim in the document (modulo whitespace and quote style)."""
    if not span:
        return False
    s = _norm(span)
    return len(s) >= 3 and s in _norm(doc.text)


class ReviewItem(BaseModel):
    """A pending `review_queue` row; written by `run.persist`, never by a pass."""

    kind: ReviewKind
    mention: str
    field: str
    entity_type_hint: EntityType | None = None
    candidates: list[dict[str, Any]] = []
    payload: dict[str, Any] = {}
    confidence: float | None = None


@dataclass
class ExtractState:
    """Accumulates each pass's output. Passes read earlier outputs and append review items."""

    session: Session
    outputs: dict[str, BaseModel] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)

    def get(self, name: str, model: type[BaseModel]) -> Any:
        out = self.outputs.get(name)
        if not isinstance(out, model):
            raise RuntimeError(f"pass {name!r} has not run (or returned the wrong type)")
        return out

    def flag_low_confidence(
        self, field_name: str, mention: str, confidence: float, payload: dict[str, Any]
    ) -> None:
        if confidence < REVIEW_THRESHOLD:
            self.review.append(
                ReviewItem(
                    kind=ReviewKind.LOW_CONFIDENCE,
                    mention=mention,
                    field=field_name,
                    payload=payload,
                    confidence=confidence,
                )
            )


def render(doc: SourceDoc) -> str:
    """The document block every prompt embeds."""
    return f"<document source=\"{doc.source}\" url=\"{doc.url}\">\n{doc.text}\n</document>"
