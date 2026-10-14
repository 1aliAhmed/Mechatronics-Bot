from __future__ import annotations

import json
import os

from app.audit import AuditLogger
from app.config import Settings, load_env_file
from app.db import Database
from app.flows.clean import sha256_file


def test_config_parsing(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("COMMUNITY_CHAT_ID", "-100123")
    monkeypatch.setenv("BOUND_COMMUNITY_ID", "-100123")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    monkeypatch.setenv("ADMIN_IDS", "12, 34")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    settings = Settings.from_env(require_runtime=True)
    assert settings.community_chat_id == -100123
    assert settings.admin_ids == frozenset({12, 34})
    assert settings.dry_run is False
    assert settings.data_dir == tmp_path / "data"


def test_env_file_loading(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_TEST_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("BOT_TEST_KEY", "from-env")
    load_env_file(env_file)
    assert os.environ["BOT_TEST_KEY"] == "from-env"
    monkeypatch.delenv("BOT_TEST_KEY")
    load_env_file(env_file)
    assert os.environ["BOT_TEST_KEY"] == "from-file"


def test_hash_dedupe_primitive(tmp_path):
    first, second = tmp_path / "one.bin", tmp_path / "two.bin"
    first.write_bytes(b"same source")
    second.write_bytes(b"same source")
    assert sha256_file(first) == sha256_file(second)
    second.write_bytes(b"different")
    assert sha256_file(first) != sha256_file(second)


def test_audit_writes_sqlite_and_daily_jsonl(tmp_path):
    db = Database(tmp_path / "bot.db")
    audit = AuditLogger(db, tmp_path / "logs")
    event = audit.record("incoming", chat_id=1, user_id=2, kind="test", content="مرحباً", file_refs=["doc.pdf"], model="model:free", params={"temperature": 0.2}, latency_ms=12)
    row = db.one("SELECT * FROM audit_log WHERE user_id=2")
    assert row is not None and row["content"] == "مرحباً"
    lines = list((tmp_path / "logs").glob("*.jsonl"))
    assert len(lines) == 1
    stored = json.loads(lines[0].read_text(encoding="utf-8"))
    assert stored == event
    assert stored["file_refs"] == ["doc.pdf"]
