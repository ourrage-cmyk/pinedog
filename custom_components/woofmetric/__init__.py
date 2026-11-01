"""Woofmetric: dog activity from a PineTime collar, on custom firmware or stock InfiniTime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothScanningMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import FIRMWARE_PINEDOG, FIRMWARE_STOCK
from .coordinator import WoofmetricCoordinator
from .protocol import SERVICE_UUID
from .stock_coordinator import StockCoordinator

PLATFORMS = ["sensor", "binary_sensor"]


@dataclass
class WoofmetricRuntime:
    coordinator: Union[WoofmetricCoordinator, StockCoordinator]


type WoofmetricConfigEntry = ConfigEntry[WoofmetricRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: WoofmetricConfigEntry) -> bool:
    address: str = entry.data["address"]
    if entry.data.get("firmware", FIRMWARE_PINEDOG) == FIRMWARE_STOCK:
        coordinator: Union[WoofmetricCoordinator, StockCoordinator] = StockCoordinator(
            hass, address, entry.entry_id
        )
        # Advertisements come many times a second; the coordinator's schedule gates them.
        matcher = {"address": address, "connectable": True}
    else:
        coordinator = WoofmetricCoordinator(hass, address, entry.entry_id)
        matcher = {"address": address, "service_uuid": SERVICE_UUID}

    await coordinator.async_load()
    entry.runtime_data = WoofmetricRuntime(coordinator)
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            coordinator.handle_advertisement,
            matcher,
            BluetoothScanningMode.PASSIVE,
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WoofmetricConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
