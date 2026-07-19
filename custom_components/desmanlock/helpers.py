"""Shared helper functions for the Desman Lock integration."""

from __future__ import annotations

from typing import Any

from .const import LOG_TYPE_OPEN_DOOR

AUTO_LOCK_TEXT = "自动上锁"
DOORBELL_RING_TEXT = "按响了门铃"


def extract_open_user(content: str | None) -> str | None:
    """Extract opener name from DSM log content."""
    if not content or content == AUTO_LOCK_TEXT or DOORBELL_RING_TEXT in content:
        return None
    if content == "密码开锁":
        return content
    if "【" in content and "】" in content:
        return content.split("【", 1)[1].split("】", 1)[0]
    return content


def latest_open_user(records: list[dict] | None) -> str | None:
    """Return the latest opener by scanning open-door records newest-first."""
    return latest_open_user_record(records).get("user")


def latest_open_user_record(records: list[dict] | None) -> dict[str, Any]:
    """Return the latest opener and the matching open-door record."""
    for day in records or []:
        day = day or {}
        for detail in day.get("logDetails") or []:
            if str(detail.get("logTypeInt")) != str(LOG_TYPE_OPEN_DOOR):
                continue
            user = extract_open_user(detail.get("content"))
            if user:
                return _record_with_datetime(day, detail, user)
    return {}


def _record_with_datetime(
    day: dict[str, Any],
    detail: dict[str, Any],
    user: str,
) -> dict[str, Any]:
    """Return a flattened open-door detail enriched with user and datetime."""
    result = dict(detail)
    log_date = day.get("logDate")
    log_time = detail.get("logTime")
    if log_date and log_time:
        result["datetime"] = f"{log_date} {log_time}"
    elif log_date:
        result["datetime"] = log_date
    result["dayTag"] = day.get("dayTag")
    result["weekTag"] = day.get("weekTag")
    result["user"] = user
    return result
