"""Config flow for Desman Lock integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .api import DesmanLockApiClient, DesmanLockApiError
from .const import (
    CONF_LOCK_ID,
    CONF_PHONE,
    CONF_REGION_ID,
    DEFAULT_REGION_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


class DesmanLockConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Desman Lock."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._user_input: dict[str, Any] = {}
        self._locks: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle account input."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = int(
                user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            )
            api = DesmanLockApiClient(
                phone=user_input[CONF_PHONE],
                password=user_input[CONF_PASSWORD],
                region_id=user_input.get(CONF_REGION_ID, DEFAULT_REGION_ID),
            )
            try:
                await api.async_login()
                self._locks = await api.async_lock_list()
                self._locks = [
                    lock
                    for lock in self._locks
                    if lock.get("lockId") not in (None, "")
                ]
            except DesmanLockApiError:
                errors["base"] = "cannot_connect"
            else:
                self._user_input = user_input
                if not self._locks:
                    errors["base"] = "no_locks"
                    return self.async_show_form(
                        step_id="user",
                        data_schema=_user_schema(user_input),
                        errors=errors,
                    )
                if len(self._locks) > 1:
                    return await self.async_step_lock()
                lock_id = str(self._locks[0]["lockId"])
                await self._async_set_lock_unique_id(lock_id)
                return self.async_create_entry(
                    title=self._entry_title(lock_id),
                    data={**user_input, CONF_LOCK_ID: lock_id},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
        )

    async def async_step_lock(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select lock when account has multiple locks."""
        errors: dict[str, str] = {}
        locks = {
            str(lock.get("lockId")): lock.get("lockName") or str(lock.get("lockId"))
            for lock in self._locks
            if lock.get("lockId") is not None
        }
        if user_input is not None:
            lock_id = user_input[CONF_LOCK_ID]
            await self._async_set_lock_unique_id(lock_id)
            return self.async_create_entry(
                title=self._entry_title(lock_id),
                data={**self._user_input, CONF_LOCK_ID: lock_id},
            )

        return self.async_show_form(
            step_id="lock",
            data_schema=vol.Schema({vol.Required(CONF_LOCK_ID): vol.In(locks)}),
            errors=errors,
        )

    async def _async_set_lock_unique_id(self, lock_id: str) -> None:
        """Set an ID that allows multiple locks from the same account."""
        await self.async_set_unique_id(f"{self._user_input[CONF_PHONE]}_{lock_id}")
        self._abort_if_unique_id_configured()

    def _entry_title(self, lock_id: str) -> str:
        """Return entry title."""
        for lock in self._locks:
            if str(lock.get("lockId")) == str(lock_id):
                return lock.get("lockName") or "Desman Lock"
        return "Desman Lock"

    @staticmethod
    @callback
    def async_get_options_flow(_config_entry: ConfigEntry) -> DesmanLockOptionsFlow:
        """Create the options flow."""
        return DesmanLockOptionsFlow()


class DesmanLockOptionsFlow(OptionsFlowWithReload):
    """Handle Desman Lock options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""
        errors: dict[str, str] = {}
        current_config = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = int(
                user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            )
            if user_input[CONF_PASSWORD] != current_config[CONF_PASSWORD]:
                api = DesmanLockApiClient(
                    phone=current_config[CONF_PHONE],
                    password=user_input[CONF_PASSWORD],
                    region_id=current_config.get(CONF_REGION_ID, DEFAULT_REGION_ID),
                )
                try:
                    await api.async_login()
                except DesmanLockApiError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(title="", data=user_input)
            else:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current_config),
            errors=errors,
        )


def _password_selector() -> selector.TextSelector:
    """Return a password selector."""
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )


def _scan_interval_validator() -> vol.All:
    """Return scan interval validator."""
    return vol.All(vol.Coerce(int), vol.Range(min=1))


def _user_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    """Return user step schema."""
    defaults = user_input or {}
    phone_key = (
        vol.Required(CONF_PHONE, default=defaults[CONF_PHONE])
        if CONF_PHONE in defaults
        else vol.Required(CONF_PHONE)
    )
    return vol.Schema(
        {
            phone_key: str,
            vol.Required(CONF_PASSWORD): _password_selector(),
            vol.Optional(
                CONF_REGION_ID,
                default=defaults.get(CONF_REGION_ID, DEFAULT_REGION_ID),
            ): str,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): _scan_interval_validator(),
        }
    )


def _options_schema(config: dict[str, Any]) -> vol.Schema:
    """Return options schema."""
    return vol.Schema(
        {
            vol.Required(
                CONF_PASSWORD,
                default=config.get(CONF_PASSWORD, ""),
            ): _password_selector(),
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): _scan_interval_validator(),
        }
    )
