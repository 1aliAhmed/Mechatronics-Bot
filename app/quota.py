from __future__ import annotations

import time

from app.config import Settings
from app.db import Database

ONE_HOUR = 3600
FIVE_HOURS = 5 * 3600
ONE_DAY = 24 * 3600

# (settings field, window seconds, Arabic label); a limit of 0 disables that window.
WINDOWS = (
    ("dm_quota_1h", ONE_HOUR, "ساعة"),
    ("dm_quota_5h", FIVE_HOURS, "5 ساعات"),
    ("dm_quota_24h", ONE_DAY, "24 ساعة"),
)


def quota_summary(settings: Settings) -> str:
    """Human-readable description of the active limits, e.g. «10 رسائل كل ساعة»."""
    parts = [f"{limit} رسائل كل {label}" for field, _, label in WINDOWS if (limit := int(getattr(settings, field))) > 0]
    return " و".join(parts) or "بلا حدود"


class QuotaService:
    """Fair-use quota for public DM users: N messages per rolling window (0 disables a window).

    Admins are expected to be filtered by the caller; this service only counts.
    """

    def __init__(self, db: Database, settings: Settings, clock=None):
        self.db = db
        self.settings = settings
        self._clock = clock or time.time

    def _stamps(self, user_id: int, now: float) -> list[float]:
        return self.db.usage_stamps(user_id, now - ONE_DAY)

    def _verdict(self, stamps: list[float], now: float) -> int:
        """0 when allowed, otherwise seconds until the user can send again."""
        retries = []
        for field, window, _ in WINDOWS:
            limit = int(getattr(self.settings, field))
            if limit <= 0:
                continue
            recent = [stamp for stamp in stamps if stamp > now - window]
            if len(recent) >= limit:
                retries.append(int(recent[0] + window - now))
        return max(1, min(retries)) if retries else 0

    def state(self, user_id: int) -> tuple[int, int, int]:
        """(used in 1h, used in 24h, retry seconds) without recording anything."""
        now = self._clock()
        stamps = self._stamps(user_id, now)
        hour = [stamp for stamp in stamps if stamp > now - ONE_HOUR]
        return len(hour), len(stamps), self._verdict(stamps, now)

    def consume(self, user_id: int) -> int:
        """Record one message; 0 when accepted, else seconds until retry."""
        now = self._clock()
        stamps = self._stamps(user_id, now)
        retry = self._verdict(stamps, now)
        if retry:
            return retry
        self.db.usage_add(user_id, now, now - ONE_DAY)
        return 0


def quota_message(settings: Settings, retry_seconds: int) -> str:
    minutes = max(1, (retry_seconds + 59) // 60)
    return (
        f"وصلت إلى الحد التجريبي المؤقت ({quota_summary(settings)}). "
        f"هذا الحد مؤقت وسيُرفع قريباً. يمكنك المحاولة مجدداً بعد ~{minutes} دقيقة."
    )
