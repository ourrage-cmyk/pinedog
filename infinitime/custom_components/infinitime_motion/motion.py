"""Decoding and step bookkeeping for a stock InfiniTime watch.

Pure logic: no Home Assistant or bleak imports, so it runs with plain pytest.

Wire formats come from InfiniTime's MotionService.cpp and BatteryInformationService.cpp
(read from the main branch in October 2026). The byte order is the host's native
order; the nRF52832 is little-endian, so these use "<".
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

MOTION_SERVICE_UUID = "00030000-78fc-48fe-8e23-433b3a1942d0"
STEP_COUNT_UUID = "00030100-78fc-48fe-8e23-433b3a1942d0"  # read, notify; uint32
MOTION_VALUES_UUID = "00030200-78fc-48fe-8e23-433b3a1942d0"  # read, notify; int16 x, y, z
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"  # read, notify; uint8 percent

KEEP_DAYS = 90
POLL_KEEP_SECONDS = 9 * 86400  # poll history for the baseline window and last hour
ACTIVE_INTERVAL_STEPS = 30  # a poll interval with at least this many steps is "active"
BASELINE_DAYS = 7
BASELINE_MIN_DAYS = 3


def decode_step_count(data: bytes) -> int:
    if len(data) < 4:
        raise ValueError(f"step count needs 4 bytes, got {len(data)}")
    return struct.unpack("<I", bytes(data[:4]))[0]


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
    """Spread of the acceleration magnitude over a short window.

    A dog lying still gives a near-constant magnitude, so the value is near zero.
    Movement widens it. The scale is the sensor's own units; it is a relative
    measure only, and its absolute scale is unverified on hardware.
    Returns None when there are too few samples to say anything.
    """
    if len(samples) < 2:
        return None
    mags = [math.sqrt(x * x + y * y + z * z) for x, y, z in samples]
    mean = sum(mags) / len(mags)
    variance = sum((m - mean) ** 2 for m in mags) / len(mags)
    return round(math.sqrt(variance), 2)


@dataclass
class StepTracker:
    """Turns a cumulative step counter into per-day step totals.

    The first reading only sets the reference point, because steps taken before
    Home Assistant first saw the watch are unknown. A reading lower than the last
    one means the watch's counter was reset, so the new value is all new steps.
    """

    last_raw: int | None = None
    days: dict[str, int] = field(default_factory=dict)
    # (unix seconds, steps since previous poll) for each poll, newest last
    polls: list[list[int]] = field(default_factory=list)

    def record(self, raw: int, today: date, now_ts: int) -> int:
        if self.last_raw is None:
            delta = 0
        elif raw >= self.last_raw:
            delta = raw - self.last_raw
        else:
            delta = raw  # counter reset
        self.last_raw = raw
        key = today.isoformat()
        self.days[key] = self.days.get(key, 0) + delta
        self.polls.append([now_ts, delta])
        self._prune(today, now_ts)
        return delta

    def steps_on(self, day: date) -> int:
        return self.days.get(day.isoformat(), 0)

    def steps_last_hour(self, now_ts: int) -> int:
        return sum(d for ts, d in self.polls if ts > now_ts - 3600)

    def active_intervals_on(self, day: date) -> int:
        """Polls on that day with at least ACTIVE_INTERVAL_STEPS steps.

        Each poll covers one interval, so this counts intervals, not minutes.
        """
        key = day.isoformat()
        return sum(
            1
            for ts, d in self.polls
            if d >= ACTIVE_INTERVAL_STEPS and _local_key(ts) == key
        )

    def baseline_pct(self, today: date) -> float | None:
        """Today's steps as a percent of the median of the previous 7 days with data.

        None until BASELINE_MIN_DAYS of history exist.
        """
        past = []
        for back in range(1, BASELINE_DAYS + 1):
            day = date.fromordinal(today.toordinal() - back)
            if day.isoformat() in self.days:
                past.append(self.days[day.isoformat()])
        if len(past) < BASELINE_MIN_DAYS:
            return None
        past.sort()
        mid = len(past) // 2
        median = past[mid] if len(past) % 2 else (past[mid - 1] + past[mid]) / 2
        if median <= 0:
            return None
        return round(100.0 * self.steps_on(today) / median, 1)

    def _prune(self, today: date, now_ts: int) -> None:
        cutoff = today.toordinal() - KEEP_DAYS
        for key in list(self.days):
            if date.fromisoformat(key).toordinal() < cutoff:
                del self.days[key]
        self.polls = [p for p in self.polls if p[0] > now_ts - POLL_KEEP_SECONDS]

    def to_dict(self) -> dict[str, Any]:
        return {"last_raw": self.last_raw, "days": dict(self.days), "polls": [list(p) for p in self.polls]}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StepTracker:
        if not data:
            return cls()
        return cls(
            last_raw=data.get("last_raw"),
            days=dict(data.get("days", {})),
            polls=[list(p) for p in data.get("polls", [])],
        )


def _local_key(ts: int) -> str:
    # Poll days are keyed in local time by the coordinator; this matches it.
    return datetime.fromtimestamp(ts).astimezone().date().isoformat()
