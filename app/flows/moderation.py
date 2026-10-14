from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, ChatPermissions, EphemeralMessageParameters,
                           InlineKeyboardButton, InlineKeyboardMarkup, Message)

from app.audit import AuditLogger
from app.config import Settings
from app.db import Database
from app.filters.engine import WordFilter

log = logging.getLogger(__name__)
router = Router()


def moderation_action(dry_run: bool) -> str:
    return "log" if dry_run else "enforce"


def mute_seconds(strike: int) -> int | None:
    if strike >= 5:
        return 24 * 3600
    if strike == 4:
        return 30 * 60
    if strike == 3:
        return 15 * 60
    return None


_admin_checks: dict[tuple[int, int], tuple[bool, float]] = {}

MUTE_NOTICE = "هذه المجموعة مقفلة مؤقتاً؛ لا يمكن إرسال الرسائل الآن. للاستفسار راسل المشرفين."


def is_mute_exempt(status: str | None, user_id: int, admin_ids) -> bool:
    return user_id in admin_ids or status in {"creator", "administrator"}


def mute_label(seconds: int) -> str:
    if seconds >= 3600:
        return f"{seconds // 3600} ساعة"
    return f"{seconds // 60} دقيقة"


def create_filter(settings: Settings, db: Database) -> WordFilter:
    words: dict[str, list[str]] = {"en": [], "ar": []}
    for row in db.all("SELECT language,word FROM blocked_words"):
        words.setdefault(str(row["language"]), []).append(str(row["word"]))
    return WordFilter(words)


def install_moderation(settings: Settings, db: Database, engine: WordFilter, audit: AuditLogger | None = None) -> Router:
    async def is_chat_admin(bot, chat_id: int, user_id: int) -> bool:
        if is_mute_exempt(None, user_id, settings.admin_ids):
            return True
        key = (chat_id, user_id)
        now = time.time()
        cached = _admin_checks.get(key)
        if cached and now - cached[1] < settings.admin_cache_seconds:
            return cached[0]
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            allowed = is_mute_exempt(member.status, user_id, settings.admin_ids)
        except Exception:
            # Transient API failure: keep the last known verdict, never cache the failure.
            return cached[0] if cached else False
        _admin_checks[key] = (allowed, now)
        if len(_admin_checks) > 500:
            for stale in list(_admin_checks)[: len(_admin_checks) - 500]:
                _admin_checks.pop(stale, None)
        return allowed

    @router.message(Command("block"))
    async def block(message: Message) -> None:
        if message.chat.id != settings.community_chat_id or not message.from_user:
            return
        try:
            member = await message.bot.get_chat_member(settings.community_chat_id, message.from_user.id)
            if member.status not in {"creator", "administrator"}:
                return
        except Exception:
            return
        word = (message.text or "").partition(" ")[2].strip()
        if not word:
            await message.reply("استخدم: /block كلمة")
            return
        lang = "ar" if any("\u0600" <= c <= "\u08ff" for c in word) else "en"
        added = engine.add(word, lang)
        if added:
            db.execute("INSERT OR IGNORE INTO blocked_words(language,word) VALUES(?,?)", (lang, word))
        await message.reply("تمت إضافة الكلمة." if added else "الكلمة موجودة بالفعل.")

    @router.message(Command("unblock"))
    async def unblock(message: Message) -> None:
        if message.chat.id != settings.community_chat_id or not message.from_user:
            return
        try:
            member = await message.bot.get_chat_member(settings.community_chat_id, message.from_user.id)
            if member.status not in {"creator", "administrator"}:
                return
        except Exception:
            return
        word = (message.text or "").partition(" ")[2].strip()
        if word and engine.remove(word):
            db.execute("DELETE FROM blocked_words WHERE word=? COLLATE NOCASE", (word,))
            await message.reply("تم حذف الكلمة.")
        else:
            await message.reply("لم أجد هذه الكلمة.")

    @router.message(Command("reset"))
    async def reset(message: Message) -> None:
        if message.chat.id != settings.community_chat_id or not message.from_user:
            return
        try:
            member = await message.bot.get_chat_member(settings.community_chat_id, message.from_user.id)
            if member.status not in {"creator", "administrator"}:
                return
        except Exception:
            return
        target = message.reply_to_message.from_user if message.reply_to_message else None
        argument = (message.text or "").partition(" ")[2].strip()
        if target is None and argument:
            token = argument.split(maxsplit=1)[0]
            if token.startswith("@"):
                user_id = db.community_user_id(token)
            else:
                try:
                    user_id = int(token)
                except ValueError:
                    user_id = None
            if user_id is None:
                await message.reply("لم أتمكن من تحديد العضو. استخدم رداً على رسالته أو /reset <user_id|@username>.")
                return
        elif target is not None:
            user_id = target.id
        else:
            await message.reply("استخدم رداً على رسالة العضو أو /reset <user_id|@username>.")
            return
        db.clear_strikes(user_id)
        db.execute("DELETE FROM violations WHERE user_id=?", (user_id,))
        await message.reply(f"تم تصفير مخالفات المستخدم {user_id}.")

    @router.message(F.chat.type.in_({"group", "supergroup"}), Command("warns"))
    async def warns(message: Message) -> None:
        if not message.from_user or not await is_chat_admin(message.bot, message.chat.id, message.from_user.id):
            return
        target = message.reply_to_message.from_user if message.reply_to_message else None
        argument = (message.text or "").partition(" ")[2].strip()
        if target is not None:
            user_id = target.id
        elif argument:
            token = argument.split(maxsplit=1)[0]
            if token.startswith("@"):
                user_id = db.community_user_id(token)
            elif token.isdigit():
                user_id = int(token)
            else:
                user_id = None
            if user_id is None:
                await message.reply("لم أتمكن من تحديد العضو. استخدم رداً على رسالته أو /warns <user_id|@username>.")
                return
        else:
            await message.reply("استخدم رداً على رسالة العضو أو /warns <user_id|@username>.")
            return
        strike = db.strike_window(user_id, settings.strike_decay_days)
        rows = db.all("SELECT word,substr(text,1,70) AS snippet,created_at FROM violations WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,))
        lines = [f"ملف العضو {user_id}", f"المخالفات خلال {settings.strike_decay_days} يوماً: {strike}"]
        if rows:
            lines.append("أحدث المخالفات:")
            for row in rows:
                lines.append(f"- {str(row['created_at'])[:16]} | {row['word']} | {str(row['snippet'])[:50]}")
        else:
            lines.append("لا مخالفات مسجلة.")
        await message.reply("\n".join(lines))

    @router.message(F.chat.type.in_({"group", "supergroup"}), Command("stats"))
    async def stats(message: Message) -> None:
        if not message.from_user or not await is_chat_admin(message.bot, message.chat.id, message.from_user.id):
            return
        day_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        month_cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        total = db.one("SELECT COUNT(*) AS n FROM violations WHERE created_at >= ?", (month_cutoff,))
        lines = ["إحصاءات الرقابة", f"المخالفات آخر ٣٠ يوماً: {int(total['n']) if total else 0}"]
        for row in db.all("SELECT substr(created_at,1,10) AS day, COUNT(*) AS n FROM violations WHERE created_at >= ? GROUP BY day ORDER BY day DESC", (day_cutoff,)):
            lines.append(f"- {row['day']}: {row['n']}")
        top_words = db.all("SELECT word, COUNT(*) AS n FROM violations WHERE created_at >= ? GROUP BY word ORDER BY n DESC LIMIT 5", (month_cutoff,))
        if top_words:
            lines.append("أكثر الكلمات: " + "، ".join(f"{row['word']} ({row['n']})" for row in top_words))
        top_users = [row for row in db.all("SELECT user_id, COUNT(*) AS n FROM violations WHERE created_at >= ? GROUP BY user_id ORDER BY n DESC LIMIT 5", (month_cutoff,)) if row["user_id"] is not None]
        if top_users:
            lines.append("أكثر المخالفين: " + "، ".join(f"{row['user_id']} ({row['n']})" for row in top_users))
        await message.reply("\n".join(lines))

    async def mute_notice(message: Message) -> None:
        deleted = False
        try:
            await message.delete()
            deleted = True
        except Exception:
            log.info("Unable to delete message in muted chat; verify bot delete rights", exc_info=True)
        log.info("muted group message chat=%s user=%s deleted=%s", message.chat.id, message.from_user.id if message.from_user else None, deleted)
        if not message.from_user:
            return
        text = MUTE_NOTICE
        try:
            sent = await message.bot.send_message(
                message.chat.id,
                text,
                ephemeral_message_parameters=EphemeralMessageParameters(receiver_user_id=message.from_user.id),
            )
            ephemeral_id = getattr(sent, "ephemeral_message_id", None)
            if ephemeral_id is None:
                raise RuntimeError("Telegram did not return an ephemeral message ID")
            if settings.mute_warning_seconds > 0:
                async def expire_notice() -> None:
                    await asyncio.sleep(settings.mute_warning_seconds)
                    try:
                        await message.bot.delete_ephemeral_message(message.chat.id, message.from_user.id, ephemeral_id)
                    except Exception:
                        log.debug("Mute notice could not be deleted", exc_info=True)
                asyncio.create_task(expire_notice())
        except Exception:
            log.info("Ephemeral mute notice unavailable; trying DM", exc_info=True)
            try:
                await message.bot.send_message(message.from_user.id, text)
            except Exception:
                log.info("Could not deliver mute notice to %s", message.from_user.id, exc_info=True)
        if audit:
            audit.record("outgoing", chat_id=message.chat.id, user_id=message.from_user.id, kind="mute", content=text, params={"warning_seconds": settings.mute_warning_seconds})

    async def offender_notice(message: Message, text: str) -> None:
        try:
            sent = await message.bot.send_message(
                message.chat.id,
                text,
                ephemeral_message_parameters=EphemeralMessageParameters(receiver_user_id=message.from_user.id),
            )
            ephemeral_id = getattr(sent, "ephemeral_message_id", None)
            if ephemeral_id is not None and settings.warning_delete_seconds > 0:
                async def expire_notice() -> None:
                    await asyncio.sleep(settings.warning_delete_seconds)
                    try:
                        await message.bot.delete_ephemeral_message(message.chat.id, message.from_user.id, ephemeral_id)
                    except Exception:
                        log.debug("Ephemeral offender notice could not be deleted", exc_info=True)
                asyncio.create_task(expire_notice())
            elif ephemeral_id is None:
                raise RuntimeError("Telegram did not return an ephemeral message ID")
        except Exception:
            log.info("Ephemeral notice unavailable; trying DM", exc_info=True)
            try:
                await message.bot.send_message(message.from_user.id, text)
            except Exception:
                log.info("Could not deliver private notice to %s", message.from_user.id, exc_info=True)

    async def warn_exempt(message: Message, hit: str, text: str) -> None:
        """Warning-only path for admins and the owner: the rules apply, strikes do not."""
        author = message.from_user.full_name if message.from_user else "غير معروف"
        log_text = f"مخالفة مرصودة (مشرف)\nالمستخدم: {author}\nالكلمة: {hit}\nالنص: {text[:700]}"
        if settings.dry_run:
            log.warning(log_text)
            if audit:
                audit.record("outgoing", chat_id=message.chat.id, user_id=message.from_user.id if message.from_user else None, kind="moderation", content=log_text, params={"dry_run": True, "actions": [], "admin": True})
            if settings.log_topic_id:
                try:
                    await message.bot.send_message(settings.community_chat_id, log_text, message_thread_id=settings.log_topic_id)
                except Exception:
                    log.exception("Could not send dry-run moderation log")
            return
        try:
            await message.delete()
        except Exception:
            log.exception("Unable to delete matched admin message; verify bot delete rights")
        if message.from_user:
            await offender_notice(
                message,
                "حُذفت رسالتك لاحتوائها كلمة من الكلمات المخالفة.\n"
                "الحسابات الإدارية قدوة للمجموعة؛ لذلك تُحذف الرسالة دائماً، ولا تُحتسب عليك مخالفات.",
            )
        if audit:
            audit.record("outgoing", chat_id=message.chat.id, user_id=message.from_user.id if message.from_user else None, kind="moderation", content=log_text, params={"dry_run": False, "actions": ["delete", "warn"], "admin": True})
        if settings.log_topic_id:
            try:
                await message.bot.send_message(settings.community_chat_id, log_text, message_thread_id=settings.log_topic_id)
            except Exception:
                log.exception("Unable to post admin moderation log")

    async def inspect(message: Message) -> None:
        text = message.text or message.caption or ""
        if message.from_user:
            db.remember_community_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
        row = db.chat_row(message.chat.id)
        if row is None:
            db.upsert_chat(message.chat.id, message.chat.title or "", message.chat.type)
            row = db.chat_row(message.chat.id)
        exempt = bool(message.from_user) and await is_chat_admin(message.bot, message.chat.id, message.from_user.id)
        if not exempt and row and row["muted"]:
            await mute_notice(message)
            return
        hit = engine.match(text)
        if not hit:
            if audit:
                audit.record("incoming", chat_id=message.chat.id, user_id=message.from_user.id if message.from_user else None, kind="group_message", content=text[:4000], file_refs=[])
            return
        if audit:
            audit.record("incoming", chat_id=message.chat.id, user_id=message.from_user.id if message.from_user else None, kind="moderation", content=text[:4000])
        if exempt:
            await warn_exempt(message, hit, text)
            return
        strike = db.strike_window(message.from_user.id, settings.strike_decay_days) if message.from_user else 0
        if settings.dry_run:
            log_text = f"مخالفة مرصودة (تجريبي)\nالمستخدم: {message.from_user.full_name if message.from_user else 'غير معروف'}\nالكلمة: {hit}\nالمخالفات الحالية: {strike}\nالنص: {text[:700]}"
            log.warning(log_text)
            if audit:
                audit.record("outgoing", chat_id=message.chat.id, user_id=message.from_user.id if message.from_user else None, kind="moderation", content=log_text, params={"dry_run": True, "actions": []})
            if settings.log_topic_id:
                try:
                    await message.bot.send_message(settings.community_chat_id, log_text, message_thread_id=settings.log_topic_id)
                except Exception:
                    log.exception("Could not send dry-run moderation log")
            return
        violation_id = db.insert("INSERT INTO violations(chat_id,user_id,word,text) VALUES(?,?,?,?)", (message.chat.id, message.from_user.id if message.from_user else None, hit, text[:4000]))
        strike = db.strike_window(message.from_user.id, settings.strike_decay_days) if message.from_user else 0
        log_text = f"مخالفة مرصودة (فعّال)\nالمستخدم: {message.from_user.full_name if message.from_user else 'غير معروف'}\nالكلمة: {hit}\nالمخالفات: {strike}\nالنص: {text[:700]}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="تجاهل", callback_data=f"mod:ignore:{violation_id}"), InlineKeyboardButton(text="كتم ٢٤ ساعة", callback_data=f"mod:mute:{violation_id}")]])
        try:
            await message.delete()
        except Exception:
            log.exception("Unable to delete matched message; verify bot delete rights")
        muted = False
        if message.from_user:
            mute = mute_seconds(strike)
            if mute:
                try:
                    await message.bot.restrict_chat_member(message.chat.id, message.from_user.id, permissions=ChatPermissions(can_send_messages=False), until_date=datetime.now(timezone.utc) + timedelta(seconds=mute))
                    muted = True
                    log_text += f"\nالإجراء: كتم {mute_label(mute)}"
                except Exception:
                    log.exception("Could not mute offender; verify bot restrict rights")
        if message.from_user:
            notice = (
                f"رسالة تخصك: رُصدت في رسالتك كلمة مخالفة وحُذفت.\n"
                f"عدد المخالفات: {strike}\n"
                + (f"تم كتمك لمدة {mute_label(mute)} بسبب تكرار المخالفات.\n" if muted else "التصعيد: من المخالفة الثالثة: كتم 15 دقيقة، ثم 30 دقيقة، ثم 24 ساعة.\n")
                + "للاستفسار راسل المشرفين."
            )
            await offender_notice(message, notice)
        if audit:
            audit.record("outgoing", chat_id=message.chat.id, user_id=message.from_user.id if message.from_user else None, kind="moderation", content=log_text, params={"dry_run": False, "actions": ["delete", "warn"] + (["mute"] if muted else [])})
        if settings.log_topic_id:
            try:
                await message.bot.send_message(settings.community_chat_id, log_text, message_thread_id=settings.log_topic_id, reply_markup=keyboard)
            except Exception:
                log.exception("Unable to post admin moderation log")

    @router.message(F.chat.type.in_({"group", "supergroup"}))
    async def moderate(message: Message) -> None:
        await inspect(message)

    @router.edited_message(F.chat.type.in_({"group", "supergroup"}))
    async def moderate_edited(message: Message) -> None:
        await inspect(message)

    @router.callback_query(F.data.startswith("mod:"))
    async def action(callback: CallbackQuery) -> None:
        if not callback.message:
            return
        try:
            member = await callback.bot.get_chat_member(settings.community_chat_id, callback.from_user.id)
            if member.status not in {"creator", "administrator"}:
                await callback.answer("هذا الإجراء للمشرفين فقط.", show_alert=True)
                return
            _, action_name, token = callback.data.split(":", 2)
            if not token.isdigit():
                await callback.answer("طلب غير صالح.", show_alert=True)
                return
            violation = db.one("SELECT chat_id,user_id FROM violations WHERE id=?", (int(token),))
            if not violation:
                await callback.answer("لم أجد المخالفة.", show_alert=True)
                return
            if action_name == "mute" and violation["user_id"]:
                from datetime import datetime, timedelta, timezone
                await callback.bot.restrict_chat_member(int(violation["chat_id"]), int(violation["user_id"]), permissions=__import__("aiogram").types.ChatPermissions(can_send_messages=False), until_date=datetime.now(timezone.utc) + timedelta(hours=24))
                await callback.answer("تم الكتم لمدة ٢٤ ساعة.")
            else:
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except Exception:
                    log.debug("Could not clear moderation buttons", exc_info=True)
                await callback.answer("تم التجاهل.")
        except Exception:
            log.exception("Moderation action failed; verify admin rights")
            await callback.answer("تعذر تنفيذ الإجراء. تحقق من صلاحيات البوت.", show_alert=True)
    return router
