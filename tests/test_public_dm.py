from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import Update

from app.ai.queue import JobQueue
from app.audit import AuditLogger
from app.config import Settings
from app.db import Database
from app.flows.admin import install_admin, intro_text
from app.flows.clean import install_clean
from app.quota import QuotaService, quota_message
from app.security import CommunityGuard


def make_settings(**overrides) -> Settings:
    base = dict(community_chat_id=-1001, admin_ids=frozenset(), dm_quota_1h=10, dm_quota_5h=0, dm_quota_24h=0, repo_url="")
    base.update(overrides)
    return replace(Settings.from_env(), **base)


def test_hourly_window_blocks_and_recovers(tmp_path):
    settings = make_settings()
    db = Database(tmp_path / "quota1h.db")
    now = [100_000.0]
    service = QuotaService(db, settings, clock=lambda: now[0])
    for _ in range(settings.dm_quota_1h):
        assert service.consume(7) == 0
    retry = service.consume(7)
    assert retry > 0
    used_hour, used_day, state_retry = service.state(7)
    assert (used_hour, used_day) == (settings.dm_quota_1h, settings.dm_quota_1h)
    assert state_retry == retry
    now[0] += 3600 + 1
    assert service.consume(7) == 0


def test_zero_windows_are_disabled(tmp_path):
    settings = make_settings(dm_quota_1h=3, dm_quota_24h=0)
    db = Database(tmp_path / "quota-off.db")
    now = [200_000.0]
    service = QuotaService(db, settings, clock=lambda: now[0])
    for _ in range(3):
        assert service.consume(9) == 0
        now[0] += 10
    assert service.consume(9) > 0
    now[0] += 3600 + 1
    for _ in range(6):
        assert service.consume(9) == 0
        now[0] += 3600 + 1


def test_quota_message_marks_the_limit_as_temporary(tmp_path):
    settings = make_settings()
    text = quota_message(settings, 90)
    assert "10 رسائل كل ساعة" in text
    assert "مؤقت" in text
    assert "2 دقيقة" in text
    assert "دقيقة" in text


def test_mark_introduced_flips_once(tmp_path):
    db = Database(tmp_path / "intro.db")
    assert db.mark_introduced(5) is True
    assert db.mark_introduced(5) is False


def test_intro_text_includes_repo_when_configured():
    with_repo = intro_text(make_settings(repo_url="https://github.com/me/megatronics-bot"))
    assert "https://github.com/me/megatronics-bot" in with_repo
    assert "10 رسائل كل ساعة" in with_repo
    assert "مؤقت" in with_repo
    without_repo = intro_text(make_settings())
    assert "GitHub" not in without_repo


def test_guard_allows_private_dm_from_anyone(tmp_path):
    settings = make_settings()
    db = Database(tmp_path / "guard-private.db")
    audit = AuditLogger(db, tmp_path / "logs")
    guard = CommunityGuard(settings, db, audit)
    calls = []

    async def handler(event, data):
        calls.append(event.message.from_user.id)

    message = SimpleNamespace(chat=SimpleNamespace(type="private", id=5), from_user=SimpleNamespace(id=777), text="hello")
    event = Update.model_construct(update_id=1, message=message)
    asyncio.run(guard(handler, event, {"bot": object()}))
    assert calls == [777]


def test_first_contact_middleware_sends_intro_once(tmp_path):
    settings = make_settings(repo_url="https://github.com/me/megatronics-bot")
    db = Database(tmp_path / "middleware.db")
    audit = AuditLogger(db, tmp_path / "logs")
    quota = QuotaService(db, settings)
    router = install_admin(settings, db, audit, SimpleNamespace(), Path("prompts") / "study_harness.md", None, quota)
    assert len(router.message.middleware) >= 1

    class Bot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text):
            self.sent.append((chat_id, text))

    bot = Bot()
    handled = []

    async def handler(event, data):
        handled.append(True)

    event = SimpleNamespace(chat=SimpleNamespace(type="private", id=10), from_user=SimpleNamespace(id=555), bot=bot)
    first = router.message.middleware[0]
    asyncio.run(first(handler, event, {}))
    asyncio.run(first(handler, event, {}))
    assert len(bot.sent) == 1 and "github.com" in bot.sent[0][1]
    assert handled == [True, True]


def _source_router(tmp_path, db, settings):
    audit = AuditLogger(db, tmp_path / "logs")
    router = install_clean(settings, db, audit, SimpleNamespace(), JobQueue(db), SimpleNamespace())
    return [h for h in router.message.handlers if getattr(h.callback, "__name__", "") == "document"][-1]


def _source_message(status: str):
    class Bot:
        async def get_chat_member(self, chat_id, user_id):
            return SimpleNamespace(status=status)

        async def download(self, file_id, destination):
            Path(destination).write_bytes(b"%PDF-1.4 fake")

    class Message:
        def __init__(self):
            self.chat = SimpleNamespace(type="private", id=42)
            self.from_user = SimpleNamespace(id=777)
            self.message_id = 3
            self.caption = None
            self.text = ""
            self.document = SimpleNamespace(file_id="f", file_name="a.pdf", mime_type="application/pdf")
            self.bot = Bot()
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append(text)

    return Message()


def _latest_payload(db):
    row = db.one("SELECT payload FROM jobs WHERE kind='source' ORDER BY id DESC LIMIT 1")
    return json.loads(row["payload"])


def test_guest_source_submission_uses_quota_and_page_cap(tmp_path):
    settings = make_settings()
    db = Database(tmp_path / "sources.db")
    handler = _source_router(tmp_path, db, settings)
    message = _source_message("member")
    asyncio.run(handler.callback(message))
    assert any("سأعمل عليه في الخلفية" in text for text in message.answers)
    payload = _latest_payload(db)
    assert payload["public"] is True
    assert payload["limit_hint"] == settings.public_source_pages == 10


def test_guest_source_submission_blocked_by_quota(tmp_path):
    settings = make_settings(dm_quota_1h=1)
    db = Database(tmp_path / "sources-quota.db")
    handler = _source_router(tmp_path, db, settings)
    asyncio.run(handler.callback(_source_message("member")))
    blocked = _source_message("member")
    asyncio.run(handler.callback(blocked))
    assert any("الحد التجريبي المؤقت" in text for text in blocked.answers)
    assert db.one("SELECT COUNT(*) AS n FROM jobs WHERE kind='source'")["n"] == 1


def test_admin_source_submission_is_uncapped_and_quota_free(tmp_path):
    settings = make_settings(dm_quota_1h=1)
    db = Database(tmp_path / "sources-admin.db")
    handler = _source_router(tmp_path, db, settings)
    for _ in range(2):
        notice = _source_message("administrator")
        asyncio.run(handler.callback(notice))
        assert any("/source_status" in text for text in notice.answers)
    assert db.one("SELECT COUNT(*) AS n FROM jobs WHERE kind='source'")["n"] == 2
    payload = _latest_payload(db)
    assert payload["public"] is False and payload["limit_hint"] is None


def test_guest_image_document_skips_sources_pipeline(tmp_path):
    import pytest
    from aiogram.dispatcher.event.bases import SkipHandler

    settings = make_settings()
    db = Database(tmp_path / "image-doc.db")
    audit = AuditLogger(db, tmp_path / "logs")
    router = install_clean(settings, db, audit, SimpleNamespace(), JobQueue(db), SimpleNamespace())
    handler = [h for h in router.message.handlers if getattr(h.callback, "__name__", "") == "document"][-1]

    class Bot:
        async def get_chat_member(self, chat_id, user_id):
            return SimpleNamespace(status="member")

    message = SimpleNamespace(
        chat=SimpleNamespace(type="private", id=42),
        from_user=SimpleNamespace(id=777),
        message_id=3,
        caption=None,
        document=SimpleNamespace(file_id="f", file_name="pic.png", mime_type="image/png"),
        bot=Bot(),
    )
    with pytest.raises(SkipHandler):
        asyncio.run(handler.callback(message))


class _PubBot:
    id = 999

    def __init__(self):
        self.sent_documents = []

    async def get_chat_member(self, chat_id, user_id):
        if user_id == 7:
            return SimpleNamespace(status="administrator" if chat_id == -1001 else "member")
        return SimpleNamespace(status={"-1001": "administrator", "-2002": "member", "-3003": "member"}.get(str(chat_id), "left"))

    async def send_document(self, chat_id, file, caption=None):
        self.sent_documents.append((chat_id, caption))


class _PubMessage:
    def __init__(self):
        self.chat = SimpleNamespace(id=7)
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))
        return None


class _PubCallback:
    def __init__(self, data, bot):
        self.data = data
        self.from_user = SimpleNamespace(id=7)
        self.message = _PubMessage()
        self.bot = bot
        self.alerts = []

    async def answer(self, text=None, **kwargs):
        self.alerts.append(text)


def _publish_router(tmp_path, db):
    from app.ai.queue import JobQueue
    from app.flows.clean import install_clean

    artifact = tmp_path / "doc.pdf"
    artifact.write_bytes(b"%PDF-1.4")
    db.execute("INSERT INTO docs(hash,artifact,markdown,source) VALUES(?,?,?,?)", ("d" * 64, str(artifact), "md", "[]"))
    for chat_id, title, kind in ((-1001, "المجتمع", "supergroup"), (-2002, "مجموعة الضيوف", "supergroup"), (-3003, "قناة التجارب", "channel")):
        db.execute("INSERT INTO chats(chat_id,title,chat_type) VALUES(?,?,?)", (chat_id, title, kind))
    settings = make_settings()
    audit = AuditLogger(db, tmp_path / "logs")
    router = install_clean(settings, db, audit, SimpleNamespace(), JobQueue(db), SimpleNamespace())
    return [h for h in router.callback_query.handlers if getattr(h.callback, "__name__", "") == "approval"][-1]


def test_publish_button_lists_groups_and_channels(tmp_path):
    db = Database(tmp_path / "publish.db")
    handler = _publish_router(tmp_path, db)
    bot = _PubBot()
    callback = _PubCallback("doc:publish:" + "d" * 32, bot)
    asyncio.run(handler.callback(callback))
    keyboard = callback.message.answers[-1][1]["reply_markup"]
    datas = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any(data.endswith(":-1001") for data in datas)
    assert any(data.endswith(":-2002") for data in datas)
    assert not any(data.endswith(":-3003") for data in datas)  # bot is not a channel admin
    assert "المجتمع الرئيسي: المجتمع" in labels


def test_publish_button_sends_to_the_chosen_chat(tmp_path):
    db = Database(tmp_path / "publish-send.db")
    handler = _publish_router(tmp_path, db)
    bot = _PubBot()
    callback = _PubCallback("doc:publish:" + "d" * 32 + ":-2002", bot)
    asyncio.run(handler.callback(callback))
    assert bot.sent_documents[-1][0] == -2002
    assert callback.alerts[-1] == "تم النشر."
