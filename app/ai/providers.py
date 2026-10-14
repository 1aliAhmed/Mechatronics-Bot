from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

# One shared Arabic message for "no usable transcription route" so callers and tests agree.
AUDIO_UNAVAILABLE = "تعذّر تفريغ التسجيل الآن؛ أعد الإرسال أو اكتب النص."

GROQ_DEFAULT_MODEL = "whisper-large-v3"
GROQ_DEFAULT_CHAT_MODEL = "openai/gpt-oss-120b"
GROQ_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"

# Containers Groq's transcription endpoint accepts, keyed by the MIME the caller reported.
AUDIO_SUFFIXES = {"audio/ogg": "ogg", "audio/oga": "ogg", "audio/opus": "opus", "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/wav": "wav", "audio/x-wav": "wav", "audio/webm": "webm", "audio/flac": "flac", "audio/x-flac": "flac"}


def has_image_parts(messages: list[dict[str, Any]]) -> bool:
    """True when any outgoing message carries an image part (so vision routing applies)."""
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"image_url", "input_image"}:
                    return True
    return False


def message_text(payload: dict[str, Any]) -> str:
    """Extract assistant text, falling back to the reasoning field used by reasoning-only models."""
    message = (payload.get("choices") or [{}])[0].get("message", {})
    return str(message.get("content") or message.get("reasoning") or "")


class GroqChat:
    """Groq free-tier chat completions via its OpenAI-compatible endpoint (no ':free' rule applies)."""

    def __init__(self, api_key: str, model: str = GROQ_DEFAULT_CHAT_MODEL, base_url: str = GROQ_DEFAULT_BASE_URL, transport: httpx.AsyncBaseTransport | None = None, rpm: int = 20):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._transport = transport
        self.interval = 60 / max(1, rpm)
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def _pace(self) -> None:
        async with self._lock:
            wait = self.interval - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    async def chat(self, messages: list[dict[str, Any]], **params: Any) -> tuple[str, dict[str, Any]]:
        await self._pace()
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=120, transport=self._transport) as client:
            for attempt in range(4):
                response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json={"model": self.model, "messages": messages, **params})
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 3:
                        response.raise_for_status()
                    await asyncio.sleep(min(20, 2 ** attempt))
                    continue
                response.raise_for_status()
                data = response.json()
                return message_text(data), data
        raise RuntimeError("Groq chat request exhausted retries")


def audio_upload_parts(mime: str, stem: str = "voice") -> tuple[str, str]:
    """Derive the multipart (filename, content-type) pair from the caller's audio MIME type."""
    kind = str(mime or "").split(";")[0].strip().lower()
    suffix = AUDIO_SUFFIXES.get(kind) or (kind.split("/")[-1] if kind.startswith("audio/") else "ogg")
    content_type = kind if kind.startswith("audio/") else (mimetypes.guess_type(f"{stem}.{suffix}")[0] or "application/octet-stream")
    return f"{stem}.{suffix}", content_type


class OpenRouter:
    def __init__(self, api_key: str, rpm: int = 8, base_url: str = "https://openrouter.ai/api/v1", groq_chat: GroqChat | None = None, chat_fallbacks: tuple[str, ...] = (), vision_fallbacks: tuple[str, ...] = (), paid_models: tuple[str, ...] = (), groq_first: bool = True, app_title: str = "", app_referer: str = ""):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.interval = 60 / max(1, rpm)
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self.groq_chat = groq_chat
        self.chat_fallbacks = tuple(chat_fallbacks)
        self.vision_fallbacks = tuple(vision_fallbacks)
        self.paid_models = tuple(paid_models)
        self.groq_first = groq_first
        self.app_title = app_title
        self.app_referer = app_referer

    def _check(self, model: str) -> None:
        """Free models are always allowed; paid models only when listed in PAID_MODELS."""
        if model.endswith(":free") or model in self.paid_models:
            return
        raise ValueError("Only :free models are allowed unless listed in PAID_MODELS")

    async def _pace(self) -> None:
        async with self._lock:
            wait = self.interval - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        await self._pace()
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        for name, value in (("HTTP-Referer", self.app_referer), ("X-Title", self.app_title)):
            if value and value.isascii():
                headers[name] = value
        async with httpx.AsyncClient(timeout=120) as client:
            for attempt in range(5):
                response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 4:
                        response.raise_for_status()
                    await asyncio.sleep(min(30, 2 ** attempt))
                    continue
                response.raise_for_status()
                return response.json()
        raise RuntimeError("OpenRouter request exhausted retries")

    async def _chat_once(self, model: str, messages: list[dict[str, Any]], **params: Any) -> tuple[str, dict[str, Any]]:
        self._check(model)
        data = await self._post({"model": model, "messages": messages, **params})
        return message_text(data), data

    async def chat(self, model: str, messages: list[dict[str, Any]], **params: Any) -> tuple[str, dict[str, Any]]:
        """Try the configured chat route order, then the requested model and matching fallbacks."""
        self._check(model)
        wants_image = has_image_parts(messages)
        use_groq = self.groq_chat is not None and not wants_image
        errors: list[str] = []

        async def groq_attempt() -> tuple[str, dict[str, Any]] | None:
            try:
                text, data = await self.groq_chat.chat(messages, **params)
                if text.strip():
                    return text, data
                errors.append("groq:empty")
            except Exception as exc:
                errors.append(f"groq:{str(exc)[:80]}")
                log.info("Groq chat route failed; trying OpenRouter", exc_info=True)
            return None

        if use_groq and self.groq_first:
            result = await groq_attempt()
            if result is not None:
                return result
        fallbacks = self.vision_fallbacks if wants_image else self.chat_fallbacks
        routes = [model] + [item for item in fallbacks if item != model]
        for candidate in routes:
            try:
                text, data = await self._chat_once(candidate, messages, **params)
                if text.strip() or candidate == routes[-1]:
                    return text, data
                errors.append(f"{candidate}:empty")
            except Exception as exc:
                errors.append(f"{candidate}:{str(exc)[:80]}")
        if use_groq and not self.groq_first:
            result = await groq_attempt()
            if result is not None:
                return result
        raise RuntimeError("All chat routes failed: " + " | ".join(errors[-3:]))

    async def audio(self, models: tuple[str, ...], prompt: str, audio: bytes, mime: str = "audio/wav") -> tuple[str, dict[str, Any]]:
        encoded = base64.b64encode(audio).decode("ascii")
        last_error: Exception | None = None
        for model in models:
            try:
                return await self._chat_once(model, [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "input_audio", "input_audio": {"data": encoded, "format": mime.split("/")[-1]}}]}], temperature=0.1)
            except Exception as exc:
                last_error = exc
        raise RuntimeError(AUDIO_UNAVAILABLE) from last_error

    async def vision(self, model: str, prompt: str, image: bytes, mime: str = "image/png") -> tuple[str, dict[str, Any]]:
        encoded = base64.b64encode(image).decode("ascii")
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}]}]
        self._check(model)
        errors: list[str] = []
        routes = [model] + [item for item in self.vision_fallbacks if item != model]
        for candidate in routes:
            try:
                text, data = await self._chat_once(candidate, messages, temperature=0.1)
                if text.strip() or candidate == routes[-1]:
                    return text, data
                errors.append(f"{candidate}:empty")
            except Exception as exc:
                errors.append(f"{candidate}:{str(exc)[:80]}")
        raise RuntimeError("All vision routes failed: " + " | ".join(errors[-3:]))


class GroqWhisper:
    """Groq free-tier Whisper transcription via its OpenAI-compatible audio endpoint.

    Groq runs its own free tier, so no ':free' suffix rule applies to this model id.
    """

    def __init__(self, api_key: str, model: str = GROQ_DEFAULT_MODEL, base_url: str = GROQ_DEFAULT_BASE_URL, transport: httpx.AsyncBaseTransport | None = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._transport = transport

    async def transcribe(self, audio: bytes, mime: str = "audio/ogg") -> tuple[str, dict[str, Any]]:
        if not audio:
            raise ValueError("التسجيل فارغ.")
        filename, content_type = audio_upload_parts(mime)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        data = {"model": self.model}
        files = {"file": (filename, audio, content_type)}
        async with httpx.AsyncClient(timeout=120, transport=self._transport) as client:
            for attempt in range(5):
                response = await client.post(f"{self.base_url}/audio/transcriptions", headers=headers, data=data, files=files)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 4:
                        response.raise_for_status()
                    await asyncio.sleep(min(30, 2 ** attempt))
                    continue
                response.raise_for_status()
                payload = response.json()
                text = str(payload.get("text") or "").strip()
                if not text:
                    raise ValueError("لم يُعثر على نص في التسجيل.")
                return text, payload
        raise RuntimeError("Groq request exhausted retries")


def audio_route(settings: Any) -> str:
    """Primary voice-transcription route: 'groq' when GROQ_API_KEY is set, else 'openrouter'."""
    return "groq" if str(getattr(settings, "groq_api_key", "") or "").strip() else "openrouter"


def build_transcriber(settings: Any) -> GroqWhisper | None:
    """Build the Groq Whisper client only when a key is configured; otherwise audio stays on OpenRouter."""
    if audio_route(settings) != "groq":
        return None
    return GroqWhisper(settings.groq_api_key, settings.groq_whisper_model, settings.groq_base_url)


async def transcribe_audio(transcriber: GroqWhisper | None, provider: OpenRouter, models: tuple[str, ...], prompt: str, audio: bytes, mime: str = "audio/ogg") -> tuple[str, dict[str, Any], str, str]:
    """Transcribe voice with Groq Whisper first, then the OpenRouter audio-model loop.

    Returns (transcript, raw response, route, model label); raises an Arabic RuntimeError
    when every route fails.
    """
    if transcriber is not None:
        try:
            text, response = await transcriber.transcribe(audio, mime)
        except Exception:
            log.warning("Groq Whisper failed; falling back to OpenRouter audio models", exc_info=True)
        else:
            return text, response, "groq", transcriber.model
    try:
        text, response = await provider.audio(models, prompt, audio, mime)
    except Exception as exc:
        raise RuntimeError(AUDIO_UNAVAILABLE) from exc
    return text, response, "openrouter", ",".join(models)
