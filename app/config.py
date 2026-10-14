from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _model_allowed(model: str, paid: tuple[str, ...]) -> bool:
    """Free models are always allowed; paid models only when explicitly listed."""
    return model.endswith(":free") or model in paid


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    community_chat_id: int
    community_username: str
    community_url: str
    audio_models: tuple[str, ...]
    max_media_bytes: int
    max_text_chars: int
    log_topic_id: int | None
    admin_ids: frozenset[int]
    openrouter_api_key: str
    chat_model: str
    vision_model: str
    dry_run: bool
    rate_limit_rpm: int
    daily_cap: int
    data_dir: Path
    warning_delete_seconds: int
    welcome_enabled: bool
    welcome_delete_seconds: int
    mute_warning_seconds: int
    source_image_limit: int
    source_web_image_limit: int
    public_source_pages: int
    strike_decay_days: int
    dm_quota_1h: int
    dm_quota_5h: int
    dm_quota_24h: int
    repo_url: str
    admin_cache_seconds: int
    context_token_budget: int
    audit_retention_days: int
    groq_api_key: str
    groq_whisper_model: str
    groq_base_url: str
    groq_chat_model: str
    chat_fallbacks: tuple[str, ...]
    vision_fallbacks: tuple[str, ...]
    paid_models: tuple[str, ...]
    groq_chat_first: bool
    image_model: str

    @classmethod
    def from_env(cls, *, require_runtime: bool = False) -> "Settings":
        chat_id = _int("COMMUNITY_CHAT_ID", 0)
        topic = _int("LOG_TOPIC_ID", 0)
        admins = frozenset(int(v.strip()) for v in os.getenv("ADMIN_IDS", "").split(",") if v.strip())
        result = cls(
            telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
            community_chat_id=_int("BOUND_COMMUNITY_ID", chat_id),
            community_username=os.getenv("BOUND_COMMUNITY_USERNAME", "").strip().lstrip("@"),
            community_url=os.getenv("BOUND_COMMUNITY_URL", "").strip(),
            audio_models=tuple(v.strip() for v in os.getenv("AUDIO_MODELS", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free").split(",") if v.strip()),
            max_media_bytes=max(1024, _int("MAX_MEDIA_BYTES", 18_874_368)),
            max_text_chars=max(1000, _int("MAX_TEXT_CHARS", 12000)),
            log_topic_id=topic or None,
            admin_ids=admins,
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            chat_model=os.getenv("CHAT_MODEL", "inclusionai/ling-3.0-flash-sante:free"),
            vision_model=os.getenv("VISION_MODEL", "dots-studio/dots-3-note-preview:free"),
            dry_run=_bool("DRY_RUN", True),
            rate_limit_rpm=max(1, _int("RATE_LIMIT_RPM", 8)),
            daily_cap=max(1, _int("DAILY_CAP", 200)),
            data_dir=Path(os.getenv("DATA_DIR", "data")).expanduser(),
            warning_delete_seconds=max(0, _int("WARNING_DELETE_SECONDS", 60)),
            welcome_enabled=_bool("WELCOME_ENABLED", True),
            welcome_delete_seconds=max(0, _int("WELCOME_DELETE_SECONDS", 60)),
            mute_warning_seconds=max(0, _int("MUTE_WARNING_SECONDS", 15)),
            source_image_limit=max(0, _int("SOURCE_IMAGE_LIMIT", 30)),
            source_web_image_limit=max(0, _int("SOURCE_WEB_IMAGE_LIMIT", 4)),
            # Page cap for non-admin source jobs (admins keep MAX_SOURCE_PAGES); 0 disables the cap.
            public_source_pages=max(0, _int("PUBLIC_SOURCE_PAGES", 10)),
            strike_decay_days=max(1, _int("STRIKE_DECAY_DAYS", 30)),
            dm_quota_1h=max(0, _int("DM_QUOTA_1H", 10)),
            dm_quota_5h=max(0, _int("DM_QUOTA_5H", 0)),
            dm_quota_24h=max(0, _int("DM_QUOTA_24H", 0)),
            repo_url=os.getenv("REPO_URL", "").strip(),
            admin_cache_seconds=max(30, _int("ADMIN_CACHE_SECONDS", 900)),
            context_token_budget=max(1000, _int("CONTEXT_TOKEN_BUDGET", 24000)),
            audit_retention_days=max(1, _int("AUDIT_RETENTION_DAYS", 90)),
            # Optional: Groq's own free-tier Whisper transcription. An empty key keeps the
            # OpenRouter audio models as the only route, so the app boots without Groq.
            groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
            groq_whisper_model=os.getenv("GROQ_WHISPER_MODEL", "").strip() or "whisper-large-v3",
            groq_base_url=os.getenv("GROQ_BASE_URL", "").strip().rstrip("/") or "https://api.groq.com/openai/v1",
            groq_chat_model=os.getenv("GROQ_CHAT_MODEL", "").strip() or "openai/gpt-oss-120b",
            chat_fallbacks=tuple(v.strip() for v in os.getenv("CHAT_FALLBACK_MODELS", "nvidia/nemotron-3-super-120b-a12b:free,poolside/laguna-s-2.1:free").split(",") if v.strip()),
            vision_fallbacks=tuple(v.strip() for v in os.getenv("VISION_FALLBACK_MODELS", "").split(",") if v.strip()),
            # Optional allowlist for paid models (OpenRouter ids without the :free suffix).
            paid_models=tuple(v.strip() for v in os.getenv("PAID_MODELS", "").split(",") if v.strip()),
            # True keeps Groq's free chat first for text-only messages; False makes the configured
            # chat model primary and uses Groq only as the last fallback.
            groq_chat_first=_bool("GROQ_CHAT_FIRST", True),
            # Optional paid image-generation fallback (used only when free generation fails).
            image_model=os.getenv("IMAGE_MODEL", "").strip(),
        )
        if require_runtime:
            # GROQ_API_KEY is optional and exempt from the ':free' suffix rule: Groq manages its own free tier.
            missing = [name for name, value in (("TELEGRAM_TOKEN", result.telegram_token), ("OPENROUTER_API_KEY", result.openrouter_api_key)) if not value]
            if not os.getenv("BOUND_COMMUNITY_ID", "").strip():
                missing.append("BOUND_COMMUNITY_ID (owner-supplied negative group ID)")
            if result.community_chat_id >= 0:
                missing.append("BOUND_COMMUNITY_ID must be the group's negative numeric ID")
            if any(not _model_allowed(model, result.paid_models) for model in result.audio_models):
                raise RuntimeError("AUDIO_MODELS must be :free models or listed in PAID_MODELS")
            if missing:
                raise RuntimeError("Missing required configuration: " + ", ".join(missing))
            if not _model_allowed(result.chat_model, result.paid_models) or not _model_allowed(result.vision_model, result.paid_models):
                raise RuntimeError("CHAT_MODEL and VISION_MODEL must be :free models or listed in PAID_MODELS")
            if any(not _model_allowed(model, result.paid_models) for model in result.chat_fallbacks + result.vision_fallbacks):
                raise RuntimeError("Fallback models must be :free models or listed in PAID_MODELS")
            if result.image_model and not _model_allowed(result.image_model, result.paid_models):
                raise RuntimeError("IMAGE_MODEL must be a :free model or listed in PAID_MODELS")
        return result


def get_settings(*, require_runtime: bool = False) -> Settings:
    return Settings.from_env(require_runtime=require_runtime)
