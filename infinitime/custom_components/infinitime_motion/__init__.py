"""InfiniTime Motion: reads steps, battery and motion from a stock InfiniTime watch."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import InfiniTimeCoordinator

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = InfiniTimeCoordinator(hass, entry.data["address"], entry.entry_id)
    await coordinator.async_load()
    entry.runtime_data = coordinator
    # Polling only. A passive advert callback would fire on every advertisement.
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
