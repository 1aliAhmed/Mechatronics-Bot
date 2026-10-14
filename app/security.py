from __future__ import annotations

import time
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Update

from app.audit import AuditLogger
from app.config import Settings
from app.db import Database


def is_bound_chat(chat_id: int | None, bound_id: int) -> bool:
    return chat_id == bound_id


def is_privileged(status: str | None, user_id: int, admin_ids: frozenset[int] | set[int]) -> bool:
    return user_id in admin_ids or status in {"creator", "administrator"}


async def is_community_admin(settings: Settings, db: Database, bot: Any, user_id: int) -> bool:
    """Bound-community admin check with caching; failures keep the last verdict."""
    if user_id in settings.admin_ids:
        return True
    row = db.one("SELECT is_admin,checked_at FROM admin_cache WHERE user_id=?", (user_id,))
    now = time.time()
    if row and now - float(row["checked_at"]) < settings.admin_cache_seconds:
        return bool(row["is_admin"])
    try:
        member = await bot.get_chat_member(settings.community_chat_id, user_id)
        allowed = member.status in {"creator", "administrator"}
    except Exception:
        # Transient API failure: keep the last known verdict and never cache the failure.
        return bool(row["is_admin"]) if row else False
    db.execute("INSERT INTO admin_cache(user_id,is_admin,checked_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET is_admin=excluded.is_admin,checked_at=excluded.checked_at", (user_id, int(allowed), now))
    return allowed


class CommunityGuard(BaseMiddleware):
    """Central authorization boundary for every Telegram update."""
    def __init__(self, settings: Settings, db: Database, audit: AuditLogger):
        self.settings, self.db, self.audit = settings, db, audit

    async def _admin(self, bot: Any, user_id: int) -> bool:
        return await is_community_admin(self.settings, self.db, bot, user_id)

    async def __call__(self, handler, event: Update, data: dict[str, Any]):
        bot = data.get("bot")
        message = event.message or event.edited_message or event.channel_post or event.edited_channel_post
        callback = event.callback_query
        chat_member = getattr(event, "chat_member", None)
        my_member = getattr(event, "my_chat_member", None)
        if my_member is not None:
            return await handler(event, data)
        if chat_member is not None:
            if chat_member.chat.id != self.settings.community_chat_id:
                return None
            return await handler(event, data)
        chat = message.chat if message else (callback.message.chat if callback and callback.message else None)
        user = (message.from_user if message else callback.from_user if callback else None)
        if chat is None:
            return None
        if chat.type != "private":
            if self.db.chat_row(chat.id) is None:
                self.db.upsert_chat(chat.id, chat.title or "", chat.type)
                self.audit.record("security", chat_id=chat.id, user_id=user.id if user else None, kind="chat_registered", content=f"تسجيل محادثة: {chat.title or chat.id}")
            if message is not None and getattr(message, "message_thread_id", None):
                created = getattr(message, "forum_topic_created", None)
                edited = getattr(message, "forum_topic_edited", None)
                title = getattr(created, "title", None) or getattr(edited, "name", None)
                self.db.topic_upsert(chat.id, int(message.message_thread_id), str(title) if title else None)
            if callback and (user is None or not await self._admin(bot, user.id)):
                await callback.answer("هذا الإجراء لمشرفي المجتمع المرتبط فقط.", show_alert=True)
                return None
            return await handler(event, data)
        # Private chats are open to everyone. Admin-only features (sources pipeline,
        # filter curation) enforce their own checks; public usage flows through the
        # fair-use quota in app/quota.py.
        if user is None:
            return None
        return await handler(event, data)
