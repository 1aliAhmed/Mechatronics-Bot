from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def initialize(self) -> None:
        with self._lock, self.connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS violations(id INTEGER PRIMARY KEY, chat_id INTEGER, user_id INTEGER, word TEXT, text TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS strikes(user_id INTEGER PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS community_users(user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS idx_community_users_username ON community_users(username COLLATE NOCASE);
            CREATE TABLE IF NOT EXISTS usage(user_id INTEGER, day TEXT, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id, day));
            CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, kind TEXT, payload TEXT, status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, error TEXT, progress TEXT);
            CREATE TABLE IF NOT EXISTS docs(hash TEXT PRIMARY KEY, artifact TEXT NOT NULL, markdown TEXT, source TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS sessions(user_id INTEGER PRIMARY KEY, history TEXT NOT NULL DEFAULT '[]', summary TEXT NOT NULL DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY, direction TEXT NOT NULL, chat_id INTEGER, user_id INTEGER, timestamp TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL, file_refs TEXT, model TEXT, params TEXT, latency_ms INTEGER);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS blocked_words(language TEXT NOT NULL, word TEXT NOT NULL, PRIMARY KEY(language, word));
            CREATE TABLE IF NOT EXISTS admin_cache(user_id INTEGER PRIMARY KEY, is_admin INTEGER NOT NULL, checked_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, message_id INTEGER, chat_id INTEGER NOT NULL, user_id INTEGER, session_user_id INTEGER, kind TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS media(id INTEGER PRIMARY KEY, message_row_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE, file_id TEXT NOT NULL, type TEXT NOT NULL, size INTEGER NOT NULL, hash TEXT NOT NULL, local_path TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX IF NOT EXISTS idx_media_hash ON media(hash);
            CREATE TABLE IF NOT EXISTS document_revisions(id INTEGER PRIMARY KEY, hash TEXT NOT NULL, user_id INTEGER NOT NULL, instruction TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS chats(chat_id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '', chat_type TEXT NOT NULL DEFAULT 'group', muted INTEGER NOT NULL DEFAULT 0, muted_at TEXT, muted_by INTEGER, notice_message_id INTEGER, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS topics(chat_id INTEGER NOT NULL, thread_id INTEGER NOT NULL, title TEXT NOT NULL DEFAULT '', muted INTEGER NOT NULL DEFAULT 0, notice_message_id INTEGER, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(chat_id, thread_id));
            CREATE TABLE IF NOT EXISTS dm_users(user_id INTEGER PRIMARY KEY, introduced INTEGER NOT NULL DEFAULT 0, first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS dm_usage(user_id INTEGER NOT NULL, ts REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_dm_usage_user ON dm_usage(user_id, ts);
            """)
            legacy = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='custom_words'").fetchone()
            if legacy:
                con.execute("INSERT OR IGNORE INTO blocked_words(language,word) SELECT language,word FROM custom_words")
                con.execute("DROP TABLE custom_words")
            job_columns = {row[1] for row in con.execute("PRAGMA table_info(jobs)")}
            if "progress" not in job_columns:
                con.execute("ALTER TABLE jobs ADD COLUMN progress TEXT")
            chat_columns = {row[1] for row in con.execute("PRAGMA table_info(chats)")}
            if "notice_message_id" not in chat_columns:
                con.execute("ALTER TABLE chats ADD COLUMN notice_message_id INTEGER")
            # Version marker for the idempotent migrations above; bump when adding new steps.
            con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_violations_user ON violations(user_id)")
            con.execute("PRAGMA user_version = 1")

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self._lock, self.connect() as con:
            cur = con.execute(sql, params)
            return cur.rowcount

    def insert(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self._lock, self.connect() as con:
            cur = con.execute(sql, params)
            return int(cur.lastrowid)

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock, self.connect() as con:
            return con.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock, self.connect() as con:
            return list(con.execute(sql, params).fetchall())

    def strike(self, user_id: int) -> int:
        self.execute("INSERT INTO strikes(user_id,count) VALUES(?,1) ON CONFLICT(user_id) DO UPDATE SET count=count+1", (user_id,))
        return self.strike_count(user_id)

    def strike_count(self, user_id: int) -> int:
        row = self.one("SELECT count FROM strikes WHERE user_id=?", (user_id,))
        return int(row["count"]) if row else 0

    def strike_window(self, user_id: int, days: int) -> int:
        """Effective strike count: violations recorded within the decay window."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        row = self.one("SELECT COUNT(*) AS n FROM violations WHERE user_id=? AND created_at >= ?", (user_id, cutoff))
        return int(row["n"]) if row else 0

    def mark_introduced(self, user_id: int) -> bool:
        """Flip the first-contact flag; True exactly once per user."""
        row = self.one("SELECT introduced FROM dm_users WHERE user_id=?", (user_id,))
        if row is None:
            self.execute("INSERT INTO dm_users(user_id,introduced) VALUES(?,1)", (user_id,))
            return True
        if not row["introduced"]:
            self.execute("UPDATE dm_users SET introduced=1 WHERE user_id=?", (user_id,))
            return True
        return False

    def usage_stamps(self, user_id: int, cutoff: float) -> list[float]:
        return [float(row["ts"]) for row in self.all("SELECT ts FROM dm_usage WHERE user_id=? AND ts >= ? ORDER BY ts", (user_id, cutoff))]

    def usage_add(self, user_id: int, ts: float, prune_before: float) -> None:
        self.execute("INSERT INTO dm_usage(user_id,ts) VALUES(?,?)", (user_id, ts))
        self.execute("DELETE FROM dm_usage WHERE user_id=? AND ts < ?", (user_id, prune_before))

    def clear_strikes(self, user_id: int) -> bool:
        return self.execute("DELETE FROM strikes WHERE user_id=?", (user_id,)) > 0

    def upsert_chat(self, chat_id: int, title: str, chat_type: str) -> None:
        self.execute("INSERT INTO chats(chat_id,title,chat_type,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title,chat_type=excluded.chat_type,updated_at=CURRENT_TIMESTAMP", (chat_id, title, chat_type))

    def chat_row(self, chat_id: int) -> sqlite3.Row | None:
        return self.one("SELECT * FROM chats WHERE chat_id=?", (chat_id,))

    def remove_chat(self, chat_id: int) -> None:
        self.execute("DELETE FROM chats WHERE chat_id=?", (chat_id,))

    def set_chat_muted(self, chat_id: int, muted: bool, by: int | None) -> None:
        self.execute("UPDATE chats SET muted=?, muted_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END, muted_by=?, updated_at=CURRENT_TIMESTAMP WHERE chat_id=?", (int(muted), int(muted), by, chat_id))

    def set_chat_notice(self, chat_id: int, message_id: int | None) -> None:
        self.execute("UPDATE chats SET notice_message_id=?, updated_at=CURRENT_TIMESTAMP WHERE chat_id=?", (message_id, chat_id))

    def topic_upsert(self, chat_id: int, thread_id: int, title: str | None = None) -> None:
        """Record a forum topic sighting; titles come from create/edit service messages."""
        if title:
            self.execute("INSERT INTO topics(chat_id,thread_id,title,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(chat_id,thread_id) DO UPDATE SET title=excluded.title, updated_at=CURRENT_TIMESTAMP", (chat_id, thread_id, title))
        else:
            self.execute("INSERT OR IGNORE INTO topics(chat_id,thread_id) VALUES(?,?)", (chat_id, thread_id))

    def set_topic_muted(self, chat_id: int, thread_id: int, muted: bool, notice_message_id: int | None = None) -> None:
        self.execute("INSERT OR IGNORE INTO topics(chat_id,thread_id) VALUES(?,?)", (chat_id, thread_id))
        self.execute("UPDATE topics SET muted=?, notice_message_id=?, updated_at=CURRENT_TIMESTAMP WHERE chat_id=? AND thread_id=?", (int(muted), notice_message_id, chat_id, thread_id))

    def topic_row(self, chat_id: int, thread_id: int):
        return self.one("SELECT thread_id,title,muted,notice_message_id FROM topics WHERE chat_id=? AND thread_id=?", (chat_id, thread_id))

    def topics_for(self, chat_id: int, limit: int = 20) -> list:
        return self.all("SELECT thread_id,title,muted,notice_message_id FROM topics WHERE chat_id=? ORDER BY updated_at DESC LIMIT ?", (chat_id, limit))

    def remember_community_user(self, user_id: int, username: str | None, full_name: str) -> None:
        self.execute(
            "INSERT INTO community_users(user_id,username,full_name) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,full_name=excluded.full_name",
            (user_id, username.lstrip("@") if username else None, full_name),
        )

    def community_user_id(self, username: str) -> int | None:
        row = self.one("SELECT user_id FROM community_users WHERE username=? COLLATE NOCASE", (username.lstrip("@"),))
        return int(row["user_id"]) if row else None

    def usage_count(self, user_id: int, day: str | None = None) -> int:
        row = self.one("SELECT count FROM usage WHERE user_id=? AND day=?", (user_id, day or date.today().isoformat()))
        return int(row["count"]) if row else 0

    def add_usage(self, user_id: int, day: str | None = None) -> int:
        day = day or date.today().isoformat()
        self.execute("INSERT INTO usage(user_id,day,count) VALUES(?,?,1) ON CONFLICT(user_id,day) DO UPDATE SET count=count+1", (user_id, day))
        return self.usage_count(user_id, day)

    def session(self, user_id: int) -> tuple[str, list[dict[str, str]]]:
        row = self.one("SELECT summary,history FROM sessions WHERE user_id=?", (user_id,))
        if not row:
            return "", []
        return str(row["summary"]), json.loads(row["history"])

    def save_session(self, user_id: int, summary: str, history: list[dict[str, str]]) -> None:
        self.execute("INSERT INTO sessions(user_id,summary,history,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET summary=excluded.summary,history=excluded.history,updated_at=CURRENT_TIMESTAMP", (user_id, summary, json.dumps(history, ensure_ascii=False)))

    def record_message(self, *, message_id: int | None, chat_id: int, user_id: int | None, session_user_id: int | None, kind: str, text: str, attachment: dict[str, Any] | None = None, attachments: list[dict[str, Any]] | None = None) -> int:
        with self._lock, self.connect() as con:
            cur = con.execute("INSERT INTO messages(message_id,chat_id,user_id,session_user_id,kind,text) VALUES(?,?,?,?,?,?)", (message_id, chat_id, user_id, session_user_id, kind, text))
            row_id = int(cur.lastrowid)
            for item in ([attachment] if attachment else []) + (attachments or []):
                con.execute("INSERT INTO media(message_row_id,file_id,type,size,hash,local_path) VALUES(?,?,?,?,?,?)", (row_id, item["file_id"], item["type"], item["size"], item["hash"], item["local_path"]))
            return row_id

    def enqueue(self, kind: str, payload: dict[str, Any]) -> int:
        with self._lock, self.connect() as con:
            cur = con.execute("INSERT INTO jobs(kind,payload) VALUES(?,?)", (kind, json.dumps(payload, ensure_ascii=False)))
            return int(cur.lastrowid)

    def pending_jobs(self) -> list[sqlite3.Row]:
        return self.all("SELECT * FROM jobs WHERE status='pending' ORDER BY id")

    def set_job(self, job_id: int, status: str, error: str | None = None) -> None:
        self.execute("UPDATE jobs SET status=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, error, job_id))

    def set_job_progress(self, job_id: int, progress: str) -> None:
        self.execute("UPDATE jobs SET progress=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (progress, job_id))
