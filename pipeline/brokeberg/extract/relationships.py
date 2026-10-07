"""Pass 5: typed edges between resolved entities.

Structured facts are edges from code: a bill's sponsors PROPOSE it; a roll call's members
VOTED_FOR / VOTED_AGAINST its bill. The LLM proposes the remaining edges only between entities
already resolved in pass 2, and never VOTED_*. Correlation, never causation: there is no CAUSES
edge type, and any edge touching an economic indicator must be CORRELATES_WITH or EXPOSED_TO.
"""

from typing import Literal

from pydantic import BaseModel, Field

from brokeberg import llm
from brokeberg.extract.doc import SYSTEM, ExtractState, SourceDoc, ground, render
from brokeberg.extract.entities import EntitiesResult, LinkedEntity
from brokeberg.extract.stance import SKIP_KINDS
from brokeberg.taxonomy import EdgeType, EntityType

PAYLOAD_ONLY = frozenset({EdgeType.VOTED_FOR, EdgeType.VOTED_AGAINST})
ECONOMIC_OK = frozenset({EdgeType.CORRELATES_WITH, EdgeType.EXPOSED_TO})
CAST: dict[str, EdgeType] = {"Yea": EdgeType.VOTED_FOR, "Nay": EdgeType.VOTED_AGAINST}

PROMPT = """List the relationships the document states between these entities (use entity_id
exactly). Only relationships the text itself supports; most pairs have none.

Entities:
{entities}

relation, one of:
SUPPORTS, OPPOSES (an actor for/against another entity, e.g. a bill or agency action),
PROPOSES (introduces/proposes a bill or policy), AFFECTS (a policy/bill bears on an industry,
state, or group), EXPOSED_TO (an industry/state is exposed to an indicator or policy),
LOCATED_IN, COMPETES_IN (a candidate in a race), ENDORSES, FUNDED_BY, RESPONDS_TO,
CORRELATES_WITH (economic co-movement; never claim one thing caused another).

For each: src_entity, relation, dst_entity, a one-sentence rationale, a verbatim span, and a
0-1 confidence.

{doc}"""


class RelationLLM(BaseModel):
    src_entity: int
    relation: EdgeType
    dst_entity: int
    rationale: str
    span: str
    confidence: float = Field(ge=0, le=1)


class RelationsLLM(BaseModel):
    relations: list[RelationLLM]


class Relation(RelationLLM):
    method: Literal["payload", "llm"]


class RelationshipsResult(BaseModel):
    relations: list[Relation]


def payload_edges(doc: SourceDoc, ents: EntitiesResult) -> list[Relation]:
    resolved = ents.resolved
    bills = [e for e in resolved if e.entity_type == EntityType.POLICY_BILL]
    bill_node = next((e for e in bills if e.method == "connector"), None)
    if bill_node is None or bill_node.entity_id is None:
        return []
    out: list[Relation] = []
    if doc.kind == "bill":
        for e in resolved:
            if e.role == "sponsor" and e.entity_id is not None:
                out.append(
                    Relation(
                        src_entity=e.entity_id, relation=EdgeType.PROPOSES,
                        dst_entity=bill_node.entity_id, rationale="listed sponsor on congress.gov",
                        span=e.span, confidence=1.0, method="payload",
                    )
                )
    elif doc.kind == "vote":
        by_cid = {e.canonical_id: e for e in resolved if e.role == "voter"}
        roll = doc.raw.get("clerk_rollnumber")
        for member in doc.raw.get("members", []):
            relation = CAST.get(member.get("vote") or "")
            voter = by_cid.get(f"bioguide:{member.get('bioguide')}")
            if relation is None or voter is None or voter.entity_id is None:
                continue  # Not Voting / Present, or a member with no node
            out.append(
                Relation(
                    src_entity=voter.entity_id, relation=relation,
                    dst_entity=bill_node.entity_id,
                    rationale=f"cast {member['vote']} on roll call {roll}",
                    span=voter.span, confidence=1.0, method="payload",
                )
            )
    return out


def _allowed(r: RelationLLM, nodes: dict[int, LinkedEntity], doc: SourceDoc) -> bool:
    if r.src_entity not in nodes or r.dst_entity not in nodes or r.src_entity == r.dst_entity:
        return False
    if r.relation in PAYLOAD_ONLY or not ground(r.span, doc):
        return False
    economic = EntityType.ECONOMIC_INDICATOR in {
        nodes[r.src_entity].entity_type, nodes[r.dst_entity].entity_type
    }
    return not economic or r.relation in ECONOMIC_OK


def relationships(doc: SourceDoc, state: ExtractState) -> RelationshipsResult:
    ents = state.get("entities", EntitiesResult)
    edges = payload_edges(doc, ents)
    nodes = {e.entity_id: e for e in ents.resolved if e.entity_id is not None}
    if doc.kind in SKIP_KINDS or len(nodes) < 2:
        return RelationshipsResult(relations=edges)

    lines = "\n".join(
        f"- entity_id={eid}: {e.canonical_id} {e.entity_type} (as \"{e.mention}\")"
        for eid, e in nodes.items()
    )
    out = llm.complete(
        PROMPT.format(entities=lines, doc=render(doc)), schema=RelationsLLM, system=SYSTEM
    )
    seen = {(r.src_entity, r.relation, r.dst_entity) for r in edges}
    for r in out.relations:
        key = (r.src_entity, r.relation, r.dst_entity)
        if key in seen or not _allowed(r, nodes, doc):
            continue
        seen.add(key)
        edges.append(Relation(**r.model_dump(), method="llm"))
        state.flag_low_confidence(
            "relationships", f"{r.src_entity} {r.relation} {r.dst_entity}", r.confidence,
            r.model_dump(mode="json"),
        )
    return RelationshipsResult(relations=edges)
