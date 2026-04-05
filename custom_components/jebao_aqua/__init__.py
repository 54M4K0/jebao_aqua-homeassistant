"""The Jebao Aqua integration."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import GizwitsApi
from .const import (
    DOMAIN,
    GIZWITS_API_URLS,
    LOGGER,
    MAX_LAN_FAILURES,
    PLATFORMS,
    UPDATE_INTERVAL,
)
from .discovery import discover_devices
from .helpers import is_device_data_valid
from .services import async_setup_services, async_unload_services


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Jebao Aqua from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    token = entry.data.get("token")
    region = entry.data.get("region")

    if not token or not region:
        LOGGER.error("API token or region not found in configuration entry")
        return False

    # Load attribute models asynchronously
    attribute_models = await _load_attribute_models(hass)

    # Initialize API with correct regional URLs
    api = GizwitsApi(
        login_url=GIZWITS_API_URLS[region]["LOGIN_URL"],
        devices_url=GIZWITS_API_URLS[region]["DEVICES_URL"],
        device_data_url=GIZWITS_API_URLS[region]["DEVICE_DATA_URL"],
        control_url=GIZWITS_API_URLS[region]["CONTROL_URL"],
        token=token,
    )
    await api.async_init_session()
    api.add_attribute_models(attribute_models)

    coordinator = GizwitsDataUpdateCoordinator(hass, api, entry)
    await coordinator.fetch_initial_device_list()

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        await api.async_close_session()
        LOGGER.error("Error setting up entry: %s", err)
        raise ConfigEntryNotReady from err

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "attribute_models": attribute_models,
    }

    # Resolve missing product key mappings after we have device data
    _resolve_missing_models(coordinator, attribute_models)

    # Auto-discover devices and update coordinator with discovered IPs
    if entry.data.get("auto_discover", True):
        await _auto_discover_devices(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (once, for the first entry)
    if len(hass.data[DOMAIN]) == 1:
        await async_setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, {})
        api: GizwitsApi | None = data.get("api")
        if api:
            await api.async_close_session()

        # Unregister services when last entry removed
        if not hass.data[DOMAIN]:
            await async_unload_services(hass)

    return unload_ok


async def _load_attribute_models(hass: HomeAssistant) -> dict:
    """Load attribute models from JSON files."""
    models_path = Path(hass.config.path("custom_components/jebao_aqua/models"))
    def _load_models() -> tuple[dict[str, dict], list[tuple[str, str]]]:
        attribute_models: dict[str, dict] = {}
        failed_files: list[tuple[str, str]] = []

        for model_file in models_path.glob("*.json"):
            try:
                with model_file.open(encoding="utf-8") as file:
                    model = json.load(file)
                attribute_models[model["product_key"]] = model
            except Exception as err:
                failed_files.append((model_file.name, repr(err)))

        return attribute_models, failed_files

    attribute_models, failed_files = await hass.async_add_executor_job(_load_models)

    for file_name, err in failed_files:
        LOGGER.error("Error loading model file %s: %s", file_name, err)

    LOGGER.debug("Loaded %d attribute models", len(attribute_models))
    return attribute_models


def _match_model_by_attrs(
    attribute_models: dict, cloud_product_key: str, device_attr_names: set[str]
) -> dict | None:
    """Match a cloud device to an APK model by attribute name overlap.

    Cloud product keys often differ from APK-bundled keys.
    We find the model whose attributes best match the device's actual data.
    """
    if not device_attr_names:
        return None

    best_match: dict | None = None
    best_score = 0

    for _pk, model in attribute_models.items():
        # Get model attrs from either format
        attrs = model.get("attrs", [])
        if not attrs:
            entities = model.get("entities", [])
            if entities:
                attrs = entities[0].get("attrs", [])

        model_attr_names = {a["name"] for a in attrs}
        overlap = len(device_attr_names & model_attr_names)

        if overlap > best_score:
            best_score = overlap
            best_match = model

    if best_match and best_score >= 3:  # At least 3 matching attrs
        LOGGER.info(
            "Matched cloud pk %s to model '%s' (%d/%d attrs overlap)",
            cloud_product_key[:12],
            best_match.get("name", "?"),
            best_score,
            len(device_attr_names),
        )
        return best_match

    LOGGER.warning(
        "No model match for cloud pk %s (best overlap: %d)",
        cloud_product_key[:12],
        best_score,
    )
    return None


def _resolve_missing_models(
    coordinator: GizwitsDataUpdateCoordinator,
    attribute_models: dict,
) -> None:
    """Resolve cloud product keys to APK models by attribute matching.

    Cloud-assigned product keys often differ from APK-bundled ones.
    After the first data fetch, we have the actual attribute names from
    each device and can match them to APK models.
    """
    for device in coordinator.device_inventory:
        pk = device.get("product_key")
        if not pk or pk in attribute_models:
            continue

        device_id = device.get("did")
        if not device_id:
            continue

        # Get actual attribute names from coordinator data
        device_data = coordinator.device_data.get(device_id, {})
        attr_dict = device_data.get("attr", {})
        if not attr_dict:
            LOGGER.debug(
                "No cloud data yet for %s, skipping model resolution", device_id
            )
            continue

        attr_names = set(attr_dict.keys())
        matched_model = _match_model_by_attrs(attribute_models, pk, attr_names)

        if matched_model:
            # Register the cloud product key as an alias
            attribute_models[pk] = matched_model
            LOGGER.info(
                "Resolved device %s (pk=%s) -> model '%s'",
                device.get("dev_alias", device_id),
                pk[:12],
                matched_model.get("name", "?"),
            )


async def _auto_discover_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: GizwitsDataUpdateCoordinator,
) -> None:
    """Auto-discover devices on the LAN and update coordinator."""
    try:
        discovered_devices = await discover_devices()
    except Exception:
        LOGGER.debug("Device discovery failed, continuing without")
        return

    if not discovered_devices:
        return

    hass.data[DOMAIN][entry.entry_id]["discovered_devices"] = discovered_devices
    LOGGER.debug("Discovered %d devices during setup", len(discovered_devices))

    for device in coordinator.device_inventory:
        device_id = device.get("did")
        if device_id and device_id in discovered_devices:
            device["lan_ip"] = discovered_devices[device_id]
            LOGGER.debug(
                "Updated device %s with discovered IP %s",
                device_id,
                discovered_devices[device_id],
            )


class GizwitsDataUpdateCoordinator(DataUpdateCoordinator):
    """Data update coordinator for Jebao devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: GizwitsApi,
        entry: ConfigEntry,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api
        self.entry = entry
        self.device_inventory: list[dict] = []
        self.device_data: dict[str, dict] = {}
        self._device_update_locks: dict[str, asyncio.Lock] = {}
        self._lan_failure_counts: dict[str, int] = {}

    async def fetch_initial_device_list(self) -> None:
        """Fetch the initial list of devices and add LAN IPs from config."""
        try:
            response = await self.api.get_devices()
            if not response or "devices" not in response:
                LOGGER.error("No 'devices' key in API response")
                return

            self.device_inventory = response["devices"]

            # Merge LAN IPs from ConfigEntry
            config_devices = self.entry.data.get("devices", [])
            for device in self.device_inventory:
                device_id = device.get("did")
                matching = next(
                    (d for d in config_devices if d.get("did") == device_id),
                    None,
                )
                if matching:
                    device["lan_ip"] = matching.get("lan_ip")

            LOGGER.debug("Fetched %d devices from cloud", len(self.device_inventory))
        except Exception:
            LOGGER.exception("Error fetching initial device list")

    async def _get_device_data(self, device_id: str) -> dict | None:
        """Get device data with LAN-first, cloud-fallback strategy."""
        if device_id not in self._device_update_locks:
            self._device_update_locks[device_id] = asyncio.Lock()

        async with self._device_update_locks[device_id]:
            device_info = next(
                (d for d in self.device_inventory if d["did"] == device_id),
                None,
            )

            # Try LAN first if we have an IP and haven't exceeded failure threshold
            lan_ip = device_info.get("lan_ip") if device_info else None
            lan_failures = self._lan_failure_counts.get(device_id, 0)

            if lan_ip and lan_failures < MAX_LAN_FAILURES:
                try:
                    data = await self.api.get_local_device_data(
                        lan_ip,
                        device_info["product_key"],
                        device_id,
                    )
                    if data:
                        self._lan_failure_counts[device_id] = 0
                        return data
                except Exception:
                    self._lan_failure_counts[device_id] = lan_failures + 1
                    LOGGER.debug(
                        "LAN poll failed for %s (%d/%d), falling back to cloud",
                        device_id,
                        lan_failures + 1,
                        MAX_LAN_FAILURES,
                    )

            # Cloud fallback
            try:
                data = await self.api.get_device_data(device_id)
                if data:
                    # Reset LAN failure count on successful cloud poll
                    # so we retry LAN next cycle
                    if lan_failures >= MAX_LAN_FAILURES:
                        self._lan_failure_counts[device_id] = 0
                        LOGGER.debug(
                            "Cloud poll succeeded for %s, will retry LAN",
                            device_id,
                        )
                    return data
            except Exception:
                LOGGER.debug("Cloud poll also failed for %s", device_id)

            return None

    async def _async_update_data(self) -> dict[str, dict]:
        """Fetch the latest status for each device."""
        new_data: dict[str, dict] = {}

        async def _update_single(device_id: str) -> tuple[str | None, dict | None]:
            try:
                device_data = await self._get_device_data(device_id)
                if device_data and isinstance(device_data.get("attr"), dict):
                    return device_id, device_data
                if device_id in self.device_data:
                    LOGGER.debug("Using cached data for device %s", device_id)
                    return device_id, self.device_data[device_id]
                LOGGER.warning("No valid data for device %s", device_id)
                return None, None
            except Exception:
                LOGGER.exception("Error updating device %s", device_id)
                if device_id in self.device_data:
                    return device_id, self.device_data[device_id]
                return None, None

        tasks = [
            _update_single(device["did"])
            for device in self.device_inventory
            if device.get("did")
        ]

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=False)
            for device_id, data in results:
                if device_id and data:
                    new_data[device_id] = data

        if not new_data:
            if self.device_data:
                LOGGER.warning("No fresh data, using last known good data")
                return self.device_data
            raise UpdateFailed("Failed to update any devices")

        self.device_data = new_data
        return new_data

    async def async_config_entry_first_refresh(self) -> None:
        """Perform first refresh and validate data."""
        await self._async_refresh(log_failures=True)
        if not any(is_device_data_valid(d) for d in self.device_data.values()):
            raise ConfigEntryNotReady("No valid device data received during setup")
