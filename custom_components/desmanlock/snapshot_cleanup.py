"""Periodic cleanup of expired alarm snapshot images.

The ``自动任务 - 德施曼门锁`` automation saves each alarm snapshot to
``<config>/www/cam/desman_<YYYYmmdd_HHMMSS>.jpg``. This module purges those
files once they are older than a configurable retention window so the folder
does not grow without bound. Only files with that exact naming pattern are
ever removed; every other file in the directory is left untouched.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import re
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Automation names snapshots as desman_<strftime('%Y%m%d_%H%M%S')>.jpg.
_SNAPSHOT_RE = re.compile(r"^desman_(\d{8}_\d{6})\.jpg$")
_NAME_FORMAT = "%Y%m%d_%H%M%S"


def purge_expired_snapshots(
    hass: HomeAssistant, retention_days: int
) -> tuple[int, int]:
    """Delete alarm snapshots older than ``retention_days``.

    Returns ``(deleted, kept)`` counts. Runs synchronously -- call through
    ``hass.async_add_executor_job`` from the event loop.
    """
    cam_dir = Path(hass.config.path("www", "cam"))
    if not cam_dir.is_dir():
        _LOGGER.debug("Snapshot directory does not exist yet: %s", cam_dir)
        return 0, 0

    # Use Home Assistant's configured local time (e.g. Asia/Shanghai) to
    # match the timezone the automation uses when stamping file names.
    # The HA container process itself may run in UTC, so datetime.now() here
    # would introduce an offset of several hours.
    cutoff = dt_util.now().replace(tzinfo=None) - timedelta(days=retention_days)
    deleted = 0
    kept = 0
    for path in cam_dir.iterdir():
        if not path.is_file():
            continue
        match = _SNAPSHOT_RE.match(path.name)
        if not match:
            # Never touch files we did not create (e.g. manual test images).
            continue
        try:
            stamp = datetime.strptime(match.group(1), _NAME_FORMAT)
        except ValueError:
            # Malformed timestamp: leave it alone rather than guess.
            _LOGGER.debug("Skipping snapshot with unparseable name: %s", path.name)
            continue
        if stamp >= cutoff:
            kept += 1
            continue
        try:
            path.unlink()
        except OSError as err:
            _LOGGER.warning("Could not delete expired snapshot %s: %s", path.name, err)
        else:
            deleted += 1
            _LOGGER.info("Deleted expired alarm snapshot: %s", path.name)

    if deleted or kept:
        _LOGGER.debug(
            "Snapshot cleanup: deleted=%d kept=%d (retention=%d days)",
            deleted,
            kept,
            retention_days,
        )
    return deleted, kept


async def async_purge_expired_snapshots(
    hass: HomeAssistant, retention_days: int
) -> tuple[int, int]:
    """Async wrapper: run the blocking directory scan in the executor."""
    return await hass.async_add_executor_job(
        purge_expired_snapshots, hass, retention_days
    )
