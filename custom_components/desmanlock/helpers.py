"""Shared helper functions for the Desman Lock integration."""

from __future__ import annotations

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
