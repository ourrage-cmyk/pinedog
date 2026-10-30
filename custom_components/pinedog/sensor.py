"""Sensors for active, sedentary and walking time, motion and baseline."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PinedogCoordinator

BASELINE_OPTIONS = ["learning", "waiting", "below", "normal", "above"]


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
            PinedogWearSensor(coordinator, entry),
            PinedogBaselineSensor(coordinator, entry),
            PinedogBaselinePercentSensor(coordinator, entry),
            PinedogBaselineConfidenceSensor(coordinator, entry),
            PinedogLastSyncSensor(coordinator, entry),
        ]
    )


class _Base(CoordinatorEntity[PinedogCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PinedogCoordinator, entry: ConfigEntry, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["address"])},
            "name": "Pinedog collar",
            "manufacturer": "Pine64",
            "model": "PineTime (dog firmware)",
        }


class PinedogMinutesSensor(_Base):
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.TOTAL

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


class PinedogMotionSensor(_Base):
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:run"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "motion", "Motion today")

    @property
    def native_value(self) -> int | None:
        today = self.coordinator.data.today
        return today.motion_counts if today else 0


class PinedogWearSensor(_Base):
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:watch-variant"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "wear", "Wear time today")

    @property
    def native_value(self) -> int:
        today = self.coordinator.data.today
        return today.active_minutes + today.sedentary_minutes if today else 0


class PinedogBaselineSensor(_Base):
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


class PinedogBaselinePercentSensor(_Base):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:percent"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "baseline_percent", "Activity vs baseline percent")

    @property
    def native_value(self) -> int | None:
        percent = self.coordinator.data.baseline.percent
        return None if percent is None else round(percent)


class PinedogBaselineConfidenceSensor(_Base):
    _attr_native_unit_of_measurement = "%"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:school"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "baseline_confidence", "Baseline confidence")

    @property
    def native_value(self) -> int:
        return round(100 * self.coordinator.data.baseline.confidence)


class PinedogLastSyncSensor(_Base):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "last_sync", "Last sync")

    @property
    def native_value(self):
        return self.coordinator.data.last_sync
