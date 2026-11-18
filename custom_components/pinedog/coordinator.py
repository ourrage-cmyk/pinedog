"""Keeps per-day totals and the sync cursor, and pulls from the watch when it is in range."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import logging
import time
from typing import Any

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .longterm import LongTerm
from .storage import STORE_VERSION, WoofStore
from .activity import NOT_WORN, Baseline, DailyTotals, Record, compute_baseline, daily_totals
from .transfer import FUTURE_SLACK_MINUTES
from .protocol import sync_requested
from .schedule import Candidate, retry_interval_for, should_attempt, should_sync_on_return
from .sync import async_pull_records, async_wait_reachable, collar_reachable, last_heard_monotonic
from .transfer import IncompleteTransfer, TransferResult, stage_failure

_LOGGER = logging.getLogger(__name__)

SHORT_TERM_DAYS = 14
KEEP_DAYS = 90  # the baseline reads up to WINDOW_DAYS; keep a margin
LOW_BATTERY_PCT = 20
# Sync now waits this long for the collar to advertise before it gives up. A sleeping
# collar advertises only every few minutes.
SYNC_NOW_WAIT_S = 240


@dataclass
class PinedogData:
    today: DailyTotals | None = None
    baseline: Baseline = field(default_factory=lambda: Baseline("learning", None, None, 0.0, 0))
    last_sync: datetime | None = None
    last_error: str | None = None
    battery_pct: int | None = None
    charging: bool = False
    power_present: bool = False
    pending: int = 0
    dropped_corrupt: int = 0
    dropped_unplaced: int = 0
    in_range: bool | None = None  # stock firmware only: the last poll reached the collar
    longterm_vs_usual_pct: float | None = None
    longterm_days: int = 0

    @property
    def low_battery(self) -> bool:
        return self.battery_pct is not None and self.battery_pct <= LOW_BATTERY_PCT and not self.charging


@dataclass
class _State:
    # Unix minute of the newest record stored. Records at or below it were
    # counted already, so a resend after a lost ack is not double counted.
    last_stored_minute: int = -1
    days: dict[str, dict[str, int]] = field(default_factory=dict)
    # Unix minute of the last Reset learning. Older records, such as a backlog the collar
    # still holds, are stored past but never counted.
    learn_from_minute: int = 0


class PinedogCoordinator(DataUpdateCoordinator[PinedogData]):
    def __init__(self, hass: HomeAssistant, address: str, entry_id: str) -> None:
        super().__init__(hass, _LOGGER, name="Pinedog", update_interval=None)
        self.address = address
        self._store: Store[dict] = WoofStore(hass, STORE_VERSION, f"pinedog.{entry_id}")
        self._state = _State()
        self._longterm = LongTerm()
        self._last_sync: datetime | None = None
        self._last_attempt: datetime | None = None
        self._last_seen: datetime | None = None
        self._last_error: str | None = None
        self._battery_pct: int | None = None
        self._charging = False
        self._power_present = False
        self._pending = 0
        self._dropped_corrupt = 0
        self._dropped_unplaced = 0
        self._busy = False
        self._force_next = False
        self.scheduler = None  # set by async_setup_entry

    async def async_load(self) -> None:
        raw = await self._store.async_load() or {}
        self._longterm = LongTerm.from_dict(raw.get("longterm"))
        self._state = _State(
            last_stored_minute=raw.get("last_stored_minute", -1),
            days=raw.get("days", {}),
            learn_from_minute=raw.get("learn_from_minute", 0),
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
        base = Baseline("waiting", None, None, 0.0, 0)
        if today is not None:
            # Short-term usual: the last 14 days. The long-term one is kept separately.
            recent = [d for d in history if (today_key - d.day).days <= SHORT_TERM_DAYS]
            base = compute_baseline(today, recent)
        now_local = dt_util.as_local(dt_util.utcnow()).replace(tzinfo=None)
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
            longterm_vs_usual_pct=self._longterm.comparison(now_local),
            longterm_days=self._longterm.days_learned,
        )

    async def _async_update_data(self) -> PinedogData:
        # Syncs are started by the shared scheduler (scheduler.py), never by a refresh.
        return self._build()

    @property
    def busy(self) -> bool:
        return self._busy

    def _attempt_allowed(self, now: datetime) -> bool:
        return should_attempt(
            now,
            self._last_attempt,
            self._last_error is not None,
            retry_interval=retry_interval_for(now, self._last_sync),
        )

    @callback
    def observe(self, now: datetime) -> None:
        """Note the newest advertisement, and flag a sync when the collar has just come back."""
        heard = last_heard_monotonic(self.hass, self.address)
        if heard is None:
            return
        heard_at = now - timedelta(seconds=max(time.monotonic() - heard, 0.0))
        if self._last_seen is not None and heard_at <= self._last_seen:
            return
        if should_sync_on_return(heard_at, self._last_seen, self._last_attempt):
            self._force_next = True
        self._last_seen = heard_at

    def candidate(self, now: datetime) -> Candidate:
        return Candidate(
            key=self.address,
            last_sync=self._last_sync,
            due=not self._busy and (self._force_next or self._attempt_allowed(now)),
            reachable=collar_reachable(self.hass, self.address),
            last_heard=self._last_seen,
        )

    async def async_scheduled_sync(self) -> None:
        """One sync chosen by the scheduler."""
        if self._busy:
            return
        self._force_next = False
        self._busy = True
        self._last_attempt = dt_util.utcnow()
        try:
            await self._sync()
            self._last_error = None
        except Exception as err:  # noqa: BLE001 - keep sensors alive on any BLE error
            self._last_error = str(stage_failure(err))
            _LOGGER.warning("Pinedog sync failed, will retry: %s", self._last_error)
        finally:
            self._busy = False
        self.async_set_updated_data(self._build())

    async def _sync(self) -> TransferResult:
        result = await async_pull_records(self.hass, self.address, self._persist)
        self._apply_result(result)
        return result

    async def async_sync_now(self) -> dict[str, Any]:
        """Sync right away, ignoring the retry schedule. Used by the Sync now button and service.

        Returns the outcome. On failure, "stage" names where it stopped (not seen, connect,
        GATT, transfer, clock, store) and "detail" says why. The same text becomes Last sync error.
        """
        if self._busy:
            return {"result": "busy", "detail": "a sync is already running"}
        self._busy = True
        try:
            # A sleeping collar advertises only every few minutes. Wait for it here rather
            # than failing at once with "not seen".
            await async_wait_reachable(self.hass, self.address, SYNC_NOW_WAIT_S)
            self._last_attempt = dt_util.utcnow()
            result = await self._sync()
        except Exception as err:  # noqa: BLE001 - report every failure with its stage
            failure = stage_failure(err)
            self._last_error = str(failure)
            _LOGGER.warning("Pinedog sync now failed at %s: %s", failure.stage, failure.detail)
            outcome = {"result": "failed", "stage": failure.stage, "detail": failure.detail}
        else:
            self._last_error = None
            outcome = {
                "result": "ok",
                "received": result.received,
                "stored": result.stored,
                "pending_left": self._pending,
            }
        finally:
            self._busy = False
        self.async_set_updated_data(self._build())
        return outcome

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
        if result.status is not None and result.status.pending and not result.acked:
            raise IncompleteTransfer(
                f"got {result.received} of {result.status.pending} records, nothing acked"
            )
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
        now_min = int(dt_util.utcnow().timestamp()) // 60
        # Records from the future are a clock error on the watch. Never move the cursor past now.
        fresh: list[Record] = []
        seen: set[int] = set()
        for rec in records:
            if rec.minute <= cursor or rec.minute > now_min + FUTURE_SLACK_MINUTES or rec.minute in seen:
                continue
            seen.add(rec.minute)
            fresh.append(rec)
        newest = max((rec.minute for rec in fresh), default=cursor)
        # Records from before a Reset learning move the cursor but are not counted.
        fresh = [rec for rec in fresh if rec.minute >= self._state.learn_from_minute]
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
        for rec in fresh:
            worn = 0 if rec.activity_class == NOT_WORN else 60
            local = dt_util.as_local(datetime.fromtimestamp(rec.minute * 60, tz=timezone.utc)).replace(tzinfo=None)
            self._longterm.observe(local, rec.counts, worn)
        for key in sorted(self._state.days)[:-KEEP_DAYS]:
            del self._state.days[key]
        self._state.last_stored_minute = max(cursor, newest)
        self._last_sync = dt_util.utcnow()
        await self._save()

    async def _save(self) -> None:
        await self._store.async_save(
            {
                "last_stored_minute": self._state.last_stored_minute,
                "days": self._state.days,
                "learn_from_minute": self._state.learn_from_minute,
                "last_sync": self._last_sync.isoformat() if self._last_sync else None,
                "longterm": self._longterm.to_dict(),
            }
        )

    async def async_reset_learning(self) -> None:
        """Forget everything learned about this dog and start again from now.

        Clears the daily totals, the 14 day usual and the long-term usual. The sync cursor
        stays, so nothing is counted twice. Records the collar made before this moment and
        has not sent yet are skipped when they arrive.
        """
        self._state.days = {}
        self._state.learn_from_minute = int(dt_util.utcnow().timestamp()) // 60
        self._longterm = LongTerm()
        await self._save()
        self.async_set_updated_data(self._build())

    @callback
    def handle_advertisement(self, info: BluetoothServiceInfoBleak, change) -> None:
        """A button press on the watch sets a sync request in its advertisement.

        Then the normal schedule is skipped. The shared scheduler is asked to choose at
        once, while the advertisement is fresh. Home Assistant calls this only when the
        advertisement content changes; the scheduler's tick covers the rest.
        """
        if sync_requested(info.manufacturer_data):
            self._force_next = True
        if self.scheduler is not None:
            self.scheduler.kick()
