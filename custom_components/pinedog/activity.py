"""Pure logic for Pinedog records: decoding, daily totals and baseline.

No Home Assistant imports here, so it can be tested with plain pytest.
"""

from __future__ import annotations

import struct
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone

RECORD_FORMAT = "<IHBB"  # minute, counts, class, crc8 (8 bytes, packed, see protocol.py)
RECORD_SIZE = struct.calcsize(RECORD_FORMAT)

REST, LIGHT, WALK, RUN = 0, 1, 2, 3
# Written while the watch is on its charger. Not worn: left out of every total.
NOT_WORN = 4
KNOWN_CLASSES = {REST, LIGHT, WALK, RUN, NOT_WORN}
ACTIVE_CLASSES = {LIGHT, WALK, RUN}
WALKING_CLASSES = {WALK, RUN}

BASELINE_DAYS = 7


@dataclass(frozen=True)
class Record:
    minute: int  # minutes since Unix epoch
    counts: int
    activity_class: int  # REST, LIGHT, WALK or RUN, unsynced bits already removed


@dataclass(frozen=True)
class DailyTotals:
    day: date
    active_minutes: int
    sedentary_minutes: int
    walking_minutes: int
    motion_counts: int


def unpack_raw(payload: bytes) -> list[tuple[int, int, int, int]]:
    """Split a payload of packed 8-byte records into (minute, counts, class byte, crc)."""
    if len(payload) % RECORD_SIZE:
        raise ValueError(f"payload length {len(payload)} is not a multiple of {RECORD_SIZE}")
    return [
        struct.unpack_from(RECORD_FORMAT, payload, offset)
        for offset in range(0, len(payload), RECORD_SIZE)
    ]


def _day_of(minute: int, tz: timezone) -> date:
    return datetime.fromtimestamp(minute * 60, tz).date()


def daily_totals(records: list[Record], tz: timezone) -> dict[date, DailyTotals]:
    """Aggregate minute records into per-day totals in the given timezone."""
    buckets: dict[date, dict[str, int]] = defaultdict(
        lambda: {"active": 0, "sedentary": 0, "walking": 0, "motion": 0}
    )
    for rec in records:
        if rec.activity_class == NOT_WORN:
            continue
        b = buckets[_day_of(rec.minute, tz)]
        if rec.activity_class in ACTIVE_CLASSES:
            b["active"] += 1
        else:
            b["sedentary"] += 1
        if rec.activity_class in WALKING_CLASSES:
            b["walking"] += 1
        b["motion"] += rec.counts
    return {
        day: DailyTotals(day, b["active"], b["sedentary"], b["walking"], b["motion"])
        for day, b in buckets.items()
    }


def baseline_status(today: DailyTotals, history: list[DailyTotals]) -> str:
    """Compare today's motion with the trailing baseline.

    Returns "learning" until BASELINE_DAYS of history exist, otherwise
    "below", "normal" or "above" based on a +/-25% band around the mean.
    """
    past = [d for d in history if d.day < today.day][-BASELINE_DAYS:]
    if len(past) < BASELINE_DAYS:
        return "learning"
    mean = sum(d.motion_counts for d in past) / len(past)
    if mean == 0:
        return "normal" if today.motion_counts == 0 else "above"
    ratio = today.motion_counts / mean
    if ratio < 0.75:
        return "below"
    if ratio > 1.25:
        return "above"
    return "normal"
