"""Pinedog: dog activity from a PineTime collar, on custom firmware or stock InfiniTime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothScanningMode
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, FIRMWARE_PINEDOG, FIRMWARE_STOCK
from .coordinator import PinedogCoordinator
from .protocol import SERVICE_UUID
from .stock_coordinator import StockCoordinator

PLATFORMS = ["sensor", "binary_sensor", "button"]
SERVICE_SYNC_NOW = "sync_now"
SYNC_NOW_SCHEMA = vol.Schema({vol.Optional("entity_id"): cv.entity_ids})


@dataclass
class PinedogRuntime:
    coordinator: Union[PinedogCoordinator, StockCoordinator]


type PinedogConfigEntry = ConfigEntry[PinedogRuntime]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async def _handle_sync_now(call: ServiceCall) -> dict:
        entries = _entries_for_call(hass, call)
        collars = []
        for entry in entries:
            outcome = await entry.runtime_data.coordinator.async_sync_now()
            collars.append({"name": entry.data.get("dog_name") or entry.data["address"], **outcome})
        return {"collars": collars}

    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_NOW,
        _handle_sync_now,
        schema=SYNC_NOW_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True


def _entries_for_call(hass: HomeAssistant, call: ServiceCall) -> list[PinedogConfigEntry]:
    """The loaded custom-firmware collars the call names, or all of them when no target is given."""
    loaded = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        and entry.data.get("firmware", FIRMWARE_PINEDOG) == FIRMWARE_PINEDOG
    ]
    targets = call.data.get("entity_id")
    if not targets:
        return loaded
    registry = er.async_get(hass)
    wanted = {registry.async_get(entity_id).config_entry_id for entity_id in targets if registry.async_get(entity_id)}
    return [entry for entry in loaded if entry.entry_id in wanted]


async def async_setup_entry(hass: HomeAssistant, entry: PinedogConfigEntry) -> bool:
    address: str = entry.data["address"]
    if entry.data.get("firmware", FIRMWARE_PINEDOG) == FIRMWARE_STOCK:
        coordinator: Union[PinedogCoordinator, StockCoordinator] = StockCoordinator(
            hass, address, entry.entry_id
        )
        # Advertisements come many times a second; the coordinator's schedule gates them.
        matcher = {"address": address, "connectable": True}
    else:
        coordinator = PinedogCoordinator(hass, address, entry.entry_id)
        matcher = {"address": address, "service_uuid": SERVICE_UUID}

    await coordinator.async_load()
    entry.runtime_data = PinedogRuntime(coordinator)
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


async def async_unload_entry(hass: HomeAssistant, entry: PinedogConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
