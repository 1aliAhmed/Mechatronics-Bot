from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from aiogram.types import BotCommandScopeChat, BotCommandScopeChatAdministrators, BotCommandScopeDefault, ChatMemberUpdated, Update

from app.audit import AuditLogger
from app.config import Settings
from app.db import Database
from app.flows.admin import command_scopes
from app.flows.community import load_rules, welcome_text
from app.security import CommunityGuard


def test_guard_passes_bound_chat_member_and_drops_foreign(tmp_path):
    settings = replace(Settings.from_env(), community_chat_id=-1001)
    db = Database(tmp_path / "guard-members.db")
    audit = AuditLogger(db, tmp_path / "logs")
    guard = CommunityGuard(settings, db, audit)
    calls: list[int] = []

    async def handler(event, data):
        calls.append(event.chat_member.chat.id)

    async def run():
        for chat_id in (-1001, -2002):
            member_update = ChatMemberUpdated.model_construct(chat=SimpleNamespace(id=chat_id))
            event = Update.model_construct(update_id=chat_id, chat_member=member_update)
            await guard(handler, event, {"bot": object()})

    asyncio.run(run())
    assert calls == [-1001]


def test_welcome_text_substitutes_name():
    assert welcome_text("ليلى", "أهلاً {name}!") == "أهلاً ليلى!"


def test_rules_loader_reads_arabic_prompt(tmp_path):
    path = tmp_path / "rules_ar.md"
    path.write_text("احترم الجميع.\n", encoding="utf-8")
    assert load_rules(path) == "احترم الجميع."


def test_database_clears_strikes(tmp_path):
    db = Database(tmp_path / "strikes.db")
    assert db.strike(42) == 1
    assert db.strike(42) == 2
    assert db.clear_strikes(42)
    assert db.one("SELECT count FROM strikes WHERE user_id=42") is None
    assert not db.clear_strikes(42)


def test_command_scopes_separate_study_community_and_admin_commands():
    scopes = command_scopes(-100123)
    assert len(scopes) == 3
    default_scope, default_commands = scopes[0]
    community_scope, community_commands = scopes[1]
    admin_scope, admin_commands = scopes[2]
    assert isinstance(default_scope, BotCommandScopeDefault)
    assert {command.command for command in default_commands} == {
        "start", "help", "new", "usage", "summary", "notes", "explain", "exercise", "flash", "menu", "groups"
    }
    assert isinstance(community_scope, BotCommandScopeChat)
    assert community_scope.chat_id == -100123
    assert [command.command for command in community_commands] == ["rules"]
    assert isinstance(admin_scope, BotCommandScopeChatAdministrators)
    assert admin_scope.chat_id == -100123
    assert {command.command for command in admin_commands} == {"block", "unblock", "reset", "warns", "stats"}
