"""Anthropic API provider (dev)."""

from functools import lru_cache
from typing import Any

import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from brokeberg.config import get_settings

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
    system: str | None,
    max_tokens: int,
    tool: dict[str, Any] | None,
    tool_name: str,
) -> str | dict[str, Any]:
    """Return text, or the forced tool's input dict when `tool` is given."""
    kwargs: dict[str, Any] = {
        "model": get_settings().llm_model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    if tool is not None:
        kwargs["tools"] = [tool]
        kwargs["tool_choice"] = {"type": "tool", "name": tool_name}

    resp = get_client().messages.create(**kwargs)

    if tool is not None:
        for block in resp.content:
            if block.type == "tool_use" and block.name == tool_name:
                return dict(block.input)
        return ""
    return "".join(block.text for block in resp.content if block.type == "text")
