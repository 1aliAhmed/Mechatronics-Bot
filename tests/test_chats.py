from __future__ import annotations

from app.config import get_settings
from app.db import Database
from app.flows.admin import REPLY_KEYBOARD, group_menu_view, welcome_keyboard
from app.flows.moderation import is_mute_exempt


def make_db(tmp_path) -> Database:
    return Database(tmp_path / "bot.db")


def test_chat_registry_roundtrip(tmp_path):
    db = make_db(tmp_path)
    db.upsert_chat(-1001, "مجموعة الاختبار", "supergroup")
    row = db.chat_row(-1001)
    assert row["title"] == "مجموعة الاختبار"
    assert row["muted"] == 0
    db.set_chat_muted(-1001, True, 42)
    row = db.chat_row(-1001)
    assert row["muted"] == 1
    assert row["muted_by"] == 42
    assert row["muted_at"]
    db.set_chat_muted(-1001, False, 42)
    assert db.chat_row(-1001)["muted"] == 0
    assert db.chat_row(-1001)["muted_at"] is None
    db.remove_chat(-1001)
    assert db.chat_row(-1001) is None


def test_mute_exempt_covers_admins_owner_and_trust_list():
    assert is_mute_exempt("creator", 1, frozenset())
    assert is_mute_exempt("administrator", 2, frozenset())
    assert is_mute_exempt("member", 3, frozenset({3}))
    assert not is_mute_exempt("member", 4, frozenset())
    assert not is_mute_exempt(None, 5, frozenset())


def test_group_menu_view_toggles():
    text, keyboard = group_menu_view("مجموعة", -1001, False)
    assert "مفتوحة" in text
    assert keyboard.inline_keyboard[0][0].callback_data == "grp:mute:-1001"
    text, keyboard = group_menu_view("مجموعة", -1001, True)
    assert "مقفلة" in text
    assert keyboard.inline_keyboard[0][0].callback_data == "grp:unmute:-1001"
    assert keyboard.inline_keyboard[1][0].callback_data == "grp:menu:-1001"


def test_mute_warning_default_is_15_seconds():
    import os
    os.environ.pop("MUTE_WARNING_SECONDS", None)
    assert get_settings().mute_warning_seconds == 15


def test_keyboards_are_compact():
    assert len(REPLY_KEYBOARD.keyboard) == 3
    assert not REPLY_KEYBOARD.is_persistent
    assert all(len(row) <= 3 for row in REPLY_KEYBOARD.keyboard)
    welcome = welcome_keyboard()
    assert len(welcome.inline_keyboard) == 3
    assert all(len(row) <= 3 for row in welcome.inline_keyboard)


def test_muted_group_deletes_member_messages_and_warns(tmp_path):
    import asyncio as _asyncio
    import dataclasses

    from app.audit import AuditLogger
    from app.config import Settings
    from app.flows.moderation import create_filter, install_moderation

    settings = dataclasses.replace(Settings.from_env(), community_chat_id=-1001, admin_ids=frozenset(), mute_warning_seconds=0)
    db = Database(tmp_path / "mute.db")
    audit = AuditLogger(db, tmp_path / "logs")
    db.upsert_chat(-2002, "مجموعة", "supergroup")
    db.set_chat_muted(-2002, True, 7)
    db.set_chat_notice(-2002, 321)
    row = db.chat_row(-2002)
    assert row["notice_message_id"] == 321
    db.set_chat_notice(-2002, None)
    assert db.chat_row(-2002)["notice_message_id"] is None

    class Chat:
        id = -2002
        type = "supergroup"
        title = "مجموعة"

    class Sent:
        message_id = 900
        ephemeral_message_id = 901

    class Bot:
        def __init__(self):
            self.ephemeral = []

        async def get_chat_member(self, chat_id, user_id):
            class Member:
                status = "administrator" if user_id == 66 else "member"
            return Member()

        async def send_message(self, chat_id, text, **kwargs):
            if kwargs.get("ephemeral_message_parameters") is not None:
                self.ephemeral.append((chat_id, text))
            return Sent()

        async def delete_ephemeral_message(self, chat_id, user_id, ephemeral_id):
            return True

    class Message:
        def __init__(self, user_id):
            self.chat = Chat()
            self.from_user = type("User", (), {"id": user_id, "username": "u", "full_name": "U"})()
            self.text = "hello"
            self.caption = None
            self.message_id = 5
            self.bot = Bot()
            self.deleted = False

        async def delete(self):
            self.deleted = True

    router = install_moderation(settings, db, create_filter(settings, db), audit)
    handler = [h for h in router.message.handlers if getattr(h.callback, "__name__", "") == "moderate"][-1]

    member = Message(55)
    _asyncio.run(handler.callback(member))
    assert member.deleted
    assert member.bot.ephemeral

    admin = Message(66)
    _asyncio.run(handler.callback(admin))
    assert not admin.deleted

    db.set_chat_muted(-2002, False, 7)
    after = Message(77)
    _asyncio.run(handler.callback(after))
    assert not after.deleted
    assert not after.bot.ephemeral
    assert db.all("SELECT id FROM audit_log WHERE kind='mute'")
