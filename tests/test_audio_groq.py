from __future__ import annotations

import asyncio
import re

import httpx
import pytest

from app.ai.providers import (AUDIO_UNAVAILABLE, GroqWhisper, audio_route,
                              audio_upload_parts, build_transcriber,
                              transcribe_audio)
from app.config import Settings


class FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        try:
            await request.aread()
        except Exception:
            pass
        status, payload = self.responses.pop(0)
        return httpx.Response(status, json=payload, request=request)


class BoomTranscriber:
    async def transcribe(self, audio, mime="audio/ogg"):
        raise RuntimeError("upstream down")


class BoomProvider:
    async def audio(self, models, prompt, audio, mime="audio/ogg"):
        raise RuntimeError("openrouter down")


class FakeProvider:
    def __init__(self, text="تفريغ بديل"):
        self.text = text

    async def audio(self, models, prompt, audio, mime="audio/ogg"):
        return self.text, {"usage": {"total_tokens": 1}}


def make_settings(monkeypatch, groq_key="", **env):
    monkeypatch.setenv("GROQ_API_KEY", groq_key)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings.from_env()


def test_audio_upload_parts_mapping():
    assert audio_upload_parts("audio/ogg", "voice") == ("voice.ogg", "audio/ogg")
    assert audio_upload_parts("audio/mpeg", "clip") == ("clip.mp3", "audio/mpeg")
    assert audio_upload_parts("audio/mp4; codecs=opus", "note") == ("note.m4a", "audio/mp4")
    name, content_type = audio_upload_parts("application/octet-stream")
    assert name == "voice.ogg" and content_type


def test_route_and_build_transcriber(monkeypatch):
    no_key = make_settings(monkeypatch, groq_key="")
    assert audio_route(no_key) == "openrouter"
    assert build_transcriber(no_key) is None

    with_key = make_settings(monkeypatch, groq_key="gsk_test", GROQ_WHISPER_MODEL="whisper-large-v3-turbo")
    assert audio_route(with_key) == "groq"
    transcriber = build_transcriber(with_key)
    assert isinstance(transcriber, GroqWhisper)
    assert transcriber.model == "whisper-large-v3-turbo"


def test_groq_whisper_transcribes_via_multipart():
    transport = FakeTransport([(200, {"text": "  مرحبا بكم  "})])
    transcriber = GroqWhisper("gsk_test", transport=transport)

    async def exercise():
        return await transcriber.transcribe(b"OggS-fake", "audio/ogg")

    text, payload = asyncio.run(exercise())
    assert text == "مرحبا بكم"
    request = transport.requests[0]
    assert str(request.url).endswith("/audio/transcriptions")
    assert "multipart/form-data" in request.headers.get("content-type", "")
    try:
        body = request.content
    except Exception:
        body = b""
    if isinstance(body, bytes):
        assert b'name="file"' in body and b"voice.ogg" in body


def test_groq_whisper_empty_transcript_raises():
    transport = FakeTransport([(200, {"text": "   "})])
    transcriber = GroqWhisper("gsk_test", transport=transport)

    async def exercise():
        with pytest.raises(ValueError):
            await transcriber.transcribe(b"OggS-fake", "audio/ogg")

    asyncio.run(exercise())


def test_transcribe_audio_prefers_groq():
    transport = FakeTransport([(200, {"text": "نص التسجيل"})])
    transcriber = GroqWhisper("gsk_test", transport=transport)

    text, _response, route, label = asyncio.run(
        transcribe_audio(transcriber, FakeProvider(), ("fallback/model:free",), "prompt", b"audio", "audio/ogg")
    )
    assert (text, route, label) == ("نص التسجيل", "groq", "whisper-large-v3")


def test_transcribe_audio_falls_back_to_openrouter():
    text, _response, route, label = asyncio.run(
        transcribe_audio(BoomTranscriber(), FakeProvider(), ("fallback/model:free",), "prompt", b"audio", "audio/ogg")
    )
    assert route == "openrouter"
    assert text == "تفريغ بديل"
    assert label == "fallback/model:free"


def test_transcribe_audio_without_groq_uses_openrouter():
    _text, _response, route, _label = asyncio.run(
        transcribe_audio(None, FakeProvider(), ("fallback/model:free",), "prompt", b"audio", "audio/ogg")
    )
    assert route == "openrouter"


def test_transcribe_audio_all_routes_fail():
    async def exercise():
        with pytest.raises(RuntimeError, match=re.escape(AUDIO_UNAVAILABLE)):
            await transcribe_audio(BoomTranscriber(), BoomProvider(), ("m:free",), "prompt", b"audio", "audio/ogg")

    asyncio.run(exercise())


def test_groq_key_is_optional_at_runtime(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-x")
    monkeypatch.setenv("BOUND_COMMUNITY_ID", "-100123")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    settings = Settings.from_env(require_runtime=True)
    assert settings.groq_api_key == ""
    assert settings.groq_whisper_model == "whisper-large-v3"
