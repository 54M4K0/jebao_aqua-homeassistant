"""Gizwits API client for Jebao Aqua integration."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp

from .const import (
    GIZWITS_APP_ID,
    LAN_PORT,
    LOGGER,
    TIMEOUT,
)

GIZWITS_ERROR_CODES: dict[str, str] = {
    "1000000": "user_not_exist",
    "1000033": "invalid_password",
}


class GizwitsApi:
    """Handles communication with Gizwits Cloud API and local LAN devices."""

    def __init__(
        self,
        login_url: str,
        devices_url: str,
        device_data_url: str,
        control_url: str,
        token: str | None = None,
    ) -> None:
        """Initialize API client."""
        self._token = token
        self._attribute_models: dict[str, dict] | None = None
        self._session: aiohttp.ClientSession | None = None
        self.login_url = login_url
        self.devices_url = devices_url
        self.device_data_url = device_data_url
        self.control_url = control_url

    # --- Session Lifecycle ---

    async def async_init_session(self) -> None:
        """Create the shared aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=TIMEOUT)
            )

    async def async_close_session(self) -> None:
        """Close the shared aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _ensure_session(self) -> aiohttp.ClientSession:
        """Return the current session, raising if not initialized."""
        if self._session is None or self._session.closed:
            raise RuntimeError(
                "Session not initialized. Call async_init_session first."
            )
        return self._session

    # --- Configuration ---

    def set_token(self, token: str) -> None:
        """Set the user token for the API."""
        self._token = token

    def add_attribute_models(self, attribute_models: dict) -> None:
        """Add attribute models to the API instance."""
        self._attribute_models = attribute_models

    # --- Cloud API Methods ---

    def _cloud_headers(self, *, with_token: bool = True) -> dict[str, str]:
        """Build standard Gizwits API headers."""
        headers: dict[str, str] = {
            "X-Gizwits-Application-Id": GIZWITS_APP_ID,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if with_token and self._token:
            headers["X-Gizwits-User-token"] = self._token
        return headers

    async def async_login(
        self, email: str, password: str
    ) -> tuple[str | None, str | None]:
        """Login to Gizwits AEP and return (token, error_code).

        Uses the Jebao AEP proxy format (appKey/version/data.account)
        as required by euaepapp.gizwits.com.
        """
        session = self._ensure_session()

        # Jebao AEP proxy format
        data = {
            "appKey": GIZWITS_APP_ID,
            "data": {
                "account": email,
                "password": password,
                "lang": "en",
            },
            "version": "2.0",
        }
        try:
            async with session.post(
                self.login_url,
                json=data,
                headers=self._cloud_headers(with_token=False),
            ) as response:
                response_text = await response.text()
                LOGGER.debug("Login response status: %s", response.status)

                try:
                    json_response = json.loads(response_text)
                except json.JSONDecodeError:
                    LOGGER.error("Failed to decode login response JSON")
                    return None, "invalid_json"

                # Check for AEP error format: {"code":"504","error":true,...}
                if json_response.get("error", False):
                    error_code = str(json_response.get("code", ""))
                    error_msg = json_response.get("message", "")
                    LOGGER.error("Login error %s: %s", error_code, error_msg)
                    return None, GIZWITS_ERROR_CODES.get(error_code, "auth")

                # AEP format: {"data": {"userToken": "..."}}
                resp_data = json_response.get("data", {})
                if isinstance(resp_data, dict):
                    token = resp_data.get("userToken")
                    if token:
                        return token, None

                # Standard Open API format: {"token": "..."}
                token = json_response.get("token")
                if token:
                    return token, None

                LOGGER.error("No token in login response: %s", response_text[:200])
                return None, "invalid_response"

        except Exception:
            LOGGER.exception("Exception during login to Gizwits API")
            return None, "connection_error"

    async def get_devices(self) -> dict | None:
        """Get a list of bound devices from cloud."""
        session = self._ensure_session()
        try:
            async with session.get(
                self.devices_url, headers=self._cloud_headers()
            ) as response:
                if response.status == 200:
                    # Gizwits sometimes returns JSON with text/html content-type
                    return await response.json(content_type=None)
                LOGGER.error("Failed to fetch devices: HTTP %s", response.status)
                return None
        except Exception:
            LOGGER.exception("Exception fetching devices from Gizwits")
            return None

    async def get_device_data(self, device_id: str) -> dict | None:
        """Get latest device data from cloud."""
        session = self._ensure_session()
        url = self.device_data_url.format(device_id=device_id)
        try:
            async with session.get(url, headers=self._cloud_headers()) as response:
                if response.status == 200:
                    return await response.json(content_type=None)
                LOGGER.error("Failed to fetch device data: HTTP %s", response.status)
                return None
        except Exception:
            LOGGER.exception("Exception fetching device data for %s", device_id)
            return None

    async def control_device(
        self, device_id: str, attributes: dict[str, Any]
    ) -> dict | None:
        """Send control command to device via cloud API."""
        session = self._ensure_session()
        url = self.control_url.format(device_id=device_id)
        data = {"attrs": attributes}

        LOGGER.debug("Cloud control %s: %s", device_id, attributes)
        try:
            async with session.post(
                url, json=data, headers=self._cloud_headers()
            ) as response:
                if response.status == 200:
                    return await response.json(content_type=None)
                LOGGER.error("Control command failed: HTTP %s", response.status)
                return None
        except Exception:
            LOGGER.exception("Exception sending control command to %s", device_id)
            return None

    # --- Local LAN Methods ---

    async def get_local_device_data(
        self, device_ip: str, product_key: str, device_id: str
    ) -> dict | None:
        """Poll local device for status via TCP/12416."""
        if not self._attribute_models:
            LOGGER.error("No attribute models loaded")
            return None

        attribute_model = self._attribute_models.get(product_key)
        if not attribute_model:
            LOGGER.error("Missing attribute model for product key: %s", product_key)
            return None

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(device_ip, LAN_PORT),
                timeout=TIMEOUT,
            )
            try:
                return await self._poll_local_device(
                    reader, writer, device_id, attribute_model
                )
            finally:
                writer.close()
                await writer.wait_closed()

        except asyncio.TimeoutError:
            LOGGER.debug("Timeout connecting to local device %s", device_ip)
            return None
        except ConnectionError as err:
            LOGGER.debug("Connection error with %s: %s", device_ip, err)
            return None
        except Exception:
            LOGGER.debug(
                "Error communicating with local device %s", device_ip, exc_info=True
            )
            return None

    async def _poll_local_device(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        device_id: str,
        attribute_model: dict,
    ) -> dict | None:
        """Execute the LAN polling sequence."""
        # Step 1: Get binding key
        await self._send_local_command(writer, b"\x00\x06")
        response = await asyncio.wait_for(reader.read(1024), timeout=TIMEOUT)
        binding_key = response[-12:]

        # Step 2: Bind with key
        await self._send_local_command(writer, b"\x00\x08", binding_key)
        await asyncio.wait_for(reader.read(1024), timeout=TIMEOUT)

        # Step 3: Request device status
        await self._send_local_command(writer, b"\x00\x93", b"\x00\x00\x00\x02\x02")
        response = await asyncio.wait_for(reader.read(1024), timeout=TIMEOUT)

        # Parse response
        payload = self._extract_device_status_payload(response)
        if payload is None:
            return None

        parsed = self._parse_device_status(payload, attribute_model)
        return {"did": device_id, "attr": parsed}

    async def control_device_local(
        self,
        device_ip: str,
        product_key: str,
        device_id: str,
        attributes: dict[str, Any],
    ) -> bool:
        """Send control command to device via local TCP."""
        if not self._attribute_models:
            return False

        attribute_model = self._attribute_models.get(product_key)
        if not attribute_model:
            LOGGER.error("Missing attribute model for %s", product_key)
            return False

        # Build the binary payload from attributes
        payload = self._build_control_payload(attributes, attribute_model)
        if payload is None:
            return False

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(device_ip, LAN_PORT),
                timeout=TIMEOUT,
            )
            try:
                # Bind first
                await self._send_local_command(writer, b"\x00\x06")
                response = await asyncio.wait_for(reader.read(1024), timeout=TIMEOUT)
                binding_key = response[-12:]

                await self._send_local_command(writer, b"\x00\x08", binding_key)
                await asyncio.wait_for(reader.read(1024), timeout=TIMEOUT)

                # Send control command (0x93 with action flag 0x01 = write)
                control_payload = b"\x00\x00\x00\x01\x01" + payload
                await self._send_local_command(writer, b"\x00\x93", control_payload)
                await asyncio.wait_for(reader.read(1024), timeout=TIMEOUT)

                LOGGER.debug("Local control sent to %s: %s", device_id, attributes)
                return True
            finally:
                writer.close()
                await writer.wait_closed()

        except Exception:
            LOGGER.debug(
                "Local control failed for %s, will try cloud", device_id, exc_info=True
            )
            return False

    # --- LAN Protocol Helpers ---

    async def _send_local_command(
        self,
        writer: asyncio.StreamWriter,
        command: bytes,
        payload: bytes = b"",
    ) -> None:
        """Send a Gizwits GAgent LAN protocol command."""
        header = b"\x00\x00\x00\x03"
        flag = b"\x00"
        length = len(flag + command + payload).to_bytes(1, byteorder="big")
        packet = header + length + flag + command + payload
        writer.write(packet)
        await writer.drain()

    def _extract_device_status_payload(self, response: bytes) -> bytes | None:
        """Extract device status payload from GAgent response."""
        pattern = b"\x00\x00\x00\x03"
        start_index = response.find(pattern)
        if start_index == -1:
            LOGGER.debug("GAgent header pattern not found in response")
            return None

        leb128_bytes = response[start_index + len(pattern) :]
        length, _ = self._decode_leb128(leb128_bytes)
        if length is None:
            LOGGER.debug("Failed to decode LEB128 payload length")
            return None

        # Subtract 8 from decoded length to get status payload size
        payload_len = length - 8
        if 0 < payload_len <= len(response):
            return response[-payload_len:]

        LOGGER.debug("Invalid payload length: %d", payload_len)
        return None

    @staticmethod
    def _decode_leb128(data: bytes) -> tuple[int | None, int]:
        """Decode LEB128 encoded data, return (value, bytes_read)."""
        result = 0
        shift = 0
        for i, byte in enumerate(data):
            result |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                return result, i + 1
            shift += 7
        return None, 0

    @staticmethod
    def _swap_endian(hex_str: str) -> str:
        """Swap endianness of the first two bytes."""
        if len(hex_str) >= 4:
            return hex_str[2:4] + hex_str[0:2] + hex_str[4:]
        return hex_str

    def _parse_device_status(
        self, payload: bytes, attribute_model: dict
    ) -> dict[str, Any]:
        """Parse device status payload based on attribute model."""
        status_data: dict[str, Any] = {}

        try:
            hex_payload = payload.hex() if isinstance(payload, bytes) else payload

            # Check if endianness swap is needed
            attrs = attribute_model.get("attrs", [])
            if not attrs:
                # New format: entities[0].attrs
                entities = attribute_model.get("entities", [])
                if entities:
                    attrs = entities[0].get("attrs", [])

            swap_needed = any(
                a["position"]["byte_offset"] == 0
                and (a["position"]["bit_offset"] + a["position"]["len"] > 8)
                for a in attrs
            )

            if swap_needed:
                hex_payload = self._swap_endian(hex_payload)

            payload_bytes = bytes.fromhex(hex_payload)

            for attr in attrs:
                name = attr["name"]
                pos = attr["position"]
                byte_offset = pos["byte_offset"]
                bit_offset = pos["bit_offset"]
                length = pos["len"]
                data_type = attr.get("data_type", "unknown")

                try:
                    if byte_offset >= len(payload_bytes):
                        continue

                    if data_type == "bool":
                        value = bool(
                            self._extract_bits(
                                payload_bytes[byte_offset], bit_offset, length
                            )
                        )
                    elif data_type == "enum":
                        enum_values = attr.get("enum", [])
                        idx = self._extract_bits(
                            payload_bytes[byte_offset], bit_offset, length
                        )
                        value = enum_values[idx] if idx < len(enum_values) else None
                    elif data_type == "uint8":
                        value = payload_bytes[byte_offset]
                    elif data_type == "binary":
                        end = byte_offset + length
                        if end <= len(payload_bytes):
                            value = payload_bytes[byte_offset:end].hex()
                        else:
                            continue
                    else:
                        continue

                    status_data[name] = value
                except (IndexError, KeyError):
                    LOGGER.debug("Skipping attr %s: payload too short", name)

        except Exception:
            LOGGER.exception("Error parsing device status payload")

        return status_data

    @staticmethod
    def _extract_bits(byte_val: int, bit_offset: int, length: int) -> int:
        """Extract specific bits from a byte value."""
        mask = (1 << length) - 1
        return (byte_val >> bit_offset) & mask

    def _build_control_payload(
        self, attributes: dict[str, Any], attribute_model: dict
    ) -> bytes | None:
        """Build a binary control payload from attribute values."""
        attrs = attribute_model.get("attrs", [])
        if not attrs:
            entities = attribute_model.get("entities", [])
            if entities:
                attrs = entities[0].get("attrs", [])

        if not attrs:
            return None

        # Find max byte needed
        max_byte = 0
        for attr in attrs:
            pos = attr["position"]
            if pos["unit"] == "byte":
                end = pos["byte_offset"] + pos["len"]
            else:
                end = pos["byte_offset"] + 1
            max_byte = max(max_byte, end)

        payload = bytearray(max_byte)

        for attr_name, value in attributes.items():
            attr_def = next((a for a in attrs if a["name"] == attr_name), None)
            if not attr_def:
                LOGGER.warning("Unknown attribute: %s", attr_name)
                continue

            pos = attr_def["position"]
            byte_offset = pos["byte_offset"]
            bit_offset = pos["bit_offset"]
            length = pos["len"]
            data_type = attr_def.get("data_type", "unknown")

            try:
                if data_type == "bool":
                    if value:
                        payload[byte_offset] |= 1 << bit_offset
                    else:
                        payload[byte_offset] &= ~(1 << bit_offset)
                elif data_type == "enum":
                    enum_values = attr_def.get("enum", [])
                    if isinstance(value, str) and value in enum_values:
                        idx = enum_values.index(value)
                    else:
                        idx = int(value)
                    mask = ((1 << length) - 1) << bit_offset
                    payload[byte_offset] = (payload[byte_offset] & ~mask) | (
                        (idx & ((1 << length) - 1)) << bit_offset
                    )
                elif data_type == "uint8":
                    payload[byte_offset] = int(value) & 0xFF
                elif data_type == "binary":
                    bin_bytes = bytes.fromhex(str(value))
                    payload[byte_offset : byte_offset + len(bin_bytes)] = bin_bytes
            except Exception:
                LOGGER.debug("Failed to encode attribute %s", attr_name, exc_info=True)

        return bytes(payload)
