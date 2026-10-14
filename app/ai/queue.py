from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from app.db import Database


class JobQueue:
    """SQLite-backed durable job records; a single worker executes recovered jobs."""
    def __init__(self, db: Database):
        self.db = db
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self.handlers: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {}
        self.worker: asyncio.Task[None] | None = None

    def register(self, kind: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self.handlers[kind] = handler

    async def start(self) -> None:
        if self.worker and not self.worker.done():
            return
        for row in self.db.all("SELECT * FROM jobs WHERE status IN ('pending','running') ORDER BY id"):
            self.db.set_job(int(row["id"]), "pending")
            await self.queue.put(int(row["id"]))
        self.worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
            self.worker = None

    async def submit(self, kind: str, payload: dict[str, Any]) -> int:
        job_id = self.db.enqueue(kind, payload)
        await self.queue.put(job_id)
        return job_id

    async def _run(self) -> None:
        while True:
            job_id = await self.queue.get()
            row = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
            if row is None:
                self.queue.task_done()
                continue
            handler = self.handlers.get(str(row["kind"]))
            try:
                if handler is None:
                    raise RuntimeError(f"No handler for job type {row['kind']}")
                self.db.set_job(job_id, "running")
                import json
                payload = json.loads(row["payload"])
                payload["job_id"] = job_id
                await handler(payload)
                self.db.set_job(job_id, "done")
            except asyncio.CancelledError:
                self.db.set_job(job_id, "pending", "worker stopped; will resume")
                raise
            except Exception as exc:
                self.db.set_job(job_id, "failed", str(exc)[:1000])
            finally:
                self.queue.task_done()
