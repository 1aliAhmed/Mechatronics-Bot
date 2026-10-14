from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, EphemeralMessageParameters, Message

from app.config import Settings
from app.db import Database

log = logging.getLogger(__name__)


def load_rules(path: Path) -> str:
    """Load the owner-editable Arabic community rules."""
    return path.read_text(encoding="utf-8").strip()


def welcome_text(name: str, template: str) -> str:
    """Render the owner-editable welcome prompt for a joining member."""
    return template.format(name=name)


def message_chunks(text: str, limit: int = 3999) -> list[str]:
    """Split text into Telegram-safe chunks, preferring paragraph boundaries."""
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit + 1)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return chunks


def joined_from_left_or_kicked(event: ChatMemberUpdated) -> bool:
    return event.old_chat_member.status in {"left", "kicked"} and event.new_chat_member.status == "member"


def install_community(settings: Settings, db: Database, rules_path: Path, welcome_path: Path) -> Router:
    router = Router()
    try:
        welcome_template = welcome_path.read_text(encoding="utf-8").strip()
    except Exception:
        log.exception("Could not load welcome prompt")
        welcome_template = "أهلاً {name}، مرحباً بك في مجتمعنا."

    @router.message(Command("rules"))
    async def rules(message: Message) -> None:
        try:
            rules_text = load_rules(rules_path)
        except Exception:
            log.exception("Could not load community rules")
            rules_text = "قواعد المجتمع غير متاحة حالياً؛ يرجى التواصل مع المشرفين."
        for chunk in message_chunks(rules_text):
            await message.answer(chunk)

    async def expire_group_message(bot, chat_id: int, message_id: int) -> None:
        if settings.welcome_delete_seconds <= 0:
            return
        await asyncio.sleep(settings.welcome_delete_seconds)
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception:
            log.debug("Welcome fallback message was already removed", exc_info=True)

    @router.chat_member()
    async def welcome(event: ChatMemberUpdated) -> None:
        if not settings.welcome_enabled or event.chat.id != settings.community_chat_id:
            return
        if not joined_from_left_or_kicked(event):
            return
        user = event.new_chat_member.user
        name = user.full_name or user.first_name or "صديقنا الجديد"
        try:
            db.remember_community_user(user.id, user.username, name)
        except Exception:
            log.exception("Could not save joining member identity")
        try:
            text = welcome_text(name, welcome_template)
            try:
                sent = await event.bot.send_message(
                    settings.community_chat_id,
                    text,
                    ephemeral_message_parameters=EphemeralMessageParameters(receiver_user_id=user.id),
                )
                ephemeral_id = getattr(sent, "ephemeral_message_id", None)
                if ephemeral_id is None:
                    raise RuntimeError("Telegram did not return an ephemeral message ID")
                if settings.welcome_delete_seconds > 0:
                    async def expire_ephemeral() -> None:
                        await asyncio.sleep(settings.welcome_delete_seconds)
                        try:
                            await event.bot.delete_ephemeral_message(settings.community_chat_id, user.id, ephemeral_id)
                        except Exception:
                            log.debug("Ephemeral welcome could not be deleted", exc_info=True)
                    asyncio.create_task(expire_ephemeral())
                return
            except Exception:
                log.info("Ephemeral welcome unavailable for user %s; trying DM", user.id, exc_info=True)
            try:
                await event.bot.send_message(user.id, text)
                return
            except Exception:
                log.info("Could not DM new member %s; using temporary group message", user.id, exc_info=True)
            import html
            mention = f'<a href="tg://user?id={user.id}">{html.escape(name)}</a>'
            sent = await event.bot.send_message(
                settings.community_chat_id,
                f"{html.escape(text)}\n\nمرحباً بك يا {mention}!",
                parse_mode="HTML",
                disable_notification=True,
            )
            if settings.welcome_delete_seconds > 0:
                asyncio.create_task(expire_group_message(event.bot, settings.community_chat_id, sent.message_id))
        except Exception:
            log.exception("Welcome handling failed for new member %s", user.id)

    @router.my_chat_member()
    async def bot_membership(event: ChatMemberUpdated) -> None:
        status = event.new_chat_member.status
        if status in {"left", "kicked"}:
            db.remove_chat(event.chat.id)
            return
        if status in {"member", "administrator"}:
            db.upsert_chat(event.chat.id, event.chat.title or "", event.chat.type)

    return router
