"""Coordinator for the Desman Lock integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DesmanLockApiClient, DesmanLockApiError
from .bluetooth import DesmanBluetoothLock
from .const import (
    DOMAIN,
    LOG_TYPE_ACTION,
    LOG_TYPE_ALARM,
    LOG_TYPE_OPEN_DOOR,
)

_LOGGER = logging.getLogger(__name__)


class DesmanLockDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Desman Lock data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: DesmanLockApiClient,
        lock_id: str,
        scan_interval: int,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api
        self.lock_id = lock_id
        self.bluetooth = DesmanBluetoothLock(hass, api, {}, {}, {})

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from DSM cloud."""
        try:
            previous_data = self.data or {}
            locks = await self.api.async_lock_list()
            locks = locks or previous_data.get("locks") or []
            selected_lock = _merge_current_with_previous(
                self._select_lock(locks),
                previous_data.get("lock") or {},
            )
            lock_id = self.lock_id
            detail: dict[str, Any] = {}
            detail_config: dict[str, Any] = {}
            open_records: list[dict[str, Any]] = []
            alarm_records: list[dict[str, Any]] = []
            action_records: list[dict[str, Any]] = []
            detail = await self.api.async_lock_detail(lock_id)
            try:
                detail_config = await self.api.async_lock_detail_and_config(lock_id)
            except DesmanLockApiError as err:
                _LOGGER.debug("Failed to fetch lock detailAndConfig: %s", err)
            open_records = await self.api.async_open_door_records(
                lock_id,
                record_type=LOG_TYPE_OPEN_DOOR,
            )
            alarm_records = await self.api.async_open_door_records(
                lock_id,
                record_type=LOG_TYPE_ALARM,
            )
            action_records = await self.api.async_open_door_records(
                lock_id,
                record_type=LOG_TYPE_ACTION,
            )
            detail = _merge_current_with_previous(
                detail,
                previous_data.get("detail") or {},
            )
            detail_config = _merge_current_with_previous(
                detail_config,
                previous_data.get("detail_config") or {},
            )
            last_open = _last_open_record(open_records) or previous_data.get("last_open") or {}
            last_alarm = _last_alarm_record(alarm_records) or previous_data.get("last_alarm") or {}
            last_action = _last_action_record(action_records) or previous_data.get("last_action") or {}
            self.bluetooth.update_data(selected_lock, detail, detail_config)
            return {
                "locks": locks,
                "lock": selected_lock,
                "lock_id": lock_id,
                "detail": detail,
                "detail_config": detail_config,
                "records": open_records or previous_data.get("records") or [],
                "last_open": last_open,
                "last_alarm": last_alarm,
                "last_action": last_action,
            }
        except DesmanLockApiError as err:
            raise UpdateFailed(str(err)) from err

    def _select_lock(self, locks: list[dict[str, Any]]) -> dict[str, Any]:
        """Select the configured lock."""
        for lock in locks:
            if str(lock.get("lockId")) == str(self.lock_id):
                return lock
        return {}


def _merge_current_with_previous(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> dict[str, Any]:
    """Fill missing current fields from the previous successful payload."""
    if not current:
        return dict(previous)
    if not previous:
        return dict(current)

    merged = dict(previous)
    for key, value in current.items():
        previous_value = previous.get(key)
        if isinstance(value, dict) and isinstance(previous_value, dict):
            merged[key] = _merge_current_with_previous(value, previous_value)
        elif value not in (None, ""):
            merged[key] = value
    return merged


def _last_open_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Flatten latest open door record detail."""
    return _last_record(records, LOG_TYPE_OPEN_DOOR)


def _last_alarm_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Flatten latest alarm record detail."""
    return _last_record(records, LOG_TYPE_ALARM)


def _last_action_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Flatten latest action record detail."""
    return _last_record(records, LOG_TYPE_ACTION)


def _last_record(records: list[dict[str, Any]], log_type_int: int) -> dict[str, Any]:
    """Return the first matching detail from the newest-first API response."""
    for day in records:
        day = day or {}
        for detail in day.get("logDetails") or []:
            if str(detail.get("logTypeInt")) != str(log_type_int):
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
            return result
    return {}
