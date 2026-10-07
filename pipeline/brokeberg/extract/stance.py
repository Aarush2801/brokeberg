"""Pass 4: stance per (resolved actor, topic). No verbatim span -> no stance.

Runs on stated positions (posts, statements, news quotes). Bill and vote items are skipped:
sponsorship and votes are structural facts, recorded as PROPOSES / VOTED_* edges in pass 5,
not inferred stances.
"""

from pydantic import BaseModel, Field

from brokeberg import llm
from brokeberg.extract.classify import Classification
from brokeberg.extract.doc import SYSTEM, ExtractState, SourceDoc, ground, render
from brokeberg.extract.entities import EntitiesResult
from brokeberg.taxonomy import INTENSITY_RANGE, EntityType, Stance, Topic

SKIP_KINDS = frozenset({"bill", "vote"})
STANCE_HOLDERS = frozenset(
    {EntityType.POLITICIAN, EntityType.CANDIDATE, EntityType.PARTY, EntityType.AGENCY}
)

PROMPT = """For each actor below, state their position on each listed topic — but ONLY where the
document itself shows that actor taking a position. Most (actor, topic) pairs will have none;
omit them. Do not infer positions from party, reputation, or outside knowledge.

Actors (use the entity_id exactly):
{actors}

Topics: {topics}

For each stance:
- entity_id, topic: from the lists above.
- position: strongly_support .. strongly_oppose, or neutral_unclear. "Support" means support for
  the policy direction the actor is advocating on that topic as described in the document.
- intensity: 0-1, how forcefully it is expressed.
- verbatim_span: the exact words from the document that show the position. Required.
- confidence: 0-1.

{doc}"""


class StanceLLM(BaseModel):
    entity_id: int
    topic: Topic
    position: Stance
    intensity: float = Field(ge=INTENSITY_RANGE[0], le=INTENSITY_RANGE[1])
    verbatim_span: str
    confidence: float = Field(ge=0, le=1)


class StancesResult(BaseModel):
    stances: list[StanceLLM]


def stance(doc: SourceDoc, state: ExtractState) -> StancesResult:
    if doc.kind in SKIP_KINDS:
        return StancesResult(stances=[])
    topics = state.get("classify", Classification).topics
    actors = {
        e.entity_id: e
        for e in state.get("entities", EntitiesResult).resolved
        if e.entity_type in STANCE_HOLDERS and e.entity_id is not None
    }
    if not topics or not actors:
        return StancesResult(stances=[])

    actor_lines = "\n".join(
        f"- entity_id={eid}: {e.canonical_id} (as \"{e.mention}\", role {e.role})"
        for eid, e in actors.items()
    )
    out = llm.complete(
        PROMPT.format(
            actors=actor_lines, topics=", ".join(topics), doc=render(doc)
        ),
        schema=StancesResult,
        system=SYSTEM,
    )
    kept: dict[tuple[int, Topic], StanceLLM] = {}
    for s in out.stances:
        # Only the actors and topics we asked about, and only with a grounded span.
        if s.entity_id not in actors or s.topic not in topics or not ground(s.verbatim_span, doc):
            continue
        key = (s.entity_id, s.topic)
        if key not in kept or s.confidence > kept[key].confidence:
            kept[key] = s
    for s in kept.values():
        state.flag_low_confidence(
            f"stance:{s.topic}", str(actors[s.entity_id].canonical_id), s.confidence,
            s.model_dump(mode="json"),
        )
    return StancesResult(stances=list(kept.values()))
