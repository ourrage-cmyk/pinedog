"""Entities: steps, activity, battery, connection state and last seen."""

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
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import InfiniTimeCoordinator, InfiniTimeData

SENSORS = (
    SensorEntityDescription(
        key="steps_today",
        translation_key="steps_today",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:shoe-print",
    ),
    SensorEntityDescription(
        key="steps_last_hour",
        translation_key="steps_last_hour",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:shoe-print",
    ),
    SensorEntityDescription(
        key="active_intervals_today",
        translation_key="active_intervals_today",
        native_unit_of_measurement="intervals",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:run",
    ),
    SensorEntityDescription(
        key="steps_vs_baseline_pct",
        translation_key="steps_vs_baseline",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line",
    ),
    SensorEntityDescription(
        key="battery_pct",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="activity",
        translation_key="activity",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:vibrate",
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
            "name": entry.title or "InfiniTime",
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
