import struct
import sys
import types
from datetime import date, datetime
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "woofmetric"
_pkg = types.ModuleType("woofmetric")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["woofmetric"] = _pkg

from woofmetric.activity import compute_baseline  # noqa: E402
from woofmetric.stock_motion import (  # noqa: E402
    BATTERY_LEVEL_UUID,
    DEFAULT_ACTIVE_THRESHOLD,
    MAX_INTERVAL_S,
    MOTION_VALUES_UUID,
    DayLog,
    activity_index,
    decode_battery,
    decode_motion,
)

DAY1 = date(2026, 11, 1)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def feed(log: DayLog, start: datetime, motions, step_s: int = 300) -> None:
    for i, m in enumerate(motions):
        t = start.timestamp() + i * step_s
        log.add_poll(int(t), m, datetime.fromtimestamp(t))


def test_uuids_match_infinitime_source():
    assert MOTION_VALUES_UUID == "00030200-78fc-48fe-8e23-433b3a1942d0"
    assert BATTERY_LEVEL_UUID == "00002a19-0000-1000-8000-00805f9b34fb"


def test_motion_is_three_little_endian_int16():
    assert decode_motion(struct.pack("<hhh", -1, 2, -300)) == (-1, 2, -300)
    with pytest.raises(ValueError):
        decode_motion(b"\x00" * 5)


def test_battery_is_clamped_to_percent_range():
    assert decode_battery(bytes([73])) == 73
    assert decode_battery(bytes([250])) == 100
    with pytest.raises(ValueError):
        decode_battery(b"")


def test_activity_index_none_too_few_and_zero_when_still():
    assert activity_index([]) is None
    assert activity_index([(0, 0, 1000)] * 20) == 0.0


def test_activity_index_grows_with_movement():
    still = [(0, 0, 1000)] * 20
    moving = [(0, 0, 1000), (400, 0, 1000), (0, 0, 600), (900, 300, 100)] * 5
    assert activity_index(moving) > activity_index(still)


def test_first_poll_sets_clock_and_adds_no_time():
    log = DayLog()
    log.add_poll(int(at(DAY1, 9).timestamp()), 80.0, at(DAY1, 9))
    assert log.daily_totals() == []


def test_time_is_split_between_active_and_sedentary_by_threshold():
    log = DayLog()
    feed(log, at(DAY1, 9), [10.0, 10.0, 80.0, 80.0, 10.0])
    (day,) = log.daily_totals()
    # The first poll only sets the clock. The next four each cover 300 s.
    assert day.active_minutes == 10
    assert day.sedentary_minutes == 10


def test_gap_longer_than_cap_is_credited_only_up_to_cap():
    log = DayLog()
    t0 = int(at(DAY1, 9).timestamp())
    log.add_poll(t0, 10.0, at(DAY1, 9))
    log.add_poll(t0 + MAX_INTERVAL_S * 3, 10.0, at(DAY1, 9, 30))
    (day,) = log.daily_totals()
    assert day.sedentary_minutes == MAX_INTERVAL_S // 60


def test_missing_motion_adds_no_time():
    log = DayLog()
    feed(log, at(DAY1, 9), [None, None, None])
    assert log.daily_totals() == []


def test_threshold_learns_from_the_dogs_own_history():
    log = DayLog()
    feed(log, at(DAY1, 0), [5.0] * 40)
    assert log.active_threshold() == 5.0
    assert log.active_threshold() != DEFAULT_ACTIVE_THRESHOLD


def test_threshold_is_default_before_enough_history():
    log = DayLog()
    feed(log, at(DAY1, 9), [5.0] * 5)
    assert log.active_threshold() == DEFAULT_ACTIVE_THRESHOLD


def test_daily_totals_feed_the_shared_baseline():
    log = DayLog()
    for back in range(1, 8):
        d = date.fromordinal(DAY1.toordinal() - back)
        feed(log, at(d, 6), [10.0] * 200)  # long wear each past day
    feed(log, at(DAY1, 6), [10.0] * 40)
    history = log.daily_totals()
    today = next(d for d in history if d.day == DAY1)
    base = compute_baseline(today, history)
    assert base.days_learned >= 1


def test_log_survives_store_round_trip():
    log = DayLog()
    feed(log, at(DAY1, 9), [10.0, 80.0, 80.0])
    restored = DayLog.from_dict(log.to_dict())
    assert restored.daily_totals() == log.daily_totals()
    assert restored.last_ts == log.last_ts
