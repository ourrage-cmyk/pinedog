"""Sensors for active, sedentary and walking time, motion and baseline."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import FIRMWARE_STOCK
from .coordinator import WoofmetricCoordinator
from .entity import WoofmetricEntity

PINEDOG_ONLY = {"walking", "pending"}
BASELINE_OPTIONS = ["learning", "below", "normal", "above"]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WoofmetricCoordinator = entry.runtime_data.coordinator
    stock = entry.data.get("firmware") == FIRMWARE_STOCK
    entities = [
            WoofmetricMinutesSensor(coordinator, entry, "active", "Active time today", "active_minutes"),
            WoofmetricMinutesSensor(coordinator, entry, "sedentary", "Sedentary time today", "sedentary_minutes"),
            WoofmetricMinutesSensor(coordinator, entry, "walking", "Walking time today", "walking_minutes"),
            WoofmetricMotionSensor(coordinator, entry),
            WoofmetricWearSensor(coordinator, entry),
            WoofmetricBaselineSensor(coordinator, entry),
            WoofmetricBaselinePercentSensor(coordinator, entry),
            WoofmetricLongTermPercentSensor(coordinator, entry),
            WoofmetricLongTermDaysSensor(coordinator, entry),
            WoofmetricBaselineConfidenceSensor(coordinator, entry),
            WoofmetricLastSyncSensor(coordinator, entry),
            WoofmetricBatterySensor(coordinator, entry),
            WoofmetricPendingSensor(coordinator, entry),
            WoofmetricLastErrorSensor(coordinator, entry),
    ]
    # Stock firmware cannot tell walking from other activity, and has no record queue.
    async_add_entities(
        e for e in entities
        if not (stock and e.unique_id.removeprefix(f"{entry.entry_id}_") in PINEDOG_ONLY)
    )


class WoofmetricMinutesSensor(WoofmetricEntity, SensorEntity):
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


class WoofmetricMotionSensor(WoofmetricEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:run"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "motion", "Motion today")

    @property
    def native_value(self) -> int | None:
        today = self.coordinator.data.today
        return today.motion_counts if today else 0


class WoofmetricWearSensor(WoofmetricEntity, SensorEntity):
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:watch-variant"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "wear", "Wear time today")

    @property
    def native_value(self) -> int:
        today = self.coordinator.data.today
        return today.active_minutes + today.sedentary_minutes if today else 0


class WoofmetricBaselineSensor(WoofmetricEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = BASELINE_OPTIONS
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "baseline", "Activity vs baseline")

    @property
    def native_value(self) -> str:
        return self.coordinator.data.baseline.status

    @property
    def extra_state_attributes(self) -> dict:
        base = self.coordinator.data.baseline
        return {
            "expected_motion_counts": None if base.expected_counts is None else round(base.expected_counts),
            "days_learned": base.days_learned,
        }


class WoofmetricLongTermPercentSensor(WoofmetricEntity, SensorEntity):
    """Today against the long-term usual at the same hours of the week. Never resets."""

    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "longterm_percent", "Activity vs long-term usual")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.longterm_vs_usual_pct


class WoofmetricLongTermDaysSensor(WoofmetricEntity, SensorEntity):
    _attr_native_unit_of_measurement = "days"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:school"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "longterm_days", "Long-term days learned")

    @property
    def native_value(self) -> int:
        return self.coordinator.data.longterm_days


class WoofmetricBaselinePercentSensor(WoofmetricEntity, SensorEntity):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:percent"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "baseline_percent", "Activity vs 14-day usual")

    @property
    def native_value(self) -> int | None:
        percent = self.coordinator.data.baseline.percent
        return None if percent is None else round(percent)


class WoofmetricBaselineConfidenceSensor(WoofmetricEntity, SensorEntity):
    _attr_native_unit_of_measurement = "%"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:school"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "baseline_confidence", "Baseline confidence")

    @property
    def native_value(self) -> int:
        return round(100 * self.coordinator.data.baseline.confidence)


class WoofmetricLastSyncSensor(WoofmetricEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "last_sync", "Last sync")

    @property
    def native_value(self):
        return self.coordinator.data.last_sync


class WoofmetricBatterySensor(WoofmetricEntity, SensorEntity):
    """Charge level, shown as a reminder to put the collar on the charger."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "battery", "Battery")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.battery_pct


class WoofmetricPendingSensor(WoofmetricEntity, SensorEntity):
    """Records the watch still holds that Home Assistant has not stored yet."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:database-clock"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "pending", "Unsynced records")

    @property
    def native_value(self) -> int:
        return self.coordinator.data.pending


class WoofmetricLastErrorSensor(WoofmetricEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:bluetooth-off"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "last_error", "Last sync error")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.last_error
