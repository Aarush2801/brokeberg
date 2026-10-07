"""Pass 3: multi-label topic / policy-area classification. Cheap model."""

from pydantic import BaseModel, Field

from brokeberg import llm
from brokeberg.config import get_settings
from brokeberg.extract.doc import SYSTEM, ExtractState, SourceDoc, render
from brokeberg.taxonomy import JurisdictionLevel, Topic

PROMPT = """Classify this item.

- topics: every policy topic the item is substantively about (0-3 usually; none is fine).
- policy_areas: the topics a law, rule, vote, or spending decision in the item would directly
  change. A subset of topics; empty for pure commentary or data.
- jurisdiction_level: federal, state, district, or local.
- election_relevance: 0-1, how much this bears on a US election (campaigns, candidates, ratings,
  fundraising, polls = high; routine legislation = low).
- confidence: 0-1 in the topic labels.

Allowed topics: {topics}

{doc}"""


class Classification(BaseModel):
    topics: list[Topic]
    policy_areas: list[Topic]
    jurisdiction_level: JurisdictionLevel
    election_relevance: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)


def classify(doc: SourceDoc, state: ExtractState) -> Classification:
    out = llm.complete(
        PROMPT.format(doc=render(doc), topics=", ".join(t.value for t in Topic)),
        schema=Classification,
        system=SYSTEM,
        model=get_settings().llm_model_cheap,
        max_tokens=512,
    )
    out.topics = list(dict.fromkeys(out.topics))
    # A policy area is by definition one of the item's topics.
    out.policy_areas = [t for t in dict.fromkeys(out.policy_areas) if t in out.topics]
    state.flag_low_confidence(
        "classify", ",".join(out.topics) or "(none)", out.confidence, out.model_dump(mode="json")
    )
    return out
