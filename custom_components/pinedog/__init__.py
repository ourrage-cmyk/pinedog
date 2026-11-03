"""Pinedog: dog activity from a PineTime collar, on custom firmware or stock InfiniTime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothScanningMode, BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import FIRMWARE_PINEDOG, FIRMWARE_STOCK
from .firmware_kind import detected_firmware
from .coordinator import PinedogCoordinator
from .protocol import SERVICE_UUID
from .stock_coordinator import StockCoordinator

PLATFORMS = ["sensor", "binary_sensor"]


@dataclass
class PinedogRuntime:
    coordinator: Union[PinedogCoordinator, StockCoordinator]


type PinedogConfigEntry = ConfigEntry[PinedogRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: PinedogConfigEntry) -> bool:
    address: str = entry.data["address"]
    stored = entry.data.get("firmware", FIRMWARE_PINEDOG)
    last = bluetooth.async_last_service_info(hass, address, connectable=True)
    firmware = detected_firmware(stored, last.service_uuids if last else None)
    if firmware != stored:
        # The watch was re-flashed after this entry was made. Use the firmware it runs now.
        hass.config_entries.async_update_entry(entry, data={**entry.data, "firmware": firmware})
    if firmware == FIRMWARE_STOCK:
        coordinator: Union[PinedogCoordinator, StockCoordinator] = StockCoordinator(
            hass,
            address,
            entry.entry_id,
            on_pinedog=lambda: _switch_to_pinedog(hass, entry),
        )
        # Advertisements come many times a second; the coordinator's schedule gates them.
        matcher = {"address": address, "connectable": True}
    else:
        coordinator = PinedogCoordinator(hass, address, entry.entry_id)
        # Match by address, not by UUID: the UUID is in the scan response, which passive scans miss.
        matcher = {"address": address, "connectable": True}

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
    if firmware == FIRMWARE_STOCK:
        # The watch may be re-flashed while HA runs, or be out of range at startup.
        # Watch for the Pinedog service, and switch the entry as soon as it shows up.
        entry.async_on_unload(
            bluetooth.async_register_callback(
                hass,
                _upgrade_callback(hass, entry),
                {"address": address, "service_uuid": SERVICE_UUID},
                BluetoothScanningMode.PASSIVE,
            )
        )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _switch_to_pinedog(hass: HomeAssistant, entry: PinedogConfigEntry) -> None:
    """Store the Pinedog firmware on the entry once, then reload it on the Pinedog path."""
    if entry.data.get("firmware") == FIRMWARE_PINEDOG:
        return
    # Store the firmware first, so a second report does not reload again.
    hass.config_entries.async_update_entry(entry, data={**entry.data, "firmware": FIRMWARE_PINEDOG})
    hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))


def _upgrade_callback(hass: HomeAssistant, entry: PinedogConfigEntry):
    @callback
    def _on_advertisement(info: BluetoothServiceInfoBleak, change) -> None:
        stored = entry.data.get("firmware", FIRMWARE_PINEDOG)
        if detected_firmware(stored, info.service_uuids) == stored:
            return
        _switch_to_pinedog(hass, entry)

    return _on_advertisement
