from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message

from app.ai.providers import GroqChat, OpenRouter, build_transcriber
from app.imagegen import generate_image, save_image
from app.audit import AuditLogger
from app.config import get_settings
from app.db import Database
from app.flows.admin import install_admin, set_commands
from app.flows.clean import install_clean
from app.flows.community import install_community
from app.flows.moderation import create_filter, install_moderation
from app.flows.visuals import cleanup_image, compose_visual, render_visual, visual_kind
from app.quota import QuotaService, quota_message
from app.security import CommunityGuard, is_community_admin
from app.ai.queue import JobQueue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings(require_runtime=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.data_dir / "bot.db")
    audit = AuditLogger(db, settings.data_dir / "logs")
    audit.prune(settings.audit_retention_days)
    bot = Bot(settings.telegram_token)
    dp = Dispatcher()
    try:
        bound = await bot.get_chat(settings.community_chat_id)
    except Exception as exc:
        raise RuntimeError(f"BOUND_COMMUNITY_ID verification failed for {settings.community_chat_id}; check id and bot membership: {exc}") from exc
    if settings.community_username and (bound.username or "").casefold() != settings.community_username.casefold():
        raise RuntimeError(f"BOUND_COMMUNITY_USERNAME mismatch: expected @{settings.community_username}, got @{bound.username or ''}")
    dp.update.middleware(CommunityGuard(settings, db, audit))
    provider = OpenRouter(
        settings.openrouter_api_key,
        settings.rate_limit_rpm,
        groq_chat=GroqChat(settings.groq_api_key, settings.groq_chat_model, settings.groq_base_url) if settings.groq_api_key else None,
        chat_fallbacks=settings.chat_fallbacks,
        vision_fallbacks=settings.vision_fallbacks,
        paid_models=settings.paid_models,
        groq_first=settings.groq_chat_first,
    )
    # Groq Whisper transcription is optional; without GROQ_API_KEY the OpenRouter audio models are used.
    transcriber = build_transcriber(settings)
    project_root = __import__("pathlib").Path(__file__).parents[1]
    dp.include_router(install_community(settings, db, project_root / "prompts" / "rules_ar.md", project_root / "prompts" / "welcome_ar.md"))
    dp.include_router(install_moderation(settings, db, create_filter(settings, db), audit))
    queue = JobQueue(db)
    dp.include_router(install_clean(settings, db, audit, provider, queue, bot))
    quota = QuotaService(db, settings)
    dp.include_router(install_admin(settings, db, audit, provider, __import__("pathlib").Path(__file__).parents[1] / "prompts" / "study_harness.md", transcriber, quota))

    @dp.message(Command("ping"))
    async def ping(message: Message) -> None:
        if message.chat.id == settings.community_chat_id:
            await message.answer("البوت يعمل.")

    @dp.message(F.chat.type == "private", F.text.regexp(r"^/(visual|image|draw)(-dot)?(\s|$)"))
    async def visual(message: Message) -> None:
        if not message.from_user:
            return
        if message.from_user.id not in settings.admin_ids and not await is_community_admin(settings, db, bot, message.from_user.id):
            retry = quota.consume(message.from_user.id)
            if retry:
                await message.answer(quota_message(settings, retry))
                return
        request = (message.text or "").partition(" ")[2].strip()
        visual_started = __import__("time").monotonic()
        audit.record("incoming", chat_id=message.chat.id, user_id=message.from_user.id, kind="visual", content=request)
        model_response = {}
        if not request:
            await message.answer("اكتب وصف الرسم بعد الأمر (/visual أو /image) أو بصيغة «ارسم …» وسأجهّزه.")
            return
        kind = "dot" if (message.text or "").startswith("/visual-dot") else "python"
        try:
            if visual_kind(request) == "illustration" and "```" not in request:
                data = await generate_image(request, settings)
                generated = save_image(data, settings)
                await message.answer_photo(FSInputFile(generated))
                cleanup_image(generated)
                audit.record("outgoing", chat_id=message.chat.id, user_id=message.from_user.id, kind="visual", content="تم إنشاء صورة", file_refs=[str(generated)], model=settings.image_model or None, params={"kind": "illustration"}, latency_ms=int((__import__("time").monotonic() - visual_started) * 1000))
                return
            if "```" not in request and not ("import " in request or "digraph" in request or "graph " in request):
                image, generated_response, _ = await compose_visual(provider, settings.chat_model, request, kind)
                model_response = generated_response
            else:
                code = request
                if kind == "python":
                    code += "\nimport matplotlib.pyplot as plt\nplt.savefig('visual.png', dpi=160, bbox_inches='tight')"
                image = await asyncio.to_thread(render_visual, code, kind=kind)
            from aiogram.types import FSInputFile
            await message.answer_photo(FSInputFile(image))
            cleanup_image(image)
            audit.record("outgoing", chat_id=message.chat.id, user_id=message.from_user.id, kind="visual", content="تم إنشاء الصورة", file_refs=[str(image)], model=settings.chat_model if model_response else None, params={"kind": kind, "model_params": {"temperature": 0.1} if model_response else {}, "usage": model_response.get("usage", {})}, latency_ms=int((__import__("time").monotonic() - visual_started) * 1000))
        except Exception as exc:
            error_text = "تعذّر إنشاء الرسم؛ جرّب وصفاً أبسط."
            await message.answer(error_text)
            audit.record("outgoing", chat_id=message.chat.id, user_id=message.from_user.id, kind="visual_error", content=error_text, model=settings.chat_model if model_response else None, params={"kind": kind, "error": str(exc)[:500]}, latency_ms=int((__import__("time").monotonic() - visual_started) * 1000))

    async def maintenance() -> None:
        while True:
            await asyncio.sleep(24 * 3600)
            try:
                audit.prune(settings.audit_retention_days)
                log.info("Periodic audit prune complete")
            except Exception:
                log.exception("Periodic audit prune failed")

    maintenance_task = asyncio.create_task(maintenance())
    await queue.start()
    await bot.delete_webhook(drop_pending_updates=False)
    await set_commands(bot, settings.community_chat_id)
    log.info("Megatronics Bot polling started")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


def main() -> None:
    import asyncio
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
