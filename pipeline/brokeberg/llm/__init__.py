"""Model interface: one `complete()` for every caller; provider chosen by LLM_PROVIDER.

The LLM is the structuring layer, not the source of truth. With `schema`, the API's structured
outputs constrain the response to the pydantic model's JSON schema (so enums are guaranteed),
and the result is validated locally as well, including constraints the API cannot enforce.
"""

import json
from typing import TypeVar, overload

from pydantic import BaseModel, ValidationError

from brokeberg.config import get_settings
from brokeberg.llm import _anthropic, _bedrock
from brokeberg.llm.errors import LLMOutputError
from brokeberg.llm.schema import enforced_schema

__all__ = ["LLMOutputError", "complete"]

M = TypeVar("M", bound=BaseModel)

# Room for adaptive thinking (on by default on current Sonnet) plus the answer.
DEFAULT_MAX_TOKENS = 16000


@overload
def complete(
    prompt: str,
    *,
    schema: None = None,
    system: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model: str | None = None,
) -> str: ...


@overload
def complete(
    prompt: str,
    *,
    schema: type[M],
    system: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model: str | None = None,
) -> M: ...


def complete(
    prompt: str,
    *,
    schema: type[BaseModel] | None = None,
    system: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model: str | None = None,
) -> str | BaseModel:
    """Run one completion. Returns text, or a validated `schema` instance when given.

    `model` overrides the default (`settings.llm_model`), e.g. `settings.llm_model_cheap`.
    """
    settings = get_settings()
    call = _anthropic.call if settings.llm_provider == "anthropic" else _bedrock.call
    text = call(
        prompt,
        model=model or settings.llm_model,
        system=system,
        max_tokens=max_tokens,
        json_schema=enforced_schema(schema) if schema is not None else None,
    )
    if schema is None:
        return text
    try:
        return schema.model_validate(json.loads(text))
    except json.JSONDecodeError as e:
        raise LLMOutputError(f"model output is not JSON: {e}") from e
    except ValidationError as e:
        raise LLMOutputError(f"output failed {schema.__name__} validation: {e}") from e
