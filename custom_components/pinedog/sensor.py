"""Sensors for active, sedentary and walking time, motion and baseline."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PinedogCoordinator
from .entity import PinedogEntity

BASELINE_OPTIONS = ["learning", "below", "normal", "above"]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PinedogCoordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            PinedogMinutesSensor(coordinator, entry, "active", "Active time today", "active_minutes"),
            PinedogMinutesSensor(coordinator, entry, "sedentary", "Sedentary time today", "sedentary_minutes"),
            PinedogMinutesSensor(coordinator, entry, "walking", "Walking time today", "walking_minutes"),
            PinedogMotionSensor(coordinator, entry),
            PinedogBaselineSensor(coordinator, entry),
            PinedogLastSyncSensor(coordinator, entry),
            PinedogBatterySensor(coordinator, entry),
            PinedogPendingSensor(coordinator, entry),
            PinedogLastErrorSensor(coordinator, entry),
        ]
    )


class PinedogMinutesSensor(PinedogEntity, SensorEntity):
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, key, name, field) -> None:
        super().__init__(coordinator, entry, key, name)
        self._field = field
        self._attr_icon = "mdi:paw"

    @property
    def native_value(self) -> int | None:
        today = self.coordinator.data.today
        if today is None:
            return 0
        return getattr(today, self._field)


class PinedogMotionSensor(PinedogEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:run"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "motion", "Motion today")

    @property
    def native_value(self) -> int | None:
        today = self.coordinator.data.today
        return today.motion_counts if today else 0


class PinedogBaselineSensor(PinedogEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = BASELINE_OPTIONS
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "baseline", "Activity vs baseline")

    @property
    def native_value(self) -> str:
        return self.coordinator.data.baseline


class PinedogLastSyncSensor(PinedogEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "last_sync", "Last sync")

    @property
    def native_value(self):
        return self.coordinator.data.last_sync


class PinedogBatterySensor(PinedogEntity, SensorEntity):
    """Charge level, shown as a reminder to put the collar on the charger."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "battery", "Battery")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.battery_pct


class PinedogPendingSensor(PinedogEntity, SensorEntity):
    """Records the watch still holds that Home Assistant has not stored yet."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:database-clock"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "pending", "Unsynced records")

    @property
    def native_value(self) -> int:
        return self.coordinator.data.pending


class PinedogLastErrorSensor(PinedogEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:bluetooth-off"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "last_error", "Last sync error")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.last_error
