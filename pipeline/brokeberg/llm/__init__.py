"""Model interface: one `complete()` for every caller; provider chosen by LLM_PROVIDER.

The LLM is the structuring layer, not the source of truth. With `schema`, output is forced
through a single tool whose input schema is the pydantic model's JSON schema, then validated.
"""

from typing import TypeVar, overload

from pydantic import BaseModel, ValidationError

from brokeberg.config import get_settings
from brokeberg.llm import _anthropic, _bedrock
from brokeberg.llm.errors import LLMOutputError

__all__ = ["LLMOutputError", "complete"]

M = TypeVar("M", bound=BaseModel)

# Name of the single forced tool used for structured output.
TOOL_NAME = "emit"


@overload
def complete(
    prompt: str, *, schema: None = None, system: str | None = None, max_tokens: int = 4096
) -> str: ...


@overload
def complete(
    prompt: str, *, schema: type[M], system: str | None = None, max_tokens: int = 4096
) -> M: ...


def complete(
    prompt: str,
    *,
    schema: type[BaseModel] | None = None,
    system: str | None = None,
    max_tokens: int = 4096,
) -> str | BaseModel:
    """Run one completion. Returns text, or a validated `schema` instance when given."""
    settings = get_settings()
    tool = None
    if schema is not None:
        tool = {
            "name": TOOL_NAME,
            "description": f"Return the result as a {schema.__name__} object.",
            "input_schema": schema.model_json_schema(),
        }

    call = _anthropic.call if settings.llm_provider == "anthropic" else _bedrock.call
    result = call(
        prompt, system=system, max_tokens=max_tokens, tool=tool, tool_name=TOOL_NAME
    )

    if schema is None:
        if not isinstance(result, str):
            raise LLMOutputError("expected text output, got structured output")
        return result
    if not isinstance(result, dict):
        raise LLMOutputError(f"model did not call the {TOOL_NAME!r} tool")
    try:
        return schema.model_validate(result)
    except ValidationError as e:
        raise LLMOutputError(f"output failed {schema.__name__} validation: {e}") from e
