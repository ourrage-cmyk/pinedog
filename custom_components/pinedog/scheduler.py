"""One scheduler for every Pinedog collar, so the radio goes to the one that needs it most.

The Pi has one Bluetooth adapter and a collar takes one connection at a time, so collars
sync in turns. Before 0.4.4 each collar ran its own timer and whichever fired first took
the adapter. The collar that had gone longest without a sync had no priority, and a
weaker collar lost out again and again. Now a single tick looks at all collars, and the
choice (schedule.pick_next) puts the stalest collar first.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .ble_lock import BLE_LOCK
from .schedule import pick_next

if TYPE_CHECKING:
    from .coordinator import PinedogCoordinator

_LOGGER = logging.getLogger(__name__)

# BlueZ forgets a collar about 30 s after its last advertisement. A short tick starts the
# connection within a few seconds of an advertisement, while the adapter still knows it.
TICK = timedelta(seconds=2)
DATA_KEY = "pinedog_scheduler"


class SyncScheduler:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._collars: dict[str, PinedogCoordinator] = {}
        self._running = False
        self._unsub = None

    @classmethod
    def get(cls, hass: HomeAssistant) -> SyncScheduler:
        scheduler = hass.data.get(DATA_KEY)
        if scheduler is None:
            scheduler = hass.data[DATA_KEY] = cls(hass)
        return scheduler

    @callback
    def register(self, coordinator: PinedogCoordinator):
        self._collars[coordinator.address] = coordinator
        if self._unsub is None:
            self._unsub = async_track_time_interval(self.hass, self._tick, TICK)

        @callback
        def _unregister() -> None:
            self._collars.pop(coordinator.address, None)
            if not self._collars and self._unsub is not None:
                self._unsub()
                self._unsub = None

        return _unregister

    @callback
    def kick(self) -> None:
        """Run the choice now, for example right after an advertisement."""
        self._tick()

    @callback
    def _tick(self, _now: datetime | None = None) -> None:
        now = dt_util.utcnow()
        for coordinator in self._collars.values():
            coordinator.observe(now)
        if self._running or BLE_LOCK.locked():
            return
        key = pick_next(now, [c.candidate(now) for c in self._collars.values()])
        if key is None:
            return
        coordinator = self._collars[key]
        _LOGGER.debug("Pinedog: syncing %s now, it is first in line", key)
        self._running = True
        self.hass.async_create_background_task(self._run(coordinator), f"pinedog sync {key}")

    async def _run(self, coordinator: PinedogCoordinator) -> None:
        try:
            await coordinator.async_scheduled_sync()
        finally:
            self._running = False
