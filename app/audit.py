from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db import Database

log = logging.getLogger(__name__)


class AuditLogger:
    def __init__(self, db: Database, logs_dir: Path):
        self.db = db
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def record(self, direction: str, *, chat_id: int | None, user_id: int | None, kind: str, content: str, file_refs: list[str] | None = None, model: str | None = None, params: dict[str, Any] | None = None, latency_ms: int | None = None, timestamp: datetime | None = None) -> dict[str, Any]:
        stamp = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        event = {"direction": direction, "chat_id": chat_id, "user_id": user_id, "timestamp": stamp, "kind": kind, "content": content, "file_refs": file_refs or [], "model": model, "params": params or {}, "latency_ms": latency_ms}
        try:
            self.db.execute("INSERT INTO audit_log(direction,chat_id,user_id,timestamp,kind,content,file_refs,model,params,latency_ms) VALUES(?,?,?,?,?,?,?,?,?,?)", (direction, chat_id, user_id, stamp, kind, content, json.dumps(event["file_refs"], ensure_ascii=False), model, json.dumps(event["params"], ensure_ascii=False), latency_ms))
            with (self.logs_dir / f"{stamp[:10]}.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            # Auditing must never break the handler it observes.
            log.exception("Audit write failed (kind=%s)", kind)
        return event

    def prune(self, retention_days: int) -> int:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        removed = self.db.execute("DELETE FROM audit_log WHERE timestamp < ?", (cutoff,))
        for path in self.logs_dir.glob("*.jsonl"):
            try:
                if datetime.strptime(path.stem, "%Y-%m-%d").date() < (datetime.now(timezone.utc).date() - timedelta(days=retention_days)):
                    path.unlink()
            except ValueError:
                continue
        return removed
