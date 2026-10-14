from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import httpx
import pytest

from app.flows.visuals import visual_kind
from app.imagegen import ImageGenerationError, generate_image, save_image


def make_settings(tmp_path, image_model=""):
    return SimpleNamespace(data_dir=tmp_path, image_model=image_model, openrouter_api_key="test-key")


def test_visual_kind_routes_charts_and_illustrations():
    assert visual_kind("ارسم منحنى الجهد مقابل التيار") == "chart"
    assert visual_kind("مخطط دائرة كهربائية") == "chart"
    assert visual_kind("plot the sine wave") == "chart"
    assert visual_kind("رسم شعار Mechtronics") == "illustration"
    assert visual_kind("صمم صورة قطة صغيرة") == "illustration"
    assert visual_kind("ارسم شيئاً جميلاً") == "chart"


async def _no_sleep(*_args, **_kwargs):
    return None


def test_generate_image_retries_pollinations_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(402, json={"error": "queue"})
        return httpx.Response(200, content=b"\xff\xd8jpegdata", headers={"content-type": "image/jpeg"})

    data = asyncio.run(generate_image("شعار تجريبي", make_settings(tmp_path), transport=httpx.MockTransport(handler)))
    assert data.startswith(b"\xff\xd8")
    assert calls["count"] == 2


def test_generate_image_fails_when_no_route_works(tmp_path, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": True})

    with pytest.raises(ImageGenerationError):
        asyncio.run(generate_image("شعار", make_settings(tmp_path), transport=httpx.MockTransport(handler)))


def test_generate_image_uses_paid_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    payload = base64.b64encode(b"png-bytes").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "image.pollinations.ai":
            return httpx.Response(503, json={"error": True})
        return httpx.Response(200, json={"choices": [{"message": {"images": [{"image_url": {"url": f"data:image/png;base64,{payload}"}}]}}]})

    settings = make_settings(tmp_path, image_model="google/gemini-3.1-flash-lite-image")
    data = asyncio.run(generate_image("logo", settings, transport=httpx.MockTransport(handler)))
    assert data == b"png-bytes"


def test_save_image_suffix_matches_magic(tmp_path):
    settings = make_settings(tmp_path)
    jpg = save_image(b"\xff\xd8abc", settings)
    png = save_image(b"\x89PNGabc", settings)
    assert jpg.suffix == ".jpg"
    assert png.suffix == ".png"
    assert jpg.read_bytes() == b"\xff\xd8abc"
    assert jpg.parent == tmp_path / "generated"
