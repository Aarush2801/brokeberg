"""Pydantic JSON schema -> the subset the API enforces for structured outputs.

The API guarantees output matches the schema (types, enums, required fields) but rejects some
keywords: numeric/string/array-length constraints, and `additionalProperties` other than false.
Those are stripped here and still enforced locally by `model_validate`.
"""

from typing import Any

from pydantic import BaseModel

UNSUPPORTED = frozenset(
    {
        "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
        "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems", "default",
    }
)


def _clean(node: Any) -> Any:
    if isinstance(node, list):
        return [_clean(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {k: _clean(v) for k, v in node.items() if k not in UNSUPPORTED}
    if out.get("type") == "object" and "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    return out


def enforced_schema(model: type[BaseModel]) -> dict[str, Any]:
    result: dict[str, Any] = _clean(model.model_json_schema())
    return result
