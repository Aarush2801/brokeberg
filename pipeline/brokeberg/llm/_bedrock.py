"""AWS Bedrock provider (prod): the Messages API over `bedrock-runtime` InvokeModel.

Requests are built by `_anthropic.messages_call`, so structured outputs, the stop-reason guard and
the absence of a thinking override are identical to dev: eval runs compare across providers.
`model` is a Bedrock inference-profile ID (LLM_MODEL / LLM_MODEL_CHEAP, e.g. `us.anthropic.…`).
InvokeModel (not the Mantle endpoint) because it serves both tiers: Haiku 4.5 is only there.
"""

from functools import lru_cache
from typing import Any

import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from brokeberg.config import get_settings
from brokeberg.llm._anthropic import _TRANSIENT, messages_call


@lru_cache
def get_client() -> anthropic.AnthropicBedrock:
    # Credentials come from the default AWS chain (the Lambda role in prod).
    return anthropic.AnthropicBedrock(aws_region=get_settings().require("aws_region"))


@retry(
    retry=retry_if_exception_type(_TRANSIENT),
    stop=stop_after_attempt(4),
    wait=wait_exponential(min=2, max=30),
    reraise=True,
)
def call(
    prompt: str,
    *,
    model: str,
    system: str | None,
    max_tokens: int,
    json_schema: dict[str, Any] | None,
) -> str:
    """Return the response text; with `json_schema`, that text is schema-constrained JSON."""
    return messages_call(
        get_client(),
        prompt,
        model=model,
        system=system,
        max_tokens=max_tokens,
        json_schema=json_schema,
    )
