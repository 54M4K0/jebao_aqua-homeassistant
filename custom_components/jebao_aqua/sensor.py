"""Sensor platform for Jebao Aqua."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .helpers import (
    get_device_info,
    is_hidden_attr,
    make_entity_id,
    make_entity_name,
    make_unique_id,
    safe_get_attr_value,
)
from .services import decode_schedule_blob


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Jebao sensor entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    attribute_models = data["attribute_models"]

    entities: list[SensorEntity] = []

    for device in coordinator.device_inventory:
        device_id = device.get("did")
        product_key = device.get("product_key")

        if not device_id or not product_key:
            continue

        model = attribute_models.get(product_key)
        if not model:
            continue

        # Get attrs from either old or new format
        attrs = model.get("attrs", [])
        if not attrs:
            entities_list = model.get("entities", [])
            if entities_list:
                attrs = entities_list[0].get("attrs", [])

        for attr in attrs:
            attr_type = attr.get("type", "")
            data_type = attr.get("data_type", "")

            # Create sensor entities for read-only numeric/enum attributes
            if data_type in ("uint8", "enum") and attr_type == "status_readonly":
                entities.append(
                    JebaoPumpSensor(
                        coordinator=coordinator,
                        device=device,
                        attribute=attr,
                    )
                )

        # --- Device info sensors ---
        entities.append(JebaoDeviceClockSensor(coordinator, device))
        entities.append(JebaoFirmwareVersionSensor(coordinator, device))
        entities.append(JebaoOnlineStatusSensor(coordinator, device))

        # --- Dosing status sensors (only for active channels per channelTTL) ---
        device_data = (coordinator.data or {}).get(device_id, {})
        channel_count = int(device_data.get("channelTTL", 0)) or 8
        for ch in range(1, channel_count + 1):
            entities.append(JebaoDosingSensor(coordinator, device, ch))

    if entities:
        async_add_entities(entities)
        LOGGER.debug("Added %d sensor entities", len(entities))


class JebaoPumpSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Jebao pump read-only sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device: dict, attribute: dict) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        self._device_id = device["did"]
        self._attr_name_str = attribute["name"]

        self._attr_name = make_entity_name(
            attribute.get("display_name", attribute["name"])
        )
        self._attr_unique_id = make_unique_id(self._device_id, self._attr_name_str)
        self.entity_id = make_entity_id("sensor", self._device_id, self._attr_name_str)

        if attribute.get("data_type") == "uint8":
            self._attr_state_class = SensorStateClass.MEASUREMENT

        # Hide if managed by smart dosing
        if is_hidden_attr(self._attr_name_str):
            self._attr_entity_registry_enabled_default = False

    @property
    def device_info(self):
        """Return device info."""
        return get_device_info(self._device)

    @property
    def native_value(self):
        """Return the sensor value."""
        return safe_get_attr_value(
            self.coordinator.data, self._device_id, self._attr_name_str
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self._device_id in (
            self.coordinator.data or {}
        )


class JebaoDeviceClockSensor(CoordinatorEntity, SensorEntity):
    """Device clock decoded from YMDData + HMSData binary attrs."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._device = device
        self._device_id = device["did"]
        self._attr_name = "Last Sync"
        self._attr_unique_id = make_unique_id(self._device_id, "last_sync")
        self.entity_id = make_entity_id("sensor", self._device_id, "last_sync")

    @property
    def device_info(self):
        """Return device info."""
        return get_device_info(self._device)

    @property
    def native_value(self) -> str | None:
        """Decode YMDData + HMSData into readable datetime string."""
        ymd = safe_get_attr_value(self.coordinator.data, self._device_id, "YMDData")
        hms = safe_get_attr_value(self.coordinator.data, self._device_id, "HMSData")

        if not ymd or not hms:
            return None

        try:
            ymd_bytes = bytes.fromhex(str(ymd))
            hms_bytes = bytes.fromhex(str(hms))

            year = ymd_bytes[0] * 100 + ymd_bytes[1]
            month = ymd_bytes[2]
            day = ymd_bytes[3]
            hour = hms_bytes[1]
            minute = hms_bytes[2]
            second = hms_bytes[3]

            return (
                f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
            )
        except (ValueError, IndexError):
            return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self._device_id in (
            self.coordinator.data or {}
        )


class JebaoFirmwareVersionSensor(CoordinatorEntity, SensorEntity):
    """Firmware and WiFi module version sensor."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:chip"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._device = device
        self._device_id = device["did"]
        self._attr_name = "Firmware Version"
        self._attr_unique_id = make_unique_id(self._device_id, "firmware_version")
        self.entity_id = make_entity_id("sensor", self._device_id, "firmware_version")

    @property
    def device_info(self):
        """Return device info."""
        return get_device_info(self._device)

    @property
    def native_value(self) -> str | None:
        """Return firmware version from device binding data."""
        mcu = self._device.get("mcu_soft_version", "")
        wifi = self._device.get("wifi_soft_version", "")
        if mcu:
            return f"MCU: {mcu}, WiFi: {wifi}" if wifi else f"MCU: {mcu}"
        return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True  # Static data from device binding


class JebaoOnlineStatusSensor(CoordinatorEntity, SensorEntity):
    """Online status from device binding."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:cloud-check"

    def __init__(self, coordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._device = device
        self._device_id = device["did"]
        self._attr_name = "Cloud Status"
        self._attr_unique_id = make_unique_id(self._device_id, "cloud_status")
        self.entity_id = make_entity_id("sensor", self._device_id, "cloud_status")

    @property
    def device_info(self):
        """Return device info."""
        return get_device_info(self._device)

    @property
    def native_value(self) -> str:
        """Return online/offline status."""
        return "Online" if self._device.get("is_online") else "Offline"

    @property
    def icon(self) -> str:
        """Return icon based on status."""
        return (
            "mdi:cloud-check"
            if self._device.get("is_online")
            else "mdi:cloud-off-outline"
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True


class JebaoDosingSensor(CoordinatorEntity, SensorEntity):
    """Per-channel dosing status summary sensor."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:eyedropper"

    def __init__(self, coordinator, device: dict, channel: int) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._device = device
        self._device_id = device["did"]
        self._channel = channel
        self._attr_name = f"Dosing CH{channel}"
        self._attr_unique_id = make_unique_id(self._device_id, f"dosing_ch{channel}")
        self.entity_id = make_entity_id(
            "sensor", self._device_id, f"dosing_ch{channel}"
        )

    @property
    def device_info(self):
        """Return device info."""
        return get_device_info(self._device)

    @property
    def native_value(self) -> str:
        """Return dosing schedule summary."""
        timer_on = safe_get_attr_value(
            self.coordinator.data, self._device_id, f"Timer{self._channel}ON"
        )
        interval = safe_get_attr_value(
            self.coordinator.data, self._device_id, f"IntervalT{self._channel}"
        )
        hex_data = safe_get_attr_value(
            self.coordinator.data, self._device_id, f"CH{self._channel}SWTime"
        )

        if not timer_on:
            return "Disabled"

        if not hex_data:
            return "Enabled (no schedule)"

        try:
            slots = decode_schedule_blob(str(hex_data))
            if not slots:
                return "Enabled (empty)"

            total_ml = sum(s["volume_ml"] for s in slots)
            n_slots = len(slots)

            # Day interval description
            if interval and int(interval) > 0:
                day_desc = f"every {int(interval) + 1} days"
            else:
                day_desc = "daily"

            if n_slots == 1:
                return f"{total_ml}ml/day, 1x at {slots[0]['time']}, {day_desc}"
            return f"{total_ml}ml/day, {n_slots}×{total_ml // n_slots}ml, {day_desc}"
        except (ValueError, TypeError):
            return "Enabled"

    @property
    def extra_state_attributes(self) -> dict:
        """Return detailed schedule as attributes."""
        hex_data = safe_get_attr_value(
            self.coordinator.data, self._device_id, f"CH{self._channel}SWTime"
        )
        if not hex_data:
            return {}

        try:
            slots = decode_schedule_blob(str(hex_data))
            return {
                "total_ml": sum(s["volume_ml"] for s in slots),
                "active_slots": len(slots),
                "schedule": slots,
            }
        except (ValueError, TypeError):
            return {}

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self._device_id in (
            self.coordinator.data or {}
        )
