"""Desman Lock cloud API client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from typing import Any
from uuid import uuid4

import requests

from .const import BASE_URL, DEFAULT_REGION_ID, USER_AGENT

REQUEST_TIMEOUT = 25


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
            return payload.get("data")

        message = payload.get("msg") or payload.get("message") or "Desman Lock API error"
        code = str(payload.get("code", ""))
        if code in {"401", "403", "10001", "10002"} or "token" in message.lower():
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
            self.login()
            return self._request("GET", path, params=params)

    def post(self, path: str, data: dict[str, Any] | None = None) -> Any:
        """Perform authenticated POST request, refreshing token once if needed."""
        self.ensure_token()
        try:
            return self._request("POST", path, data=data)
        except DesmanLockAuthError:
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

    async def async_open_door_records(self, lock_id: str) -> list[dict[str, Any]]:
        """Async open door records wrapper."""
        return await asyncio.to_thread(self.open_door_records, lock_id)

    async def async_alarm_records(self, lock_id: str) -> list[dict[str, Any]]:
        """Async alarm records wrapper."""
        return await asyncio.to_thread(
            self.open_door_records,
            lock_id,
            page_size=20,
            record_type=2,
        )

    async def async_dynamic_password(self, lock_id: str) -> Any:
        """Async dynamic password wrapper."""
        return await asyncio.to_thread(self.dynamic_password, lock_id)

    async def async_digit_passwords(self, lock_id: str) -> list[dict[str, Any]]:
        """Async digit passwords wrapper."""
        return await asyncio.to_thread(self.digit_passwords, lock_id)
