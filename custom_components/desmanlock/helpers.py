"""Shared helper functions for the Desman Lock integration."""

from __future__ import annotations

from .const import LOG_TYPE_OPEN_DOOR

AUTO_LOCK_TEXT = "自动上锁"


def extract_open_user(content: str | None) -> str | None:
    """Extract opener name from DSM log content."""
    if not content or content == AUTO_LOCK_TEXT:
        return None
    if content == "密码开锁":
        return content
    if "【" in content and "】" in content:
        return content.split("【", 1)[1].split("】", 1)[0]
    return content


def latest_open_user(records: list[dict] | None) -> str | None:
    """Return the latest opener by scanning open-door records newest-first."""
    for day in records or []:
        day = day or {}
        for detail in day.get("logDetails") or []:
            if str(detail.get("logTypeInt")) != str(LOG_TYPE_OPEN_DOOR):
                continue
            user = extract_open_user(detail.get("content"))
            if user:
                return user
    return None
