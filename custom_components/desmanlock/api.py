"""Desman Lock cloud API client."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from email.utils import formatdate
import hashlib
import hmac
import json
import logging
from threading import Lock
import time
from typing import Any
from uuid import uuid4

import requests

from .const import (
    APP_VERSION,
    APP_VERSION_CODE,
    BASE_URL,
    DEFAULT_REGION_ID,
    USER_AGENT,
)

REQUEST_TIMEOUT = 25

_ALI_OPEN_ACCOUNT_HOST = "sdk.openaccount.aliyun.com"
_ALI_IOT_HOST = "api.link.aliyun.com"
_ALI_IOT_APP_KEY = "27572231"
_ALI_IOT_APP_SECRET = "12e0452d8b5173804109fceba4bdcaa5"
_ALI_AUTH_ERROR_CODES = {401, 26101, 26251}

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
    _iot_token: str | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _iot_token_expires_at: float = field(
        default=0, init=False, repr=False, compare=False
    )
    _ali_auth_lock: Lock = field(
        default_factory=Lock, init=False, repr=False, compare=False
    )

    def _headers(self, *, auth: bool = True) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "zh-Hans-CN;q=1",
            "appVersion": APP_VERSION,
            "appVersionCode": APP_VERSION_CODE,
            "phoneType": "Android",
            "clientType": "ANDROID",
            "regionId": self.region_id,
            "language": "zh-Hans",
            "requestId": str(uuid4()),
            "type": "",
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
        _LOGGER.debug(
            "Desman API response: method=%s path=%s http_status=%s",
            method,
            path,
            response.status_code,
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
        _LOGGER.debug("Logging in to Desman API for phone ending in %s", self.phone[-4:])
        password_md5 = hashlib.md5(self.password.encode()).hexdigest()
        data = self._request(
            "POST",
            "/nyuwa/login/passWord",
            data={
                "userPhone": self.phone,
                "passWord2": password_md5,
                "regionCode": self.region_id,
            },
            auth=False,
        )
        if not data:
            raise DesmanLockAuthError("Login response does not contain token")
        token = data[0].get("token") if isinstance(data, list) else data.get("token")
        if not token:
            raise DesmanLockAuthError("Login response does not contain token")
        self.token = token
        self._invalidate_iot_token()
        _LOGGER.debug("Desman API login succeeded")
        return token

    @staticmethod
    def _ali_signature(
        method: str,
        path: str,
        headers: dict[str, str],
        *,
        query: dict[str, str] | None = None,
        form: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        """Return the signature used by Alibaba Cloud API Gateway."""
        signed_headers = sorted(
            name for name in headers if name.startswith("x-ca-")
        )
        resource_params = {**(query or {}), **(form or {})}
        resource = path
        if resource_params:
            resource += "?" + "&".join(
                key + (f"={value}" if value else "")
                for key, value in sorted(resource_params.items())
            )
        string_to_sign = "\n".join(
            (
                method,
                headers.get("accept", ""),
                headers.get("content-md5", ""),
                headers.get("content-type", ""),
                headers.get("date", ""),
            )
        ) + "\n"
        string_to_sign += "".join(
            f"{name}:{headers[name]}\n" for name in signed_headers
        )
        string_to_sign += resource
        signature = base64.b64encode(
            hmac.new(
                _ALI_IOT_APP_SECRET.encode(),
                string_to_sign.encode(),
                hashlib.sha1,
            ).digest()
        ).decode()
        return signature, ",".join(signed_headers)

    @classmethod
    def _ali_gateway_headers(
        cls,
        host: str,
        path: str,
        *,
        content_type: str,
        body: bytes | None = None,
        query: dict[str, str] | None = None,
        form: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build Alibaba Cloud API Gateway request headers."""
        headers = {
            "accept": "application/json; charset=utf-8",
            "content-type": content_type,
            "date": formatdate(usegmt=True),
            "host": host,
            "user-agent": "ALIYUN-ANDROID-DEMO",
            "x-ca-key": _ALI_IOT_APP_KEY,
            "x-ca-nonce": str(uuid4()),
            "x-ca-signature-method": "HmacSHA1",
            "x-ca-timestamp": str(int(time.time() * 1000)),
            "CA_VERSION": "1",
        }
        if body:
            headers["content-md5"] = base64.b64encode(
                hashlib.md5(body).digest()
            ).decode()
        signature, signed_headers = cls._ali_signature(
            "POST", path, headers, query=query, form=form
        )
        headers["x-ca-signature-headers"] = signed_headers
        headers["x-ca-signature"] = signature
        return headers

    @staticmethod
    def _unwrap_ali_response(response: requests.Response) -> dict[str, Any]:
        """Unwrap the API Gateway envelope used by both Alibaba APIs."""
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") is None and isinstance(payload.get("data"), dict):
            return payload["data"]
        return payload

    def _open_account_session(self) -> str:
        """Exchange the Desman access token for an OpenAccount session ID."""
        self.ensure_token()
        path = "/api/prd/loginbyoauth.json"
        request = {
            "oauthPlateform": 23,
            "oauthAppKey": _ALI_IOT_APP_KEY,
            "authCode": self.token,
            "riskControlInfo": {
                "platformName": "android",
                "platformVersion": "33",
                "appVersion": APP_VERSION_CODE,
                "appVersionName": APP_VERSION,
                "sdkVersion": "3.4.2",
                "locale": "zh_CN",
                "netType": "wifi",
                "USE_OA_PWD_ENCRYPT": "true",
                "USE_H5_NC": "true",
                "packageName": "com.dsm.secondlock",
            },
        }
        form = {
            "loginByOauthRequest": json.dumps(
                request, separators=(",", ":"), ensure_ascii=False
            )
        }
        response = requests.post(
            f"https://{_ALI_OPEN_ACCOUNT_HOST}{path}",
            headers=self._ali_gateway_headers(
                _ALI_OPEN_ACCOUNT_HOST,
                path,
                content_type="application/x-www-form-urlencoded; charset=utf-8",
                form=form,
            ),
            data=form,
            timeout=REQUEST_TIMEOUT,
        )
        payload = self._unwrap_ali_response(response)
        if payload.get("code") != 1:
            message = str(payload.get("message") or payload.get("code") or "")
            if _is_auth_error(str(payload.get("code") or ""), message):
                raise DesmanLockAuthError(message)
            raise DesmanLockApiError(
                f"Alibaba OpenAccount login failed: {message}"
            )
        login = (payload.get("data") or {}).get("loginSuccessResult") or {}
        if not (session_id := login.get("sid")):
            raise DesmanLockApiError("Alibaba OpenAccount response contains no sid")
        return str(session_id)

    def _ali_iot_request(
        self,
        path: str,
        api_version: str,
        params: dict[str, Any],
        *,
        iot_token: str | None = None,
    ) -> dict[str, Any]:
        """Send an Alibaba IoT API Gateway request."""
        request_id = str(uuid4())
        request: dict[str, Any] = {"apiVer": api_version}
        if iot_token:
            request["iotToken"] = iot_token
        payload = {
            "id": request_id,
            "version": "1.0",
            "request": request,
            "params": params,
        }
        body = json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False
        ).encode()
        query = {"x-ca-request-id": request_id}
        response = requests.post(
            f"https://{_ALI_IOT_HOST}{path}",
            headers=self._ali_gateway_headers(
                _ALI_IOT_HOST,
                path,
                content_type="application/octet-stream; charset=utf-8",
                body=body,
                query=query,
            ),
            params=query,
            data=body,
            timeout=REQUEST_TIMEOUT,
        )
        return self._unwrap_ali_response(response)

    def _create_iot_token(self) -> tuple[str, int]:
        """Create an Alibaba IoT token using the OpenAccount session."""
        session_id = self._open_account_session()
        payload = self._ali_iot_request(
            "/account/createSessionByAuthCode",
            "1.0.4",
            {
                "request": {
                    "authCode": session_id,
                    "appKey": _ALI_IOT_APP_KEY,
                    "accountType": "OA_SESSION",
                }
            },
        )
        if payload.get("code") != 200:
            raise DesmanLockApiError(
                f"Alibaba IoT login failed: {payload.get('message') or payload.get('code')}"
            )
        data = payload.get("data") or {}
        if not (iot_token := data.get("iotToken")):
            raise DesmanLockApiError("Alibaba IoT response contains no iotToken")
        try:
            expires_in = int(data.get("iotTokenExpire") or 1800)
        except (TypeError, ValueError):
            expires_in = 1800
        return str(iot_token), expires_in

    def _invalidate_iot_token(self) -> None:
        """Discard the cached Alibaba IoT token."""
        self._iot_token = None
        self._iot_token_expires_at = 0

    def _ensure_iot_token(self) -> str:
        """Return a valid cached Alibaba IoT token."""
        if self._iot_token and time.monotonic() < self._iot_token_expires_at:
            return self._iot_token
        with self._ali_auth_lock:
            if self._iot_token and time.monotonic() < self._iot_token_expires_at:
                return self._iot_token
            try:
                token, expires_in = self._create_iot_token()
            except DesmanLockAuthError:
                self.token = None
                self.login()
                token, expires_in = self._create_iot_token()
            self._iot_token = token
            self._iot_token_expires_at = time.monotonic() + max(
                1, min(expires_in - 60, 3600)
            )
            return token

    def picture_url(self, iot_id: str, picture_id: str) -> str:
        """Resolve an app picture ID to a temporary Alibaba OSS URL."""
        for attempt in range(2):
            payload = self._ali_iot_request(
                "/vision/customer/picture/querybyids",
                "2.1.0",
                {
                    "iotId": iot_id,
                    "pictureIdList": [picture_id],
                    "type": 0,
                },
                iot_token=self._ensure_iot_token(),
            )
            code = payload.get("code")
            if code == 200:
                pictures = (payload.get("data") or {}).get("pictureList") or []
                if not pictures:
                    raise DesmanLockApiError(
                        "Alibaba picture response contains no picture"
                    )
                picture = pictures[0]
                if url := picture.get("thumbUrl") or picture.get("pictureUrl"):
                    return str(url)
                raise DesmanLockApiError(
                    "Alibaba picture response contains no picture URL"
                )
            if code in _ALI_AUTH_ERROR_CODES and attempt == 0:
                self._invalidate_iot_token()
                continue
            raise DesmanLockApiError(
                f"Alibaba picture query failed: {payload.get('message') or code}"
            )
        raise DesmanLockApiError("Alibaba picture query failed")

    def picture(self, iot_id: str, picture_id: str) -> tuple[bytes, str]:
        """Resolve and download a picture from Alibaba OSS."""
        try:
            response = requests.get(
                self.picture_url(iot_id, picture_id), timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
        except requests.HTTPError as err:
            status = err.response.status_code if err.response is not None else "unknown"
            raise DesmanLockApiError(
                f"Unable to download Alibaba picture: HTTP {status}"
            ) from None
        except requests.RequestException as err:
            raise DesmanLockApiError(
                f"Unable to download Alibaba picture: {type(err).__name__}"
            ) from None
        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        if not content_type.startswith("image/"):
            raise DesmanLockApiError(
                f"Alibaba picture has invalid content type: {content_type or 'unknown'}"
            )
        return response.content, content_type

    def ali_invoke_thing_service(
        self,
        iot_id: str,
        identifier: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke an Alibaba IoT thing service."""
        for attempt in range(2):
            payload = self._ali_iot_request(
                "/thing/service/invoke",
                "1.0.2",
                {
                    "iotId": iot_id,
                    "identifier": identifier,
                    "args": args or {},
                },
                iot_token=self._ensure_iot_token(),
            )
            code = payload.get("code")
            if code == 200:
                return payload
            if code in _ALI_AUTH_ERROR_CODES and attempt == 0:
                self._invalidate_iot_token()
                continue
            raise DesmanLockApiError(
                "Alibaba thing service failed: "
                f"{payload.get('message') or code}"
            )
        raise DesmanLockApiError("Alibaba thing service failed")

    def ali_thing_status(self, iot_id: str) -> dict[str, Any]:
        """Return Alibaba IoT thing online status."""
        for attempt in range(2):
            payload = self._ali_iot_request(
                "/thing/status/get",
                "1.0.2",
                {"iotId": iot_id},
                iot_token=self._ensure_iot_token(),
            )
            code = payload.get("code")
            if code == 200:
                data = payload.get("data")
                return data if isinstance(data, dict) else {}
            if code in _ALI_AUTH_ERROR_CODES and attempt == 0:
                self._invalidate_iot_token()
                continue
            raise DesmanLockApiError(
                "Alibaba thing status query failed: "
                f"{payload.get('message') or code}"
            )
        raise DesmanLockApiError("Alibaba thing status query failed")

    def ali_thing_properties(self, iot_id: str) -> dict[str, Any]:
        """Return Alibaba IoT thing properties."""
        for attempt in range(2):
            payload = self._ali_iot_request(
                "/thing/properties/get",
                "1.0.2",
                {"iotId": iot_id},
                iot_token=self._ensure_iot_token(),
            )
            code = payload.get("code")
            if code == 200:
                data = payload.get("data")
                return data if isinstance(data, dict) else {}
            if code in _ALI_AUTH_ERROR_CODES and attempt == 0:
                self._invalidate_iot_token()
                continue
            raise DesmanLockApiError(
                "Alibaba thing properties query failed: "
                f"{payload.get('message') or code}"
            )
        raise DesmanLockApiError("Alibaba thing properties query failed")

    def ali_camera_status(self, iot_id: str) -> int:
        """Return App-style Alibaba camera status."""
        status = self.ali_thing_status(iot_id).get("status")
        if status == 1:
            properties = self.ali_thing_properties(iot_id)
            low_power = properties.get("LowPowerState")
            low_power_value = (
                low_power.get("value") if isinstance(low_power, dict) else None
            )
            if low_power_value == 1:
                return 11
            if low_power_value == 0:
                return 1
            return -1
        if status in (0, 3, 8):
            return int(status)
        return -1

    def ali_wake_camera(self, iot_id: str) -> None:
        """Wake an Alibaba low-power camera using the App-style flow."""
        status = self.ali_camera_status(iot_id)
        if status == 1:
            return
        if status == 3:
            raise DesmanLockApiError("Alibaba camera is offline")
        if status == 8:
            raise DesmanLockApiError("Alibaba camera is disabled")
        if status != 11:
            raise DesmanLockApiError(f"Alibaba camera status is unknown: {status}")

        for wake_round in range(3):
            for _ in range(10):
                try:
                    self.ali_invoke_thing_service(iot_id, "WakeUp")
                except DesmanLockApiError as err:
                    _LOGGER.debug("Alibaba camera wake-up request failed: %s", err)
                time.sleep(0.5)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                status = self.ali_camera_status(iot_id)
                if status == 1:
                    return
                if status in (3, 8):
                    break
                time.sleep(1)
            _LOGGER.debug("Alibaba camera wake-up round %s did not finish", wake_round + 1)

        raise DesmanLockApiError("Alibaba camera wake-up timed out")

    def ali_live_stream(
        self,
        iot_id: str,
        *,
        wake_up: bool = True,
        api_version: str = "2.1.8",
        stream_type: int = 0,
        start_push: bool = False,
    ) -> dict[str, Any]:
        """Return Alibaba LinkVisual live-stream parameters.

        The LinkVisual SDK requests a relay/P2P session and then completes a
        private native signalling flow.  The returned relay URL is a candidate
        media endpoint, but by itself it has not been proven to be directly
        readable by FFmpeg/Home Assistant.  ``start_push`` is kept for
        diagnostics only; the Android app does not call these services before
        the player has already produced video.
        """
        def query_relay(*, attempts: int = 1) -> dict[str, Any]:
            last_message: str | int | None = None
            auth_retried = False
            for query_attempt in range(attempts):
                payload = self._ali_iot_request(
                    "/vision/customer/stream/query",
                    api_version,
                    {
                        "iotId": iot_id,
                        "streamType": stream_type,
                        "relayEncrypted": False,
                        "relayEncryptType": 0,
                        "forceIFrame": True,
                        "enablePrePlay": True,
                        "needDomainName": True,
                        "enableWebSocket": True,
                        "enablePortPredict": True,
                        "clientType": "Android",
                        "cacheDuration": 0,
                    },
                    iot_token=self._ensure_iot_token(),
                )
                code = payload.get("code")
                last_message = payload.get("message") or code
                if code == 200:
                    data = payload.get("data")
                    if not isinstance(data, dict):
                        raise DesmanLockApiError(
                            "Alibaba live stream response contains no data"
                        )
                    if not data.get("relayUrl"):
                        raise DesmanLockApiError(
                            "Alibaba live stream response contains no relay URL"
                        )
                    return data
                if code in _ALI_AUTH_ERROR_CODES and not auth_retried:
                    auth_retried = True
                    self._invalidate_iot_token()
                    continue
                if (
                    query_attempt < attempts - 1
                    and "offline" in str(last_message).lower()
                ):
                    time.sleep(2)
                    continue
                raise DesmanLockApiError(
                    f"Alibaba live stream query failed: {last_message}"
                )
            raise DesmanLockApiError(
                f"Alibaba live stream query failed: {last_message}"
            )

        def start_push_streaming(data: dict[str, Any]) -> dict[str, Any]:
            relay_url = data.get("relayUrl")
            if not isinstance(relay_url, str) or not relay_url:
                raise DesmanLockApiError(
                    "Alibaba live stream response contains no relay URL"
                )
            self.ali_invoke_thing_service(iot_id, "StartVideo")
            return self.ali_invoke_thing_service(
                iot_id,
                "StartPushStreaming",
                {
                    "PushUrl": relay_url,
                    "StreamType": stream_type,
                    "Scheme": 0,
                    "EncryptKey": "",
                    "EncryptType": 0,
                    "PreTime": 0,
                },
            )

        if wake_up:
            self.ali_wake_camera(iot_id)
            try:
                query_relay(attempts=3)
            except DesmanLockApiError as err:
                _LOGGER.debug(
                    "Alibaba live stream warm-up query failed: %s",
                    err,
                )
            time.sleep(1)

        data = query_relay(attempts=3 if wake_up else 1)
        data["directPlayable"] = False
        if start_push:
            try:
                response = start_push_streaming(data)
                data["pushStarted"] = True
                data["pushResponse"] = response.get("data")
            except DesmanLockApiError as err:
                data["pushStarted"] = False
                data["pushError"] = str(err)
                raise
        return data

    def ali_stop_live_stream(self, iot_id: str, *, stream_type: int = 0) -> None:
        """Ask the Alibaba device to stop pushing a live stream."""
        try:
            self.ali_invoke_thing_service(
                iot_id,
                "StopPushStreaming",
                {"StreamType": stream_type},
            )
        finally:
            self.ali_invoke_thing_service(iot_id, "AppHangUpVideo")

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

    def lock_battery_curve(self, lock_id: str) -> dict[str, Any]:
        """Return the lock battery curve containing small and big batteries."""
        data = self.get(
            "/nyuwa/dc/lock/battery/getLockBatteryCurve", {"lockId": lock_id}
        )
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
        record_type: int,
        page_number: int = 1,
        page_size: int = 5,
    ) -> list[dict[str, Any]]:
        """Return open door records."""
        params: dict[str, Any] = {
            "lockId": lock_id,
            "pageNumber": str(page_number),
            "pageSize": str(page_size),
            "type": str(record_type),
        }
        return self.get("/nyuwa/dc/lock/log/open/door/type", params) or []

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

    async def async_lock_battery_curve(self, lock_id: str) -> dict[str, Any]:
        """Async lock battery curve wrapper."""
        return await asyncio.to_thread(self.lock_battery_curve, lock_id)

    async def async_lock_protocol_config(
        self, lock_mac: str, meter_type: str, firmware_version: str
    ) -> dict[str, Any]:
        """Return protocol capabilities asynchronously."""
        return await asyncio.to_thread(
            self.lock_protocol_config, lock_mac, meter_type, firmware_version
        )

    async def async_open_door_records(
        self,
        lock_id: str,
        *,
        record_type: int,
        page_number: int = 1,
        page_size: int = 5,
    ) -> list[dict[str, Any]]:
        """Async open door records wrapper."""
        return await asyncio.to_thread(
            self.open_door_records,
            lock_id,
            page_number=page_number,
            page_size=page_size,
            record_type=record_type,
        )

    async def async_picture(
        self, iot_id: str, picture_id: str
    ) -> tuple[bytes, str]:
        """Resolve and download an Alibaba picture asynchronously."""
        return await asyncio.to_thread(self.picture, iot_id, picture_id)

    async def async_ali_live_stream(
        self,
        iot_id: str,
        *,
        wake_up: bool = True,
        stream_type: int = 0,
        start_push: bool = False,
    ) -> dict[str, Any]:
        """Return Alibaba LinkVisual live-stream parameters asynchronously."""
        return await asyncio.to_thread(
            self.ali_live_stream,
            iot_id,
            wake_up=wake_up,
            stream_type=stream_type,
            start_push=start_push,
        )

    async def async_ali_stop_live_stream(
        self,
        iot_id: str,
        *,
        stream_type: int = 0,
    ) -> None:
        """Ask the Alibaba device to stop pushing a live stream asynchronously."""
        await asyncio.to_thread(
            self.ali_stop_live_stream,
            iot_id,
            stream_type=stream_type,
        )

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
