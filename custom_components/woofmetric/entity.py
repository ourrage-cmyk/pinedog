"""Shared base for Woofmetric entities."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WoofmetricCoordinator


class WoofmetricEntity(CoordinatorEntity[WoofmetricCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: WoofmetricCoordinator, entry: ConfigEntry, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["address"])},
            "name": "Woofmetric collar",
            "manufacturer": "Pine64",
            "model": "PineTime (dog firmware)",
        }
