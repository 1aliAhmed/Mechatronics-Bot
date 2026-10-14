from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from app.audit import AuditLogger
from app.config import Settings
from app.db import Database
from app.flows.admin import MUTE_TOPIC_NOTICE, group_menu_view, install_admin, topics_view
from app.quota import QuotaService
from app.security import CommunityGuard


def make_settings(**overrides) -> Settings:
    base = dict(community_chat_id=-1001, admin_ids=frozenset(), dm_quota_1h=10, dm_quota_5h=0, dm_quota_24h=0, repo_url="")
    base.update(overrides)
    return replace(Settings.from_env(), **base)


def test_topic_table_roundtrip(tmp_path):
    db = Database(tmp_path / "topics.db")
    db.topic_upsert(-1001, 77, "المختبر")
    db.topic_upsert(-1001, 78)
    db.set_topic_muted(-1001, 77, True, 500)
    row = db.topic_row(-1001, 77)
    assert row["title"] == "المختبر" and row["muted"] == 1 and row["notice_message_id"] == 500
    assert [entry["thread_id"] for entry in db.topics_for(-1001)] == [77, 78] or [entry["thread_id"] for entry in db.topics_for(-1001)] == [78, 77]
    db.set_topic_muted(-1001, 77, False, None)
    assert db.topic_row(-1001, 77)["muted"] == 0


def test_topics_view_labels_and_callbacks():
    rows = [{"thread_id": 77, "title": "المختبر", "muted": 1, "notice_message_id": 500}, {"thread_id": 78, "title": "", "muted": 0, "notice_message_id": None}]
    text, keyboard = topics_view(-1001, rows)
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    datas = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "المختبر — مكتوم" in labels
    assert "موضوع #78" in labels
    assert "grptt:-1001:77" in datas and "grptt:-1001:78" in datas
    assert f"grp:menu:-1001" in datas
    empty_text, empty_keyboard = topics_view(-1001, [])
    assert "لا توجد مواضيع" in empty_text
    assert len(empty_keyboard.inline_keyboard) == 1


def test_group_menu_shows_topics_button_only_for_forums():
    _, forum_menu = group_menu_view("المجتمع", -1001, False, forum=True)
    datas = [button.callback_data for row in forum_menu.inline_keyboard for button in row]
    assert "grpt:-1001" in datas
    _, plain_menu = group_menu_view("مجموعة", -1002, False, forum=False)
    datas = [button.callback_data for row in plain_menu.inline_keyboard for button in row]
    assert not any(data.startswith("grpt:") for data in datas)


def test_guard_records_topics_and_titles(tmp_path):
    settings = make_settings()
    db = Database(tmp_path / "guard-topics.db")
    guard = CommunityGuard(settings, db, AuditLogger(db, tmp_path / "logs"))
    handled = []

    async def handler(event, data):
        handled.append(True)
        return "ok"

    def update(**message_fields):
        fields = {"chat": SimpleNamespace(id=-1001, type="supergroup", title="المجتمع"), "from_user": SimpleNamespace(id=5), "message_thread_id": None, "forum_topic_created": None, "forum_topic_edited": None}
        fields.update(message_fields)
        message = SimpleNamespace(**fields)
        return SimpleNamespace(message=message, edited_message=None, channel_post=None, edited_channel_post=None, callback_query=None)

    plain = update(message_thread_id=77)
    asyncio.run(guard(handler, plain, {"bot": None}))
    assert db.topic_row(-1001, 77) is not None and db.topic_row(-1001, 77)["title"] == ""
    created = update(message_thread_id=78, forum_topic_created=SimpleNamespace(title="مختبر الاتصالات"))
    asyncio.run(guard(handler, created, {"bot": None}))
    assert db.topic_row(-1001, 78)["title"] == "مختبر الاتصالات"
    edited = update(message_thread_id=78, forum_topic_edited=SimpleNamespace(name="مختبر الاتصالات 2"))
    asyncio.run(guard(handler, edited, {"bot": None}))
    assert db.topic_row(-1001, 78)["title"] == "مختبر الاتصالات 2"
    assert len(handled) == 3


class _TopicBot:
    id = 999

    def __init__(self):
        self.closed, self.reopened, self.deleted, self.pinned, self.sent = [], [], [], [], []

    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status="administrator")

    async def close_forum_topic(self, chat_id, message_thread_id):
        self.closed.append((chat_id, message_thread_id))
        return True

    async def reopen_forum_topic(self, chat_id, message_thread_id):
        self.reopened.append((chat_id, message_thread_id))
        return True

    async def send_message(self, chat_id, text, message_thread_id=None, **kwargs):
        self.sent.append((chat_id, text, message_thread_id))
        return SimpleNamespace(message_id=500)

    async def pin_chat_message(self, chat_id, message_id, **kwargs):
        self.pinned.append((chat_id, message_id))
        return True

    async def unpin_chat_message(self, chat_id, message_id):
        self.deleted.append(("unpin", chat_id, message_id))
        return True

    async def delete_message(self, chat_id, message_id):
        self.deleted.append(("delete", chat_id, message_id))
        return True


class _TopicMessage:
    def __init__(self):
        self.chat = SimpleNamespace(id=7)
        self.edits = []

    async def edit_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))
        return None

    async def answer(self, text=None, **kwargs):
        return None


class _TopicCallback:
    def __init__(self, data, bot):
        self.data = data
        self.from_user = SimpleNamespace(id=7)
        self.message = _TopicMessage()
        self.bot = bot
        self.alerts = []

    async def answer(self, text=None, **kwargs):
        self.alerts.append(text)


def _topic_router(tmp_path, db):
    settings = make_settings()
    audit = AuditLogger(db, tmp_path / "logs")
    router = install_admin(settings, db, audit, SimpleNamespace(), Path("prompts") / "study_harness.md", None, QuotaService(db, settings))
    return [h for h in router.callback_query.handlers if getattr(h.callback, "__name__", "") == "topic_toggle"][-1]


def test_topic_toggle_mutes_and_unmutes_with_notice_cleanup(tmp_path):
    db = Database(tmp_path / "toggle.db")
    db.topic_upsert(-1001, 77, "المختبر")
    handler = _topic_router(tmp_path, db)
    bot = _TopicBot()

    callback = _TopicCallback("grptt:-1001:77", bot)
    asyncio.run(handler.callback(callback))
    assert bot.closed == [(-1001, 77)]
    assert bot.sent and bot.sent[-1][2] == 77 and MUTE_TOPIC_NOTICE in bot.sent[-1][1]
    assert bot.pinned == [(-1001, 500)]
    row = db.topic_row(-1001, 77)
    assert row["muted"] == 1 and row["notice_message_id"] == 500
    assert callback.alerts[-1] == "تم كتم الموضوع؛ لن يكتب الأعضاء فيه حتى فك الكتم."

    callback = _TopicCallback("grptt:-1001:77", bot)
    asyncio.run(handler.callback(callback))
    assert bot.reopened == [(-1001, 77)]
    assert ("unpin", -1001, 500) in bot.deleted and ("delete", -1001, 500) in bot.deleted
    row = db.topic_row(-1001, 77)
    assert row["muted"] == 0 and row["notice_message_id"] is None
    assert callback.alerts[-1] == "تم إلغاء كتم الموضوع."