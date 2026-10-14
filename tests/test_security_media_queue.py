from __future__ import annotations

import asyncio

import pytest

from app.ai.queue import JobQueue
from app.config import Settings
from app.db import Database
from app.media import normalize_text, store_media
from app.security import CommunityGuard, is_bound_chat, is_privileged
from app.flows.admin import aggregate_album_items, audio_mime


def test_guard_pure_policy():
    assert is_bound_chat(-1001, -1001)
    assert not is_bound_chat(-1002, -1001)
    assert is_privileged("administrator", 7, frozenset())
    assert is_privileged("member", 7, frozenset({7}))
    assert not is_privileged("member", 8, frozenset({7}))


def test_guard_registers_new_group_and_forwards(tmp_path):
    class Bot:
        def __init__(self):
            self.sent = []
        async def send_message(self, chat_id, text):
            self.sent.append((chat_id, text))

    class Chat:
        id = -2002
        type = "supergroup"
        title = "مجموعة بعيدة"
    class User:
        id = 9
    class Message:
        chat = Chat()
        from_user = User()
    class Update:
        message = Message()
        edited_message = channel_post = edited_channel_post = callback_query = None

    settings = Settings.from_env()
    settings = __import__("dataclasses").replace(settings, community_chat_id=-1001, admin_ids=frozenset())
    db = Database(tmp_path / "guard.db")
    audit = __import__("app.audit", fromlist=["AuditLogger"]).AuditLogger(db, tmp_path / "logs")
    guard, bot, calls = CommunityGuard(settings, db, audit), Bot(), []
    async def handler(event, data):
        calls.append(True)
    async def run():
        await guard(handler, Update(), {"bot": bot})
        await guard(handler, Update(), {"bot": bot})
    asyncio.run(run())
    assert calls == [True, True]
    assert bot.sent == []
    row = db.chat_row(-2002)
    assert row is not None and row["title"] == "مجموعة بعيدة"


def test_album_aggregation_and_audio_mime():
    first = {"message_id": 12, "file_id": "a"}
    second = {"message_id": 11, "file_id": "b"}
    assert aggregate_album_items([first], second) == [second, first]
    assert aggregate_album_items([first], {**first, "file_id": "updated"}) == [{**first, "file_id": "updated"}]
    assert audio_mime({"local_path": "recording.mp3"}) == "audio/mpeg"
    assert audio_mime({"local_path": "track.m4a"}) == "audio/mp4"


def test_text_normalization_caps():
    assert normalize_text("  hello\n  world ", 20) == "hello world"
    with pytest.raises(ValueError):
        normalize_text("long text", 4)


def test_media_mime_follows_original_audio_extension(tmp_path, monkeypatch):
    monkeypatch.setattr("app.media.shutil.which", lambda _: None)
    mp3 = store_media(b"mp3", tmp_path, file_id="mp3", kind="audio", max_bytes=100, filename="clip.mp3")
    m4a = store_media(b"m4a", tmp_path, file_id="m4a", kind="audio", max_bytes=100, filename="clip.m4a")
    assert mp3["mime"] == "audio/mpeg"
    assert m4a["mime"] == "audio/mp4"


def test_media_storage_records_hash_and_image_validation(tmp_path):
    record = store_media(b"payload", tmp_path, file_id="f1", kind="document", max_bytes=100, filename="a.bin")
    db = Database(tmp_path / "bot.db")
    row_id = db.record_message(message_id=4, chat_id=1, user_id=2, session_user_id=2, kind="document", text="", attachment=record)
    media = db.one("SELECT * FROM media WHERE message_row_id=?", (row_id,))
    assert media["file_id"] == "f1" and media["hash"] == record["hash"]
    with pytest.raises(ValueError):
        store_media(b"x" * 101, tmp_path, file_id="f2", kind="document", max_bytes=100)
    with pytest.raises(ValueError):
        store_media(b"not an image", tmp_path, file_id="f3", kind="image", max_bytes=100)


def test_job_queue_recovers_running_work(tmp_path):
    db = Database(tmp_path / "bot.db")
    first_id = db.enqueue("unit", {"value": 1})
    db.set_job(first_id, "running")
    queue = JobQueue(db)
    seen = []

    async def handler(payload):
        seen.append(payload["value"])

    queue.register("unit", handler)

    async def exercise():
        await queue.start()
        await asyncio.wait_for(queue.queue.join(), 1)
        queue.worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queue.worker

    asyncio.run(exercise())
    assert seen == [1]
    assert db.one("SELECT status FROM jobs WHERE id=?", (first_id,))["status"] == "done"


def test_bound_config_requires_negative_id(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.delenv("BOUND_COMMUNITY_ID", raising=False)
    monkeypatch.setenv("COMMUNITY_CHAT_ID", "123")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    with pytest.raises(RuntimeError, match="negative numeric ID"):
        Settings.from_env(require_runtime=True)
