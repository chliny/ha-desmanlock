"""Desman Lock cloud API client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import logging
from typing import Any
from uuid import uuid4

import requests

from .const import BASE_URL, DEFAULT_REGION_ID, USER_AGENT

REQUEST_TIMEOUT = 25

_AUTH_ERROR_CODES = {"401", "403", "10001", "10002"}
_AUTH_ERROR_MESSAGES = ("未登录", "重新登录", "登录已过期", "登录失效")

_LOGGER = logging.getLogger(__name__)


def _is_auth_error(code: str, message: str) -> bool:
    """Return whether an API error indicates an expired login session."""
    return (
        code in _AUTH_ERROR_CODES
        or "token" in message.lower()
        or any(text in message for text in _AUTH_ERROR_MESSAGES)
    )


class DesmanLockApiError(Exception):
    """Base Desman Lock API error."""


class DesmanLockAuthError(DesmanLockApiError):
    """Desman Lock authentication error."""


@dataclass
class DesmanLockApiClient:
    """Synchronous Desman Lock API client wrapped by async helpers."""

    phone: str
    password: str
    region_id: str = DEFAULT_REGION_ID
    token: str | None = None

    def _headers(self, *, auth: bool = True) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "zh-Hans-CN;q=1",
            "regionId": self.region_id,
            "language": "zh-Hans",
            "requestId": str(uuid4()),
        }
        if auth and self.token:
            headers["token"] = self.token
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        url = f"{BASE_URL}{path}"
        response = requests.request(
            method,
            url,
            headers=self._headers(auth=auth),
            params=params,
            data=data,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("success") is True:
            result = payload.get("data")
            _LOGGER.debug(
                "Desman API succeeded: path=%s data_type=%s data_keys=%s",
                path,
                type(result).__name__,
                sorted(result) if isinstance(result, dict) else None,
            )
            return result

        message = payload.get("msg") or payload.get("message") or "Desman Lock API error"
        code = str(payload.get("code", ""))
        _LOGGER.debug("Desman API failed: path=%s code=%s message=%s", path, code, message)
        if _is_auth_error(code, message):
            self.token = None
            raise DesmanLockAuthError(message)
        raise DesmanLockApiError(message)

    def login(self) -> str:
        """Log in and return an access token."""
        password_md5 = hashlib.md5(self.password.encode()).hexdigest()
        data = self._request(
            "POST",
            "/nyuwa/login/passWord",
            data={"userPhone": self.phone, "passWord2": password_md5},
            auth=False,
        )
        if not data:
            raise DesmanLockAuthError("Login response does not contain token")
        token = data[0].get("token") if isinstance(data, list) else data.get("token")
        if not token:
            raise DesmanLockAuthError("Login response does not contain token")
        self.token = token
        _LOGGER.debug("Desman API login succeeded")
        return token

    def ensure_token(self) -> None:
        """Ensure token exists."""
        if not self.token:
            self.login()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Perform authenticated GET request, refreshing token once if needed."""
        self.ensure_token()
        try:
            return self._request("GET", path, params=params)
        except DesmanLockAuthError:
            _LOGGER.debug("Authentication expired; logging in again")
            self.login()
            return self._request("GET", path, params=params)

    def post(self, path: str, data: dict[str, Any] | None = None) -> Any:
        """Perform authenticated POST request, refreshing token once if needed."""
        self.ensure_token()
        try:
            return self._request("POST", path, data=data)
        except DesmanLockAuthError:
            _LOGGER.debug("Authentication expired; logging in again")
            self.login()
            return self._request("POST", path, data=data)

    def lock_list(self) -> list[dict[str, Any]]:
        """Return locks bound to the account."""
        data = self.get("/nyuwa/dc/list", {"deviceType": "1"})
        return data or []

    def lock_detail(self, lock_id: str) -> dict[str, Any]:
        """Return lock detail."""
        data = self.get("/nyuwa/dc/lock/detail", {"lockId": lock_id})
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    def lock_detail_and_config(self, lock_id: str) -> dict[str, Any]:
        """Return lock detail and config from newer app API."""
        data = self.get("/nyuwa/deviceV2/lock/detailAndConfig", {"lockId": lock_id})
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    def lock_protocol_config(
        self, lock_mac: str, meter_type: str, firmware_version: str
    ) -> dict[str, Any]:
        """Return the protocol capabilities used by the app dispatcher."""
        data = self.get(
            "/nyuwa/cc/lock/config/detail",
            {
                "lockMac": lock_mac,
                "meterType": meter_type,
                "firmwareVersion": firmware_version,
            },
        )
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    def open_door_records(
        self,
        lock_id: str,
        *,
        page_number: int = 1,
        page_size: int = 5,
        record_type: int | None = 1,
    ) -> list[dict[str, Any]]:
        """Return open door records."""
        params: dict[str, Any] = {
            "lockId": lock_id,
            "pageNumber": str(page_number),
            "pageSize": str(page_size),
        }
        path = "/nyuwa/dc/lock/log/open/door"
        if record_type is not None:
            params["type"] = str(record_type)
            path = "/nyuwa/dc/lock/log/open/door/type"
        return self.get(path, params) or []

    def dynamic_password(self, lock_id: str) -> Any:
        """Create a dynamic password."""
        return self.get("/nyuwa/dc/dynamic/password/create", {"lockId": lock_id})

    def phone_open_control_state(self, lock_id: str) -> bool:
        """Run the server-side phone unlock preflight used by the app."""
        data = self.get(
            "/nyuwa/dc/lock/unlock",
            {"lockId": lock_id, "phoneOpenType": "1", "shakeType": "-1"},
        )
        if isinstance(data, list):
            data = data[0] if data else {}
        allowed = bool(data.get("flag")) if isinstance(data, dict) else bool(data)
        _LOGGER.debug(
            "Desman phone unlock preflight: lock_id=%s allowed=%s", lock_id, allowed
        )
        return allowed

    def open_door_secret(self, lock_id: str, lock_mac: str) -> dict[str, Any]:
        """Return the first BLE challenge command used by the official app."""
        _LOGGER.debug("Requesting BLE challenge command for lock MAC %s", lock_mac)
        data = self.get(
            "/nyuwa/command/lock/secret",
            {"lockId": lock_id, "lockMac": lock_mac},
        )
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    @staticmethod
    def _command_data(data: Any) -> dict[str, Any]:
        """Normalize a command response returned as an object or one-item list."""
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    def id2_enable_command(self, lock_mac: str, enabled: bool) -> dict[str, Any]:
        """Return command 0x67, used by LockOpenId2 before authentication."""
        return self._command_data(
            self.post(
                "/nyuwa/command/0x67",
                {"lockMac": lock_mac, "id2Status": "1" if enabled else "0"},
            )
        )

    def id2_command_option(
        self, lock_mac: str, auth_code: str = "", id2: str = ""
    ) -> dict[str, Any]:
        """Return the 0x65/0x66 command selected by LockOpenId2."""
        return self._command_data(
            self.get(
                "/nyuwa/id2/command/option",
                {"lockMac": lock_mac, "authCode": auth_code, "id2": id2},
            )
        )

    def id2_token_needs_update(self, lock_mac: str) -> bool:
        """Return whether the cloud-side ID2 token must be activated again."""
        data = self.get("/nyuwa/id2/token/expires", {"lockMac": lock_mac})
        if isinstance(data, list):
            data = data[0] if data else {}
        return bool(data.get("needUpdate")) if isinstance(data, dict) else bool(data)

    def id2_lock_id_command(self, lock_mac: str) -> dict[str, Any]:
        """Return command 0x6A which reads the secure element ID2 value."""
        return self._command_data(
            self.get("/nyuwa/command/0x6A", {"lockMac": lock_mac})
        )

    def id2_challenge_command(
        self, lock_mac: str, id2: str, *, is_fail: bool = False
    ) -> dict[str, Any]:
        """Return the ID2 activation challenge command."""
        return self._command_data(
            self.get(
                "/nyuwa/id2/challenge/get",
                {"lockMac": lock_mac, "id2": id2, "isFail": str(is_fail).lower()},
            )
        )

    def id2_upload_auth_code(self, lock_mac: str, id2: str, auth_code: str) -> str:
        """Upload the lock authentication code and return its cloud token."""
        data = self.get(
            "/nyuwa/id2/verify/token/get",
            {"lockMac": lock_mac, "id2": id2, "authCode": auth_code},
        )
        if isinstance(data, list):
            data = data[0] if data else {}
        return (
            str(data.get("token") or "")
            if isinstance(data, dict)
            else str(data or "")
        )

    def id2_token_r1_command(self, lock_mac: str) -> dict[str, Any]:
        """Return command 0x68 containing the token and random R1."""
        return self._command_data(
            self.get("/nyuwa/id2/tokenAndR1/get", {"lockMac": lock_mac})
        )

    def id2_verify_r1_command(
        self, lock_mac: str, enc_r1: str, random_r2: str
    ) -> dict[str, Any]:
        """Verify encrypted R1 and return command 0x69 containing encoded R2."""
        return self._command_data(
            self.get(
                "/nyuwa/id2/verifyR1/encodeR2",
                {"lockMac": lock_mac, "encR1": enc_r1, "R2": random_r2},
            )
        )

    def id2_decrypt_lock_data(self, lock_mac: str, packet: bytes) -> bytes:
        """Decrypt an ID2 BLE response through ReceiverHelper's cloud API."""
        data = self.get(
            "/nyuwa/id2/decryption",
            {"lockMac": lock_mac, "data": packet.hex().upper()},
        )
        if isinstance(data, list):
            data = data[0] if data else {}
        value = data.get("data") if isinstance(data, dict) else data
        if not isinstance(value, str):
            raise DesmanLockApiError("ID2 decryption response contains no data")
        try:
            return bytes.fromhex(value.replace(" ", ""))
        except ValueError as err:
            raise DesmanLockApiError("ID2 decryption response is invalid") from err

    def open_door_command(
        self,
        *,
        lock_mac: str,
        lock_secret: str,
        use_dh_secret: bool,
        lock_type: str,
        lock_user_id: str,
        lock_temp_user_id: str,
    ) -> dict[str, Any]:
        """Return the encrypted BLE unlock command used by the official app."""
        _LOGGER.debug(
            "Requesting BLE unlock command: lock_mac=%s lock_type=%s "
            "user_id_present=%s temp_user_id_present=%s secret_length=%s",
            lock_mac,
            lock_type,
            bool(lock_user_id),
            bool(lock_temp_user_id),
            len(lock_secret),
        )
        data = self.get(
            "/nyuwa/command/lock/open/door",
            {
                "lockDhSecret": lock_secret if use_dh_secret else "",
                "lockSecret": "" if use_dh_secret else lock_secret,
                "lockType": lock_type,
                "lockUserId": lock_user_id,
                "lockTempUserId": lock_temp_user_id,
                "lockMac": lock_mac,
            },
        )
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    def digit_passwords(self, lock_id: str) -> list[dict[str, Any]]:
        """Return digit password list."""
        return self.get("/nyuwa/dc/dp/list", {"lockId": lock_id}) or []

    def add_digit_password(
        self,
        lock_id: str,
        real_time_switch: int,
        range_time: str,
        remarks: str,
        alarm_switch: int,
    ) -> Any:
        """Add a digit password."""
        return self.post(
            "/nyuwa/dc/dp/insert",
            {
                "lockId": lock_id,
                "realTimeSwitch": str(real_time_switch),
                "rangeTime": range_time,
                "remarks": remarks,
                "alarmSwitch": str(alarm_switch),
            },
        )

    def update_digit_password(
        self,
        password_id: str,
        remarks: str,
        real_time_switch: int,
        range_time: str,
        state: int,
    ) -> Any:
        """Update a digit password."""
        return self.post(
            "/nyuwa/dc/dp/edit",
            {
                "id": password_id,
                "remarks": remarks,
                "realTimeSwitch": str(real_time_switch),
                "rangeTime": range_time,
                "state": str(state),
            },
        )

    async def async_login(self) -> str:
        """Async login wrapper."""
        return await asyncio.to_thread(self.login)

    async def async_lock_list(self) -> list[dict[str, Any]]:
        """Async lock list wrapper."""
        return await asyncio.to_thread(self.lock_list)

    async def async_lock_detail(self, lock_id: str) -> dict[str, Any]:
        """Async lock detail wrapper."""
        return await asyncio.to_thread(self.lock_detail, lock_id)

    async def async_lock_detail_and_config(self, lock_id: str) -> dict[str, Any]:
        """Async lock detail and config wrapper."""
        return await asyncio.to_thread(self.lock_detail_and_config, lock_id)

    async def async_lock_protocol_config(
        self, lock_mac: str, meter_type: str, firmware_version: str
    ) -> dict[str, Any]:
        """Return protocol capabilities asynchronously."""
        return await asyncio.to_thread(
            self.lock_protocol_config, lock_mac, meter_type, firmware_version
        )

    async def async_open_door_records(self, lock_id: str) -> list[dict[str, Any]]:
        """Async open door records wrapper."""
        return await asyncio.to_thread(self.open_door_records, lock_id)

    async def async_dynamic_password(self, lock_id: str) -> Any:
        """Async dynamic password wrapper."""
        return await asyncio.to_thread(self.dynamic_password, lock_id)

    async def async_phone_open_control_state(self, lock_id: str) -> bool:
        """Run the phone unlock preflight asynchronously."""
        return await asyncio.to_thread(self.phone_open_control_state, lock_id)

    async def async_open_door_secret(
        self, lock_id: str, lock_mac: str
    ) -> dict[str, Any]:
        """Return the BLE challenge command asynchronously."""
        return await asyncio.to_thread(self.open_door_secret, lock_id, lock_mac)

    async def async_open_door_command(self, **kwargs: Any) -> dict[str, Any]:
        """Return the encrypted BLE unlock command asynchronously."""
        return await asyncio.to_thread(self.open_door_command, **kwargs)

    async def async_id2_enable_command(
        self, lock_mac: str, enabled: bool
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.id2_enable_command, lock_mac, enabled)

    async def async_id2_command_option(
        self, lock_mac: str, auth_code: str = "", id2: str = ""
    ) -> dict[str, Any]:
        """Return the LockOpenId2 command option asynchronously."""
        return await asyncio.to_thread(
            self.id2_command_option, lock_mac, auth_code, id2
        )

    async def async_id2_token_needs_update(self, lock_mac: str) -> bool:
        return await asyncio.to_thread(self.id2_token_needs_update, lock_mac)

    async def async_id2_lock_id_command(self, lock_mac: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.id2_lock_id_command, lock_mac)

    async def async_id2_challenge_command(
        self, lock_mac: str, id2: str, *, is_fail: bool = False
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.id2_challenge_command, lock_mac, id2, is_fail=is_fail
        )

    async def async_id2_upload_auth_code(
        self, lock_mac: str, id2: str, auth_code: str
    ) -> str:
        return await asyncio.to_thread(
            self.id2_upload_auth_code, lock_mac, id2, auth_code
        )

    async def async_id2_token_r1_command(self, lock_mac: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.id2_token_r1_command, lock_mac)

    async def async_id2_verify_r1_command(
        self, lock_mac: str, enc_r1: str, random_r2: str
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.id2_verify_r1_command, lock_mac, enc_r1, random_r2
        )

    async def async_id2_decrypt_lock_data(
        self, lock_mac: str, packet: bytes
    ) -> bytes:
        return await asyncio.to_thread(self.id2_decrypt_lock_data, lock_mac, packet)

    async def async_digit_passwords(self, lock_id: str) -> list[dict[str, Any]]:
        """Async digit passwords wrapper."""
        return await asyncio.to_thread(self.digit_passwords, lock_id)
