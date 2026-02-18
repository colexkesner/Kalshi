from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_ms() -> str:
    return str(int(now_utc().timestamp() * 1000))
