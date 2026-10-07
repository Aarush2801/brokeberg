"""Anthropic API provider (dev)."""

from functools import lru_cache
from typing import Any

import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from brokeberg.config import get_settings
from brokeberg.llm.errors import LLMOutputError

_TRANSIENT = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


@lru_cache
def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().require("anthropic_api_key"))


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
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    if json_schema is not None:
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}

    resp = get_client().messages.create(**kwargs)

    # A truncated or refused response may not match the schema; never pass it on as valid.
    if resp.stop_reason in ("max_tokens", "refusal"):
        raise LLMOutputError(f"model stopped with stop_reason={resp.stop_reason!r}")
    return "".join(block.text for block in resp.content if block.type == "text")
