"""Pinedog: pulls motion records from a PineTime collar watch over Bluetooth."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothScanningMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import PinedogCoordinator
from .protocol import SERVICE_UUID

PLATFORMS = ["sensor"]


@dataclass
class PinedogRuntime:
    coordinator: PinedogCoordinator


type PinedogConfigEntry = ConfigEntry[PinedogRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: PinedogConfigEntry) -> bool:
    address: str = entry.data["address"]
    coordinator = PinedogCoordinator(hass, address, entry.entry_id)
    await coordinator.async_load()

    entry.runtime_data = PinedogRuntime(coordinator)
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            coordinator.handle_advertisement,
            {"address": address, "service_uuid": SERVICE_UUID},
            BluetoothScanningMode.PASSIVE,
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PinedogConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
