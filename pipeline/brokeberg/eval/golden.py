"""The golden set: hand-labeled items mirroring the pass outputs.

Labeling rules (also in `golden/README.md`):
- `entities`: every registry entity (canonical ID) named in the item's body, plus the bill an
  item is about. NOT the author, sponsor, or voters — those come from structured fields and are
  not what this eval measures.
- `stances`: only positions the text itself shows, for resolvable actors.
- `verified: true` only after a human has checked every label on the item.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from brokeberg.extract.doc import SourceDoc
from brokeberg.taxonomy import EventType, SourceType, Stance, Topic

GOLDEN_FILE = Path(__file__).resolve().parent / "golden" / "items.yaml"

# Roles that come from structured payload fields; excluded from entity scoring.
STRUCTURAL_ROLES = frozenset({"author", "sponsor", "voter"})


class ExpectedStance(BaseModel):
    canonical_id: str
    topic: Topic
    position: Stance


class Expected(BaseModel):
    relevant: bool
    event_type: EventType | None = None
    entities: list[str] = Field(default_factory=list)
    topics: list[Topic] = Field(default_factory=list)
    stances: list[ExpectedStance] = Field(default_factory=list)


class GoldenItem(BaseModel):
    id: str
    source: str
    source_type: SourceType
    url: str
    text: str
    event_time: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    resolved: list[str] = Field(default_factory=list)
    synthetic: bool = False
    verified: bool = False
    notes: str | None = None
    expected: Expected

    def doc(self) -> SourceDoc:
        return SourceDoc.build(
            source=self.source,
            source_type=self.source_type,
            url=self.url,
            body=self.text,
            event_time=self.event_time,
            raw=self.raw,
            resolved=self.resolved,
        )


def load(path: Path = GOLDEN_FILE) -> list[GoldenItem]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = [GoldenItem.model_validate(i) for i in data["items"]]
    ids = [i.id for i in items]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate golden ids: {sorted(dupes)}")
    return items
