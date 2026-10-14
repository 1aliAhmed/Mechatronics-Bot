from __future__ import annotations

import asyncio

import pytest

from app.ai.providers import OpenRouter, message_text


class FakeGroq:
    def __init__(self, text="", error=None):
        self.text = text
        self.error = error
        self.calls = 0
        self.model = "fake"

    async def chat(self, messages, **params):
        self.calls += 1
        if self.error:
            raise self.error
        return self.text, {"route": "groq"}


def make_provider(groq=None, fallbacks=(), results=None):
    provider = OpenRouter("key", 8, groq_chat=groq, chat_fallbacks=tuple(fallbacks))
    calls = []

    async def fake_once(model, messages, **params):
        calls.append(model)
        result = (results or {}).get(model, RuntimeError(f"404 {model}"))
        if isinstance(result, Exception):
            raise result
        return result, {"model": model}

    provider._chat_once = fake_once
    return provider, calls


def test_groq_is_tried_first_and_wins():
    provider, calls = make_provider(groq=FakeGroq("hello"), results={"a:free": "or"})
    text, _ = asyncio.run(provider.chat("a:free", [{"role": "user", "content": "x"}]))
    assert text == "hello" and calls == []


def test_falls_back_to_openrouter_after_groq_error():
    provider, calls = make_provider(groq=FakeGroq(error=RuntimeError("boom")), results={"a:free": "or"})
    text, _ = asyncio.run(provider.chat("a:free", [{"role": "user", "content": "x"}]))
    assert text == "or" and calls == ["a:free"]


def test_empty_groq_falls_through_to_fallback_model():
    provider, calls = make_provider(groq=FakeGroq(""), fallbacks=("b:free",), results={"a:free": RuntimeError("404"), "b:free": "ok"})
    text, _ = asyncio.run(provider.chat("a:free", [{"role": "user", "content": "x"}]))
    assert text == "ok" and calls == ["a:free", "b:free"]


def test_all_chat_routes_failing_raises():
    provider, _ = make_provider(groq=FakeGroq(error=RuntimeError("boom")), fallbacks=("b:free",))
    with pytest.raises(RuntimeError, match="All chat routes failed"):
        asyncio.run(provider.chat("a:free", [{"role": "user", "content": "x"}]))


def test_non_free_chat_model_rejected():
    provider, _ = make_provider()
    with pytest.raises(ValueError):
        asyncio.run(provider.chat("paid-model", [{"role": "user", "content": "x"}]))


def test_vision_ignores_groq_and_uses_fallbacks():
    groq = FakeGroq("should not be used")
    provider = OpenRouter("key", 8, groq_chat=groq, vision_fallbacks=("v2:free",))
    calls = []

    async def fake_once(model, messages, **params):
        calls.append(model)
        if model == "v1:free":
            raise RuntimeError("404")
        return "blue", {"model": model}

    provider._chat_once = fake_once
    text, _ = asyncio.run(provider.vision("v1:free", "what color", b"img"))
    assert text == "blue"
    assert calls == ["v1:free", "v2:free"]
    assert groq.calls == 0


def test_message_text_uses_reasoning_when_content_missing():
    assert message_text({"choices": [{"message": {"content": None, "reasoning": "thought"}}]}) == "thought"
    assert message_text({"choices": [{"message": {"content": "hello"}}]}) == "hello"
