from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, Field

from brokeberg import llm
from brokeberg.llm import _anthropic
from brokeberg.llm.schema import enforced_schema
from brokeberg.taxonomy import Topic


class Point(BaseModel):
    x: int
    y: int


class Labeled(BaseModel):
    topics: list[Topic]
    name: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    note: str | None = None


class FakeMessages:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.text = text
        self.stop_reason = stop_reason
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)], stop_reason=self.stop_reason
        )


def _install(monkeypatch: pytest.MonkeyPatch, text: str, stop: str = "end_turn") -> FakeMessages:
    messages = FakeMessages(text, stop)
    monkeypatch.setattr(_anthropic, "get_client", lambda: SimpleNamespace(messages=messages))
    return messages


def test_text_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = _install(monkeypatch, "hello")
    assert llm.complete("hi") == "hello"
    assert "output_config" not in messages.kwargs


def test_schema_uses_enforced_json_schema_and_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = _install(monkeypatch, '{"x": 1, "y": 2}')
    assert llm.complete("give a point", schema=Point) == Point(x=1, y=2)
    fmt = messages.kwargs["output_config"]["format"]
    assert fmt == {"type": "json_schema", "schema": enforced_schema(Point)}
    assert "tools" not in messages.kwargs and "tool_choice" not in messages.kwargs


def test_enforced_schema_keeps_enums_and_strips_unsupported_keywords() -> None:
    s = enforced_schema(Labeled)
    assert s["additionalProperties"] is False
    assert set(s["required"]) == {"topics", "name", "confidence", "note"}
    flat = str(s)
    assert "inflation_cost_of_living" in flat  # enum survives
    for kw in ("minLength", "minimum", "maximum", "default"):
        assert kw not in flat


def test_local_validation_still_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    # ge/le are stripped from the API schema, so they must be enforced here.
    _install(monkeypatch, '{"topics": [], "name": "a", "confidence": 1.5, "note": null}')
    with pytest.raises(llm.LLMOutputError):
        llm.complete("label", schema=Labeled)


def test_non_json_output_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, "not json")
    with pytest.raises(llm.LLMOutputError):
        llm.complete("give a point", schema=Point)


@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_truncated_or_refused_output_raises(monkeypatch: pytest.MonkeyPatch, stop: str) -> None:
    _install(monkeypatch, '{"x": 1, "y": 2}', stop)
    with pytest.raises(llm.LLMOutputError):
        llm.complete("give a point", schema=Point)


def test_model_defaults_to_settings_and_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = _install(monkeypatch, "ok")
    llm.complete("hi")
    assert messages.kwargs["model"] == llm.get_settings().llm_model
    llm.complete("hi", model="claude-haiku-4-5")
    assert messages.kwargs["model"] == "claude-haiku-4-5"
