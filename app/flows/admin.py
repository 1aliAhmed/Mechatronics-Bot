from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (BotCommand, BotCommandScopeChat,
                           BotCommandScopeChatAdministrators, BotCommandScopeDefault,
                           InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                           Message, ReplyKeyboardMarkup)

from app.ai.providers import GroqWhisper, OpenRouter, transcribe_audio
from app.audit import AuditLogger
from app.config import Settings
from app.db import Database
from app.formatting import apply_style
from app.media import normalize_text, store_media
from app.quota import QuotaService, quota_message, quota_summary
from app.security import is_community_admin
from app.imagegen import generate_image, save_image
from app.flows.clean import apply_revision, doc_keyboard, document_filename
from app.flows.visuals import cleanup_image, compose_visual, render_blocks, visual_kind

VISUAL_HINTS = ("draw ", "draw me", "make a graph", "make a plot", "make a chart", "make a diagram", "make an image", "make a picture", "create a graph", "create a chart", "create a diagram", "create an image", "generate a graph", "generate an image", "i want a graph", "i want an image", "i want a chart", "i want a diagram", "plot the", "plot a", "graph of", "chart of", "diagram of", "visualize", "visualise")
VISUAL_VERB_TOKENS = frozenset({"رسم", "ارسم", "أرسم", "ارسمي", "أرسمي", "رسمة", "رسمه", "صمم", "صممي", "صمّم"})
ARABIC_VISUAL_NOUNS = ("رسم بياني", "رسمة", "مخطط", "صورة توضيحية")
NON_REQUEST_PREFIXES = frozenset({"اشرح", "اشرحي", "فسر", "فسري", "وضح", "وضحي", "حل", "حلي", "احسب", "احسبي", "ما", "ماذا", "كيف", "لماذا", "هل", "علل", "اذكر", "explain", "what", "how", "why", "solve", "describe", "when", "where", "which"})


def wants_visual(text: str) -> bool:
    lowered = (text or "").casefold()
    if any(hint in lowered for hint in VISUAL_HINTS):
        return True
    tokens = re.findall(r"[^\W_]+", lowered)
    if not tokens or tokens[0] in NON_REQUEST_PREFIXES:
        return False
    if any(token in VISUAL_VERB_TOKENS for token in tokens[:3]):
        return True
    return any(noun in lowered for noun in ARABIC_VISUAL_NOUNS)

log = logging.getLogger(__name__)
router = Router()
AUDIO_TRANSCRIBE_PROMPT = "Transcribe the recording accurately, then answer its content in English."
PRESETS = {"summary": "Summarize the following content as focused bullet points.", "notes": "Turn the material into organized study notes.", "explain": "Explain the idea step by step with an example.", "exercise": "Create a graded exercise with a hint and a full solution.", "flash": "Create question/answer flashcards for revision."}
PRESET_PROMPTS = {"summary": "أرسل الآن ما تريد تلخيصه: نص أو صورة أو تسجيل.", "notes": "أرسل الآن المادة التي تريد تحويلها إلى ملاحظات منظمة.", "explain": "أرسل الآن ما تريد شرحه — نصاً أو صورة أو تسجيلاً.", "exercise": "أرسل الآن الموضوع أو المسألة التي نبني عليها التمرين.", "flash": "أرسل الآن المادة وسأحوّلها إلى بطاقات سؤال وجواب."}


def preset_reply_text(key: str) -> str:
    return PRESET_PROMPTS[key]


def split_preset_caption(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    head, _, rest = text.partition(" ")
    key = head[1:].split("@")[0].lower() if head.startswith("/") else ""
    if key in PRESETS:
        return rest.strip(), PRESETS[key]
    return text, ""


HELP_TEXT = ("دليل نافذة الدراسة\n\n"
             "أدوات المحتوى\n"
             "تلخيص المحتوى بنقاط مركزة (/summary)\n"
             "تحويل المحتوى إلى ملاحظات منظمة (/notes)\n"
             "شرح الفكرة خطوة بخطوة مع مثال (/explain)\n"
             "بناء تمرين تدريجي مع تلميح وحل (/exercise)\n"
             "إنشاء بطاقات سؤال وجواب للمراجعة (/flash)\n"
             "إنشاء رسم تعليمي؛ اكتب الوصف بعد الأمر (/visual)\n\n"
             "المحادثة\n"
             "بدء محادثة جديدة ومسح السياق السابق (/new)\n"
             "عرض هذه القائمة في أي وقت (/menu)\n"
             "معرفة استهلاكك اليومي (/usage)\n\n"
             "إدارة المجتمع\n"
             "عرض المجموعات التي تديرها وكتمها أو إلغاء كتمها (/groups)\n\n"
             "طريقة العمل\n"
             "أرسل المادة — نصاً أو صورة أو تسجيلاً أو ملفاً نصياً — ثم اختر الإجراء، أو ابدأ بالإجراء وسأطلب منك المادة.\n"
             "أما PDF والصور المتعددة فهي مصادر: أعالجها صفحة صفحة وأعيدها إليك كملف نظيف قابل للنشر.")
MENU_ACTIONS = (("تلخيص", "summary"), ("ملاحظات", "notes"), ("شرح", "explain"), ("تمرين", "exercise"), ("بطاقات", "flash"), ("رسم", "visual"), ("المجموعات", "groups"), ("محادثة جديدة", "new"), ("مساعدة", "help"))
MENU_ACTION_KEYS = frozenset(action for _, action in MENU_ACTIONS)
WELCOME = ("أهلاً بك في نافذة الدراسة.\n\n"
           "هذه مساحة خاصة بمشرفي المجتمع، تجمع عملكم مع الذكاء الاصطناعي في مكان واحد: اسأل، اشرح، لخّص، وحوّل المصادر الملوثة إلى مواد منظمة.\n\n"
           "ما الذي يمكنك إرساله؟\n"
           "نص — اكتب سؤالك أو الصق المادة.\n"
           "صورة — مسألة أو سبورة أو شكل هندسي.\n"
           "تسجيل صوتي — محاضرة أو شرح شفهي.\n"
           "ملف نصي — txt أو md أو csv.\n"
           "PDF أو صور متعددة — كمصدر يُعالج ويُعاد إليك منسقاً.\n\n"
           "ابدأ من القائمة أدناه، أو أرسل سؤالك مباشرة.")
REPLY_KEYBOARD = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="تلخيص"), KeyboardButton(text="ملاحظات"), KeyboardButton(text="شرح")],
    [KeyboardButton(text="تمرين"), KeyboardButton(text="بطاقات"), KeyboardButton(text="رسم")],
    [KeyboardButton(text="محادثة جديدة"), KeyboardButton(text="المجموعات"), KeyboardButton(text="مساعدة")],
], resize_keyboard=True, input_field_placeholder="أرسل سؤالك أو مادة دراسية")


def welcome_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"menu:{action}") for label, action in MENU_ACTIONS[index:index + 3]]
        for index in range(0, len(MENU_ACTIONS), 3)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def preset_key(user_id: int) -> str:
    return f"preset:{user_id}"


def preset_request(key: str, command_text: str | None) -> tuple[str, str]:
    content = (command_text or "").partition(" ")[2].strip()
    # The reply-keyboard command buttons append an Arabic label; that label is not content.
    labels = {"summary": "تلخيص", "notes": "ملاحظات", "explain": "شرح", "exercise": "تمرين", "flash": "بطاقات"}
    if content == labels[key]:
        content = ""
    return (content, "" if content else preset_reply_text(key))


def menu_action_from_callback(data: str | None) -> str | None:
    if not data or not data.startswith("menu:"):
        return None
    action = data.partition(":")[2]
    return action if action in MENU_ACTION_KEYS else None


MUTE_GROUP_NOTICE = "تم إغلاق الكتابة في هذه المجموعة مؤقتاً. للاستفسار راسل المشرفين."
MUTE_TOPIC_NOTICE = "تم إغلاق الكتابة في هذا الموضوع مؤقتاً. للاستفسار راسل المشرفين."


def group_menu_view(title: str, chat_id: int, muted: bool, forum: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    status = "مقفلة" if muted else "مفتوحة"
    text = f"المجموعة: {title or chat_id}\nالحالة: {status}"
    toggle = InlineKeyboardButton(
        text="إلغاء الكتم" if muted else "كتم المجموعة",
        callback_data=f"grp:{'unmute' if muted else 'mute'}:{chat_id}",
    )
    rows = [[toggle]]
    if forum:
        rows.append([InlineKeyboardButton(text="المواضيع (كتم/فك)", callback_data=f"grpt:{chat_id}")])
    rows.append([InlineKeyboardButton(text="تحديث", callback_data=f"grp:menu:{chat_id}")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def topics_view(chat_id: int, rows: list) -> tuple[str, InlineKeyboardMarkup]:
    buttons = []
    for row in rows:
        title = str(row["title"]) or f"موضوع #{row['thread_id']}"
        label = f"{title} — مكتوم" if row["muted"] else title
        buttons.append([InlineKeyboardButton(text=label[:60], callback_data=f"grptt:{chat_id}:{row['thread_id']}")])
    buttons.append([InlineKeyboardButton(text="رجوع", callback_data=f"grp:menu:{chat_id}")])
    text = "اختر موضوعاً لكتمه أو فك كتمه:" if len(buttons) > 1 else "لا توجد مواضيع مسجّلة بعد؛ ستظهر تلقائياً بعد أول رسالة في أي موضوع."
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


def aggregate_album_items(existing: list[dict], item: dict) -> list[dict]:
    """Return album items ordered by Telegram message id without duplicates."""
    items = [entry for entry in existing if entry.get("message_id") != item.get("message_id")]
    items.append(item)
    return sorted(items, key=lambda entry: entry["message_id"])


def audio_mime(record: dict, filename: str = "") -> str:
    mime = str(record.get("mime") or "").strip()
    if mime.startswith("audio/"):
        return mime
    import mimetypes
    path = str(record.get("local_path") or filename)
    return mimetypes.guess_type(path)[0] or "application/octet-stream"



def intro_text(settings: Settings) -> str:
    lines = [
        "أهلاً بك! أنا مساعد مجتمع الميكاترونكس — بوت دراسي على تيليجرام:",
        "• أرسل نصاً أو صورة أو رسالة صوتية وسأشرح أو ألخّص أو أحلّل.",
        "• رُد على أي رسالة بـ /summary أو /explain أو /exercise أو /flash للحصول على مخرجات جاهزة.",
        "• «ارسم …» أو /visual لإنشاء رسم بياني أو مخطط.",
        "• /menu القائمة، /new محادثة جديدة، /usage حصّتك الحالية.",
        f"الاستخدام مجاني للجميع — الحد الحالي: {quota_summary(settings)} (حد تجريبي مؤقت سيُرفع قريباً).",
    ]
    if settings.repo_url:
        lines.append(f"الكود مفتوح المصدر على GitHub: {settings.repo_url}")
    return "\n".join(lines)


def install_admin(settings: Settings, db: Database, audit: AuditLogger, provider: OpenRouter, prompt_path: Path, transcriber: GroqWhisper | None = None, quota: QuotaService | None = None) -> Router:
    system_prompt = prompt_path.read_text(encoding="utf-8")
    gate_lock = asyncio.Lock()
    last_request = 0.0
    quota = quota or QuotaService(db, settings)

    async def is_admin(message: Message) -> bool:
        if not message.from_user:
            return False
        return await is_community_admin(settings, db, message.bot, message.from_user.id)

    async def quota_gate(message: Message) -> bool:
        """True when the sender may proceed; non-admins spend one quota message."""
        if not message.from_user or await is_admin(message):
            return True
        retry = quota.consume(message.from_user.id)
        if retry:
            await message.answer(quota_message(settings, retry))
            return False
        return True

    async def permit(message: Message) -> bool:
        return message.chat.type == "private" and message.from_user is not None

    async def typing(message: Message) -> None:
        try:
            await message.bot.send_chat_action(message.chat.id, "typing")
        except Exception:
            log.debug("Could not show typing indicator", exc_info=True)

    async def first_contact(handler, event: Message, data):
        if event.chat.type == "private" and event.from_user and db.mark_introduced(event.from_user.id):
            try:
                await event.bot.send_message(event.chat.id, intro_text(settings))
            except Exception:
                log.debug("Could not deliver intro message", exc_info=True)
        return await handler(event, data)

    router.message.middleware(first_contact)

    async def show_welcome(message: Message) -> None:
        await message.answer(WELCOME, reply_markup=welcome_keyboard())
        await message.answer("يمكنك استخدام الأزرار الدائمة أسفل الشاشة في أي وقت.", reply_markup=REPLY_KEYBOARD)

    @router.message(F.chat.type == "private", Command("start"))
    async def start(message: Message) -> None:
        if await permit(message):
            await show_welcome(message)

    @router.message(F.chat.type == "private", Command("menu"))
    async def menu(message: Message) -> None:
        if await permit(message):
            await show_welcome(message)

    @router.message(F.chat.type == "private", Command("help"))
    async def help_command(message: Message) -> None:
        if await permit(message):
            await message.answer(HELP_TEXT, reply_markup=REPLY_KEYBOARD)

    @router.callback_query(F.data.startswith("menu:"))
    async def menu_callback(callback) -> None:
        if not callback.data or not callback.message or not callback.from_user:
            await callback.answer()
            return
        # The dispatcher-level CommunityGuard admits every private update; each menu
        # action is safe for the public window (group management self-checks per group).
        action = menu_action_from_callback(callback.data)
        if action is None:
            await callback.answer("الخيار غير معروف.", show_alert=True)
            return
        await callback.answer()
        user_id = callback.from_user.id
        if action in PRESETS:
            db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (preset_key(user_id), action))
            await callback.message.answer(preset_reply_text(action), reply_markup=REPLY_KEYBOARD)
        elif action == "new":
            db.save_session(user_id, "", [])
            db.execute("DELETE FROM settings WHERE key=?", (preset_key(user_id),))
            await callback.message.answer("بدأنا صفحة جديدة؛ المحادثة السابقة انتهت.", reply_markup=REPLY_KEYBOARD)
        elif action == "help":
            await callback.message.answer(HELP_TEXT, reply_markup=REPLY_KEYBOARD)
        elif action == "visual":
            await callback.message.answer("اكتب وصف الرسم في رسالة — مثلاً: ارسم منحنى جيب التمام — وسأجهّزه.", reply_markup=REPLY_KEYBOARD)
        elif action == "groups":
            await groups_command(callback.message)

    @router.message(F.chat.type == "private", Command("new"))
    async def new(message: Message) -> None:
        if await permit(message) and message.from_user:
            db.save_session(message.from_user.id, "", [])
            db.execute("DELETE FROM settings WHERE key=?", (preset_key(message.from_user.id),))
            await message.answer("بدأنا صفحة جديدة؛ المحادثة السابقة انتهت.", reply_markup=REPLY_KEYBOARD)

    @router.message(F.chat.type == "private", Command("usage"))
    async def usage(message: Message) -> None:
        if await permit(message) and message.from_user:
            user_id = message.from_user.id
            if await is_admin(message):
                await message.answer(f"استخدمت اليوم {db.usage_count(user_id)} طلباً (بلا حد على المشرفين).")
                return
            used_hour, used_day, retry = quota.state(user_id)
            text = f"حصّتك: {used_hour} خلال الساعة الأخيرة و{used_day} خلال 24 ساعة — الحد الحالي: {quota_summary(settings)} (تجريبي مؤقت)."
            if retry:
                text += f"\nيمكنك الإرسال مجدداً بعد ~{max(1, (retry + 59) // 60)} دقيقة."
            await message.answer(text)

    async def groups_command(message: Message) -> None:
        if not message.from_user:
            return
        rows = db.all("SELECT chat_id,title,chat_type,muted FROM chats WHERE chat_type IN ('group','supergroup') ORDER BY title")
        manageable = []
        for row in rows:
            try:
                member = await message.bot.get_chat_member(int(row["chat_id"]), message.from_user.id)
            except Exception:
                continue
            if member.status in {"creator", "administrator"}:
                manageable.append(row)
        if not manageable:
            await message.answer("لا توجد مجموعات تديرها ويوجد فيها البوت حالياً. أضف البوت إلى المجموعة أولاً.", reply_markup=REPLY_KEYBOARD)
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=str(row["title"]) or str(row["chat_id"]), callback_data=f"grp:menu:{row['chat_id']}")]
            for row in manageable[:20]
        ])
        await message.answer("اختر مجموعة لإدارتها:", reply_markup=keyboard)

    @router.message(F.chat.type == "private", Command("groups"))
    async def groups(message: Message) -> None:
        if await permit(message):
            await groups_command(message)

    @router.callback_query(F.data.startswith("grp:"))
    async def group_callback(callback) -> None:
        if not callback.data or not callback.message or not callback.from_user:
            await callback.answer()
            return
        try:
            _, action, raw_id = callback.data.split(":", 2)
            chat_id = int(raw_id)
        except (ValueError, IndexError):
            await callback.answer("طلب غير صالح.", show_alert=True)
            return
        try:
            member = await callback.bot.get_chat_member(chat_id, callback.from_user.id)
            if member.status not in {"creator", "administrator"}:
                await callback.answer("هذه الإجراءات لمشرفي المجموعة فقط.", show_alert=True)
                return
        except Exception:
            await callback.answer("تعذر التحقق من صلاحيتك في المجموعة.", show_alert=True)
            return
        row = db.chat_row(chat_id)
        if row is None:
            await callback.answer("المجموعة غير مسجلة.", show_alert=True)
            return
        if action in {"mute", "unmute"}:
            muted = action == "mute"
            previous = row
            if muted:
                try:
                    bot_member = await callback.bot.get_chat_member(chat_id, callback.bot.id)
                except Exception:
                    bot_member = None
                if bot_member is None or bot_member.status not in {"administrator", "creator"}:
                    await callback.answer("أضف البوت مشرفاً في المجموعة أولاً.", show_alert=True)
                    return
                db.set_chat_muted(chat_id, True, callback.from_user.id)
                try:
                    notice = await callback.bot.send_message(chat_id, MUTE_GROUP_NOTICE)
                    db.set_chat_notice(chat_id, notice.message_id)
                    try:
                        await callback.bot.pin_chat_message(chat_id, notice.message_id, disable_notification=True)
                    except Exception:
                        log.debug("Could not pin mute notice", exc_info=True)
                except Exception:
                    log.warning("Could not post mute notice in %s", chat_id, exc_info=True)
            else:
                db.set_chat_muted(chat_id, False, callback.from_user.id)
                notice_id = int(previous["notice_message_id"]) if previous and previous["notice_message_id"] else None
                if notice_id is None:
                    try:
                        chat = await callback.bot.get_chat(chat_id)
                        pinned = getattr(chat, "pinned_message", None)
                        if pinned is not None and pinned.from_user is not None and pinned.from_user.id == callback.bot.id:
                            notice_id = pinned.message_id
                    except Exception:
                        notice_id = None
                if notice_id:
                    try:
                        await callback.bot.unpin_chat_message(chat_id, notice_id)
                    except Exception:
                        log.debug("Could not unpin mute notice", exc_info=True)
                    try:
                        await callback.bot.delete_message(chat_id, notice_id)
                    except Exception:
                        log.debug("Could not delete mute notice", exc_info=True)
                db.set_chat_notice(chat_id, None)
            audit.record("outgoing", chat_id=chat_id, user_id=callback.from_user.id, kind="chat_mute", content="كتم المجموعة" if muted else "إلغاء كتم المجموعة")
            row = db.chat_row(chat_id)
        forum = False
        if chat_id == settings.community_chat_id:
            try:
                chat = await callback.bot.get_chat(chat_id)
                forum = bool(getattr(chat, "is_forum", False))
            except Exception:
                forum = False
        text, keyboard = group_menu_view(str(row["title"]), chat_id, bool(row["muted"]), forum)
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)
        except Exception:
            await callback.message.answer(text, reply_markup=keyboard)
        answers = {"mute": "تم الكتم؛ لن يكتب الأعضاء حتى إلغاء الكتم.", "unmute": "تم إلغاء الكتم.", "menu": "محدّث."}
        await callback.answer(answers.get(action, "محدّث."))

    async def topic_admin(callback) -> bool:
        """Shared requester check for topic actions."""
        try:
            member = await callback.bot.get_chat_member(int(callback.data.split(":", 2)[1]), callback.from_user.id)
        except Exception:
            await callback.answer("تعذر التحقق من صلاحيتك في المجموعة.", show_alert=True)
            return False
        if member.status not in {"creator", "administrator"}:
            await callback.answer("هذه الإجراءات لمشرفي المجموعة فقط.", show_alert=True)
            return False
        return True

    @router.callback_query(F.data.startswith("grpt:"))
    async def topics_callback(callback) -> None:
        if not callback.data or not callback.message or not callback.from_user:
            await callback.answer()
            return
        try:
            chat_id = int(callback.data.split(":", 2)[2])
        except (ValueError, IndexError):
            await callback.answer("طلب غير صالح.", show_alert=True)
            return
        if not await topic_admin(callback):
            return
        text, keyboard = topics_view(chat_id, db.topics_for(chat_id))
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)
        except Exception:
            await callback.message.answer(text, reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(F.data.startswith("grptt:"))
    async def topic_toggle(callback) -> None:
        if not callback.data or not callback.message or not callback.from_user:
            await callback.answer()
            return
        try:
            _, raw_chat, raw_thread = callback.data.split(":", 2)
            chat_id, thread_id = int(raw_chat), int(raw_thread)
        except (ValueError, IndexError):
            await callback.answer("طلب غير صالح.", show_alert=True)
            return
        if not await topic_admin(callback):
            return
        row = db.topic_row(chat_id, thread_id)
        muted = bool(row["muted"]) if row else False
        if not muted:
            try:
                bot_member = await callback.bot.get_chat_member(chat_id, callback.bot.id)
            except Exception:
                bot_member = None
            if bot_member is None or bot_member.status not in {"administrator", "creator"}:
                await callback.answer("أضف البوت مشرفاً في المجموعة أولاً.", show_alert=True)
                return
            try:
                await callback.bot.close_forum_topic(chat_id, thread_id)
            except Exception:
                log.warning("Could not close topic %s in %s", thread_id, chat_id, exc_info=True)
                await callback.answer("تعذر كتم الموضوع؛ تأكد من صلاحيات البوت.", show_alert=True)
                return
            notice_id = None
            try:
                notice = await callback.bot.send_message(chat_id, MUTE_TOPIC_NOTICE, message_thread_id=thread_id)
                notice_id = notice.message_id
                try:
                    await callback.bot.pin_chat_message(chat_id, notice.message_id, disable_notification=True)
                except Exception:
                    log.debug("Could not pin topic mute notice", exc_info=True)
            except Exception:
                log.warning("Could not post topic mute notice in %s/%s", chat_id, thread_id, exc_info=True)
            db.set_topic_muted(chat_id, thread_id, True, notice_id)
            audit.record("outgoing", chat_id=chat_id, user_id=callback.from_user.id, kind="topic_mute", content=f"كتم الموضوع {thread_id}")
            answer = "تم كتم الموضوع؛ لن يكتب الأعضاء فيه حتى فك الكتم."
        else:
            try:
                await callback.bot.reopen_forum_topic(chat_id, thread_id)
            except Exception:
                log.warning("Could not reopen topic %s in %s", thread_id, chat_id, exc_info=True)
                await callback.answer("تعذر فك كتم الموضوع.", show_alert=True)
                return
            if row is not None and row["notice_message_id"]:
                try:
                    await callback.bot.unpin_chat_message(chat_id, int(row["notice_message_id"]))
                except Exception:
                    log.debug("Could not unpin topic mute notice", exc_info=True)
                try:
                    await callback.bot.delete_message(chat_id, int(row["notice_message_id"]))
                except Exception:
                    log.debug("Could not delete topic mute notice", exc_info=True)
            db.set_topic_muted(chat_id, thread_id, False, None)
            audit.record("outgoing", chat_id=chat_id, user_id=callback.from_user.id, kind="topic_mute", content=f"إلغاء كتم الموضوع {thread_id}")
            answer = "تم إلغاء كتم الموضوع."
        text, keyboard = topics_view(chat_id, db.topics_for(chat_id))
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)
        except Exception:
            await callback.message.answer(text, reply_markup=keyboard)
        await callback.answer(answer)

    async def preset(message: Message, key: str) -> None:
        if await permit(message):
            text, followup = preset_request(key, message.text)
            if followup:
                if message.from_user:
                    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (preset_key(message.from_user.id), key))
                await message.answer(followup, reply_markup=REPLY_KEYBOARD)
                return
            if message.from_user:
                db.execute("DELETE FROM settings WHERE key=?", (preset_key(message.from_user.id),))
            await respond(message, text, PRESETS[key])

    def consume_pending(user_id: int) -> str:
        row = db.one("SELECT value FROM settings WHERE key=?", (preset_key(user_id),))
        if not row:
            return ""
        db.execute("DELETE FROM settings WHERE key=?", (preset_key(user_id),))
        return PRESETS.get(str(row["value"]), "")

    for key in PRESETS:
        async def handler(message: Message, item: str = key) -> None:
            await preset(message, item)
        router.message.register(handler, F.chat.type == "private", F.text, Command(key))

    async def respond(message: Message, user_text: str, directive: str = "", attachment: dict | None = None, attachments: list[dict] | None = None) -> None:
        nonlocal last_request
        if not message.from_user:
            return
        user_id = message.from_user.id
        if not await is_admin(message) and db.usage_count(user_id) >= settings.daily_cap:
            await message.answer("وصلت إلى سقف الاستخدام اليومي؛ نستأنف غداً.")
            return
        if not user_text and not attachment:
            await message.answer("أرسل سؤالك مباشرة، أو المادة التي تريد العمل عليها.")
            return
        await typing(message)
        try:
            user_text = normalize_text(user_text, settings.max_text_chars)
        except ValueError as exc:
            await message.answer(str(exc))
            audit.record("incoming", chat_id=message.chat.id, user_id=user_id, kind="validation_error", content=str(exc))
            return
        if not await quota_gate(message):
            return
        started = time.monotonic()
        db.record_message(message_id=message.message_id, chat_id=message.chat.id, user_id=user_id, session_user_id=user_id, kind="user", text=user_text, attachment=attachment, attachments=attachments)
        file_refs = [str(item["local_path"]) for item in (([attachment] if attachment else []) + (attachments or []))]
        audit.record("incoming", chat_id=message.chat.id, user_id=user_id, kind="chat", content=user_text, file_refs=file_refs)
        summary, history = db.session(user_id)
        token_budget = settings.context_token_budget
        if len(system_prompt) + sum(len(item["content"]) for item in history) > token_budget * 4:
            while history and len(system_prompt) + sum(len(item["content"]) for item in history) > token_budget * 4:
                old_user = history.pop(0)
                old_assistant = history.pop(0) if history else {"content": ""}
                try:
                    summary, _ = await provider.chat(settings.chat_model, [{"role": "system", "content": "Update the previous study summary with the key facts, decisions, and terms from the older turn. Write briefly in English."}, {"role": "user", "content": f"Previous summary:\n{summary}\n\nUser question:\n{old_user['content']}\n\nAnswer:\n{old_assistant['content']}"}], temperature=0.1)
                except Exception:
                    summary = (summary + "\n" + old_user["content"][:900] + "\n" + old_assistant["content"][:900]).strip()[-12000:]
            db.save_session(user_id, summary, history)
        messages = [{"role": "system", "content": system_prompt + ("\nملخص سياق سابق: " + summary if summary else "") }]
        messages.extend(history[-20:])
        content = (directive + "\n\n" if directive else "") + user_text
        messages.append({"role": "user", "content": content})
        media_path = str(attachment["local_path"]) if attachment else ""
        try:
            await asyncio.wait_for(gate_lock.acquire(), timeout=240)
        except asyncio.TimeoutError:
            await message.answer("الخدمة مشغولة هذه اللحظة؛ أعد المحاولة بعد قليل.")
            return
        try:
            delay = 60 / settings.rate_limit_rpm - (time.monotonic() - last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            last_request = time.monotonic()
            log.info("ai: start chat=%s", message.chat.id)
            try:
                if attachments and all(item["type"] == "image" for item in attachments):
                    import base64
                    parts = [{"type": "text", "text": content or "Analyse the attached images together."}]
                    for item in attachments:
                        with open(str(item["local_path"]), "rb") as image_file:
                            encoded = base64.b64encode(image_file.read()).decode("ascii")
                        parts.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + encoded}})
                    messages[-1]["content"] = parts
                    answer, response = await provider.chat(settings.vision_model, messages, temperature=0.4)
                    if not answer.strip():
                        log.warning("Vision model returned empty content; retrying once")
                        answer, response = await provider.chat(settings.vision_model, messages, temperature=0.4)
                    history_content = (content + "\n\nImage analysis: " + answer).strip()
                elif attachment and attachment["type"] == "image":
                    with open(media_path, "rb") as image_file:
                        raw = image_file.read()
                    import base64
                    messages[-1]["content"] = [{"type": "text", "text": content or "Describe and analyse this image for the study session."}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")}}]
                    answer, response = await provider.chat(settings.vision_model, messages, temperature=0.4)
                    if not answer.strip():
                        log.warning("Vision model returned empty content; retrying once")
                        answer, response = await provider.chat(settings.vision_model, messages, temperature=0.4)
                    history_content = (content + "\n\nImage analysis: " + answer).strip()
                    messages[-1] = {"role": "user", "content": history_content}
                    answer, response = await provider.chat(settings.chat_model, messages, temperature=0.4)
                elif attachment and attachment["type"] in {"voice", "audio"}:
                    mime = audio_mime(attachment, media_path)
                    with open(media_path, "rb") as audio_file:
                        raw = audio_file.read()
                    # Groq Whisper first when configured; OpenRouter audio models remain the fallback.
                    transcript, response, route, audio_model = await transcribe_audio(transcriber, provider, settings.audio_models, AUDIO_TRANSCRIBE_PROMPT, raw, mime)
                    audit.record("incoming", chat_id=message.chat.id, user_id=user_id, kind="transcription", content=transcript, file_refs=[media_path], model=audio_model, params={"route": route, "mime": mime}, latency_ms=int((time.monotonic() - started) * 1000))
                    history_content = content + "\n\nTranscript: " + transcript
                    messages[-1] = {"role": "user", "content": history_content}
                    answer, response = await provider.chat(settings.chat_model, messages, temperature=0.4)
                else:
                    history_content = content
                    answer, response = await provider.chat(settings.chat_model, messages, temperature=0.4)
            except Exception as exc:
                log.exception("OpenRouter chat failed")
                error_text = "تعذّر الوصول إلى المساعد الآن؛ أعد المحاولة بعد قليل."
                await message.answer(error_text)
                audit.record("outgoing", chat_id=message.chat.id, user_id=user_id, kind="chat_error", content=error_text, model=settings.chat_model, params={"error": str(exc)[:500]}, latency_ms=int((time.monotonic() - started) * 1000))
                return
            log.info("ai: model done chat=%s", message.chat.id)
        finally:
            gate_lock.release()
        answer = apply_style(answer)
        images, cleaned = await render_blocks(answer)
        if images:
            answer = cleaned or "جهّزت الرسم."
        elapsed = int((time.monotonic() - started) * 1000)
        db.add_usage(user_id)
        history.extend([{"role": "user", "content": history_content}, {"role": "assistant", "content": answer}])
        # Conservative character-based approximation, bounded history; earlier turns move into a rolling extract.
        while sum(len(entry["content"]) for entry in history) > settings.context_token_budget * 4 and len(history) > 2:
            removed = history.pop(0)
            history.pop(0)
            try:
                summary, _ = await provider.chat(settings.chat_model, [{"role": "system", "content": "أنشئ ملخصاً تراكمياً عربياً موجزاً للحقائق والتعاريف من الحوار المحذوف."}, {"role": "user", "content": f"{summary}\n\n{removed['content']}"}], temperature=0.1)
            except Exception:
                summary = (summary + "\n" + removed["content"][:1200]).strip()[-12000:]
        db.save_session(user_id, summary, history)
        db.record_message(message_id=None, chat_id=message.chat.id, user_id=user_id, session_user_id=user_id, kind="assistant", text=answer)
        audit.record("outgoing", chat_id=message.chat.id, user_id=user_id, kind="chat", content=answer, model=settings.chat_model, file_refs=[str(image) for image in images], params={"temperature": 0.4, "usage": response.get("usage", {})}, latency_ms=elapsed)
        for image in images:
            await message.answer_photo(__import__("aiogram").types.FSInputFile(image))
            cleanup_image(image)
        for start_at in range(0, len(answer), 4000):
            await message.answer(answer[start_at:start_at + 4000])

    async def visual_from_chat(message: Message, request: str) -> None:
        if not message.from_user:
            return
        if not await quota_gate(message):
            return
        await typing(message)
        started = time.monotonic()
        audit.record("incoming", chat_id=message.chat.id, user_id=message.from_user.id, kind="visual", content=request)
        if visual_kind(request) == "illustration":
            try:
                data = await generate_image(request, settings)
                path = save_image(data, settings)
                await message.answer_photo(__import__("aiogram").types.FSInputFile(path))
                cleanup_image(path)
                audit.record("outgoing", chat_id=message.chat.id, user_id=message.from_user.id, kind="visual", content="تم إنشاء صورة", file_refs=[str(path)], model=settings.image_model or None, params={"kind": "illustration"}, latency_ms=int((time.monotonic() - started) * 1000))
                return
            except Exception:
                log.warning("Illustration generation failed; falling back to the chart renderer", exc_info=True)
        try:
            image, response, _ = await compose_visual(provider, settings.chat_model, request, "python")
            await message.answer_photo(__import__("aiogram").types.FSInputFile(image))
            cleanup_image(image)
            audit.record("outgoing", chat_id=message.chat.id, user_id=message.from_user.id, kind="visual", content="تم إنشاء الصورة", file_refs=[str(image)], model=settings.chat_model, params={"usage": response.get("usage", {})}, latency_ms=int((time.monotonic() - started) * 1000))
        except Exception as exc:
            error_text = "تعذّر إنشاء الرسم؛ جرّب وصفاً أبسط."
            await message.answer(error_text)
            audit.record("outgoing", chat_id=message.chat.id, user_id=message.from_user.id, kind="visual_error", content=error_text, model=settings.chat_model, params={"error": str(exc)[:500]}, latency_ms=int((time.monotonic() - started) * 1000))

    @router.message(F.chat.type == "private", F.text)
    async def ordinary_chat(message: Message) -> None:
        if message.text and not message.text.startswith("/") and await permit(message):
            shortcuts = {"تلخيص": "summary", "ملاحظات": "notes", "شرح": "explain", "تمرين": "exercise", "بطاقات": "flash", "محادثة جديدة": "new", "مساعدة": "help", "رسم": "visual", "المجموعات": "groups"}
            action = shortcuts.get(message.text.strip())
            if action == "new":
                await new(message)
                return
            if action == "help":
                await help_command(message)
                return
            if action == "visual":
                await message.answer("اكتب وصف الرسم في رسالة — مثلاً: ارسم منحنى جيب التمام — وسأجهّزه.", reply_markup=REPLY_KEYBOARD)
                return
            if action == "groups":
                await groups_command(message)
                return
            if message.from_user:
                pending = db.one("SELECT value FROM settings WHERE key=?", (f"docrevise:{message.from_user.id}",))
                if pending:
                    db.execute("DELETE FROM settings WHERE key=?", (f"docrevise:{message.from_user.id}",))
                    await typing(message)
                    result = await apply_revision(settings, db, provider, audit, str(pending["value"]), message.text, message.chat.id, message.from_user.id)
                    if result is None:
                        await message.answer("لم أجد المادة الأصلية.")
                    else:
                        new_hash, artifact = result
                        row = db.one("SELECT markdown FROM docs WHERE hash=?", (new_hash,))
                        filename = document_filename(str(row["markdown"] if row else ""), Path(artifact).suffix or ".pdf")
                        await message.answer_document(__import__("aiogram").types.FSInputFile(artifact, filename=filename), caption="نسخة معدّلة جاهزة؛ راجعها قبل النشر.", reply_markup=doc_keyboard(new_hash))
                    return
            if action in PRESETS:
                db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (preset_key(message.from_user.id), action))
                await message.answer(preset_reply_text(action), reply_markup=REPLY_KEYBOARD)
                return
            if wants_visual(message.text):
                await visual_from_chat(message, message.text)
                return
            directive = consume_pending(message.from_user.id) if message.from_user else ""
            await respond(message, message.text, directive)

    @router.message(F.chat.type == "private", F.photo, F.media_group_id)
    async def photo_album(message: Message) -> None:
        if not await permit(message) or not message.from_user or not message.photo:
            return
        await typing(message)
        key = f"admin_album:{message.chat.id}:{message.media_group_id}"
        item = {"file_id": message.photo[-1].file_id, "message_id": message.message_id, "user_id": message.from_user.id, "caption": message.caption or ""}
        async with gate_lock:
            row = db.one("SELECT value FROM settings WHERE key=?", (key,))
            items = aggregate_album_items(json.loads(row["value"]) if row else [], item)
            db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, json.dumps(items, ensure_ascii=False)))
        await asyncio.sleep(1.5)
        async with gate_lock:
            row = db.one("SELECT value FROM settings WHERE key=?", (key,))
            if not row:
                return
            items = __import__("json").loads(row["value"])
            db.execute("DELETE FROM settings WHERE key=?", (key,))
        if any(entry["user_id"] != message.from_user.id for entry in items):
            await message.answer("تعذر جمع الصور لأن مرسل الألبوم غير متطابق.")
            return
        try:
            attachments = []
            import io
            for entry in items:
                buffer = io.BytesIO()
                await message.bot.download(entry["file_id"], destination=buffer)
                attachments.append(store_media(buffer.getvalue(), settings.data_dir, file_id=entry["file_id"], kind="image", max_bytes=settings.max_media_bytes, filename=f"{entry['message_id']}.jpg"))
            caption = next((entry["caption"] for entry in items if entry["caption"]), "")
            prompt_text, caption_directive = split_preset_caption(normalize_text(caption, settings.max_text_chars))
            directive = caption_directive or consume_pending(message.from_user.id)
            await respond(message, prompt_text or "Analyse the album images together.", directive, attachments=attachments)
        except Exception as exc:
            error = str(exc) if isinstance(exc, ValueError) else "تعذر حفظ صور الألبوم أو تحليلها."
            await message.answer(error)
            audit.record("incoming", chat_id=message.chat.id, user_id=message.from_user.id, kind="media_error", content=error)

    @router.message(F.chat.type == "private", F.photo | F.voice | F.audio | F.document, F.media_group_id == None)
    async def multimodal(message: Message) -> None:
        if not await permit(message) or not message.from_user:
            return
        await typing(message)
        try:
            if message.photo:
                file, kind, name = message.photo[-1], "image", f"{message.message_id}.jpg"
            elif message.voice:
                file, kind, name = message.voice, "voice", f"{message.message_id}.ogg"
            elif message.audio:
                file, kind, name = message.audio, "audio", message.audio.file_name or f"{message.message_id}.audio"
            else:
                file, kind, name = message.document, "document", message.document.file_name or f"{message.message_id}.bin"
                if str(getattr(message.document, "mime_type", "") or "").startswith("image/"):
                    kind = "image"
            if file.file_size and file.file_size > settings.max_media_bytes:
                raise ValueError(f"حجم الملف يتجاوز الحد المسموح ({settings.max_media_bytes // (1024 * 1024)} ميجابايت).")
            import io
            buffer = io.BytesIO()
            await message.bot.download(file.file_id, destination=buffer)
            record = store_media(buffer.getvalue(), settings.data_dir, file_id=file.file_id, kind=kind, max_bytes=settings.max_media_bytes, filename=name)
            prompt_text, caption_directive = split_preset_caption(normalize_text(message.caption or "", settings.max_text_chars))
            if kind == "document":
                suffix = Path(name).suffix.lower()
                if suffix not in {".txt", ".md", ".csv", ".log", ".json"}:
                    await message.answer("حُفظ الملف وسُجّل. أعالج الملفات النصية والصور والتسجيلات، وأعالج PDF والصور المتعددة كمصادر — أرسل ما يناسبك.")
                    audit.record("incoming", chat_id=message.chat.id, user_id=message.from_user.id, kind="document_unsupported", content=message.caption or "", file_refs=[str(record["local_path"])])
                    return
                try:
                    document_text = Path(str(record["local_path"])).read_text(encoding="utf-8")
                except (UnicodeError, OSError) as exc:
                    raise ValueError("تعذر قراءة المستند النصي بترميز UTF-8.") from exc
                prompt_text = normalize_text(((prompt_text + "\n") if prompt_text else "") + document_text, settings.max_text_chars)
                directive = caption_directive or consume_pending(message.from_user.id)
                await respond(message, prompt_text, directive, attachment=record)
                return
            if kind in {"voice", "audio"} and str(record.get("mime", "")).startswith("audio/ogg"):
                # Compatible models may accept OGG directly; provide explicit graceful fallback on rejection.
                pass
            directive = caption_directive or consume_pending(message.from_user.id)
            await respond(message, prompt_text or ("Analyse the attached image for the study session." if kind == "image" else "Transcribe the recording and answer it."), directive, attachment=record)
        except Exception as exc:
            if message.from_user:
                audit.record("incoming", chat_id=message.chat.id, user_id=message.from_user.id, kind="media_error", content=str(exc)[:500])
            error = str(exc) if isinstance(exc, ValueError) else "تعذر حفظ الملف أو التحقق منه."
            await message.answer(error)
            audit.record("incoming", chat_id=message.chat.id, user_id=message.from_user.id, kind="media_error", content=error)

    return router


def command_scopes(community_chat_id: int) -> list[tuple[object, list[BotCommand]]]:
    """Build the public, community, and administrator command menus."""
    study_commands = [
        BotCommand(command="start", description="بدء نافذة الدراسة"),
        BotCommand(command="help", description="عرض دليل الاستخدام"),
        BotCommand(command="new", description="محادثة جديدة"),
        BotCommand(command="usage", description="الاستخدام اليومي"),
        BotCommand(command="summary", description="تلخيص"),
        BotCommand(command="notes", description="ملاحظات دراسية"),
        BotCommand(command="explain", description="شرح خطوة بخطوة"),
        BotCommand(command="exercise", description="تمرين تدريبي"),
        BotCommand(command="flash", description="بطاقات مراجعة"),
        BotCommand(command="menu", description="عرض القائمة الرئيسية"),
        BotCommand(command="groups", description="إدارة المجموعات (كتم/إلغاء)"),
    ]
    return [
        (BotCommandScopeDefault(), study_commands),
        (BotCommandScopeChat(chat_id=community_chat_id), [BotCommand(command="rules", description="قواعد المجتمع")]),
        (BotCommandScopeChatAdministrators(chat_id=community_chat_id), [
            BotCommand(command="block", description="إضافة كلمة إلى المرشح"),
            BotCommand(command="unblock", description="حذف كلمة من المرشح"),
            BotCommand(command="reset", description="تصفير مخالفات عضو"),
            BotCommand(command="warns", description="ملف مخالفات عضو"),
            BotCommand(command="stats", description="إحصاءات الرقابة"),
        ]),
    ]


async def set_commands(bot, community_chat_id: int) -> None:
    for scope, commands in command_scopes(community_chat_id):
        await bot.set_my_commands(commands, scope=scope)
