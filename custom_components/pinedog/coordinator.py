"""Keeps per-day totals and the sync cursor, and pulls from the watch when it is in range."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import logging

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .activity import DailyTotals, baseline_status, daily_totals
from .schedule import should_attempt
from .sync import async_pull_records
from .transfer import Pairs

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
KEEP_DAYS = 60


@dataclass
class PinedogData:
    today: DailyTotals | None = None
    baseline: str = "learning"
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
        self._last_attempt: datetime | None = None
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
        self._last_attempt = self._last_sync
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
        base = "learning"
        if today is not None:
            base = baseline_status(today, history)
        return PinedogData(
            today=today,
            baseline=base,
            last_sync=self._last_sync,
            last_error=self._last_error,
            dropped_unsynced=self._dropped,
        )

    async def _async_update_data(self) -> PinedogData:
        if not self._attempt_allowed():
            return self._build()
        self._last_attempt = dt_util.utcnow()
        try:
            await self._sync()
            self._last_error = None
        except Exception as err:  # noqa: BLE001 - keep sensors alive on any BLE error
            self._last_error = str(err)
            _LOGGER.debug("Pinedog sync failed: %s", err)
        return self._build()

    def _attempt_allowed(self) -> bool:
        return should_attempt(
            dt_util.utcnow(), self._last_attempt, self._last_error is not None
        )

    async def _sync(self) -> None:
        await async_pull_records(
            self.hass, self.address, self._state.last_acked_minute + 1, self._persist
        )

    async def _persist(self, pairs: Pairs) -> None:
        """Store records before the watch is acked. Runs once per transfer.

        The watch may resend records we already counted, for example when an
        ack was lost. The cursor drops those, so totals are never double counted.
        """
        cursor = self._state.last_acked_minute
        fresh = [(rec, ok) for rec, ok in pairs if rec.minute > cursor]
        synced = [rec for rec, ok in fresh if ok]
        self._dropped += len(fresh) - len(synced)
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
        self._state.last_acked_minute = max(cursor, max(rec.minute for rec, _ in pairs))
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
        """Start a sync when the watch is seen, subject to the attempt schedule."""
        if not self._attempt_allowed():
            return
        self.hass.async_create_task(self.async_request_refresh())
