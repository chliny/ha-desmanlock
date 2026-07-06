"""Lock platform for Desman Lock."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_LOCK_ID,
    ATTR_LOCK_MAC,
    ATTR_LOCK_TYPE,
    ATTR_OPEN_CONTENT,
    ATTR_OPEN_LOG_TYPE,
    ATTR_OPEN_MEDIA_PIC,
    ATTR_OPEN_MEDIA_VIDEO,
    ATTR_OPEN_TIME,
    ATTR_OPEN_USER,
)
from .coordinator import DesmanLockDataUpdateCoordinator
from .entity import DesmanLockEntity

AUTO_LOCK_TEXT = "自动上锁"

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Desman Lock lock entity."""
    coordinator: DesmanLockDataUpdateCoordinator = entry.runtime_data
    async_add_entities([DesmanCloudLock(coordinator)])


class DesmanCloudLock(DesmanLockEntity, LockEntity):
    """Desman cloud lock entity."""

    _attr_name = None

    def __init__(self, coordinator: DesmanLockDataUpdateCoordinator) -> None:
        """Initialize lock entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self.lock_id}_lock"

    @property
    def is_locked(self) -> bool | None:
        """Return true if the lock is locked."""
        last_open = self.last_open_data
        log_type = last_open.get("logType")
        content = last_open.get("content")
        if log_type == AUTO_LOCK_TEXT or content == AUTO_LOCK_TEXT:
            return True
        if log_type or content:
            return False
        return None

    @property
    def changed_by(self) -> str | None:
        """Return latest opener."""
        return _extract_user(self.last_open_data.get("content"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        lock = self.lock_data
        detail = self.detail_data
        last_open = self.last_open_data
        return {
            ATTR_LOCK_ID: self.lock_id,
            ATTR_LOCK_MAC: detail.get("lockMac") or lock.get("lockMac"),
            ATTR_LOCK_TYPE: lock.get("lockType"),
            ATTR_OPEN_USER: _extract_user(last_open.get("content")),
            ATTR_OPEN_CONTENT: last_open.get("content"),
            ATTR_OPEN_LOG_TYPE: last_open.get("logType"),
            ATTR_OPEN_TIME: last_open.get("datetime"),
            ATTR_OPEN_MEDIA_PIC: last_open.get("pic"),
            ATTR_OPEN_MEDIA_VIDEO: last_open.get("video"),
            "battery_update_time": detail.get("batteryUpdateTime") or lock.get("batteryUpdateTime"),
            "battery_status": detail.get("batteryStatus"),
            "cateye_battery": detail.get("cateyeBattery"),
            "wifi_state": detail.get("lockWifiState") or lock.get("lockWifiState"),
            "network_signal": detail.get("networkSignal"),
            "iot_id": detail.get("iotId") or lock.get("iotId"),
        }

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock through the local Bluetooth transport."""
        _LOGGER.debug("Home Assistant requested unlock for Desman lock %s", self.lock_id)
        self._attr_is_unlocking = True
        self.async_write_ha_state()
        try:
            await self.coordinator.bluetooth.async_unlock()
            _LOGGER.debug("Bluetooth unlock completed for Desman lock %s", self.lock_id)
        except Exception:
            _LOGGER.exception("Bluetooth unlock failed for Desman lock %s", self.lock_id)
            raise
        finally:
            self._attr_is_unlocking = False
            await self.coordinator.async_request_refresh()

    async def async_lock(self, **kwargs: Any) -> None:
        """Refresh state after the lock's automatic relock cycle."""
        _LOGGER.debug("Home Assistant requested lock-state confirmation for %s", self.lock_id)
        self._attr_is_locking = True
        self.async_write_ha_state()
        try:
            await self.coordinator.async_request_refresh()
            if self.is_locked is False:
                raise HomeAssistantError(
                    "This Desman model exposes no active lock command; "
                    "close the door and wait for automatic locking"
                )
        finally:
            self._attr_is_locking = False
            self.async_write_ha_state()


def _extract_user(content: str | None) -> str | None:
    """Extract opener name from DSM log content."""
    if not content or content == AUTO_LOCK_TEXT:
        return None
    if content == "密码开锁":
        return content
    if "【" in content and "】" in content:
        return content.split("【", 1)[1].split("】", 1)[0]
    return content
