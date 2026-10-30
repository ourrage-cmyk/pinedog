"""Charging and low-battery state from the watch's status."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PinedogEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            PinedogChargingSensor(coordinator, entry),
            PinedogLowBatterySensor(coordinator, entry),
        ]
    )


class PinedogChargingSensor(PinedogEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "charging", "Charging")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.charging


class PinedogLowBatterySensor(PinedogEntity, BinarySensorEntity):
    """On when the battery is at or below the low threshold and not charging."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "low_battery", "Charge soon")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.low_battery
