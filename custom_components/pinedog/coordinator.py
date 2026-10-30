"""Keeps per-day totals and the sync cursor, and pulls from the watch when it is in range."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import logging

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .activity import Baseline, DailyTotals, compute_baseline, daily_totals
from .sync import async_pull_records

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
MIN_SYNC_INTERVAL = timedelta(minutes=30)
KEEP_DAYS = 90  # the baseline reads up to WINDOW_DAYS; keep a margin


@dataclass
class PinedogData:
    today: DailyTotals | None = None
    baseline: Baseline = field(default_factory=lambda: Baseline("learning", None, None, 0.0, 0))
    last_sync: datetime | None = None
    last_error: str | None = None
    dropped_unsynced: int = 0


@dataclass
class _State:
    last_acked_minute: int = -1
    days: dict[str, dict[str, int]] = field(default_factory=dict)


class PinedogCoordinator(DataUpdateCoordinator[PinedogData]):
    def __init__(self, hass: HomeAssistant, address: str, entry_id: str) -> None:
        super().__init__(hass, _LOGGER, name="Pinedog", update_interval=None)
        self.address = address
        self._store: Store[dict] = Store(hass, STORE_VERSION, f"pinedog.{entry_id}")
        self._state = _State()
        self._last_sync: datetime | None = None
        self._last_error: str | None = None
        self._dropped = 0

    async def async_load(self) -> None:
        raw = await self._store.async_load() or {}
        self._state = _State(
            last_acked_minute=raw.get("last_acked_minute", -1),
            days=raw.get("days", {}),
        )
        last = raw.get("last_sync")
        self._last_sync = datetime.fromisoformat(last) if last else None
        self.data = self._build()

    def _history(self) -> list[DailyTotals]:
        out = []
        for key, v in sorted(self._state.days.items()):
            out.append(
                DailyTotals(
                    date.fromisoformat(key),
                    v["active"],
                    v["sedentary"],
                    v["walking"],
                    v["motion"],
                )
            )
        return out

    def _build(self) -> PinedogData:
        history = self._history()
        today_key = dt_util.now().date()
        today = next((d for d in history if d.day == today_key), None)
        base = Baseline("waiting", None, None, 0.0, 0)
        if today is not None:
            base = compute_baseline(today, history)
        return PinedogData(
            today=today,
            baseline=base,
            last_sync=self._last_sync,
            last_error=self._last_error,
            dropped_unsynced=self._dropped,
        )

    async def _async_update_data(self) -> PinedogData:
        if self._last_sync and dt_util.utcnow() - self._last_sync < MIN_SYNC_INTERVAL:
            return self._build()
        try:
            await self._sync()
            self._last_error = None
        except Exception as err:  # noqa: BLE001 - keep sensors alive on any BLE error
            self._last_error = str(err)
            _LOGGER.debug("Pinedog sync failed: %s", err)
        return self._build()

    async def _sync(self) -> None:
        pairs = await async_pull_records(
            self.hass, self.address, self._state.last_acked_minute + 1
        )
        synced = [rec for rec, ok in pairs if ok]
        self._dropped += len(pairs) - len(synced)
        if pairs:
            self._state.last_acked_minute = max(rec.minute for rec, _ in pairs)
            tz = dt_util.get_default_time_zone()
            for day, totals in daily_totals(synced, tz).items():
                cur = self._state.days.setdefault(
                    day.isoformat(),
                    {"active": 0, "sedentary": 0, "walking": 0, "motion": 0},
                )
                cur["active"] += totals.active_minutes
                cur["sedentary"] += totals.sedentary_minutes
                cur["walking"] += totals.walking_minutes
                cur["motion"] += totals.motion_counts
            for key in sorted(self._state.days)[:-KEEP_DAYS]:
                del self._state.days[key]
        self._last_sync = dt_util.utcnow()
        await self._store.async_save(
            {
                "last_acked_minute": self._state.last_acked_minute,
                "days": self._state.days,
                "last_sync": self._last_sync.isoformat(),
            }
        )

    @callback
    def handle_advertisement(self, info: BluetoothServiceInfoBleak, change) -> None:
        """Start a sync when the watch is seen, at most once per interval."""
        if self._last_sync and dt_util.utcnow() - self._last_sync < MIN_SYNC_INTERVAL:
            return
        self.hass.async_create_task(self.async_request_refresh())
