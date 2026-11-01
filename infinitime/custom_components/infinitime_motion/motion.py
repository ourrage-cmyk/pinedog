"""Activity logic for a stock InfiniTime watch worn by a dog.

Pure logic: no Home Assistant or bleak imports, so it runs with plain pytest.

The watch keeps no per-minute history for BLE, so everything here is built from
polls. Each poll samples raw acceleration for a short window. That sample stands
for the time since the previous poll (capped), and the day log accumulates it.

Wire formats come from InfiniTime's MotionService.cpp and BatteryInformationService.cpp
(main branch, October 2026). Byte order is little-endian (nRF52832).
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

MOTION_VALUES_UUID = "00030200-78fc-48fe-8e23-433b3a1942d0"  # read, notify; int16 x, y, z
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"  # read, notify; uint8 percent

# Placeholders until real dog data exists. See infinitime/README.md.
DEFAULT_ACTIVE_THRESHOLD = 50.0  # motion index above this is "active" before learning
MIN_THRESHOLD_SAMPLES = 30  # intervals of this dog's own history before it learns a threshold
ACTIVE_PERCENTILE = 0.30  # the dog's own 30th percentile: the quietest 30% of its history is sedentary
MAX_INTERVAL_S = 600  # a gap longer than this between polls is unknown, not sedentary
HISTORY_DAYS = 14  # window for the usual pattern and the threshold
MIN_USUAL_DAYS = 3  # days of history before a "usual" comparison appears
MORE_THAN_USUAL_PCT = 115.0
LESS_THAN_USUAL_PCT = 85.0
KEEP_DAYS = 60


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


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


@dataclass
class DayLog:
    """Per-day active and sedentary seconds, plus a per-hour activity score.

    intervals keeps (unix seconds, motion index) for the threshold. The threshold is
    this dog's own, so it adapts as its history grows.
    """

    last_ts: int | None = None
    days: dict[str, dict[str, Any]] = field(default_factory=dict)
    intervals: list[list[float]] = field(default_factory=list)

    def add_poll(self, ts: int, motion: float | None, local: datetime) -> None:
        seconds = 0
        if self.last_ts is not None and ts > self.last_ts:
            seconds = min(ts - self.last_ts, MAX_INTERVAL_S)
        self.last_ts = ts
        if motion is None or seconds == 0:
            self._prune(local.date())
            return

        threshold = self.active_threshold()
        active = motion >= threshold
        day = self.days.setdefault(
            local.date().isoformat(), {"active_s": 0, "sedentary_s": 0, "score": [0.0] * 24}
        )
        day["active_s" if active else "sedentary_s"] += seconds
        day["score"][local.hour] = round(day["score"][local.hour] + motion * seconds, 2)
        self.intervals.append([ts, motion])
        self._prune(local.date(), now_ts=ts)

    def active_threshold(self) -> float:
        values = [m for _, m in self.intervals]
        if len(values) < MIN_THRESHOLD_SAMPLES:
            return DEFAULT_ACTIVE_THRESHOLD
        return _percentile(values, ACTIVE_PERCENTILE)

    def today(self, day: date) -> dict[str, Any]:
        return self.days.get(day.isoformat(), {"active_s": 0, "sedentary_s": 0, "score": [0.0] * 24})

    def score_today(self, day: date) -> float:
        return round(sum(self.today(day)["score"]), 1)

    def usual_comparison(self, local: datetime) -> tuple[float | None, int]:
        """Today so far as a percent of the usual amount at this hour.

        The usual amount is the median, over past days, of the score up to the same hour.
        Returns (percent or None, number of past days used).
        """
        today = local.date()
        hour = local.hour
        expected = []
        for key, day in self.days.items():
            d = date.fromisoformat(key)
            if d >= today or (today - d).days > HISTORY_DAYS:
                continue
            total = sum(day["score"][: hour + 1])
            if total > 0:
                expected.append(total)
        if len(expected) < MIN_USUAL_DAYS:
            return None, len(expected)
        usual = _median(expected)
        if usual <= 0:
            return None, len(expected)
        actual = sum(self.today(today)["score"][: hour + 1])
        return round(100.0 * actual / usual, 1), len(expected)

    def _prune(self, today: date, now_ts: int | None = None) -> None:
        cutoff = today.toordinal() - KEEP_DAYS
        for key in list(self.days):
            if date.fromisoformat(key).toordinal() < cutoff:
                del self.days[key]
        if now_ts is None:
            now_ts = int(datetime(today.year, today.month, today.day).timestamp())
        window_start = now_ts - HISTORY_DAYS * 86400
        self.intervals = [i for i in self.intervals if i[0] >= window_start]

    def to_dict(self) -> dict[str, Any]:
        return {"last_ts": self.last_ts, "days": self.days, "intervals": self.intervals}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DayLog:
        if not data:
            return cls()
        return cls(
            last_ts=data.get("last_ts"),
            days=dict(data.get("days", {})),
            intervals=[list(i) for i in data.get("intervals", [])],
        )
