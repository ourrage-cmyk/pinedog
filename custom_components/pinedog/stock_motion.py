"""Activity logic for a collar running stock InfiniTime.

Pure logic: no Home Assistant or bleak imports, so it runs with plain pytest.

Stock InfiniTime keeps no per-minute history for BLE. Each poll samples raw
acceleration for a short window. That sample stands for the time since the previous
poll, capped at MAX_INTERVAL_S, and the day log accumulates it. Days are turned into
the same DailyTotals the Pinedog firmware produces, so the baseline code is shared.

Wire formats come from InfiniTime's MotionService.cpp and BatteryInformationService.cpp
(main branch, October 2026). Byte order is little-endian (nRF52832).
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .activity import DailyTotals
from .longterm import LongTerm

MOTION_VALUES_UUID = "00030200-78fc-48fe-8e23-433b3a1942d0"  # read, notify; int16 x, y, z
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"  # read, notify; uint8 percent

# Placeholders until real dog data exists. See docs/STOCK_INFINITIME.md.
DEFAULT_ACTIVE_THRESHOLD = 50.0  # motion index at or above this is "active" before learning
MIN_THRESHOLD_SAMPLES = 30  # intervals of this dog's own history before it learns a threshold
ACTIVE_PERCENTILE = 0.30  # the quietest 30% of the dog's own history counts as sedentary
MAX_INTERVAL_S = 600  # a gap longer than this between polls is unknown, not sedentary
HISTORY_DAYS = 14  # window for the threshold
KEEP_DAYS = 60  # day totals kept for the baseline, which reads up to 60 days
COUNTS_PER_UNIT = 100  # motion counts per motion index second, so stock and Pinedog scales look alike


def decode_motion(data: bytes) -> tuple[int, int, int]:
    if len(data) < 6:
        raise ValueError(f"motion sample needs 6 bytes, got {len(data)}")
    x, y, z = struct.unpack("<hhh", bytes(data[:6]))
    return x, y, z


def decode_battery(data: bytes) -> int:
    if not data:
        raise ValueError("battery level is empty")
    return min(max(data[0], 0), 100)


def activity_index(samples: list[tuple[int, int, int]]) -> float | None:
    """Spread of the acceleration magnitude over a sample window.

    A dog lying still gives a near-constant magnitude, so the value is near zero.
    Relative only: the absolute scale of the sensor units is unverified on hardware.
    Returns None when there are too few samples to say anything.
    """
    if len(samples) < 2:
        return None
    mags = [math.sqrt(x * x + y * y + z * z) for x, y, z in samples]
    mean = sum(mags) / len(mags)
    variance = sum((m - mean) ** 2 for m in mags) / len(mags)
    return round(math.sqrt(variance), 2)


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(int(q * len(ordered)), len(ordered) - 1)]


@dataclass
class DayLog:
    """Per-day active and sedentary seconds and motion, plus recent intervals for the threshold."""

    last_ts: int | None = None
    days: dict[str, dict[str, float]] = field(default_factory=dict)
    intervals: list[list[float]] = field(default_factory=list)
    longterm: LongTerm = field(default_factory=LongTerm)

    def add_poll(self, ts: int, motion: float | None, local: datetime) -> None:
        seconds = 0
        if self.last_ts is not None and ts > self.last_ts:
            seconds = min(ts - self.last_ts, MAX_INTERVAL_S)
        self.last_ts = ts
        if motion is None or seconds == 0:
            self._prune(local.date(), ts)
            return

        active = motion >= self.active_threshold()
        day = self.days.setdefault(
            local.date().isoformat(), {"active_s": 0.0, "sedentary_s": 0.0, "motion": 0.0}
        )
        day["active_s" if active else "sedentary_s"] += seconds
        day["motion"] += motion * seconds
        self.intervals.append([ts, motion])
        self.longterm.observe(local, motion * seconds, seconds)
        self._prune(local.date(), ts)

    def active_threshold(self) -> float:
        values = [m for _, m in self.intervals]
        if len(values) < MIN_THRESHOLD_SAMPLES:
            return DEFAULT_ACTIVE_THRESHOLD
        return _percentile(values, ACTIVE_PERCENTILE)

    def daily_totals(self) -> list[DailyTotals]:
        """Day totals in the shape the Pinedog firmware produces, for the shared baseline."""
        out = []
        for key in sorted(self.days):
            d = self.days[key]
            out.append(
                DailyTotals(
                    date.fromisoformat(key),
                    round(d["active_s"] / 60),
                    round(d["sedentary_s"] / 60),
                    0,  # stock firmware cannot tell walking from other activity
                    round(d["motion"] * COUNTS_PER_UNIT / 60),
                )
            )
        return out

    def _prune(self, today: date, now_ts: int) -> None:
        cutoff = today.toordinal() - KEEP_DAYS
        for key in list(self.days):
            if date.fromisoformat(key).toordinal() < cutoff:
                del self.days[key]
        window_start = now_ts - HISTORY_DAYS * 86400
        self.intervals = [i for i in self.intervals if i[0] >= window_start]

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_ts": self.last_ts,
            "days": self.days,
            "intervals": self.intervals,
            "longterm": self.longterm.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DayLog:
        if not data:
            return cls()
        return cls(
            last_ts=data.get("last_ts"),
            days=dict(data.get("days", {})),
            intervals=[list(i) for i in data.get("intervals", [])],
            longterm=LongTerm.from_dict(data.get("longterm")),
        )
