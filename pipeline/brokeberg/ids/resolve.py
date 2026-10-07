"""Mention -> canonical entity. Deterministic code; no LLM, and never mints an entity.

Strategy: exact normalized alias match -> fuzzy match over aliases -> None (caller sends the
mention to the review queue). An unresolved result still lists the nearest candidates.

Fuzzy uses `token_sort_ratio`, not `WRatio`: WRatio's partial/token-set scoring lets a bare
surname alias ("kelly") match any longer name containing it ("Megyn Kelly"), which would silently
link the wrong person. Aliases containing digits (FEC IDs, etc.) are exact-match only.
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel
from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.db.models import Entity
from brokeberg.taxonomy import EntityType

# Thresholds are code, not judgment calls: tune them against the golden set, never ad hoc.
FUZZY_ACCEPT = 90.0  # minimum token_sort_ratio to accept a fuzzy match
FUZZY_MARGIN = 8.0  # best entity must beat the runner-up entity by at least this much
MAX_CANDIDATES = 5

_HONORIFICS = re.compile(
    r"^(?:the honorable|honorable|hon|senator|sen|representative|rep|congressman|"
    r"congresswoman|dr|mr|mrs|ms|gov|governor)\b\s*"
)
_SUFFIXES = re.compile(r"\s+(?:jr|sr|ii|iii|iv)$")
_PARENS = re.compile(r"\([^)]*\)")


class Candidate(BaseModel):
    entity_id: int
    canonical_id: str
    name: str
    score: float


class ResolveResult(BaseModel):
    entity_id: int | None
    canonical_id: str | None
    confidence: float
    method: Literal["exact", "fuzzy", "none"]
    candidates: list[Candidate]


@dataclass(frozen=True)
class AliasRecord:
    entity_id: int
    canonical_id: str
    name: str
    aliases: Sequence[str]


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def normalize(mention: str) -> list[str]:
    """Normalized forms of a mention, most specific first.

    'Sen. Rick Scott (R-FL)' -> ['rick scott r fl', 'rick scott'].
    """
    raw = mention.strip().lstrip("@")
    forms: list[str] = []
    for variant in (raw, _PARENS.sub(" ", raw)):
        text = _fold(variant)
        text = _HONORIFICS.sub("", text)
        text = _SUFFIXES.sub("", text)
        if text and text not in forms:
            forms.append(text)
    return forms


@dataclass
class AliasIndex:
    records: dict[int, AliasRecord]
    exact: dict[str, set[int]] = field(default_factory=dict)
    fuzzy_choices: list[str] = field(default_factory=list)
    fuzzy_owner: list[int] = field(default_factory=list)

    @classmethod
    def build(cls, records: Iterable[AliasRecord]) -> "AliasIndex":
        index = cls(records={r.entity_id: r for r in records})
        for rec in index.records.values():
            for alias in (rec.name, *rec.aliases):
                for form in normalize(alias):
                    index.exact.setdefault(form, set()).add(rec.entity_id)
                    if not any(c.isdigit() for c in form):
                        index.fuzzy_choices.append(form)
                        index.fuzzy_owner.append(rec.entity_id)
        return index

    def _candidate(self, entity_id: int, score: float) -> Candidate:
        rec = self.records[entity_id]
        return Candidate(
            entity_id=entity_id, canonical_id=rec.canonical_id, name=rec.name, score=score
        )

    def _fuzzy_scores(self, form: str) -> list[tuple[int, float]]:
        """Best score per entity, descending."""
        best: dict[int, float] = {}
        for _choice, score, i in process.extract(
            form, self.fuzzy_choices, scorer=fuzz.token_sort_ratio, limit=None
        ):
            owner = self.fuzzy_owner[i]
            if score > best.get(owner, -1.0):
                best[owner] = float(score)
        return sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))

    def resolve(self, mention: str) -> ResolveResult:
        forms = normalize(mention)

        for form in forms:
            hits = self.exact.get(form)
            if not hits:
                continue
            if len(hits) == 1:
                (eid,) = hits
                rec = self.records[eid]
                return ResolveResult(
                    entity_id=eid,
                    canonical_id=rec.canonical_id,
                    confidence=1.0,
                    method="exact",
                    candidates=[self._candidate(eid, 100.0)],
                )
            if form == forms[-1]:
                # Ambiguous even at the least specific form: surface everyone, decide nothing.
                return _unresolved([self._candidate(e, 100.0) for e in sorted(hits)])

        if not forms or not self.fuzzy_choices:
            return _unresolved([])

        scored = self._fuzzy_scores(forms[-1])
        candidates = [self._candidate(e, s) for e, s in scored[:MAX_CANDIDATES]]
        best_id, best = scored[0]
        runner_up = scored[1][1] if len(scored) > 1 else 0.0
        if best >= FUZZY_ACCEPT and best - runner_up >= FUZZY_MARGIN:
            return ResolveResult(
                entity_id=best_id,
                canonical_id=self.records[best_id].canonical_id,
                confidence=round(best / 100.0, 4),
                method="fuzzy",
                candidates=candidates,
            )
        return _unresolved(candidates)


def _unresolved(candidates: list[Candidate]) -> ResolveResult:
    return ResolveResult(
        entity_id=None, canonical_id=None, confidence=0.0, method="none", candidates=candidates
    )


_CACHE: dict[tuple[str, tuple[EntityType, ...]], AliasIndex] = {}


def clear_cache() -> None:
    """Drop cached alias indexes (call after seeding or after entities change)."""
    _CACHE.clear()


def load_index(session: Session, entity_types: Sequence[EntityType]) -> AliasIndex:
    key = (str(session.get_bind().engine.url), tuple(sorted(entity_types)))
    if key not in _CACHE:
        rows = session.execute(
            select(Entity.id, Entity.canonical_id, Entity.name, Entity.aliases).where(
                Entity.entity_type.in_(entity_types)
            )
        )
        _CACHE[key] = AliasIndex.build(
            AliasRecord(entity_id=r.id, canonical_id=r.canonical_id, name=r.name, aliases=r.aliases)
            for r in rows
        )
    return _CACHE[key]


def resolve(
    session: Session, mention: str, entity_type: EntityType | Sequence[EntityType]
) -> ResolveResult:
    """Resolve a mention to an existing entity of the given type(s), or None with candidates."""
    types = [entity_type] if isinstance(entity_type, EntityType) else list(entity_type)
    return load_index(session, types).resolve(mention)
