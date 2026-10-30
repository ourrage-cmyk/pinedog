import struct
import sys
from datetime import date, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"))

from activity import (  # noqa: E402
    LIGHT, REST, RUN, WALK, RECORD_SIZE, DailyTotals, Record,
    baseline_status, daily_totals, unpack_raw,
)

UTC = timezone.utc


def pack(minute, counts, cls):
    # The CRC byte is irrelevant here; protocol tests cover it.
    return struct.pack("<IHBB", minute, counts, cls, 0)


def test_unpack_roundtrip():
    payload = pack(1000, 500, WALK) + pack(1001, 3, REST)
    assert unpack_raw(payload) == [(1000, 500, WALK, 0), (1001, 3, REST, 0)]
    assert RECORD_SIZE == 8


def test_unpack_rejects_partial_record():
    with pytest.raises(ValueError):
        unpack_raw(b"\x00" * 9)


def test_daily_totals_split_by_day_and_class():
    day0 = 20000 * 1440  # midnight UTC, as minutes
    recs = [
        Record(day0 + 0, 0, REST),
        Record(day0 + 1, 400, WALK),
        Record(day0 + 2, 1500, RUN),
        Record(day0 + 3, 100, LIGHT),
        Record(day0 + 1440, 50, REST),
    ]
    totals = daily_totals(recs, UTC)
    d0 = totals[date(2024, 10, 4)]
    assert d0.active_minutes == 3
    assert d0.sedentary_minutes == 1
    assert d0.walking_minutes == 2
    assert d0.motion_counts == 2000
    assert totals[date(2024, 10, 5)].sedentary_minutes == 1


def _day(d, motion, wear=720):
    """A day with the given wear minutes and motion. Wear is split into rest."""
    return DailyTotals(d, 0, wear, 0, motion)


def _history(values, start=date(2026, 10, 1)):
    from datetime import timedelta
    return [_day(start + timedelta(days=i), v) for i, v in enumerate(values)]


def test_baseline_learning_until_seven_days():
    hist = _history([1000] * 6)
    today = _day(date(2026, 10, 7), 1000)
    assert baseline_status(today, hist) == "learning"


def test_baseline_bands():
    hist = _history([1000] * 7)
    day = date(2026, 10, 8)
    assert baseline_status(_day(day, 700), hist) == "below"
    assert baseline_status(_day(day, 1000), hist) == "normal"
    assert baseline_status(_day(day, 1300), hist) == "above"


def test_baseline_ignores_today_in_history():
    hist = _history([1000] * 6) + [_day(date(2026, 10, 8), 9999)]
    today = _day(date(2026, 10, 8), 1000)
    assert baseline_status(today, hist) == "learning"


def test_baseline_needs_consecutive_calendar_days():
    # Seven recorded days, but one calendar day is missing: not a baseline.
    from datetime import timedelta
    hist = [_day(date(2026, 10, 1) + timedelta(days=i), 1000) for i in range(8) if i != 3]
    assert baseline_status(_day(date(2026, 10, 9), 1000), hist) == "learning"


def test_baseline_does_not_call_early_morning_below():
    # Two hours into the day, motion is small only because little time has passed.
    hist = _history([1000] * 7)
    early = DailyTotals(date(2026, 10, 8), 0, 120, 0, 100)
    assert baseline_status(early, hist) == "learning"


def test_baseline_ignores_days_with_little_wear():
    # Seven prior days, but the most recent one was barely worn: it does not count.
    hist = _history([1000] * 6) + [DailyTotals(date(2026, 10, 7), 0, 60, 0, 99999)]
    assert baseline_status(_day(date(2026, 10, 8), 1000), hist) == "learning"


def test_not_worn_minutes_are_left_out_of_totals():
    # Charging minutes must not count as sedentary or active time.
    from activity import NOT_WORN

    day0 = 20000 * 1440
    recs = [Record(day0 + 0, 0, REST), Record(day0 + 1, 0, NOT_WORN), Record(day0 + 2, 500, WALK)]
    d0 = daily_totals(recs, UTC)[date(2024, 10, 4)]
    assert d0.sedentary_minutes == 1
    assert d0.active_minutes == 1
