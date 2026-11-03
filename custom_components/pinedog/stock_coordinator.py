"""Stock InfiniTime collar: polls while in range, keeps the day log, feeds the same entities.

Exposes the same surface as PinedogCoordinator (data, async_load, handle_advertisement),
so the sensors and binary sensors do not need to know which firmware is running.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import time

from bleak.exc import BleakError
from homeassistant.core import HomeAssistant, callback
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .activity import Baseline, compute_baseline
from .coordinator import PinedogData
from .schedule import TURN_WINDOW, should_attempt, synced_recently
from .stock_ble import async_read_watch
from .stock_motion import DayLog, MAX_INTERVAL_S, activity_index
from .storage import STORE_VERSION, WoofStore

_LOGGER = logging.getLogger(__name__)

SHORT_TERM_DAYS = 14
SAMPLE_SECONDS = 20.0  # motion window per poll (was 60 s); the notify radio and accelerometer run for this long each poll
# Polls at most MAX_INTERVAL_S apart while the collar is in range, so every interval is credited.
SUCCESS_INTERVAL = timedelta(seconds=MAX_INTERVAL_S)
RETRY_INTERVAL = timedelta(minutes=2)
POLL_INTERVAL = timedelta(seconds=MAX_INTERVAL_S)


class StockCoordinator(DataUpdateCoordinator[PinedogData]):
    def __init__(self, hass: HomeAssistant, address: str, entry_id: str) -> None:
        super().__init__(hass, _LOGGER, name="Pinedog stock", update_interval=POLL_INTERVAL)
        self.address = address
        self._store = WoofStore(hass, STORE_VERSION, f"pinedog_stock.{entry_id}")
        self.log = DayLog()
        self._last_sync: datetime | None = None
        self._last_attempt: datetime | None = None
        self._last_error: str | None = None
        self._battery_pct: int | None = None
        self._busy = False

    async def async_load(self) -> None:
        raw = await self._store.async_load() or {}
        self.log = DayLog.from_dict(raw.get("log"))
        last = raw.get("last_sync")
        self._last_sync = datetime.fromisoformat(last) if last else None
        self.data = self._build()

    async def _async_update_data(self) -> PinedogData:
        if self._busy or synced_recently(dt_util.utcnow(), self._last_sync):
            # Another poll is running, or this collar synced inside its turn window.
            return self._build()
        self._busy = True
        self._last_attempt = dt_util.utcnow()
        try:
            reading = await async_read_watch(self.hass, self.address, SAMPLE_SECONDS)
        except Exception as err:  # noqa: BLE001 - keep entities alive on any BLE error
            self._last_error = str(err) or type(err).__name__
            _LOGGER.debug("Collar not reachable, will retry: %s", self._last_error)
            return self._build()
        finally:
            self._busy = False

        self._last_error = None
        now_utc = dt_util.utcnow()
        local = dt_util.as_local(now_utc).replace(tzinfo=None)
        if reading.battery_pct is not None:
            self._battery_pct = reading.battery_pct
        self.log.add_poll(int(time.time()), activity_index(reading.motion_samples), local)
        self._last_sync = now_utc
        # Save before returning, so a restart does not double count an interval.
        await self._store.async_save(
            {"log": self.log.to_dict(), "last_sync": now_utc.isoformat()}
        )
        return self._build()

    def _build(self) -> PinedogData:
        history = self.log.daily_totals()
        today_key = dt_util.now().date()
        today = next((d for d in history if d.day == today_key), None)
        base = Baseline("waiting", None, None, 0.0, 0)
        if today is not None:
            recent = [d for d in history if (today_key - d.day).days <= SHORT_TERM_DAYS]
            base = compute_baseline(today, recent)
        now_local = dt_util.as_local(dt_util.utcnow()).replace(tzinfo=None)
        return PinedogData(
            today=today,
            baseline=base,
            last_sync=self._last_sync,
            last_error=self._last_error,
            battery_pct=self._battery_pct,
            charging=False,  # not exposed by stock InfiniTime over BLE
            power_present=False,
            pending=0,
            dropped_corrupt=0,
            dropped_unplaced=0,
            in_range=self._last_error is None and self._last_attempt is not None,
            longterm_vs_usual_pct=self.log.longterm.comparison(now_local),
            longterm_days=self.log.longterm.days_learned,
        )

    @callback
    def handle_advertisement(self, info: BluetoothServiceInfoBleak, change) -> None:
        """Poll when the collar advertises, at most once per SUCCESS_INTERVAL.

        Advertisements arrive many times a second, so the schedule gate matters.
        """
        if self._busy or synced_recently(dt_util.utcnow(), self._last_sync, TURN_WINDOW):
            return
        if not should_attempt(
            dt_util.utcnow(),
            self._last_attempt,
            self._last_error is not None,
            SUCCESS_INTERVAL,
            RETRY_INTERVAL,
        ):
            return
        self.hass.async_create_task(self.async_request_refresh())
