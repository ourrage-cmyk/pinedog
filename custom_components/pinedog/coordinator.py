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

from .activity import DailyTotals, Record, baseline_status, daily_totals
from .schedule import should_attempt
from .sync import async_pull_records
from .transfer import TransferResult

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
KEEP_DAYS = 60
LOW_BATTERY_PCT = 20


@dataclass
class PinedogData:
    today: DailyTotals | None = None
    baseline: str = "learning"
    last_sync: datetime | None = None
    last_error: str | None = None
    battery_pct: int | None = None
    charging: bool = False
    power_present: bool = False
    pending: int = 0
    dropped_corrupt: int = 0
    dropped_unplaced: int = 0

    @property
    def low_battery(self) -> bool:
        return self.battery_pct is not None and self.battery_pct <= LOW_BATTERY_PCT and not self.charging


@dataclass
class _State:
    # Unix minute of the newest record stored. Records at or below it were
    # counted already, so a resend after a lost ack is not double counted.
    last_stored_minute: int = -1
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
        self._battery_pct: int | None = None
        self._charging = False
        self._power_present = False
        self._pending = 0
        self._dropped_corrupt = 0
        self._dropped_unplaced = 0

    async def async_load(self) -> None:
        raw = await self._store.async_load() or {}
        self._state = _State(
            last_stored_minute=raw.get("last_stored_minute", -1),
            days=raw.get("days", {}),
        )
        last = raw.get("last_sync")
        self._last_sync = datetime.fromisoformat(last) if last else None
        self._last_attempt = self._last_sync
        self.data = self._build()

    def _history(self) -> list[DailyTotals]:
        return [
            DailyTotals(
                date.fromisoformat(key),
                v["active"],
                v["sedentary"],
                v["walking"],
                v["motion"],
            )
            for key, v in sorted(self._state.days.items())
        ]

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
            battery_pct=self._battery_pct,
            charging=self._charging,
            power_present=self._power_present,
            pending=self._pending,
            dropped_corrupt=self._dropped_corrupt,
            dropped_unplaced=self._dropped_unplaced,
        )

    async def _async_update_data(self) -> PinedogData:
        if not self._attempt_allowed():
            return self._build()
        self._last_attempt = dt_util.utcnow()
        try:
            await self._sync()
            self._last_error = None
        except Exception as err:  # noqa: BLE001 - keep sensors alive on any BLE error
            self._last_error = str(err) or type(err).__name__
            _LOGGER.warning("Pinedog sync failed, will retry: %s", self._last_error)
        return self._build()

    def _attempt_allowed(self) -> bool:
        return should_attempt(
            dt_util.utcnow(), self._last_attempt, self._last_error is not None
        )

    async def _sync(self) -> None:
        result = await async_pull_records(self.hass, self.address, self._persist)
        self._apply_result(result)

    def _apply_result(self, result: TransferResult) -> None:
        if result.status is not None:
            st = result.status
            self._battery_pct = st.battery_pct
            self._charging = st.charging
            self._power_present = st.power_present
            # Records the watch added after our status read stay pending for the next sync.
            self._pending = max(st.pending - result.received, 0)
        self._dropped_corrupt += result.corrupt
        self._dropped_unplaced += result.unplaced
        if result.corrupt or result.unplaced:
            _LOGGER.warning(
                "Pinedog sync dropped %d corrupt and %d unplaceable records",
                result.corrupt,
                result.unplaced,
            )

    async def _persist(self, records: list[Record]) -> None:
        """Store records before the watch is acked. Runs once per transfer.

        Called with the records already placed in unix time and CRC-checked.
        """
        cursor = self._state.last_stored_minute
        fresh = [rec for rec in records if rec.minute > cursor]
        tz = dt_util.get_default_time_zone()
        for day, totals in daily_totals(fresh, tz).items():
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
        if records:
            self._state.last_stored_minute = max(cursor, max(rec.minute for rec in records))
        self._last_sync = dt_util.utcnow()
        await self._store.async_save(
            {
                "last_stored_minute": self._state.last_stored_minute,
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
