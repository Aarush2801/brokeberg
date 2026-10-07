"""Pass 0: relevance gate. Is this item political/economic and in MVP scope? Cheap model."""

from pydantic import BaseModel, Field

from brokeberg import llm
from brokeberg.config import get_settings
from brokeberg.extract.doc import SYSTEM, ExtractState, SourceDoc, render

# Sources that are in scope by construction (federal legislative records, Senate FEC filings).
# They skip the LLM: no point paying to ask whether a Senate roll call is political.
IN_SCOPE_SOURCES = frozenset({"congress", "senate_votes", "fec"})

PROMPT = """Decide whether this item belongs in a US federal political-economic intelligence feed.

RELEVANT: US federal politics or government (Congress, especially the Senate; the White House;
federal agencies; courts on federal matters), US elections and campaigns, US economic data or
policy (inflation, jobs, rates, trade, taxes, debt), and geopolitics that bears on US policy.
NOT RELEVANT: sports, entertainment, weather, lifestyle, personal life, purely local news with no
federal angle, or content with no factual claim (greetings, thanks, holiday wishes).

{doc}

Return `relevant`, a one-sentence `reason`, and your `confidence` (0-1) in the decision."""


class GateResult(BaseModel):
    relevant: bool
    reason: str
    confidence: float = Field(ge=0, le=1)


def gate(doc: SourceDoc, state: ExtractState) -> GateResult:
    if doc.source in IN_SCOPE_SOURCES:
        return GateResult(relevant=True, reason=f"{doc.source} is in scope", confidence=1.0)
    return llm.complete(
        PROMPT.format(doc=render(doc)),
        schema=GateResult,
        system=SYSTEM,
        model=get_settings().llm_model_cheap,
        max_tokens=512,
    )
