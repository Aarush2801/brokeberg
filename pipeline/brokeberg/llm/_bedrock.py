"""AWS Bedrock provider (prod), via the Converse API."""

from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import ClientError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from brokeberg.config import get_settings

_TRANSIENT_CODES = {"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException"}


def _is_transient(e: BaseException) -> bool:
    return isinstance(e, ClientError) and e.response["Error"]["Code"] in _TRANSIENT_CODES


@lru_cache
def get_client() -> Any:
    return boto3.client("bedrock-runtime", region_name=get_settings().require("aws_region"))


@retry(
    retry=retry_if_exception(_is_transient),
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
    """Return the response text (Converse API)."""
    if json_schema is not None:
        # TODO(day 7): structured outputs on Bedrock. Current Sonnet rejects the forced-tool
        # pattern Converse would need; move this provider to the Messages-API Bedrock client.
        raise NotImplementedError("structured output on Bedrock is not wired yet (Day 7)")
    kwargs: dict[str, Any] = {
        "modelId": model,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if system:
        kwargs["system"] = [{"text": system}]
    resp = get_client().converse(**kwargs)
    content = resp["output"]["message"]["content"]
    return "".join(block["text"] for block in content if "text" in block)
