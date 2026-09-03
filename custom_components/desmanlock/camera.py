"""Camera platform for Desman Lock."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlsplit

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.camera.const import DATA_CAMERA_PREFS
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DesmanLockDataUpdateCoordinator
from .entity import DesmanLockEntity

# A valid 16 x 9 white JPEG. Camera previews must never start the live stream;
# use this until the integration's internal LinkVisual decoder has produced a frame.
_WHITE_PREVIEW_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCAAJABADASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/ALLAB//Z"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Desman Lock camera entities."""
    coordinator: DesmanLockDataUpdateCoordinator = entry.runtime_data
    async_add_entities([DesmanLiveCamera(coordinator)])


class DesmanLiveCamera(DesmanLockEntity, Camera):
    """Experimental live-video camera for Desman peephole locks."""

    _attr_name = None
    _attr_translation_key = "live_video"
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, coordinator: DesmanLockDataUpdateCoordinator) -> None:
        """Initialize the live-video camera."""
        Camera.__init__(self)
        DesmanLockEntity.__init__(self, coordinator)
        self.entity_id = f"camera.{DOMAIN}_{self.lock_id}_live_video"
        self._attr_unique_id = f"{DOMAIN}_{self.lock_id}_live_video"
        self._last_stream_info: dict[str, Any] = {}
        self._last_stream_error: str | None = None
        self._preview_image = _WHITE_PREVIEW_JPEG

    async def async_added_to_hass(self) -> None:
        """Add the entity and disable HA's automatic stream preloading."""
        await super().async_added_to_hass()
        camera_prefs = self.hass.data.get(DATA_CAMERA_PREFS)
        if camera_prefs is not None:
            await camera_prefs.async_update(
                self.entity_id,
                preload_stream=False,
            )

    @property
    def iot_id(self) -> str | None:
        """Return this lock's Alibaba IoT ID."""
        for source in self._device_sources:
            if value := source.get("iotId") or source.get("iotIdStr"):
                return str(value)
        return None

    @property
    def xm_sn(self) -> str | None:
        """Return this lock's Xiongmai serial number."""
        for source in self._device_sources:
            if value := source.get("sn") or source.get("serialNum"):
                return str(value)
        return None

    @property
    def video_platform(self) -> str:
        """Return the detected video platform."""
        if self.iot_id:
            return "ali_linkvisual"
        if self.xm_sn:
            return "xiongmai"
        return "unknown"

    @property
    def available(self) -> bool:
        """Return whether this camera can attempt a stream."""
        return super().available and self.video_platform == "ali_linkvisual"

    @property
    def is_streaming(self) -> bool:
        """Do not claim that a configured-but-idle camera is streaming."""
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return video platform metadata."""
        relay_url = self._last_stream_info.get("relayUrl")
        signal_url = self._last_stream_info.get("signalUrl")
        requires_decryption = bool(self._last_stream_info.get("relayDecryptKey"))
        stream_host = (
            urlsplit(relay_url).netloc if isinstance(relay_url, str) else None
        )
        signal_host = (
            urlsplit(signal_url).netloc if isinstance(signal_url, str) else None
        )
        stream_kind = (
            "linkvisual_native"
            if self.video_platform == "ali_linkvisual"
            else None
        )

        return {
            "video_platform": self.video_platform,
            "iot_id_present": self.iot_id is not None,
            "xm_sn_present": self.xm_sn is not None,
            "stream_kind": stream_kind,
            "stream_host": stream_host,
            "signal_host": signal_host,
            "type_list": self._last_stream_info.get("typeList"),
            "requires_linkvisual_decryption": requires_decryption,
            "relay_url_available": bool(relay_url),
            "direct_ha_stream_verified": bool(
                self._last_stream_info.get("directPlayable")
            ),
            "push_started": self._last_stream_info.get("pushStarted"),
            "push_error": self._last_stream_info.get("pushError"),
            "last_stream_error": self._last_stream_error,
        }

    @property
    def use_stream_for_stills(self) -> bool:
        """Never start the power-hungry live stream to generate a preview."""
        return False

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes:
        """Return the last frame produced by the internal video pipeline."""
        del width, height
        return self._preview_image

    async def stream_source(self) -> str | None:
        """Return a source only when HA explicitly requests live playback."""
        iot_id = self.iot_id
        if not iot_id:
            self._last_stream_error = "This lock has no Alibaba IoT ID"
            return None

        try:
            stream_info = await self.coordinator.api.async_ali_live_stream(
                iot_id,
                wake_up=True,
            )
        except Exception as err:  # Home Assistant logs the camera context.
            self._last_stream_info = {}
            self._last_stream_error = str(err)
            return None

        self._last_stream_info = stream_info
        self._last_stream_error = None
        relay_url = stream_info.get("relayUrl")
        if not stream_info.get("directPlayable"):
            self._last_stream_error = (
                "Alibaba LinkVisual relay URL requires native SDK signalling; "
                "direct Home Assistant streaming is not verified"
            )
            return None
        return str(relay_url) if relay_url else None

    @property
    def _device_sources(self) -> tuple[dict[str, Any], ...]:
        """Return all known device payload locations."""
        detail_config = self.detail_config_data
        return (
            self.lock_data,
            self.detail_data,
            detail_config,
            detail_config.get("lockDetailInfo") or {},
            detail_config.get("lockDetail") or {},
            detail_config.get("lockBaseInfo") or {},
        )
