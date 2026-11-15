"""Buttons per custom-firmware collar: Sync now, and Reset learning."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import FIRMWARE_PINEDOG
from .coordinator import PinedogCoordinator
from .entity import PinedogEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # Stock InfiniTime has no record queue to sync, so it gets no button.
    if entry.data.get("firmware", FIRMWARE_PINEDOG) != FIRMWARE_PINEDOG:
        return
    coordinator = entry.runtime_data.coordinator
    async_add_entities([PinedogSyncButton(coordinator, entry), PinedogResetLearningButton(coordinator, entry)])


class PinedogSyncButton(PinedogEntity, ButtonEntity):
    _attr_icon = "mdi:sync"

    def __init__(self, coordinator: PinedogCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "sync_now", "Sync now")

    async def async_press(self) -> None:
        outcome = await self.coordinator.async_sync_now()
        if outcome["result"] == "busy":
            raise HomeAssistantError("A sync is already running. Try again in a moment.")
        if outcome["result"] == "failed":
            raise HomeAssistantError(f"Sync failed at {outcome['stage']}: {outcome['detail']}")


class PinedogResetLearningButton(PinedogEntity, ButtonEntity):
    """Starts the dog's usual pattern again from now. Use after days of wrong or missing data."""

    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: PinedogCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "reset_learning", "Reset learning")

    async def async_press(self) -> None:
        await self.coordinator.async_reset_learning()
