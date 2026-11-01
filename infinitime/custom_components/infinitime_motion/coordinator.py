"""Polls the watch on a timer, keeps step history, and feeds the sensors."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import logging
import time

from bleak.exc import BleakError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .ble import async_read_watch
from .motion import StepTracker, activity_index

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
POLL_INTERVAL = timedelta(minutes=15)
SAMPLE_SECONDS = 5.0  # a short motion window per poll; keeps the radio time low


@dataclass
class InfiniTimeData:
    connected: bool
    steps_today: int | None
    steps_last_hour: int | None
    active_intervals_today: int | None
    steps_vs_baseline_pct: float | None
    battery_pct: int | None
    activity: float | None
    last_seen: datetime | None


class InfiniTimeCoordinator(DataUpdateCoordinator[InfiniTimeData]):
    def __init__(self, hass: HomeAssistant, address: str, entry_id: str) -> None:
        super().__init__(hass, _LOGGER, name="InfiniTime", update_interval=POLL_INTERVAL)
        self.address = address
        self._store: Store[dict] = Store(hass, STORE_VERSION, f"infinitime_motion.{entry_id}")
        self.tracker = StepTracker()
        self._last_seen: datetime | None = None

    async def async_load(self) -> None:
        raw = await self._store.async_load() or {}
        self.tracker = StepTracker.from_dict(raw.get("tracker"))
        last = raw.get("last_seen")
        self._last_seen = datetime.fromisoformat(last) if last else None

    async def _async_update_data(self) -> InfiniTimeData:
        try:
            reading = await async_read_watch(self.hass, self.address, SAMPLE_SECONDS)
        except (BleakError, ConnectionError, HomeAssistantError, TimeoutError) as err:
            if self.data is None:
                # First poll failed: let HA retry the setup instead of showing empty sensors.
                raise UpdateFailed(f"InfiniTime not reachable: {err}") from err
            _LOGGER.debug("InfiniTime not reachable: %s", err)
            return replace(self.data, connected=False)

        now = dt_util.utcnow()
        today = dt_util.as_local(now).date()
        self.tracker.record(reading.steps, today, int(time.time()))
        self._last_seen = now
        # Save before returning, so a restart does not count the same steps twice.
        await self._store.async_save(
            {"tracker": self.tracker.to_dict(), "last_seen": now.isoformat()}
        )

        return InfiniTimeData(
            connected=True,
            steps_today=self.tracker.steps_on(today),
            steps_last_hour=self.tracker.steps_last_hour(int(time.time())),
            active_intervals_today=self.tracker.active_intervals_on(today),
            steps_vs_baseline_pct=self.tracker.baseline_pct(today),
            battery_pct=reading.battery_pct,
            activity=activity_index(reading.motion_samples),
            last_seen=self._last_seen,
        )
