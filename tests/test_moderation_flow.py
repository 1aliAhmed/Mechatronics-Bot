from __future__ import annotations

import asyncio
import dataclasses

from app.audit import AuditLogger
from app.config import Settings
from app.db import Database
from app.flows import moderation as moderation_module
from app.flows.moderation import create_filter, install_moderation


class _Chat:
    id = -3003
    type = "supergroup"
    title = "مجموعة"


class _User:
    def __init__(self, user_id):
        self.id = user_id
        self.username = "u"
        self.full_name = "User"


class _Bot:
    def __init__(self, fail_member_check=False, status="member"):
        self.fail_member_check = fail_member_check
        self.status = status
        self.sent = []

    async def get_chat_member(self, chat_id, user_id):
        if self.fail_member_check:
            raise RuntimeError("api down")
        return type("Member", (), {"status": self.status})()

    async def send_message(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return type("Sent", (), {"message_id": 2, "ephemeral_message_id": 1})()

    async def delete_ephemeral_message(self, *args, **kwargs):
        return True


class _Msg:
    def __init__(self, text, user_id=88, bot=None):
        self.chat = _Chat()
        self.from_user = _User(user_id)
        self.text = text
        self.caption = None
        self.message_id = 1
        self.bot = bot or _Bot()
        self.deleted = False
        self.replies = []
        self.answers = []

    async def delete(self):
        self.deleted = True

    async def answer(self, text=None, *args, **kwargs):
        if text is not None:
            self.answers.append(text)
        return None

    async def reply(self, text, **kwargs):
        self.replies.append(text)

    reply_to_message = None


def _settings(**overrides):
    settings = dataclasses.replace(Settings.from_env(), community_chat_id=-1001, admin_ids=frozenset(), mute_warning_seconds=0, warning_delete_seconds=0)
    return dataclasses.replace(settings, **overrides) if overrides else settings


def _handler(settings, db, audit):
    router = install_moderation(settings, db, create_filter(settings, db), audit)
    return [h for h in router.message.handlers if getattr(h.callback, "__name__", "") == "moderate"][-1]


def _db_with_word(tmp_path, name: str) -> Database:
    db = Database(tmp_path / name)
    db.execute("INSERT INTO blocked_words(language,word) VALUES('en','badword')")
    return db


def test_dry_run_does_not_write_or_strike(tmp_path):
    settings = _settings(dry_run=True)
    db = _db_with_word(tmp_path, "dry.db")
    audit = AuditLogger(db, tmp_path / "logs")
    handler = _handler(settings, db, audit)
    message = _Msg("say badword now")
    asyncio.run(handler.callback(message))
    assert not message.deleted
    assert db.all("SELECT id FROM violations") == []
    assert db.strike_window(88, 30) == 0
    assert db.all("SELECT id FROM audit_log WHERE kind='moderation'")


def test_enforce_writes_violation_and_strike(tmp_path):
    settings = _settings(dry_run=False)
    db = _db_with_word(tmp_path, "armed.db")
    audit = AuditLogger(db, tmp_path / "logs")
    handler = _handler(settings, db, audit)
    message = _Msg("say badword now")
    asyncio.run(handler.callback(message))
    assert message.deleted
    assert len(db.all("SELECT id FROM violations")) == 1
    assert db.strike_window(88, 30) == 1


def test_member_violation_warning_is_offender_only(tmp_path):
    moderation_module._admin_checks.clear()
    settings = _settings(dry_run=False)
    db = _db_with_word(tmp_path, "offender-only.db")
    audit = AuditLogger(db, tmp_path / "logs")
    handler = _handler(settings, db, audit)
    message = _Msg("say badword now")
    asyncio.run(handler.callback(message))
    assert message.deleted
    assert message.answers == []  # nothing visible to the group
    sent = message.bot.sent
    assert len(sent) == 1
    assert "ephemeral_message_parameters" in sent[0][1]


def test_admin_violation_warns_without_strikes(tmp_path):
    moderation_module._admin_checks.clear()
    settings = _settings(dry_run=False)
    db = _db_with_word(tmp_path, "admin-violation.db")
    audit = AuditLogger(db, tmp_path / "logs")
    handler = _handler(settings, db, audit)
    message = _Msg("say badword now", user_id=44, bot=_Bot(status="administrator"))
    asyncio.run(handler.callback(message))
    assert message.deleted
    assert message.answers == []
    assert len(message.bot.sent) == 1
    assert "ephemeral_message_parameters" in message.bot.sent[0][1]
    assert db.all("SELECT id FROM violations") == []
    assert db.strike_window(44, 30) == 0
    params = [str(row["params"]) for row in db.all("SELECT params FROM audit_log WHERE kind='moderation'")]
    assert any('"admin": true' in entry for entry in params)


def test_admin_violation_dry_run_logs_only(tmp_path):
    moderation_module._admin_checks.clear()
    settings = _settings(dry_run=True)
    db = _db_with_word(tmp_path, "admin-dry.db")
    audit = AuditLogger(db, tmp_path / "logs")
    handler = _handler(settings, db, audit)
    message = _Msg("say badword now", user_id=44, bot=_Bot(status="administrator"))
    asyncio.run(handler.callback(message))
    assert not message.deleted
    assert db.all("SELECT id FROM violations") == []
    params = [str(row["params"]) for row in db.all("SELECT params FROM audit_log WHERE kind='moderation'")]
    assert any('"admin": true' in entry for entry in params)


def test_edited_message_violation_is_removed(tmp_path):
    settings = _settings(dry_run=False)
    db = _db_with_word(tmp_path, "edited.db")
    audit = AuditLogger(db, tmp_path / "logs")
    router = install_moderation(settings, db, create_filter(settings, db), audit)
    handler = [h for h in router.edited_message.handlers if getattr(h.callback, "__name__", "") == "moderate_edited"][-1]
    message = _Msg("say badword after editing")
    asyncio.run(handler.callback(message))
    assert message.deleted
    assert len(db.all("SELECT id FROM violations")) == 1


def test_strike_window_decays_old_violations(tmp_path):
    from datetime import datetime, timedelta, timezone

    db = Database(tmp_path / "decay.db")
    old = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")
    fresh = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("INSERT INTO violations(chat_id,user_id,word,text,created_at) VALUES(?,?,?,?,?)", (-1, 5, "w", "t", old))
    db.execute("INSERT INTO violations(chat_id,user_id,word,text,created_at) VALUES(?,?,?,?,?)", (-1, 5, "w", "t", fresh))
    assert db.strike_window(5, 30) == 1
    assert db.strike_window(5, 60) == 2


def test_warns_reports_member_history(tmp_path):
    moderation_module._admin_checks.clear()
    settings = _settings(dry_run=False)
    db = Database(tmp_path / "warns.db")
    db.execute("INSERT INTO violations(chat_id,user_id,word,text) VALUES(?,?,?,?)", (-3003, 55, "badword", "a snippet of the text"))
    audit = AuditLogger(db, tmp_path / "logs")
    router = install_moderation(settings, db, create_filter(settings, db), audit)
    handler = [h for h in router.message.handlers if getattr(h.callback, "__name__", "") == "warns"][-1]
    message = _Msg("/warns 55", user_id=99, bot=_Bot(status="administrator"))
    asyncio.run(handler.callback(message))
    report = message.replies[0]
    assert "المخالفات خلال 30 يوماً: 1" in report
    assert "badword" in report and "a snippet of the text" in report


def test_stats_reports_recent_activity(tmp_path):
    moderation_module._admin_checks.clear()
    settings = _settings(dry_run=False)
    db = Database(tmp_path / "stats.db")
    db.execute("INSERT INTO violations(chat_id,user_id,word,text) VALUES(?,?,?,?)", (-3003, 55, "badword", "t"))
    audit = AuditLogger(db, tmp_path / "logs")
    router = install_moderation(settings, db, create_filter(settings, db), audit)
    handler = [h for h in router.message.handlers if getattr(h.callback, "__name__", "") == "stats"][-1]
    message = _Msg("/stats", user_id=99, bot=_Bot(status="administrator"))
    asyncio.run(handler.callback(message))
    report = message.replies[0]
    assert "إحصاءات الرقابة" in report
    assert "المخالفات آخر ٣٠ يوماً: 1" in report
    assert "badword" in report


def test_transient_admin_check_failure_is_not_cached(tmp_path):
    moderation_module._admin_checks.clear()
    settings = _settings(dry_run=False)
    db = _db_with_word(tmp_path, "cache.db")
    audit = AuditLogger(db, tmp_path / "logs")
    handler = _handler(settings, db, audit)
    bot = _Bot(fail_member_check=True, status="administrator")
    first = _Msg("badword", user_id=99, bot=bot)
    asyncio.run(handler.callback(first))
    assert first.deleted
    assert len(db.all("SELECT id FROM violations")) == 1
    bot.fail_member_check = False
    second = _Msg("badword", user_id=99, bot=bot)
    asyncio.run(handler.callback(second))
    assert second.deleted
    # The recovered check marks the sender exempt: warned again, but no new violation row.
    assert len(db.all("SELECT id FROM violations")) == 1
    assert db.strike_window(99, 30) == 1
