"""Config flow for Jebao Aqua integration."""

from __future__ import annotations

import asyncio
import ipaddress
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .api import GizwitsApi
from .const import (
    DEFAULT_REGION,
    DISCOVERY_TIMEOUT,
    DOMAIN,
    GIZWITS_API_URLS,
    LOGGER,
    SERVICE_MAP,
)
from .discovery import discover_devices

_LOGGER = logging.getLogger(__name__)

# Country choices with readable names (subset of SERVICE_MAP countries)
COUNTRY_CHOICES: dict[str, str] = {
    "PL": "Poland",
    "GB": "United Kingdom",
    "DE": "Germany",
    "FR": "France",
    "US": "United States",
    "CA": "Canada",
    "AU": "Australia",
    "NL": "Netherlands",
    "IT": "Italy",
    "ES": "Spain",
    "SE": "Sweden",
    "NO": "Norway",
    "DK": "Denmark",
    "FI": "Finland",
    "AT": "Austria",
    "BE": "Belgium",
    "CH": "Switzerland",
    "CZ": "Czech Republic",
    "IE": "Ireland",
    "PT": "Portugal",
    "GR": "Greece",
    "HU": "Hungary",
    "RO": "Romania",
    "BG": "Bulgaria",
    "HR": "Croatia",
    "SK": "Slovakia",
    "SI": "Slovenia",
    "LT": "Lithuania",
    "LV": "Latvia",
    "EE": "Estonia",
    "CN": "China",
    "JP": "Japan",
    "KR": "South Korea",
    "SG": "Singapore",
    "HK": "Hong Kong",
    "TW": "Taiwan",
    "IN": "India",
    "BR": "Brazil",
    "MX": "Mexico",
    "ZA": "South Africa",
    "AE": "United Arab Emirates",
    "SA": "Saudi Arabia",
    "IL": "Israel",
    "TR": "Turkey",
    "RU": "Russia",
    "UA": "Ukraine",
    "NZ": "New Zealand",
}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Jebao Aqua."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._api: GizwitsApi | None = None
        self._devices: dict | None = None
        self._config: dict = {
            "token": None,
            "devices": [],
            "region": None,
            "email": None,
            "country": None,
        }

    async def async_step_user(self, user_input=None):
        """Handle user credential step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            country_code = user_input["country"]
            self._config["country"] = country_code
            region = SERVICE_MAP.get(country_code.upper(), DEFAULT_REGION)
            self._config["region"] = region
            self._config["email"] = user_input["email"]

            api = GizwitsApi(
                login_url=GIZWITS_API_URLS[region]["LOGIN_URL"],
                devices_url=GIZWITS_API_URLS[region]["DEVICES_URL"],
                device_data_url=GIZWITS_API_URLS[region]["DEVICE_DATA_URL"],
                control_url=GIZWITS_API_URLS[region]["CONTROL_URL"],
            )
            await api.async_init_session()

            try:
                token, error_code = await api.async_login(
                    user_input["email"], user_input["password"]
                )

                if token:
                    api.set_token(token)
                    self._config["token"] = token
                    self._devices = await api.get_devices()

                    if self._devices and "devices" in self._devices:
                        # Try device discovery
                        try:
                            discovered = await asyncio.wait_for(
                                discover_devices(),
                                timeout=DISCOVERY_TIMEOUT + 2,
                            )
                            for device in self._devices["devices"]:
                                device["lan_ip"] = discovered.get(device["did"])
                        except (asyncio.TimeoutError, Exception):
                            LOGGER.warning(
                                "Discovery failed, proceeding with manual IP"
                            )
                            for device in self._devices["devices"]:
                                device["lan_ip"] = None

                        return await self.async_step_device_setup()
                    else:
                        errors["base"] = "no_devices"
                else:
                    errors["base"] = error_code or "auth"
            finally:
                await api.async_close_session()

        # Determine default country from HA config
        ha_country = (self.hass.config.country or "").upper()
        default_country = ha_country if ha_country in COUNTRY_CHOICES else "US"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("country", default=default_country): vol.In(
                        COUNTRY_CHOICES
                    ),
                    vol.Required("email"): str,
                    vol.Required("password"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_device_setup(self, user_input=None):
        """Handle device IP configuration step."""
        errors: dict[str, str] = {}

        device_map = {
            device.get("dev_alias", device["did"]): device
            for device in self._devices["devices"]
        }

        if user_input is not None:
            devices = []
            for alias, device in device_map.items():
                ip = user_input.get(alias, "")
                device_data = device.copy()
                device_data["lan_ip"] = ip if ip else None
                devices.append(device_data)

            if not errors:
                self._config["devices"] = devices
                LOGGER.debug("Final device configuration: %d devices", len(devices))
                return self.async_create_entry(
                    title="Jebao Aquarium Pumps", data=self._config
                )

        # Build form schema
        data_schema = {}
        for device in self._devices["devices"]:
            alias = device.get("dev_alias") or device["did"]
            data_schema[vol.Optional(alias, default=device.get("lan_ip") or "")] = str

        return self.async_show_form(
            step_id="device_setup",
            data_schema=vol.Schema(data_schema),
            description_placeholders={
                "number_of_devices": str(len(self._devices["devices"]))
            },
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow handler."""
        return JebaoPumpOptionsFlowHandler()


class JebaoPumpOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Jebao Pump integration."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._api: GizwitsApi | None = None
        self._devices: dict | None = None
        self._config: dict = {}

    async def async_step_init(self, user_input=None):
        """Manage options."""
        if user_input is not None:
            if user_input["next_step"] == "reconfigure":
                return await self.async_step_reconfigure()
            return self.async_create_entry(title="", data=user_input)

        email = self.config_entry.data.get("email")
        region = self.config_entry.data.get("region")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("next_step"): vol.In(
                        {"reconfigure": "Update credentials and rediscover devices"}
                    )
                }
            ),
            description_placeholders={
                "current_email": email or "Not set",
                "current_region": region or "Not set",
            },
        )

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfiguration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            country_code = user_input["country"]
            region = SERVICE_MAP.get(country_code.upper(), DEFAULT_REGION)

            self._config = {
                "email": user_input["email"],
                "country": country_code,
                "region": region,
                "devices": [],
            }

            api = GizwitsApi(
                login_url=GIZWITS_API_URLS[region]["LOGIN_URL"],
                devices_url=GIZWITS_API_URLS[region]["DEVICES_URL"],
                device_data_url=GIZWITS_API_URLS[region]["DEVICE_DATA_URL"],
                control_url=GIZWITS_API_URLS[region]["CONTROL_URL"],
            )
            await api.async_init_session()

            try:
                token, error_code = await api.async_login(
                    user_input["email"], user_input["password"]
                )
                if token:
                    self._config["token"] = token
                    api.set_token(token)
                    self._devices = await api.get_devices()

                    if self._devices and "devices" in self._devices:
                        try:
                            discovered = await asyncio.wait_for(
                                discover_devices(), timeout=DISCOVERY_TIMEOUT + 2
                            )
                            for device in self._devices["devices"]:
                                device["lan_ip"] = discovered.get(device["did"])
                        except (asyncio.TimeoutError, Exception):
                            LOGGER.warning("Discovery failed during reconfigure")
                            for device in self._devices["devices"]:
                                device["lan_ip"] = None

                        return await self.async_step_device_setup()
                    else:
                        errors["base"] = "no_devices"
                else:
                    errors["base"] = error_code or "auth"
            finally:
                await api.async_close_session()

        stored_country = self.config_entry.data.get("country", "US")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required("country", default=stored_country): vol.In(
                        COUNTRY_CHOICES
                    ),
                    vol.Required(
                        "email", default=self.config_entry.data.get("email", "")
                    ): str,
                    vol.Required("password"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_device_setup(self, user_input=None):
        """Handle device setup during reconfiguration."""
        errors: dict[str, str] = {}

        device_map = {
            device.get("dev_alias", device["did"]): device["did"]
            for device in self._devices["devices"]
        }

        if user_input is not None:
            existing_devices = {
                device["did"]: device
                for device in self.config_entry.data.get("devices", [])
            }

            new_devices = []
            for alias, device_id in device_map.items():
                ip = user_input.get(alias, "")
                if ip:
                    try:
                        ipaddress.ip_address(ip)
                    except ValueError:
                        errors[alias] = "invalid_ip"
                        continue

                if device_id in existing_devices:
                    device_data = existing_devices[device_id].copy()
                    device_data["lan_ip"] = ip or None
                    new_devices.append(device_data)
                else:
                    new_devices.append({"did": device_id, "lan_ip": ip or None})

            if not errors:
                new_data = {
                    "email": self._config["email"],
                    "token": self._config["token"],
                    "region": self._config["region"],
                    "country": self._config["country"],
                    "devices": new_devices,
                }

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=new_data,
                    options={},
                )

                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                return self.async_create_entry(title="", data={})

        # Build form schema
        data_schema = {}
        for device in self._devices["devices"]:
            alias = device.get("dev_alias") or device["did"]
            data_schema[vol.Optional(alias, default=device.get("lan_ip") or "")] = str

        return self.async_show_form(
            step_id="device_setup",
            data_schema=vol.Schema(data_schema),
            description_placeholders={
                "number_of_devices": str(len(self._devices["devices"]))
            },
            errors=errors,
        )
