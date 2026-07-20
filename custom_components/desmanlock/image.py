"""Image platform for Desman Lock."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import DesmanLockApiError
from .const import DOMAIN
from .coordinator import DesmanLockDataUpdateCoordinator
from .entity import DesmanLockEntity


IMAGES: tuple[ImageEntityDescription, ...] = (
    ImageEntityDescription(
        key="last_open_snapshot",
        translation_key="last_open_snapshot",
    ),
    ImageEntityDescription(
        key="last_alarm_snapshot",
        translation_key="last_alarm_snapshot",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Desman Lock image entities."""
    coordinator: DesmanLockDataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        DesmanLockSnapshotImage(hass, coordinator, description)
        for description in IMAGES
    )


class DesmanLockSnapshotImage(DesmanLockEntity, ImageEntity):
    """A snapshot resolved through Alibaba Link Visual."""

    entity_description: ImageEntityDescription

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DesmanLockDataUpdateCoordinator,
        description: ImageEntityDescription,
    ) -> None:
        """Initialize the image entity."""
        ImageEntity.__init__(self, hass)
        DesmanLockEntity.__init__(self, coordinator)
        self.entity_description = description
        self.entity_id = f"image.{DOMAIN}_{self.lock_id}_{description.key}"
        self._attr_unique_id = f"{DOMAIN}_{self.lock_id}_{description.key}"
        self._image_signature: tuple[str | None, str | None, str | None] | None = None
        self._image_bytes: bytes | None = None
        self._image_lock = asyncio.Lock()
        self._update_image_data()

    @property
    def record_data(self) -> dict[str, Any]:
        """Return the record backing this image."""
        return self.coordinator.data.get(self.entity_description.key) or {}

    @property
    def iot_id(self) -> str | None:
        """Return this lock's Alibaba IoT ID."""
        detail_config = self.detail_config_data
        sources = (
            self.lock_data,
            self.detail_data,
            detail_config,
            detail_config.get("lockDetailInfo") or {},
            detail_config.get("lockDetail") or {},
        )
        for source in sources:
            if value := source.get("iotId") or source.get("iotIdStr"):
                return str(value)
        return None

    @property
    def image_last_updated(self) -> datetime | None:
        """Return when the snapshot record changed."""
        return self._attr_image_last_updated

    @property
    def available(self) -> bool:
        """Return whether the snapshot can be resolved."""
        return (
            super().available
            and bool(self.record_data.get("pic"))
            and self.iot_id is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return snapshot record metadata."""
        record = self.record_data
        return {
            "content": record.get("content"),
            "log_type": record.get("logType"),
            "time": record.get("datetime"),
        }

    async def async_image(self) -> bytes | None:
        """Resolve and return the current snapshot bytes."""
        if self._image_bytes is not None:
            return self._image_bytes
        picture_id = self.record_data.get("pic")
        iot_id = self.iot_id
        if not picture_id or not iot_id:
            return None

        signature = self._image_signature
        async with self._image_lock:
            if self._image_bytes is not None:
                return self._image_bytes
            try:
                image_bytes, content_type = await self.coordinator.api.async_picture(
                    iot_id, str(picture_id)
                )
            except DesmanLockApiError as err:
                raise HomeAssistantError(str(err)) from err
            if signature == self._image_signature:
                self._image_bytes = image_bytes
                self._attr_content_type = content_type
            return image_bytes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Invalidate cached bytes when the backing record changes."""
        self._update_image_data()
        super()._handle_coordinator_update()

    def _update_image_data(self) -> None:
        """Update image metadata from coordinator data."""
        record = self.record_data
        signature = (
            str(record.get("pic")) if record.get("pic") else None,
            str(record.get("datetime")) if record.get("datetime") else None,
            self.iot_id,
        )
        if signature == self._image_signature:
            return
        self._image_signature = signature
        self._image_bytes = None
        self._cached_image = None
        self._attr_image_last_updated = dt_util.utcnow() if signature[0] else None
        self.async_update_token()
