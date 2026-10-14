from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.ai.queue import JobQueue
from app.db import Database
from app.flows.clean import MAX_SOURCE_PAGES, requested_page_limit, transcribe_page


def test_requested_page_limit_parses_first_n():
    assert requested_page_limit("read the first 10 pages and make a new pdf explaining the content") == 10
    assert requested_page_limit("أول 10 صفحات من الكتاب") == 10
    assert requested_page_limit("no page mention here") is None
    assert requested_page_limit("") is None


def test_requested_page_limit_is_capped():
    assert MAX_SOURCE_PAGES == 200
    assert requested_page_limit("first 500 pages") == 200
    assert requested_page_limit("first 200 pages") == 200
    assert requested_page_limit("first 0 pages") == 1


class FakeProvider:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    async def vision(self, model, prompt, image, mime="image/png"):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


async def _instant_sleep(_):
    return None


def test_transcribe_page_retries_failures_and_empty_content():
    provider = FakeProvider([RuntimeError("boom"), ("", {}), ("النص النهائي", {"ok": True})])
    with patch("asyncio.sleep", _instant_sleep):
        text, response = asyncio.run(transcribe_page(provider, "model", 1, b"img", attempts=3))
    assert text == "النص النهائي"
    assert provider.calls == 3


def test_transcribe_page_returns_none_after_exhausting_attempts():
    provider = FakeProvider([RuntimeError("a"), RuntimeError("b"), RuntimeError("c")])
    with patch("asyncio.sleep", _instant_sleep):
        result = asyncio.run(transcribe_page(provider, "model", 2, b"img", attempts=3))
    assert result is None
    assert provider.calls == 3


def test_queue_injects_job_id_and_progress_is_queryable(tmp_path):
    async def scenario():
        db = Database(tmp_path / "jobs.db")
        queue = JobQueue(db)
        seen = {}

        async def handler(payload):
            seen["job_id"] = payload.get("job_id")
            db.set_job_progress(int(payload["job_id"]), "1/1")

        queue.register("demo", handler)
        await queue.start()
        job_id = await queue.submit("demo", {})
        row = None
        for _ in range(200):
            row = db.one("SELECT status,progress FROM jobs WHERE id=?", (job_id,))
            if row and row["status"] == "done":
                break
            await asyncio.sleep(0.05)
        await queue.stop()
        return seen, row

    seen, row = asyncio.run(scenario())
    assert seen["job_id"] is not None
    assert row["status"] == "done"
    assert row["progress"] == "1/1"
