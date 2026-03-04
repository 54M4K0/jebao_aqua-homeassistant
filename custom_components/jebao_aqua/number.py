"""Number platform for Jebao Aqua."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
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
    """Set up Jebao number entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    attribute_models = data["attribute_models"]

    entities: list[JebaoPumpNumber] = []

    for device in coordinator.device_inventory:
        product_key = device.get("product_key")
        model = attribute_models.get(product_key) if product_key else None
        if not model:
            continue

        for attr in get_model_attrs(model):
            if (
                attr.get("type") == "status_writable"
                and attr.get("data_type") == "uint8"
            ):
                entities.append(JebaoPumpNumber(coordinator, device, attr))

    if entities:
        async_add_entities(entities)
        LOGGER.debug("Added %d number entities", len(entities))


class JebaoPumpNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Jebao Pump numeric control."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, device: dict, attribute: dict) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        self._device_id = device["did"]
        self._attr_name_key = attribute["name"]

        self._attr_name = make_entity_name(
            attribute.get("display_name", attribute["name"])
        )
        self._attr_unique_id = make_unique_id(self._device_id, self._attr_name_key)
        self.entity_id = make_entity_id("number", self._device_id, self._attr_name_key)

        # Hide raw firmware attrs managed by smart dosing
        if is_hidden_attr(self._attr_name_key):
            self._attr_entity_registry_enabled_default = False

        # Set min/max/step from uint_spec
        uint_spec = attribute.get("uint_spec", {})
        self._attr_native_min_value = float(uint_spec.get("min", 0))
        self._attr_native_max_value = float(uint_spec.get("max", 100))
        self._attr_native_step = float(uint_spec.get("ratio", 1))

    @property
    def device_info(self):
        """Return device info."""
        return get_device_info(self._device)

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        value = safe_get_attr_value(
            self.coordinator.data, self._device_id, self._attr_name_key
        )
        return float(value) if value is not None else None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self._device_id in (
            self.coordinator.data or {}
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set a new value."""
        # uint8 values are always integers
        int_value = int(value)
        await self.coordinator.api.control_device(
            self._device_id, {self._attr_name_key: int_value}
        )
        await self.coordinator.async_request_refresh()

    @property
    def translation_key(self) -> str:
        """Return translation key."""
        return self._attr_name_key.lower()
