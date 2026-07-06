"""Bluetooth transport for Desman locks."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import DesmanLockApiClient

WRITE_CHARACTERISTIC = "0000ffe9-0000-1000-8000-00805f9b34fb"
NOTIFY_CHARACTERISTIC = "0000ffe4-0000-1000-8000-00805f9b34fb"
RESPONSE_TIMEOUT = 15
CONNECTION_TIMEOUT = 100
SCAN_TIMEOUT = 100

_LOGGER = logging.getLogger(__name__)


class DesmanBleakClient(BleakClient):
    """Bleak client with a longer timeout for weak, briefly awake locks."""

    async def connect(self, **kwargs: Any) -> bool:
        """Connect using the Desman-specific timeout."""
        kwargs["timeout"] = CONNECTION_TIMEOUT
        return await super().connect(**kwargs)


class DesmanBluetoothLock:
    """Execute the two-step encrypted unlock exchange used by the app."""

    def __init__(
        self,
        hass: HomeAssistant | None,
        api: DesmanLockApiClient,
        lock: dict[str, Any],
        detail: dict[str, Any],
        detail_config: dict[str, Any] | None = None,
    ) -> None:
        self._hass = hass
        self._api = api
        self._lock = lock
        self._detail = detail
        self._detail_config = detail_config or {}
        self._client: DesmanBleakClient | None = None
        self._operation_lock = asyncio.Lock()
        self._id2_cipher_state = False

    def update_data(
        self,
        lock: dict[str, Any],
        detail: dict[str, Any],
        detail_config: dict[str, Any],
    ) -> None:
        """Update cloud data without dropping a live GATT connection."""
        self._lock = lock
        self._detail = detail
        self._detail_config = detail_config

    async def async_close(self) -> None:
        """Close the persistent Bluetooth connection."""
        client, self._client = self._client, None
        if client is not None and client.is_connected:
            await client.disconnect()

    def _disconnected(self, client: DesmanBleakClient) -> None:
        """Forget a connection dropped by the lock."""
        if self._client is client:
            self._client = None
        _LOGGER.debug("Desman lock disconnected")

    async def async_unlock(self, ble_device: Any | None = None) -> None:
        """Exchange the challenge and send the encrypted unlock command."""
        async with self._operation_lock:
            await self._async_unlock(ble_device)

    async def _async_unlock(self, ble_device: Any | None = None) -> None:
        """Execute one unlock while holding the operation lock."""
        lock_id = str(self._lock.get("lockId") or self._detail.get("lockId") or "")
        lock_mac = str(
            self._detail.get("lockMac") or self._lock.get("lockMac") or ""
        ).upper()
        if not lock_id or not lock_mac:
            raise HomeAssistantError("Desman lock ID or Bluetooth MAC is unavailable")

        _LOGGER.debug("Running Desman phone unlock preflight for lock %s", lock_id)
        if not await self._api.async_phone_open_control_state(lock_id):
            raise HomeAssistantError(
                "The Desman server does not allow phone unlock in the current environment"
            )

        protocol = await self._async_protocol(lock_mac)
        _LOGGER.debug(
            "Starting Desman Bluetooth unlock: lock_id=%s lock_mac=%s lock_type=%s",
            lock_id,
            lock_mac,
            self._lock.get("lockType") or self._detail.get("type"),
        )
        client = self._client
        if client is not None and client.is_connected:
            _LOGGER.debug("Reusing persistent connection to Desman lock %s", lock_mac)
        elif ble_device is None and self._hass is not None:
            ble_device = bluetooth.async_ble_device_from_address(
                self._hass, lock_mac, connectable=True
            )
            if ble_device is None:
                ble_device = _ha_device_by_lock_name(self._hass, lock_mac)
        if client is None and ble_device is None and self._hass is None:
            _LOGGER.debug(
                "Scanning up to %s seconds for Desman lock %s (name suffix %s)",
                SCAN_TIMEOUT,
                lock_mac,
                _lock_name_suffix(lock_mac),
            )
            ble_device = await async_find_desman_device(lock_mac)
        if client is None and ble_device is None:
            raise HomeAssistantError(
                f"Desman lock {lock_mac} is not in Bluetooth range; wake its keypad and retry"
            )

        if client is None:
            _LOGGER.debug(
                "Connecting to Desman lock: address=%s name=%s",
                ble_device.address,
                ble_device.name,
            )
            try:
                client = await establish_connection(
                    client_class=DesmanBleakClient,
                    device=ble_device,
                    name=f"Desman lock {lock_mac}",
                    disconnected_callback=self._disconnected,
                )
            except Exception:
                _LOGGER.exception("Failed to connect to Desman lock %s", lock_mac)
                raise
            self._client = client
            _LOGGER.debug("Connected persistently to Desman lock %s", lock_mac)

        if protocol == "ID2":
            await self._async_id2_prepare(client, lock_mac)

        secret_data = await self._api.async_open_door_secret(lock_id, lock_mac)
        challenge_command = _command_bytes(secret_data)
        _LOGGER.debug(
            "Sending BLE challenge command: length=%s command=0x%02X",
            len(challenge_command),
            challenge_command[2] if len(challenge_command) > 2 else challenge_command[0],
        )
        challenge_reply = await self._async_write_and_wait(client, challenge_command)
        if protocol == "ID2":
            challenge_reply = await self._api.async_id2_decrypt_lock_data(
                lock_mac, challenge_reply
            )
        challenge_ack = challenge_reply[5] if len(challenge_reply) > 5 else -1
        _LOGGER.debug(
            "Received BLE challenge response: length=%s command=%s ack=%s",
            len(challenge_reply),
            f"0x{challenge_reply[2]:02X}" if len(challenge_reply) > 2 else "unknown",
            challenge_ack,
        )
        if challenge_ack != 0:
            raise HomeAssistantError(
                "Desman lock rejected the challenge command with "
                f"acknowledgement {challenge_ack}"
            )
        # LockBleUtils' default response-data mode passes the analyzer's data
        # area (without frame header, ACK, and CRC) to the standard opener.
        secret_reply = _response_data(challenge_reply)
        if protocol == "DH" and len(challenge_reply) > 4 and challenge_reply[2] == 0x70:
            secret_reply = challenge_reply[:4]
        _LOGGER.debug(
            "Extracted BLE challenge secret: protocol=%s length=%s",
            protocol,
            len(secret_reply),
        )
        command_data = await self._api.async_open_door_command(
            lock_mac=lock_mac,
            lock_secret=secret_reply.hex().upper(),
            use_dh_secret=protocol == "DH",
            lock_type=str(
                self._lock.get("lockType") or self._detail.get("type") or ""
            ),
            lock_user_id=_first_value(
                self._lock,
                self._detail,
                keys=("lockUserId", "userId"),
            ),
            lock_temp_user_id=_first_value(
                self._lock,
                self._detail,
                keys=("lockTempUserId", "tempUserId"),
            ),
        )
        unlock_command = _command_bytes(command_data)
        _LOGGER.debug(
            "Sending BLE unlock command: protocol=%s length=%s command=0x%02X",
            protocol,
            len(unlock_command),
            unlock_command[2] if len(unlock_command) > 2 else unlock_command[0],
        )
        unlock_reply = await self._async_write_and_wait(client, unlock_command)
        if protocol == "ID2":
            unlock_reply = await self._api.async_id2_decrypt_lock_data(
                lock_mac, unlock_reply
            )
        unlock_ack = unlock_reply[5] if len(unlock_reply) > 5 else -1
        _LOGGER.debug(
            "Received BLE unlock response: length=%s command=%s ack=%s",
            len(unlock_reply),
            f"0x{unlock_reply[2]:02X}" if len(unlock_reply) > 2 else "unknown",
            unlock_ack,
        )
        if len(unlock_reply) < 8 or unlock_reply[2] != unlock_command[2]:
            raise HomeAssistantError("Desman lock returned an invalid unlock response")
        if unlock_ack != 0:
            raise HomeAssistantError(
                f"Desman lock rejected the unlock command with acknowledgement {unlock_ack}"
            )

    async def _async_protocol(self, lock_mac: str) -> str:
        """Select the app protocol from current device capabilities."""
        meter_type = str(
            self._detail.get("meterType") or self._lock.get("meterType") or ""
        )
        firmware = str(
            self._detail.get("softwareVersion")
            or self._lock.get("softwareVersion")
            or ""
        )
        config = await self._api.async_lock_protocol_config(
            lock_mac, meter_type, firmware
        )
        base_info = config.get("lockBaseInfo") or {}
        encryption = str(base_info.get("openDoorEncryType") or "").upper()
        cipher_state = config.get("cipherState")
        self._id2_cipher_state = cipher_state is True or str(cipher_state) == "1"
        protocol = "ID2" if encryption == "ID2" else (
            "DH" if encryption == "DH" or config.get("cipherType") == 3 else "STANDARD"
        )
        _LOGGER.debug(
            "Selected Desman unlock protocol: protocol=%s encryption=%s "
            "encryption_lock=%s cipher_type=%s cipher_state=%s",
            protocol,
            encryption or "unknown",
            base_info.get("encryptionLock"),
            config.get("cipherType"),
            config.get("cipherState"),
        )
        return protocol

    async def _async_id2_prepare(self, client: Any, lock_mac: str) -> None:
        """Run the LockOpenId2 enable, activation and authentication tasks."""
        _LOGGER.debug(
            "Starting ID2 preparation: lock_mac=%s cipher_state=%s",
            lock_mac,
            self._id2_cipher_state,
        )
        enable = _command_bytes(
            await self._api.async_id2_enable_command(
                lock_mac, self._id2_cipher_state
            )
        )
        await self._async_id2_exchange(client, enable, "enable")
        if not self._id2_cipher_state:
            return

        await self._async_lock_open_id2(client, lock_mac)
        await self._async_id2_authenticate(client, lock_mac)
        _LOGGER.debug("LockOpenId2 authentication completed for %s", lock_mac)

    async def _async_id2_authenticate(self, client: Any, lock_mac: str) -> None:
        """Run Id2Helper.id2Authentication's 0x68/0x69 exchange."""
        token_r1 = _command_bytes(
            await self._api.async_id2_token_r1_command(lock_mac)
        )
        reply = await self._async_id2_exchange(client, token_r1, "token-r1")
        # The native OnXIAODILockId2Listener exposes the 32 binary response
        # bytes as a 64-character hexadecimal string before splitting it.
        token_response = _response_data(reply).hex().upper()
        if len(token_response) != 64:
            raise HomeAssistantError(
                "Desman ID2 token/R1 response must contain 64 characters "
                f"(received {len(token_response)})"
            )
        verify = _command_bytes(
            await self._api.async_id2_verify_r1_command(
                lock_mac, token_response[:32], token_response[32:]
            )
        )
        await self._async_id2_exchange(client, verify, "verify-r1")

    async def _async_lock_open_id2(self, client: Any, lock_mac: str) -> None:
        """Execute LockOpenId2.createId2Task's 0x65/0x66 state machine."""
        auth_code = ""
        id2 = ""
        for attempt in range(6):
            command = _command_bytes(
                await self._api.async_id2_command_option(
                    lock_mac, auth_code=auth_code, id2=id2
                )
            )
            command_id = command[2] if len(command) > 2 else -1
            if command_id not in (0x65, 0x66):
                raise HomeAssistantError(
                    f"LockOpenId2 returned unsupported command 0x{command_id:02X}"
                )
            reply = await self._async_id2_exchange(
                client, command, f"open-option-{command_id:02x}"
            )
            ack = reply[5]
            data = _response_data(reply)
            if command_id == 0x66:
                if auth_code:
                    raise HomeAssistantError(
                        "LockOpenId2 returned command 0x66 more than once"
                    )
                auth_code = _response_text(reply, "ID2 authentication code")
                _LOGGER.debug(
                    "LockOpenId2 received authentication code: length=%s",
                    len(data),
                )
                continue

            # XIAODIBLEReceived accepts ACK 0, or ACK 1 with 24 data bytes.
            # LockOpenId2 repeats createId2Task only for callback result 2;
            # that callback stores the returned ID2 for the next option call.
            if ack == 0:
                return
            if ack == 1 and len(data) == 24:
                id2 = _response_text(reply, "ID2 identifier")
                _LOGGER.debug(
                    "LockOpenId2 received ID2 identifier: length=%s attempt=%s",
                    len(data),
                    attempt + 1,
                )
                continue
            raise HomeAssistantError(
                f"LockOpenId2 0x65 failed: ack={ack} data_length={len(data)}"
            )
        raise HomeAssistantError("LockOpenId2 state-machine retry limit exceeded")

    async def _async_id2_exchange(
        self, client: Any, command: bytes, step: str
    ) -> bytes:
        """Send one ID2 command and validate its framed response."""
        command_id = command[2] if len(command) > 2 else -1
        _LOGGER.debug(
            "Sending ID2 %s command: command=0x%02X length=%s",
            step,
            command_id,
            len(command),
        )
        reply = await self._async_write_and_wait(client, command)
        ack = reply[5] if len(reply) > 5 else -1
        _LOGGER.debug(
            "Received ID2 %s response: command=%s ack=%s data_length=%s",
            step,
            f"0x{reply[2]:02X}" if len(reply) > 2 else "unknown",
            ack,
            len(_response_data(reply)),
        )
        if ack not in (0, 1, 2):
            raise HomeAssistantError(
                f"Desman ID2 {step} command failed with lock acknowledgement {ack}"
            )
        return reply

    async def _async_write_and_wait(self, client: Any, command: bytes) -> bytes:
        """Write one app-generated packet and collect its complete notification."""
        loop = asyncio.get_running_loop()
        response: asyncio.Future[bytes] = loop.create_future()
        received = bytearray()

        def notification_handler(_sender: Any, data: bytearray) -> None:
            if response.done():
                return
            received.extend(data)
            if len(received) < 5:
                return
            expected_length = int.from_bytes(received[3:5], "big") + 7
            if len(received) >= expected_length:
                response.set_result(bytes(received[:expected_length]))

        await client.start_notify(NOTIFY_CHARACTERISTIC, notification_handler)
        _LOGGER.debug("Enabled notifications on %s", NOTIFY_CHARACTERISTIC)
        try:
            for offset in range(0, len(command), 20):
                chunk = command[offset : offset + 20]
                _LOGGER.debug(
                    "Writing BLE chunk: offset=%s length=%s total=%s",
                    offset,
                    len(chunk),
                    len(command),
                )
                await client.write_gatt_char(
                    WRITE_CHARACTERISTIC, chunk, response=True
                )
            return await asyncio.wait_for(response, RESPONSE_TIMEOUT)
        except TimeoutError as err:
            raise HomeAssistantError("Desman lock did not answer the Bluetooth command") from err
        finally:
            await client.stop_notify(NOTIFY_CHARACTERISTIC)


def _command_bytes(data: dict[str, Any]) -> bytes:
    """Extract the hexadecimal command returned by either command endpoint."""
    command = data.get("command") or data.get("cmd") or data.get("hex")
    if not isinstance(command, str):
        raise HomeAssistantError("Desman command response does not contain a command")
    try:
        command_bytes = bytes.fromhex(command.replace(" ", ""))
    except ValueError as err:
        raise HomeAssistantError("Desman command response contains invalid hex data") from err
    if not command_bytes:
        raise HomeAssistantError("Desman command response contains an empty command")
    return command_bytes


def _first_value(
    *sources: dict[str, Any], keys: tuple[str, ...]
) -> str:
    """Return the first non-empty value for any key from ordered sources."""
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value is not None and value != "":
                return str(value)
    return ""


def _response_data(packet: bytes) -> bytes:
    """Extract the protocol data area (after command, length and ACK)."""
    if len(packet) < 7:
        return b""
    # The two-byte payload length includes the one-byte ACK at packet[5].
    data_length = max(0, int.from_bytes(packet[3:5], "big") - 1)
    return packet[6 : 6 + data_length]


def _response_text(packet: bytes, description: str) -> str:
    """Decode an ID2 response data area as the SDK's UTF-8 String does."""
    try:
        value = _response_data(packet).decode("utf-8")
    except UnicodeDecodeError as err:
        raise HomeAssistantError(
            f"Desman {description} response is not valid UTF-8"
        ) from err
    if not value:
        raise HomeAssistantError(f"Desman {description} response is empty")
    return value


def _lock_name_suffix(lock_mac: str) -> str:
    """Return the suffix used by LOCK_xxxx advertisements."""
    return lock_mac.replace(":", "").replace("-", "")[-4:].lower()


async def async_find_desman_device(
    lock_mac: str, timeout: float = SCAN_TIMEOUT
) -> Any | None:
    """Find a lock by MAC on Linux or LOCK_xxxx name on CoreBluetooth."""
    return await BleakScanner.find_device_by_filter(
        lambda device, advertisement: _matches_lock_advertisement(
            lock_mac,
            device.address,
            advertisement.local_name or device.name,
            advertisement.rssi,
        ),
        timeout=timeout,
    )


def _matches_lock_advertisement(
    lock_mac: str,
    address: str,
    name: str | None,
    rssi: int | None = None,
) -> bool:
    """Match either the cloud MAC or Desman's LOCK_<MAC suffix> name."""
    normalized_address = address.upper().replace("-", ":")
    normalized_name = (name or "").lower()
    matched = normalized_address == lock_mac.upper() or normalized_name == (
        f"lock_{_lock_name_suffix(lock_mac)}"
    )
    if normalized_name.startswith("lock_") or matched:
        _LOGGER.debug(
            "Observed Desman BLE candidate: address=%s name=%s rssi=%s matched=%s",
            address,
            name,
            rssi,
            matched,
        )
    return matched


def _ha_device_by_lock_name(hass: HomeAssistant, lock_mac: str) -> Any | None:
    """Find a HA-cached BLE device using Desman's stable advertisement name."""
    for service_info in bluetooth.async_discovered_service_info(
        hass, connectable=True
    ):
        if _matches_lock_advertisement(
            lock_mac,
            service_info.address,
            service_info.name,
            service_info.rssi,
        ):
            _LOGGER.debug(
                "Using HA Bluetooth discovery match for %s: address=%s name=%s",
                lock_mac,
                service_info.address,
                service_info.name,
            )
            return service_info.device
    return None
