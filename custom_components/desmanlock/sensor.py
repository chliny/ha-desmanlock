"""Sensor platform for Desman Lock."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DesmanLockDataUpdateCoordinator
from .entity import DesmanLockEntity
from .helpers import extract_open_user, latest_open_user


@dataclass(frozen=True, kw_only=True)
class DesmanSensorEntityDescription(SensorEntityDescription):
    """Desman Lock sensor description."""

    value_fn: Callable[[DesmanLockDataUpdateCoordinator], Any]
    attributes_fn: Callable[[DesmanLockDataUpdateCoordinator], dict[str, Any]] | None = None


SENSORS: tuple[DesmanSensorEntityDescription, ...] = (
    DesmanSensorEntityDescription(
        key="battery_percentage",
        translation_key="battery_percentage",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        value_fn=lambda coordinator: _first_value(
            _detail_and_config(coordinator),
            coordinator.data.get("detail", {}),
            coordinator.data.get("lock", {}),
            "batteryPercentage",
            "batteryLevel",
        ),
    ),
    DesmanSensorEntityDescription(
        key="cateye_battery_percentage",
        translation_key="cateye_battery_percentage",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        value_fn=lambda coordinator: _first_value(
            _detail_and_config(coordinator),
            coordinator.data.get("detail", {}),
            "catBatteryPercentage",
        ),
    ),
    DesmanSensorEntityDescription(
        key="battery_status",
        translation_key="battery_status",
        value_fn=lambda coordinator: _first_value(
            _detail_and_config(coordinator), coordinator.data.get("detail", {}), "batteryStatus"
        ),
    ),
    DesmanSensorEntityDescription(
        key="last_open_user",
        translation_key="last_open_user",
        value_fn=lambda coordinator: _last_open_user_state(coordinator),
        attributes_fn=lambda coordinator: _last_open_record_attributes(coordinator),
    ),
    DesmanSensorEntityDescription(
        key="last_open_mode",
        translation_key="last_open_mode",
        value_fn=lambda coordinator: (coordinator.data.get("last_open", {}) or {}).get("logType"),
        attributes_fn=lambda coordinator: _last_open_record_attributes(coordinator),
    ),
    DesmanSensorEntityDescription(
        key="last_open_time",
        translation_key="last_open_time",
        value_fn=lambda coordinator: (coordinator.data.get("last_open", {}) or {}).get("datetime"),
    ),
    DesmanSensorEntityDescription(
        key="open_door_log",
        translation_key="open_door_log",
        icon="mdi:bell",
        value_fn=lambda coordinator: _open_door_log_state(coordinator),
        attributes_fn=lambda coordinator: _open_door_log_attributes(coordinator),
    ),
    DesmanSensorEntityDescription(
        key="alarm_log",
        translation_key="alarm_log",
        icon="mdi:alert",
        value_fn=lambda coordinator: _alarm_log_state(coordinator),
        attributes_fn=lambda coordinator: _alarm_log_attributes(coordinator),
    ),
    DesmanSensorEntityDescription(
        key="action_log",
        translation_key="action_log",
        icon="mdi:history",
        value_fn=lambda coordinator: _action_log_state(coordinator),
        attributes_fn=lambda coordinator: _action_log_attributes(coordinator),
    ),
    DesmanSensorEntityDescription(
        key="network_signal",
        translation_key="network_signal",
        value_fn=lambda coordinator: _first_value(
            _detail_and_config(coordinator), coordinator.data.get("detail", {}), "networkSignal"
        ),
    ),
    DesmanSensorEntityDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: _detail_and_config(coordinator).get("lockWifiSsid"),
    ),
    DesmanSensorEntityDescription(
        key="wifi_state",
        translation_key="wifi_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: _detail_and_config(coordinator).get("lockWifiState"),
    ),
    DesmanSensorEntityDescription(
        key="network_mode",
        translation_key="network_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: _detail_and_config(coordinator).get("networkMode"),
    ),
    DesmanSensorEntityDescription(
        key="software_version",
        translation_key="software_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: _detail_and_config(coordinator).get("softwareVersion"),
    ),
    DesmanSensorEntityDescription(
        key="fingerprint_used_count",
        translation_key="fingerprint_used_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: _detail_and_config(coordinator).get("fingerUsedNum"),
    ),
    DesmanSensorEntityDescription(
        key="fingerprint_available_count",
        translation_key="fingerprint_available_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: _detail_and_config(coordinator).get("fingerUnusedNum"),
    ),
    DesmanSensorEntityDescription(
        key="face_used_count",
        translation_key="face_used_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: _detail_and_config(coordinator).get("faceUsedNum"),
    ),
    DesmanSensorEntityDescription(
        key="face_available_count",
        translation_key="face_available_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: _detail_and_config(coordinator).get("faceUnusedNum"),
    ),
    DesmanSensorEntityDescription(
        key="doorbell_volume",
        translation_key="doorbell_volume",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: _detail_and_config(coordinator).get("doorBellVolume"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Desman Lock sensors."""
    coordinator: DesmanLockDataUpdateCoordinator = entry.runtime_data
    async_add_entities(DesmanLockSensor(coordinator, description) for description in SENSORS)


class DesmanLockSensor(DesmanLockEntity, SensorEntity):
    """Desman Lock sensor."""

    entity_description: DesmanSensorEntityDescription

    def __init__(
        self,
        coordinator: DesmanLockDataUpdateCoordinator,
        description: DesmanSensorEntityDescription,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self.lock_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return native value."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return sensor-specific state attributes."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator)


def _first_value(*sources_and_keys: Any) -> Any:
    """Return the first non-empty value for keys across dictionaries."""
    sources = [item for item in sources_and_keys if isinstance(item, dict)]
    keys = [item for item in sources_and_keys if isinstance(item, str)]
    for key in keys:
        for source in sources:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return None


def _detail_and_config(coordinator: DesmanLockDataUpdateCoordinator) -> dict[str, Any]:
    """Return the lock detail object from the detail-and-config response."""
    data = coordinator.data.get("detail_config") or {}
    return data.get("lockDetailInfo") or data.get("lockDetail") or data


def _open_door_log_state(coordinator: DesmanLockDataUpdateCoordinator) -> str | None:
    """Return a concise state for the latest open-door log."""
    return _log_record_state(coordinator, "last_open")


def _open_door_log_attributes(coordinator: DesmanLockDataUpdateCoordinator) -> dict[str, Any]:
    """Return useful fields from the latest open-door log."""
    return _log_record_attributes(coordinator, "last_open", include_user=True)


def _last_open_user_state(coordinator: DesmanLockDataUpdateCoordinator) -> str | None:
    """Return the latest opener by scanning open-door records newest-first."""
    return latest_open_user(coordinator.data.get("records"))


def _last_open_record_attributes(
    coordinator: DesmanLockDataUpdateCoordinator,
) -> dict[str, Any]:
    """Return log time from the latest open-door record."""
    record = coordinator.data.get("last_open") or {}
    return {"logtime": record.get("datetime")}


def _alarm_log_state(coordinator: DesmanLockDataUpdateCoordinator) -> str | None:
    """Return a concise state for the latest alarm log."""
    return _log_record_state(coordinator, "last_alarm")


def _alarm_log_attributes(
    coordinator: DesmanLockDataUpdateCoordinator,
) -> dict[str, Any]:
    """Return useful fields from the latest alarm log."""
    return _log_record_attributes(coordinator, "last_alarm")


def _action_log_state(coordinator: DesmanLockDataUpdateCoordinator) -> str | None:
    """Return a concise state for the latest action log."""
    return _log_record_state(coordinator, "last_action")


def _action_log_attributes(
    coordinator: DesmanLockDataUpdateCoordinator,
) -> dict[str, Any]:
    """Return useful fields from the latest action log."""
    return _log_record_attributes(coordinator, "last_action")


def _log_record_state(
    coordinator: DesmanLockDataUpdateCoordinator,
    key: str,
) -> str | None:
    """Return a concise state for a latest log record."""
    record = coordinator.data.get(key) or {}
    return record.get("content") or record.get("logType")


def _log_record_attributes(
    coordinator: DesmanLockDataUpdateCoordinator,
    key: str,
    *,
    include_user: bool = False,
) -> dict[str, Any]:
    """Return common useful fields from a latest log record."""
    record = coordinator.data.get(key) or {}
    attributes = {
        "content": record.get("content"),
        "log_type": record.get("logType"),
        "log_type_int": record.get("logTypeInt"),
        "log_event_type": record.get("logEventType"),
        "time": record.get("datetime"),
        "picture": record.get("pic"),
        "video": record.get("video"),
    }
    if include_user:
        attributes["user"] = extract_open_user(record.get("content"))
    return attributes
