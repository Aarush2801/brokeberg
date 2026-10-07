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
    system: str | None,
    max_tokens: int,
    tool: dict[str, Any] | None,
    tool_name: str,
) -> str | dict[str, Any]:
    """Return text, or the forced tool's input dict when `tool` is given."""
    kwargs: dict[str, Any] = {
        "modelId": get_settings().llm_model,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if system:
        kwargs["system"] = [{"text": system}]
    if tool is not None:
        kwargs["toolConfig"] = {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "inputSchema": {"json": tool["input_schema"]},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": tool_name}},
        }

    resp = get_client().converse(**kwargs)
    content = resp["output"]["message"]["content"]

    if tool is not None:
        for block in content:
            use = block.get("toolUse")
            if use and use.get("name") == tool_name:
                return dict(use["input"])
        return ""
    return "".join(block["text"] for block in content if "text" in block)
