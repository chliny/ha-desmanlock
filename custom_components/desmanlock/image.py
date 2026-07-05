"""Image platform for Desman Lock."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import BASE_URL
from .coordinator import DesmanLockDataUpdateCoordinator
from .entity import DesmanLockEntity

ALARM_SNAPSHOT_COUNT = 5
MEDIA_SOURCE_TYPES = {"0", "1", "2", "3"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Desman Lock image entity."""
    coordinator: DesmanLockDataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        [DesmanLockSnapshotImage(hass, coordinator)]
        + [
            DesmanLockAlarmSnapshotImage(hass, coordinator, position)
            for position in range(ALARM_SNAPSHOT_COUNT)
        ]
    )


class DesmanLockSnapshotImage(DesmanLockEntity, ImageEntity):
    """Latest unlock snapshot image."""

    _attr_translation_key = "last_open_snapshot"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DesmanLockDataUpdateCoordinator,
    ) -> None:
        """Initialize the image entity."""
        ImageEntity.__init__(self, hass)
        DesmanLockEntity.__init__(self, coordinator)
        self._attr_unique_id = f"{self.lock_id}_last_open_snapshot"
        self._image_signature: tuple[str | None, str | None] | None = None
        self._image_url: str | None = None
        self._image_last_updated: datetime | None = None
        self._update_image_data()

    @property
    def image_url(self) -> str | None:
        """Return the latest unlock snapshot URL."""
        return self._image_url

    @property
    def image_last_updated(self) -> datetime | None:
        """Return when the snapshot changed."""
        return self._image_last_updated

    @property
    def available(self) -> bool:
        """Return whether a snapshot is available."""
        return super().available and self._image_url is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return metadata for the snapshot."""
        record = self.last_open_data
        return {
            "content": record.get("content"),
            "log_type": record.get("logType"),
            "time": record.get("datetime"),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh the image when the latest unlock record changes."""
        self._update_image_data()
        super()._handle_coordinator_update()

    def _update_image_data(self) -> None:
        """Update image metadata from coordinator data."""
        record = self.last_open_data
        picture = record.get("pic") or None
        event_time = record.get("datetime") or None
        signature = (picture, event_time)
        if signature == self._image_signature:
            return

        self._image_signature = signature
        self._image_url = _snapshot_url(picture)
        self._image_last_updated = dt_util.utcnow() if self._image_url else None
        self._cached_image = None


class DesmanLockAlarmSnapshotImage(DesmanLockSnapshotImage):
    """Latest security alarm snapshot image."""

    _attr_translation_key = "last_alarm_snapshot"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DesmanLockDataUpdateCoordinator,
        position: int,
    ) -> None:
        """Initialize the alarm snapshot entity."""
        self._position = position
        super().__init__(hass, coordinator)
        self._attr_unique_id = (
            f"{self.lock_id}_last_alarm_snapshot"
            if position == 0
            else f"{self.lock_id}_alarm_snapshot_{position + 1}"
        )
        self._attr_translation_placeholders = {"position": str(position + 1)}

    @property
    def last_open_data(self) -> dict[str, Any]:
        """Return latest security alarm record data."""
        snapshots = self.coordinator.data.get("alarm_snapshots", [])
        if self._position >= len(snapshots):
            return {}
        return snapshots[self._position]


def _snapshot_url(picture: str | None) -> str | None:
    """Return a fetchable URL, excluding app-specific media descriptors."""
    if not picture:
        return None

    parsed = urlparse(picture)
    if parsed.scheme in {"http", "https"}:
        return picture

    parts = parsed.path.strip("/").split("/")
    if len(parts) > 1 and parts[0] in MEDIA_SOURCE_TYPES:
        return None

    return urljoin(BASE_URL, picture)
