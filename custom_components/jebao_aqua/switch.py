"""Switch platform for Jebao Aqua."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .helpers import (
    get_device_info,
    get_model_attrs,
    is_hidden_attr,
    make_entity_id,
    make_entity_name,
    make_unique_id,
    safe_get_attr_value,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Jebao switch entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    attribute_models = data["attribute_models"]

    entities: list[JebaoPumpSwitch] = []

    for device in coordinator.device_inventory:
        product_key = device.get("product_key")
        model = attribute_models.get(product_key) if product_key else None
        if not model:
            continue

        for attr in get_model_attrs(model):
            if is_hidden_attr(attr.get("name", "")):
                continue
            if (
                attr.get("type") == "status_writable"
                and attr.get("data_type") == "bool"
            ):
                entities.append(JebaoPumpSwitch(coordinator, device, attr))

    if entities:
        async_add_entities(entities)
        LOGGER.debug("Added %d switch entities", len(entities))


class JebaoPumpSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Jebao Pump boolean switch."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device: dict, attribute: dict) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        self._device_id = device["did"]
        self._attr_name_key = attribute["name"]

        self._attr_name = make_entity_name(
            attribute.get("display_name", attribute["name"])
        )
        self._attr_unique_id = make_unique_id(self._device_id, self._attr_name_key)
        self.entity_id = make_entity_id("switch", self._device_id, self._attr_name_key)

        # Hide raw firmware attrs managed by smart dosing
        if is_hidden_attr(self._attr_name_key):
            self._attr_entity_registry_enabled_default = False

    @property
    def device_info(self):
        """Return device info."""
        return get_device_info(self._device)

    @property
    def is_on(self) -> bool | None:
        """Return the on/off state."""
        value = safe_get_attr_value(
            self.coordinator.data, self._device_id, self._attr_name_key
        )
        return bool(value) if value is not None else None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self._device_id in (
            self.coordinator.data or {}
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.coordinator.api.control_device(
            self._device_id, {self._attr_name_key: True}
        )
        # Optimistic update — immediately reflect state
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.coordinator.api.control_device(
            self._device_id, {self._attr_name_key: False}
        )
        await self.coordinator.async_request_refresh()

    @property
    def translation_key(self) -> str:
        """Return translation key."""
        return self._attr_name_key.lower()
