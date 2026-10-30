"""Pure logic for Pinedog records: decoding, daily totals and baseline.

No Home Assistant imports here, so it can be tested with plain pytest.
"""

from __future__ import annotations

import math
import struct
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

RECORD_FORMAT = "<IHBB"  # minute, counts, class, crc8 (8 bytes, packed, see protocol.py)
RECORD_SIZE = struct.calcsize(RECORD_FORMAT)

REST, LIGHT, WALK, RUN = 0, 1, 2, 3
# Written while the watch is on its charger. Not worn: left out of every total.
NOT_WORN = 4
KNOWN_CLASSES = {REST, LIGHT, WALK, RUN, NOT_WORN}
ACTIVE_CLASSES = {LIGHT, WALK, RUN}
WALKING_CLASSES = {WALK, RUN}

BASELINE_DAYS = 7
MINUTES_PER_DAY = 1440

# Baseline tuning. See docs/ACTIVITY.md for the reasoning behind each value.
MIN_WEAR_MINUTES = 6 * 60  # a day needs this much wear to count toward the baseline
MIN_TODAY_WEAR_MINUTES = 60  # below this, today is too early to compare
WINDOW_DAYS = 60  # history older than this is ignored
HALF_LIFE_DAYS = 14.0  # a day this old counts half as much as yesterday
WEEKDAY_HALF_LIFE_DAYS = 56.0  # weekday history needs a longer memory: about 8 of each weekday
MIN_LEARNED_DAYS = 7  # below this many valid days, status is "learning" (estimate still shown)
PRIOR_COUNTS_PER_MINUTE = 100.0  # population guess, replaced as data arrives
PRIOR_WEIGHT_DAYS = 1.0  # how many days of data the prior is worth
WEEKDAY_PRIOR_WEIGHT_DAYS = 2.0  # weekday history is shrunk toward all days
SD_FLOOR = 0.25  # minimum spread in log units, so one quiet week is not overconfident
STATUS_BAND_SD = 1.0  # within this many sd of baseline counts as normal


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


@dataclass(frozen=True)
class Baseline:
    status: str  # "learning", "waiting", "below", "normal" or "above"
    expected_counts: float | None  # expected full-day counts for today's weekday
    percent: float | None  # estimated full-day counts as % of expected
    confidence: float  # 0 to 1: share of the estimate that comes from data, not prior
    days_learned: int


def _weighted_median(values: list[float], weights: list[float]) -> float:
    pairs = sorted(zip(values, weights))
    half = sum(weights) / 2
    acc = 0.0
    for value, weight in pairs:
        acc += weight
        if acc >= half:
            return value
    return pairs[-1][0]


def _robust_location(values: list[float], weights: list[float]) -> tuple[float, float]:
    """Weighted median and robust spread of log values.

    A median is used rather than a mean because a single extreme day (a bath,
    a vet visit, a broken collar) has no effect on it, and the spread comes
    from the median absolute deviation for the same reason.
    """
    med = _weighted_median(values, weights)
    dev = [abs(v - med) for v in values]
    sd = 1.4826 * _weighted_median(dev, weights)
    return med, max(sd, SD_FLOOR)


def _shrink(mean: float, n_eff: float, prior: float, prior_weight: float) -> float:
    return (n_eff * mean + prior_weight * prior) / (n_eff + prior_weight)


def _full_day_counts(day: DailyTotals) -> float | None:
    """Motion scaled to a full day, so partly worn days are comparable."""
    worn = day.active_minutes + day.sedentary_minutes
    if worn <= 0:
        return None
    return day.motion_counts * MINUTES_PER_DAY / worn


def compute_baseline(today: DailyTotals, history: list[DailyTotals]) -> Baseline:
    """Rolling baseline for today's motion, learned from past days.

    Each past day contributes its full-day motion estimate on the log scale.
    Days are weighted by age (half-life HALF_LIFE_DAYS), days with too little
    wear are skipped, and the centre is a weighted median, so outlier days do
    not move it. The estimate is pulled toward a population prior while data
    is scarce. The status is withheld until MIN_LEARNED_DAYS valid days exist,
    but the estimate and confidence are reported from the first valid day.
    """
    valid = []
    for d in history:
        age = (today.day - d.day).days
        if age < 1 or age > WINDOW_DAYS:
            continue
        worn = d.active_minutes + d.sedentary_minutes
        if worn < MIN_WEAR_MINUTES:
            continue
        est = _full_day_counts(d)
        if est is None:
            continue
        valid.append((d.day, math.log(max(est, 1.0)), age))

    if not valid:
        return Baseline("learning", None, None, 0.0, 0)

    prior = math.log(PRIOR_COUNTS_PER_MINUTE * MINUTES_PER_DAY)
    values = [v for _, v, _ in valid]
    weights = [0.5 ** (age / HALF_LIFE_DAYS) for _, _, age in valid]
    mean, sd = _robust_location(values, weights)
    n_eff = sum(weights)
    overall = _shrink(mean, n_eff, prior, PRIOR_WEIGHT_DAYS)

    same_day = [
        (v, 0.5 ** (age / WEEKDAY_HALF_LIFE_DAYS))
        for d, v, age in valid
        if d.weekday() == today.day.weekday()
    ]
    expected_log = overall
    if same_day:
        wd_mean, _ = _robust_location([v for v, _ in same_day], [w for _, w in same_day])
        expected_log = _shrink(
            wd_mean, sum(w for _, w in same_day), overall, WEEKDAY_PRIOR_WEIGHT_DAYS
        )

    expected = math.exp(expected_log)
    confidence = n_eff / (n_eff + PRIOR_WEIGHT_DAYS)
    learning = len(valid) < MIN_LEARNED_DAYS
    today_est = _full_day_counts(today)
    worn_today = today.active_minutes + today.sedentary_minutes
    if today_est is None or worn_today < MIN_TODAY_WEAR_MINUTES:
        status, percent = "waiting", None
    else:
        percent = 100.0 * today_est / expected
        z = (math.log(max(today_est, 1.0)) - expected_log) / sd
        if z < -STATUS_BAND_SD:
            status = "below"
        elif z > STATUS_BAND_SD:
            status = "above"
        else:
            status = "normal"
    if learning:
        status = "learning"
    return Baseline(status, expected, percent, confidence, len(valid))
