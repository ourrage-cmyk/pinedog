"""Entities: active and sedentary time, activity score, usual comparison, battery, connection."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import InfiniTimeCoordinator, InfiniTimeData

SENSORS = (
    SensorEntityDescription(
        key="active_minutes_today",
        translation_key="active_minutes_today",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:run",
    ),
    SensorEntityDescription(
        key="sedentary_minutes_today",
        translation_key="sedentary_minutes_today",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:sleep",
    ),
    SensorEntityDescription(
        key="activity_score_today",
        translation_key="activity_score_today",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:chart-bar",
    ),
    SensorEntityDescription(
        key="activity_vs_usual_pct",
        translation_key="activity_vs_usual",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line",
    ),
    SensorEntityDescription(
        key="usual_status",
        translation_key="usual_status",
        icon="mdi:scale-balance",
    ),
    SensorEntityDescription(
        key="learning_days",
        translation_key="learning_days",
        native_unit_of_measurement="days",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:school",
    ),
    SensorEntityDescription(
        key="battery_pct",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)

BINARY_SENSORS = (
    BinarySensorEntityDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: InfiniTimeCoordinator = entry.runtime_data
    async_add_entities(
        [InfiniTimeSensor(coordinator, entry, d) for d in SENSORS]
        + [InfiniTimeBinarySensor(coordinator, entry, d) for d in BINARY_SENSORS]
    )


class _InfiniTimeEntity(CoordinatorEntity[InfiniTimeCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: InfiniTimeCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title or "Dog collar",
            "manufacturer": "PINETIME",
            "model": "InfiniTime (stock firmware)",
        }

    def _value(self, key: str):
        data: InfiniTimeData | None = self.coordinator.data
        return None if data is None else getattr(data, key)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class InfiniTimeSensor(_InfiniTimeEntity, SensorEntity):
    def __init__(self, coordinator, entry, description: SensorEntityDescription) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self._value(self.entity_description.key)


class InfiniTimeBinarySensor(_InfiniTimeEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry, description: BinarySensorEntityDescription) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self._value(self.entity_description.key)
