"""Base Desman Lock entity."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import DesmanLockDataUpdateCoordinator


class DesmanLockEntity(CoordinatorEntity[DesmanLockDataUpdateCoordinator]):
    """Base Desman Lock entity."""

    _attr_has_entity_name = True

    @property
    def lock_id(self) -> str:
        """Return selected lock id."""
        return str(self.coordinator.data.get("lock_id") or "")

    @property
    def lock_data(self) -> dict[str, Any]:
        """Return selected lock data."""
        return self.coordinator.data.get("lock") or {}

    @property
    def detail_data(self) -> dict[str, Any]:
        """Return selected lock detail data."""
        return self.coordinator.data.get("detail") or {}

    @property
    def detail_config_data(self) -> dict[str, Any]:
        """Return selected lock detail-and-config data."""
        return self.coordinator.data.get("detail_config") or {}

    @property
    def last_open_data(self) -> dict[str, Any]:
        """Return latest open record."""
        return self.coordinator.data.get("last_open") or {}

    @property
    def suggested_object_id(self) -> str | None:
        """Return a stable, readable entity object id suggestion."""
        suffix = getattr(self, "_desman_object_id_suffix", None)
        if suffix is None:
            return None
        lock_name = self.lock_data.get("lockName")
        lock_part = slugify(str(lock_name)) if lock_name else slugify(self.lock_id)
        return "_".join((DOMAIN, lock_part, slugify(suffix)))

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        lock = self.lock_data
        detail = self.detail_data
        name = detail.get("lockName") or lock.get("lockName") or "Desman Lock"
        return DeviceInfo(
            identifiers={(DOMAIN, self.lock_id)},
            name=name,
            manufacturer="Desman",
            model=detail.get("meterType") or lock.get("meterType") or lock.get("lockType"),
            sw_version=detail.get("softwareVersion") or lock.get("softwareVersion"),
            serial_number=detail.get("sn") or lock.get("sn"),
        )
