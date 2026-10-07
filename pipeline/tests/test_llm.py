from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from brokeberg import llm
from brokeberg.llm import _anthropic


class Point(BaseModel):
    x: int
    y: int


class FakeMessages:
    def __init__(self, content: list[Any]) -> None:
        self.content = content
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(content=self.content)


def _install(monkeypatch: pytest.MonkeyPatch, content: list[Any]) -> FakeMessages:
    messages = FakeMessages(content)
    monkeypatch.setattr(_anthropic, "get_client", lambda: SimpleNamespace(messages=messages))
    return messages


def _tool_use(data: dict[str, Any]) -> Any:
    return SimpleNamespace(type="tool_use", name=llm.TOOL_NAME, input=data)


def test_text_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [SimpleNamespace(type="text", text="hello")])
    assert llm.complete("hi") == "hello"


def test_schema_forces_tool_and_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = _install(monkeypatch, [_tool_use({"x": 1, "y": 2})])
    result = llm.complete("give a point", schema=Point)
    assert result == Point(x=1, y=2)
    assert messages.kwargs["tool_choice"] == {"type": "tool", "name": llm.TOOL_NAME}
    assert messages.kwargs["tools"][0]["input_schema"] == Point.model_json_schema()


def test_schema_invalid_output_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [_tool_use({"x": "not-an-int"})])
    with pytest.raises(llm.LLMOutputError):
        llm.complete("give a point", schema=Point)


def test_schema_missing_tool_call_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [SimpleNamespace(type="text", text="no tool")])
    with pytest.raises(llm.LLMOutputError):
        llm.complete("give a point", schema=Point)
