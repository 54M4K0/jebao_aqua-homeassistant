"""Binary sensor platform for Jebao Aqua."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up Jebao binary sensor entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    attribute_models = data["attribute_models"]

    entities: list[JebaoPumpFaultSensor] = []

    for device in coordinator.device_inventory:
        product_key = device.get("product_key")
        model = attribute_models.get(product_key) if product_key else None
        if not model:
            continue

        for attr in get_model_attrs(model):
            if attr.get("type") == "fault" and attr.get("data_type") == "bool":
                entities.append(JebaoPumpFaultSensor(coordinator, device, attr))

    if entities:
        async_add_entities(entities)
        LOGGER.debug("Added %d binary sensor entities", len(entities))


class JebaoPumpFaultSensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Jebao Pump fault indicator."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, device: dict, attribute: dict) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        self._device_id = device["did"]
        self._attr_name_key = attribute["name"]

        self._attr_name = make_entity_name(
            attribute.get("display_name", attribute["name"])
        )
        self._attr_unique_id = make_unique_id(self._device_id, self._attr_name_key)
        self.entity_id = make_entity_id(
            "binary_sensor", self._device_id, self._attr_name_key
        )

        # Hide raw firmware attrs managed by smart dosing
        if is_hidden_attr(self._attr_name_key):
            self._attr_entity_registry_enabled_default = False

    @property
    def device_info(self):
        """Return device info."""
        return get_device_info(self._device)

    @property
    def is_on(self) -> bool | None:
        """Return True if fault is detected."""
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

    @property
    def translation_key(self) -> str:
        """Return translation key."""
        return self._attr_name_key.lower()
