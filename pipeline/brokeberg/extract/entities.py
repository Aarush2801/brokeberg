"""Pass 2: entity mentions -> canonical IDs.

The LLM finds mentions; deterministic code (`ids.resolve`) links them. The LLM never chooses an
ID. An unresolved mention goes to the review queue, never to `entities`.
"""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from brokeberg import llm
from brokeberg.db.models import Entity, ReviewKind
from brokeberg.extract.bills import ensure_bill
from brokeberg.extract.doc import SYSTEM, ExtractState, ReviewItem, SourceDoc, ground, render
from brokeberg.ids import fec
from brokeberg.ids.canonical import Namespace, split
from brokeberg.ids.resolve import resolve
from brokeberg.taxonomy import EntityType

Role = Literal["actor", "target", "subject", "mentioned"]

PROMPT = """List every named entity this document mentions that a political-economic graph would
track: politicians, candidates, agencies, committees, parties, races, US states, economic
indicators, bills, countries, companies, industries, interest groups/PACs.

For each mention:
- mention: the name exactly as written (keep titles/party tags, e.g. "Sen. Rick Scott (R-FL)").
- entity_type: one of the allowed types. A sitting senator is a Politician.
- role: actor (did the thing), target (it was done to them), subject (the topic of the item),
  or mentioned.
- span: a short verbatim excerpt containing the mention.
- confidence: 0-1 that the mention and its type are right.

Do not list the document's author or a bill's sponsor from the header lines unless they are
also named in the body. Do not invent entities that are only implied.

{doc}"""


class MentionLLM(BaseModel):
    mention: str = Field(min_length=1)
    entity_type: EntityType
    role: Role
    span: str
    confidence: float = Field(ge=0, le=1)


class MentionsLLM(BaseModel):
    mentions: list[MentionLLM]


class LinkedEntity(BaseModel):
    mention: str
    entity_id: int | None
    canonical_id: str | None
    entity_type: EntityType
    role: str
    span: str
    confidence: float = Field(ge=0, le=1)
    method: Literal["connector", "exact", "fuzzy", "none"]


class EntitiesResult(BaseModel):
    entities: list[LinkedEntity]

    @property
    def resolved(self) -> list[LinkedEntity]:
        return [e for e in self.entities if e.entity_id is not None]


# Which node types a mention of a given type may link to. An incumbent is one node: a candidate
# mention can resolve to a Politician carrying the FEC ID in its aliases.
_SEARCH: dict[EntityType, list[EntityType]] = {
    EntityType.POLITICIAN: [EntityType.POLITICIAN, EntityType.CANDIDATE],
    EntityType.CANDIDATE: [EntityType.CANDIDATE, EntityType.POLITICIAN],
}


def _lookup(entity: Entity | None) -> tuple[int, str, EntityType] | None:
    if entity is None:
        return None
    return entity.id, entity.canonical_id, entity.entity_type


def _connector_role(doc: SourceDoc, ns: Namespace) -> tuple[str, str]:
    """(role, span) for an ID the connector resolved from a structured field."""
    first_line = doc.body.splitlines()[0] if doc.body else doc.url
    if doc.kind == "vote" and ns == Namespace.BIOGUIDE:
        return "voter", first_line
    if doc.kind == "bill" and ns == Namespace.BIOGUIDE:
        line = next((h for h in doc.header if h.startswith("Sponsor: ")), first_line)
        return "sponsor", line
    author = next((h for h in doc.header if h.startswith("Author: ")), None)
    if author and ns == Namespace.BIOGUIDE:
        return "author", author
    return "subject", first_line


def connector_entities(state: ExtractState, doc: SourceDoc) -> list[LinkedEntity]:
    """IDs the connector already resolved by exact registry lookup, plus the item's bill node."""
    out: list[LinkedEntity] = []
    for cid in doc.resolved:
        ns, raw = split(cid)
        if ns == Namespace.FEC:
            hit = _lookup(fec.by_fec_id(state.session, raw))
        else:
            hit = _lookup(state.session.scalar(select(Entity).where(Entity.canonical_id == cid)))
        if hit is None:
            continue  # a registry ID with no node yet (e.g. a non-incumbent FEC candidate)
        role, span = _connector_role(doc, ns)
        out.append(
            LinkedEntity(
                mention=cid, entity_id=hit[0], canonical_id=hit[1], entity_type=hit[2],
                role=role, span=span, confidence=1.0, method="connector",
            )
        )
    bill_node = ensure_bill(state.session, doc)
    if bill_node is not None:
        out.append(
            LinkedEntity(
                mention=bill_node.canonical_id, entity_id=bill_node.id,
                canonical_id=bill_node.canonical_id, entity_type=EntityType.POLICY_BILL,
                role="subject", span=doc.body.splitlines()[0], confidence=1.0, method="connector",
            )
        )
    return out


def link(state: ExtractState, m: MentionLLM) -> LinkedEntity:
    types = _SEARCH.get(m.entity_type, [m.entity_type])
    r = resolve(state.session, m.mention, types)
    if r.entity_id is None:
        state.review.append(
            ReviewItem(
                kind=ReviewKind.UNRESOLVED_MENTION,
                mention=m.mention,
                field="entities",
                entity_type_hint=m.entity_type,
                candidates=[c.model_dump() for c in r.candidates],
                payload={"role": m.role, "span": m.span},
                confidence=m.confidence,
            )
        )
        return LinkedEntity(
            mention=m.mention, entity_id=None, canonical_id=None, entity_type=m.entity_type,
            role=m.role, span=m.span, confidence=m.confidence, method="none",
        )
    entity_type = state.session.scalar(select(Entity.entity_type).where(Entity.id == r.entity_id))
    linked = LinkedEntity(
        mention=m.mention, entity_id=r.entity_id, canonical_id=r.canonical_id,
        entity_type=entity_type or m.entity_type, role=m.role, span=m.span,
        confidence=round(min(m.confidence, r.confidence), 4), method=r.method,
    )
    state.flag_low_confidence("entities", m.mention, linked.confidence, linked.model_dump())
    return linked


def _dedupe(entities: list[LinkedEntity]) -> list[LinkedEntity]:
    """One row per (entity, role) — the event_entities key — keeping the most confident."""
    best: dict[tuple[int, str], LinkedEntity] = {}
    unresolved: list[LinkedEntity] = []
    for e in entities:
        if e.entity_id is None:
            unresolved.append(e)
            continue
        key = (e.entity_id, e.role)
        if key not in best or e.confidence > best[key].confidence:
            best[key] = e
    return [*best.values(), *unresolved]


def entities(doc: SourceDoc, state: ExtractState) -> EntitiesResult:
    found = connector_entities(state, doc)
    out = llm.complete(PROMPT.format(doc=render(doc)), schema=MentionsLLM, system=SYSTEM)
    for m in out.mentions:
        if not ground(m.span, doc) or not ground(m.mention, doc):
            continue  # no verbatim span, no claim
        found.append(link(state, m))
    return EntitiesResult(entities=_dedupe(found))
