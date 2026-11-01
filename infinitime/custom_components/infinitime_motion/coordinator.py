"""Polls the watch on a timer, keeps the dog's day log, and feeds the entities."""

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
from .motion import (
    LESS_THAN_USUAL_PCT,
    MORE_THAN_USUAL_PCT,
    DayLog,
    activity_index,
)

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
POLL_INTERVAL = timedelta(minutes=5)
SAMPLE_SECONDS = 60.0  # motion window per poll; stands for the time since the last poll


@dataclass
class InfiniTimeData:
    connected: bool
    active_minutes_today: float | None
    sedentary_minutes_today: float | None
    activity_score_today: float | None
    activity_vs_usual_pct: float | None
    usual_status: str
    learning_days: int
    battery_pct: int | None
    last_seen: datetime | None


class InfiniTimeCoordinator(DataUpdateCoordinator[InfiniTimeData]):
    def __init__(self, hass: HomeAssistant, address: str, entry_id: str) -> None:
        super().__init__(hass, _LOGGER, name="InfiniTime", update_interval=POLL_INTERVAL)
        self.address = address
        self._store: Store[dict] = Store(hass, STORE_VERSION, f"infinitime_motion.{entry_id}")
        self.log = DayLog()
        self._last_seen: datetime | None = None
        self._battery: int | None = None

    async def async_load(self) -> None:
        raw = await self._store.async_load() or {}
        self.log = DayLog.from_dict(raw.get("log"))
        last = raw.get("last_seen")
        self._last_seen = datetime.fromisoformat(last) if last else None

    async def _async_update_data(self) -> InfiniTimeData:
        try:
            reading = await async_read_watch(self.hass, self.address, SAMPLE_SECONDS)
        except (BleakError, ConnectionError, HomeAssistantError, TimeoutError) as err:
            if self.data is None:
                # First poll failed: let HA retry setup instead of showing empty entities.
                raise UpdateFailed(f"InfiniTime not reachable: {err}") from err
            _LOGGER.debug("InfiniTime not reachable: %s", err)
            return replace(self.data, connected=False)

        now_utc = dt_util.utcnow()
        local = dt_util.as_local(now_utc).replace(tzinfo=None)
        if reading.battery_pct is not None:
            self._battery = reading.battery_pct
        self.log.add_poll(int(time.time()), activity_index(reading.motion_samples), local)
        self._last_seen = now_utc
        # Save before returning, so a restart does not double count an interval.
        await self._store.async_save(
            {"log": self.log.to_dict(), "last_seen": now_utc.isoformat()}
        )
        return self._build(local, connected=True)

    def _build(self, local: datetime, connected: bool) -> InfiniTimeData:
        today = local.date()
        pct, usual_days = self.log.usual_comparison(local)
        if pct is None:
            status = "learning"
        elif pct > MORE_THAN_USUAL_PCT:
            status = "more"
        elif pct < LESS_THAN_USUAL_PCT:
            status = "less"
        else:
            status = "typical"
        day = self.log.today(today)
        return InfiniTimeData(
            connected=connected,
            active_minutes_today=round(day["active_s"] / 60, 1),
            sedentary_minutes_today=round(day["sedentary_s"] / 60, 1),
            activity_score_today=self.log.score_today(today),
            activity_vs_usual_pct=pct,
            usual_status=status,
            learning_days=usual_days,
            battery_pct=self._battery,
            last_seen=self._last_seen,
        )
