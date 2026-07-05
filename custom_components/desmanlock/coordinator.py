"""Coordinator for the Desman Lock integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DesmanLockApiClient, DesmanLockApiError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class DesmanLockDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Desman Lock data update coordinator."""

    def __init__(self, hass: HomeAssistant, api: DesmanLockApiClient, lock_id: str | None) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.api = api
        self.lock_id = lock_id

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from DSM cloud."""
        try:
            locks = await self.api.async_lock_list()
            selected_lock = self._select_lock(locks)
            lock_id = str(selected_lock.get("lockId") or self.lock_id or "")
            detail: dict[str, Any] = {}
            detail_config: dict[str, Any] = {}
            records: list[dict[str, Any]] = []
            alarm_records: list[dict[str, Any]] = []
            if lock_id:
                detail = await self.api.async_lock_detail(lock_id)
                try:
                    detail_config = await self.api.async_lock_detail_and_config(lock_id)
                except DesmanLockApiError as err:
                    _LOGGER.debug("Failed to fetch lock detailAndConfig: %s", err)
                records = await self.api.async_open_door_records(lock_id)
                alarm_records = await self.api.async_alarm_records(lock_id)
            return {
                "locks": locks,
                "lock": selected_lock,
                "lock_id": lock_id,
                "detail": detail,
                "detail_config": detail_config,
                "records": records,
                "last_open": _last_open_record(records),
                "alarm_records": alarm_records,
                "alarm_snapshots": _picture_records(alarm_records, limit=5),
            }
        except DesmanLockApiError as err:
            raise UpdateFailed(str(err)) from err

    def _select_lock(self, locks: list[dict[str, Any]]) -> dict[str, Any]:
        """Select configured lock or first lock."""
        if not locks:
            return {}
        if not self.lock_id:
            return locks[0]
        for lock in locks:
            if str(lock.get("lockId")) == str(self.lock_id):
                return lock
        return locks[0]


def _last_open_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Flatten latest open door record detail."""
    return _last_record(records)


def _last_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Flatten the latest grouped record detail."""
    if not records:
        return {}
    latest_day = records[0] or {}
    details = latest_day.get("logDetails") or []
    if not details:
        return {"date": latest_day.get("logDate")}
    latest_detail = details[-1]
    result = dict(latest_detail)
    log_date = latest_day.get("logDate")
    log_time = latest_detail.get("logTime")
    if log_date and log_time:
        result["datetime"] = f"{log_date} {log_time}"
    elif log_date:
        result["datetime"] = log_date
    result["dayTag"] = latest_day.get("dayTag")
    result["weekTag"] = latest_day.get("weekTag")
    return result


def _picture_records(
    records: list[dict[str, Any]], *, limit: int
) -> list[dict[str, Any]]:
    """Flatten recent grouped records that contain pictures."""
    pictures: list[dict[str, Any]] = []
    for day in records:
        details = day.get("logDetails") or []
        for detail in reversed(details):
            if not detail.get("pic"):
                continue
            result = dict(detail)
            log_date = day.get("logDate")
            log_time = detail.get("logTime")
            if log_date and log_time:
                result["datetime"] = f"{log_date} {log_time}"
            elif log_date:
                result["datetime"] = log_date
            result["dayTag"] = day.get("dayTag")
            result["weekTag"] = day.get("weekTag")
            pictures.append(result)
            if len(pictures) >= limit:
                return pictures
    return pictures
