"""Services for Jebao Aqua integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv  # noqa: F401

from .const import DOMAIN, LOGGER

# CH*SWTime attribute names by channel index (1-based)
CH_SWTIME_ATTRS = {i: f"CH{i}SWTime" for i in range(1, 9)}
TIMER_ON_ATTRS = {i: f"Timer{i}ON" for i in range(1, 9)}
INTERVAL_ATTRS = {i: f"IntervalT{i}" for i in range(1, 9)}

SERVICE_SET_DOSING_SCHEDULE = "set_dosing_schedule"

SET_DOSING_SCHEMA = vol.Schema(
    {
        vol.Required("channel"): vol.All(int, vol.Range(min=1, max=8)),
        vol.Required("daily_ml"): vol.All(int, vol.Range(min=1, max=9999)),
        vol.Required("doses_per_day"): vol.All(int, vol.Range(min=1, max=24)),
        vol.Optional("day_interval", default=0): vol.All(int, vol.Range(min=0, max=30)),
        vol.Optional("enable", default=True): bool,
    }
)


def generate_schedule_blob(daily_ml: int, doses_per_day: int) -> str:
    """Generate a 96-byte CH*SWTime hex blob.

    Creates `doses_per_day` evenly-distributed time slots across 24 hours,
    each with a volume calculated to deliver `daily_ml` total.

    Format per slot: [hour, minute, vol_high, vol_low] (4 bytes)
    24 slots × 4 bytes = 96 bytes = 192 hex chars.
    """
    dose_base = daily_ml // doses_per_day
    remainder = daily_ml % doses_per_day

    # Calculate interval between doses
    hours_interval = 24 / doses_per_day

    slots = []
    for i in range(doses_per_day):
        # Evenly distribute across 24 hours
        total_minutes = int(i * hours_interval * 60)
        hour = total_minutes // 60
        minute = total_minutes % 60

        # Distribute remainder across first N slots
        vol = dose_base + (1 if i < remainder else 0)
        slots.append((hour, minute, vol))

    # Pad remaining slots with zeros
    for _ in range(24 - doses_per_day):
        slots.append((0, 0, 0))

    # Build hex string
    hex_out = ""
    for hour, minute, vol in slots:
        vol_hi = (vol >> 8) & 0xFF
        vol_lo = vol & 0xFF
        hex_out += f"{hour:02x}{minute:02x}{vol_hi:02x}{vol_lo:02x}"

    return hex_out


def decode_schedule_blob(hex_data: str) -> list[dict]:
    """Decode a CH*SWTime hex blob into readable slot list."""
    raw = bytes.fromhex(hex_data)
    slots = []
    for i in range(min(24, len(raw) // 4)):
        offset = i * 4
        hour = raw[offset]
        minute = raw[offset + 1]
        vol = (raw[offset + 2] << 8) | raw[offset + 3]
        if vol > 0:
            slots.append(
                {
                    "slot": i,
                    "time": f"{hour:02d}:{minute:02d}",
                    "volume_ml": vol,
                }
            )
    return slots


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up Jebao Aqua services."""

    async def handle_set_dosing_schedule(call: ServiceCall) -> None:
        """Handle the set_dosing_schedule service call."""
        channel = call.data["channel"]
        daily_ml = call.data["daily_ml"]
        doses_per_day = call.data["doses_per_day"]
        day_interval = call.data.get("day_interval", 0)
        enable = call.data.get("enable", True)

        # Validate: minimum dose is 1ml
        dose_per_slot = daily_ml / doses_per_day
        if dose_per_slot < 1:
            LOGGER.error(
                "Dose per slot (%.1f ml) is less than minimum 1ml. "
                "Reduce doses_per_day or increase daily_ml.",
                dose_per_slot,
            )
            return

        # Generate CH*SWTime blob
        schedule_hex = generate_schedule_blob(daily_ml, doses_per_day)

        LOGGER.info(
            "Setting CH%d dosing schedule: %dml/day in %d doses "
            "(%.1f ml/dose), day_interval=%d, enable=%s",
            channel,
            daily_ml,
            doses_per_day,
            dose_per_slot,
            day_interval,
            enable,
        )

        # Find the coordinator for the first available entry
        for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
            coordinator = entry_data.get("coordinator")
            if not coordinator or not coordinator.device_inventory:
                continue

            # Use first device (or could accept device_id as param)
            device = coordinator.device_inventory[0]
            device_id = device["did"]

            # Build control payload
            attrs = {
                CH_SWTIME_ATTRS[channel]: schedule_hex,
                TIMER_ON_ATTRS[channel]: 1 if enable else 0,
                INTERVAL_ATTRS[channel]: day_interval,
            }

            try:
                await coordinator.api.control_device(device_id, attrs)
                LOGGER.info(
                    "Dosing schedule sent to device %s, channel %d",
                    device_id,
                    channel,
                )
                await coordinator.async_request_refresh()
            except Exception:
                LOGGER.exception(
                    "Failed to send dosing schedule to device %s",
                    device_id,
                )
            return

        LOGGER.error("No Jebao device found to send dosing schedule")

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DOSING_SCHEDULE,
        handle_set_dosing_schedule,
        schema=SET_DOSING_SCHEMA,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload Jebao Aqua services."""
    hass.services.async_remove(DOMAIN, SERVICE_SET_DOSING_SCHEDULE)
