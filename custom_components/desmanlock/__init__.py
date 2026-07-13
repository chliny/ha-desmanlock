"""Desman Lock integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import DesmanLockApiClient
from .const import (
    CONF_LOCK_ID,
    CONF_PHONE,
    CONF_REGION_ID,
    DEFAULT_REGION_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
    SERVICE_ADD_DIGIT_PASSWORD,
    SERVICE_GET_DIGIT_PASSWORDS,
    SERVICE_GET_DYNAMIC_PASSWORD,
    SERVICE_UPDATE_DIGIT_PASSWORD,
)
from .coordinator import DesmanLockDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

type DesmanLockConfigEntry = ConfigEntry[DesmanLockDataUpdateCoordinator]

SERVICE_LOCK_ID = vol.Optional(CONF_LOCK_ID)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up global Desman Lock services."""
    _async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DesmanLockConfigEntry) -> bool:
    """Set up Desman Lock from a config entry."""
    config = {**entry.data, **entry.options}
    configured_lock_id = config[CONF_LOCK_ID]
    if not configured_lock_id:
        raise ConfigEntryError("Desman Lock config entry has no lock ID")
    lock_id = str(configured_lock_id)
    api = DesmanLockApiClient(
        phone=config[CONF_PHONE],
        password=config[CONF_PASSWORD],
        region_id=config.get(CONF_REGION_ID, DEFAULT_REGION_ID),
    )
    coordinator = DesmanLockDataUpdateCoordinator(
        hass,
        api,
        lock_id,
        int(config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DesmanLockConfigEntry) -> bool:
    """Unload a Desman Lock config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.bluetooth.async_close()
    return unloaded


def _async_setup_services(hass: HomeAssistant) -> None:
    """Register Desman Lock services."""
    if hass.services.has_service(DOMAIN, SERVICE_GET_DYNAMIC_PASSWORD):
        return

    async def get_dynamic_password(call: ServiceCall) -> dict[str, Any]:
        coordinator = _coordinator_from_call(hass, call)
        lock_id = _lock_id_from_call(coordinator, call)
        return {"data": await coordinator.api.async_dynamic_password(lock_id)}

    async def get_digit_passwords(call: ServiceCall) -> dict[str, Any]:
        coordinator = _coordinator_from_call(hass, call)
        lock_id = _lock_id_from_call(coordinator, call)
        return {"data": await coordinator.api.async_digit_passwords(lock_id)}

    async def add_digit_password(call: ServiceCall) -> dict[str, Any]:
        coordinator = _coordinator_from_call(hass, call)
        lock_id = _lock_id_from_call(coordinator, call)
        result = await hass.async_add_executor_job(
            coordinator.api.add_digit_password,
            lock_id,
            call.data["real_time_switch"],
            call.data["range_time"],
            call.data.get("remarks", ""),
            call.data.get("alarm_switch", 0),
        )
        return {"data": result}

    async def update_digit_password(call: ServiceCall) -> dict[str, Any]:
        coordinator = _coordinator_from_call(hass, call)
        result = await hass.async_add_executor_job(
            coordinator.api.update_digit_password,
            call.data["id"],
            call.data.get("remarks", ""),
            call.data["real_time_switch"],
            call.data["range_time"],
            call.data["state"],
        )
        return {"data": result}

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DYNAMIC_PASSWORD,
        get_dynamic_password,
        schema=vol.Schema({SERVICE_LOCK_ID: cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DIGIT_PASSWORDS,
        get_digit_passwords,
        schema=vol.Schema({SERVICE_LOCK_ID: cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_DIGIT_PASSWORD,
        add_digit_password,
        schema=vol.Schema(
            {
                SERVICE_LOCK_ID: cv.string,
                vol.Required("real_time_switch"): vol.In((0, 1)),
                vol.Required("range_time"): cv.string,
                vol.Optional("remarks", default=""): cv.string,
                vol.Optional("alarm_switch", default=0): vol.In((0, 1)),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_DIGIT_PASSWORD,
        update_digit_password,
        schema=vol.Schema(
            {
                vol.Required("id"): cv.string,
                vol.Optional("remarks", default=""): cv.string,
                vol.Required("real_time_switch"): vol.In((0, 1)),
                vol.Required("range_time"): cv.string,
                vol.Required("state"): cv.positive_int,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )


def _coordinator_from_call(hass: HomeAssistant, call: ServiceCall) -> DesmanLockDataUpdateCoordinator:
    """Return the first coordinator, or one matching requested lock id."""
    entries = hass.config_entries.async_entries(DOMAIN)
    requested_lock_id = call.data.get(CONF_LOCK_ID)
    for entry in entries:
        if entry.state is not ConfigEntryState.LOADED:
            continue
        coordinator = entry.runtime_data
        if not requested_lock_id or str(coordinator.lock_id) == str(requested_lock_id):
            return coordinator
    raise HomeAssistantError("No loaded Desman Lock config entry found")


def _lock_id_from_call(coordinator: DesmanLockDataUpdateCoordinator, call: ServiceCall) -> str:
    """Return lock id from service call or coordinator."""
    return str(call.data.get(CONF_LOCK_ID) or coordinator.lock_id or coordinator.data.get("lock_id"))
