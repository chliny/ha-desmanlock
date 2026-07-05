"""Config flow for Desman Lock integration."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
import voluptuous as vol

from .api import DesmanLockApiClient, DesmanLockApiError
from .const import CONF_LOCK_ID, CONF_PHONE, CONF_REGION_ID, DEFAULT_REGION_ID, DOMAIN


class DesmanLockConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Desman Lock."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._user_input: dict[str, Any] = {}
        self._locks: list[dict[str, Any]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle account input."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api = DesmanLockApiClient(
                phone=user_input[CONF_PHONE],
                password=user_input[CONF_PASSWORD],
                region_id=user_input.get(CONF_REGION_ID, DEFAULT_REGION_ID),
            )
            try:
                await api.async_login()
                self._locks = await api.async_lock_list()
            except DesmanLockApiError:
                errors["base"] = "cannot_connect"
            else:
                self._user_input = user_input
                await self.async_set_unique_id(user_input[CONF_PHONE])
                self._abort_if_unique_id_configured()
                if len(self._locks) > 1:
                    return await self.async_step_lock()
                lock_id = str(self._locks[0].get("lockId")) if self._locks else ""
                return self.async_create_entry(
                    title=self._entry_title(lock_id),
                    data={**user_input, CONF_LOCK_ID: lock_id},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PHONE): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_REGION_ID, default=DEFAULT_REGION_ID): str,
                }
            ),
            errors=errors,
        )

    async def async_step_lock(self, user_input: dict[str, Any] | None = None):
        """Select lock when account has multiple locks."""
        errors: dict[str, str] = {}
        locks = {
            str(lock.get("lockId")): lock.get("lockName") or str(lock.get("lockId"))
            for lock in self._locks
            if lock.get("lockId") is not None
        }
        if user_input is not None:
            lock_id = user_input[CONF_LOCK_ID]
            return self.async_create_entry(
                title=self._entry_title(lock_id),
                data={**self._user_input, CONF_LOCK_ID: lock_id},
            )

        return self.async_show_form(
            step_id="lock",
            data_schema=vol.Schema({vol.Required(CONF_LOCK_ID): vol.In(locks)}),
            errors=errors,
        )

    def _entry_title(self, lock_id: str) -> str:
        """Return entry title."""
        for lock in self._locks:
            if str(lock.get("lockId")) == str(lock_id):
                return lock.get("lockName") or "Desman Lock"
        return "Desman Lock"
