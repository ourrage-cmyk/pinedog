"""Charging and low-battery state from the watch's status."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import FIRMWARE_STOCK
from .entity import WoofmetricEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    if entry.data.get("firmware") == FIRMWARE_STOCK:
        # Stock firmware does not report charging, so only the low battery and range sensors apply.
        async_add_entities([WoofmetricLowBatterySensor(coordinator, entry), WoofmetricInRangeSensor(coordinator, entry)])
        return
    async_add_entities(
        [
            WoofmetricChargingSensor(coordinator, entry),
            WoofmetricLowBatterySensor(coordinator, entry),
        ]
    )


class WoofmetricChargingSensor(WoofmetricEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "charging", "Charging")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.charging


class WoofmetricLowBatterySensor(WoofmetricEntity, BinarySensorEntity):
    """On when the battery is at or below the low threshold and not charging."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "low_battery", "Charge soon")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.low_battery


class WoofmetricInRangeSensor(WoofmetricEntity, BinarySensorEntity):
    """Stock firmware only: on when the last poll reached the collar."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "in_range", "In range")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.in_range
