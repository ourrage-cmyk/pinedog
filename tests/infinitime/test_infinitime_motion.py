import struct
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "infinitime" / "custom_components" / "infinitime_motion"),
)

from motion import (  # noqa: E402
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


def at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second)


def ts(dt: datetime) -> int:
    return int(dt.timestamp())


def feed(log: DayLog, start: datetime, motions: list[float | None], step_s: int = 300) -> None:
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
    assert activity_index([(0, 0, 1000)]) is None
    assert activity_index([(0, 0, 1000)] * 20) == 0.0


def test_activity_index_grows_with_movement():
    still = [(0, 0, 1000)] * 20
    moving = [(0, 0, 1000), (400, 0, 1000), (0, 0, 600), (900, 300, 100)] * 5
    assert activity_index(moving) > activity_index(still)


def test_first_poll_sets_reference_and_adds_no_time():
    log = DayLog()
    log.add_poll(ts(at(DAY1, 9)), 80.0, at(DAY1, 9))
    assert log.today(DAY1)["active_s"] == 0
    assert log.today(DAY1)["sedentary_s"] == 0


def test_time_is_split_between_active_and_sedentary_by_threshold():
    log = DayLog()
    start = at(DAY1, 9)
    feed(log, start, [10.0, 10.0, 80.0, 80.0, 10.0])
    day = log.today(DAY1)
    # The first poll only sets the clock. The next four each cover 300 s.
    assert day["active_s"] == 600
    assert day["sedentary_s"] == 600


def test_gap_longer_than_cap_is_unknown_not_sedentary():
    log = DayLog()
    log.add_poll(ts(at(DAY1, 9)), 10.0, at(DAY1, 9))
    log.add_poll(ts(at(DAY1, 9)) + MAX_INTERVAL_S * 3, 10.0, at(DAY1, 9, 30))
    day = log.today(DAY1)
    assert day["sedentary_s"] == MAX_INTERVAL_S


def test_missing_motion_adds_no_time():
    log = DayLog()
    feed(log, at(DAY1, 9), [None, None, None])
    assert log.today(DAY1)["sedentary_s"] == 0


def test_threshold_learns_from_the_dogs_own_history():
    log = DayLog()
    # Quiet dog: motion mostly 5, occasionally 20. Default threshold is 50, so nothing is active.
    quiet = [5.0] * 40
    feed(log, at(DAY1, 0), quiet)
    assert log.active_threshold() != DEFAULT_ACTIVE_THRESHOLD
    assert log.active_threshold() == 5.0


def test_threshold_is_default_before_enough_history():
    log = DayLog()
    feed(log, at(DAY1, 9), [5.0] * 5)
    assert log.active_threshold() == DEFAULT_ACTIVE_THRESHOLD


def test_score_accumulates_motion_times_seconds():
    log = DayLog()
    feed(log, at(DAY1, 9), [10.0, 10.0, 10.0])
    assert log.score_today(DAY1) == pytest.approx(10.0 * 300 * 2)


def test_usual_needs_minimum_past_days():
    log = DayLog()
    assert log.usual_comparison(at(DAY1, 12)) == (None, 0)


def test_usual_compares_same_hour_against_median_of_past_days():
    log = DayLog()
    # Three past days, each with the same activity from 09:00 to 10:00.
    for back in (3, 2, 1):
        d = date.fromordinal(DAY1.toordinal() - back)
        feed(log, at(d, 9), [10.0] * 12)  # 12 polls x 300 s = one hour, score 36000 per day
    # Today: double the motion in the same hour.
    feed(log, at(DAY1, 9), [20.0] * 12)
    pct, used = log.usual_comparison(at(DAY1, 10, 30))
    assert used == 3
    assert pct == pytest.approx(200.0, rel=0.05)


def test_old_days_and_intervals_are_pruned():
    log = DayLog()
    feed(log, at(date(2026, 1, 1), 9), [10.0] * 3)
    feed(log, at(DAY1, 9), [10.0] * 3)
    assert "2026-01-01" not in log.days
    assert all(i[0] > ts(at(DAY1, 9)) - 14 * 86400 for i in log.intervals)


def test_log_survives_store_round_trip():
    log = DayLog()
    feed(log, at(DAY1, 9), [10.0, 80.0, 80.0])
    restored = DayLog.from_dict(log.to_dict())
    assert restored.today(DAY1) == log.today(DAY1)
    assert restored.last_ts == log.last_ts
