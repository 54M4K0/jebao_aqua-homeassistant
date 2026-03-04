"""Select platform for Jebao Aqua."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
    translate_enum_value,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Jebao select entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    attribute_models = data["attribute_models"]

    entities: list[JebaoPumpSelect] = []

    for device in coordinator.device_inventory:
        product_key = device.get("product_key")
        model = attribute_models.get(product_key) if product_key else None
        if not model:
            continue

        for attr in get_model_attrs(model):
            if (
                attr.get("type") == "status_writable"
                and attr.get("data_type") == "enum"
            ):
                entities.append(JebaoPumpSelect(coordinator, device, attr))

    if entities:
        async_add_entities(entities)
        LOGGER.debug("Added %d select entities", len(entities))


class JebaoPumpSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Jebao Pump selectable option."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device: dict, attribute: dict) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        self._device_id = device["did"]
        self._attr_name_key = attribute["name"]

        self._attr_name = make_entity_name(
            attribute.get("display_name", attribute["name"])
        )
        self._attr_unique_id = make_unique_id(self._device_id, self._attr_name_key)
        self.entity_id = make_entity_id("select", self._device_id, self._attr_name_key)

        # Hide raw firmware attrs managed by smart dosing
        if is_hidden_attr(self._attr_name_key):
            self._attr_entity_registry_enabled_default = False

        # Enum options — translate CN to EN for display
        self._enum_values: list[str] = attribute.get("enum", [])
        self._translated_options = [translate_enum_value(v) for v in self._enum_values]
        # Reverse map: EN option -> CN firmware value
        self._option_to_firmware = dict(
            zip(self._translated_options, self._enum_values)
        )
        self._firmware_to_option = dict(
            zip(self._enum_values, self._translated_options)
        )
        self._attr_options = list(self._translated_options)

    @property
    def device_info(self):
        """Return device info."""
        return get_device_info(self._device)

    @property
    def current_option(self) -> str | None:
        """Return the current selected option (translated)."""
        value = safe_get_attr_value(
            self.coordinator.data, self._device_id, self._attr_name_key
        )
        if value is not None and value in self._firmware_to_option:
            return self._firmware_to_option[value]
        return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self._device_id in (
            self.coordinator.data or {}
        )

    async def async_select_option(self, option: str) -> None:
        """Handle option selection — translate EN back to CN for firmware."""
        firmware_value = self._option_to_firmware.get(option)
        if firmware_value is None:
            LOGGER.warning("Invalid option %s for %s", option, self._attr_name_key)
            return

        # Send the enum index as the value
        enum_index = self._enum_values.index(firmware_value)
        await self.coordinator.api.control_device(
            self._device_id, {self._attr_name_key: enum_index}
        )
        await self.coordinator.async_request_refresh()

    @property
    def translation_key(self) -> str:
        """Return translation key."""
        return self._attr_name_key.lower()
