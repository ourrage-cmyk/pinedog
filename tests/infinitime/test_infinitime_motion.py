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
    STEP_COUNT_UUID,
    MOTION_VALUES_UUID,
    BATTERY_LEVEL_UUID,
    StepTracker,
    activity_index,
    decode_battery,
    decode_motion,
    decode_step_count,
)

DAY1 = date(2026, 11, 1)
DAY2 = date(2026, 11, 2)


def local_ts(day: date, hour: int, minute: int = 0) -> int:
    # Naive datetimes are local time, matching how the tracker keys days.
    return int(datetime(day.year, day.month, day.day, hour, minute).timestamp())


def test_uuids_match_infinitime_source():
    # Values from InfiniTime MotionService.cpp (main branch, Oct 2026).
    assert STEP_COUNT_UUID == "00030100-78fc-48fe-8e23-433b3a1942d0"
    assert MOTION_VALUES_UUID == "00030200-78fc-48fe-8e23-433b3a1942d0"
    assert BATTERY_LEVEL_UUID == "00002a19-0000-1000-8000-00805f9b34fb"


def test_step_count_is_little_endian_uint32():
    assert decode_step_count(struct.pack("<I", 12345)) == 12345


def test_step_count_short_payload_raises():
    with pytest.raises(ValueError):
        decode_step_count(b"\x01\x02")


def test_motion_is_three_little_endian_int16():
    assert decode_motion(struct.pack("<hhh", -1, 2, -300)) == (-1, 2, -300)


def test_motion_short_payload_raises():
    with pytest.raises(ValueError):
        decode_motion(b"\x00" * 5)


def test_battery_is_clamped_to_percent_range():
    assert decode_battery(bytes([73])) == 73
    assert decode_battery(bytes([250])) == 100
    with pytest.raises(ValueError):
        decode_battery(b"")


def test_activity_none_with_too_few_samples():
    assert activity_index([]) is None
    assert activity_index([(0, 0, 1000)]) is None


def test_activity_zero_for_constant_magnitude():
    assert activity_index([(0, 0, 1000)] * 20) == 0.0


def test_activity_grows_with_movement():
    still = [(0, 0, 1000)] * 20
    moving = [(0, 0, 1000), (400, 0, 1000), (0, 0, 600), (900, 300, 100)] * 5
    assert activity_index(moving) > activity_index(still)


def test_first_reading_sets_reference_and_counts_nothing():
    tracker = StepTracker()
    assert tracker.record(5000, DAY1, local_ts(DAY1, 9)) == 0
    assert tracker.steps_on(DAY1) == 0


def test_steps_accumulate_per_day():
    tracker = StepTracker()
    tracker.record(1000, DAY1, local_ts(DAY1, 9))
    assert tracker.record(1400, DAY1, local_ts(DAY1, 10)) == 400
    assert tracker.record(1500, DAY2, local_ts(DAY2, 9)) == 100
    assert tracker.steps_on(DAY1) == 400
    assert tracker.steps_on(DAY2) == 100


def test_counter_reset_counts_the_new_value():
    tracker = StepTracker()
    tracker.record(9000, DAY1, local_ts(DAY1, 9))
    assert tracker.record(250, DAY1, local_ts(DAY1, 10)) == 250
    assert tracker.steps_on(DAY1) == 250


def test_steps_last_hour_uses_only_recent_polls():
    tracker = StepTracker()
    now = local_ts(DAY1, 12)
    tracker.record(0, DAY1, now - 7200)
    tracker.record(100, DAY1, now - 5400)  # 100 steps, 90 min ago: outside the hour
    tracker.record(250, DAY1, now - 1800)  # 150 steps, 30 min ago
    tracker.record(300, DAY1, now)  # 50 steps, now
    assert tracker.steps_last_hour(now) == 200


def test_active_intervals_count_polls_over_threshold():
    tracker = StepTracker()
    t = local_ts(DAY1, 8)
    tracker.record(0, DAY1, t)
    tracker.record(10, DAY1, t + 900)  # 10 steps: not active
    tracker.record(60, DAY1, t + 1800)  # 50 steps: active
    tracker.record(90, DAY1, t + 2700)  # 30 steps: active (threshold is inclusive)
    assert tracker.active_intervals_on(DAY1) == 2


def test_baseline_is_none_without_enough_history():
    tracker = StepTracker()
    tracker.days = {"2026-10-30": 5000, "2026-10-31": 6000}
    assert tracker.baseline_pct(DAY1) is None


def test_baseline_pct_is_today_against_median_of_past_week():
    tracker = StepTracker()
    tracker.days = {
        "2026-10-25": 2000,
        "2026-10-26": 4000,
        "2026-10-27": 6000,
        "2026-10-28": 8000,
        "2026-10-29": 10000,
        "2026-10-30": 3000,  # median of the seven is 6000
        "2026-10-31": 9000,
        "2026-11-01": 9000,
    }
    assert tracker.baseline_pct(DAY1) == 150.0


def test_tracker_survives_store_round_trip():
    tracker = StepTracker()
    tracker.record(100, DAY1, local_ts(DAY1, 9))
    tracker.record(160, DAY1, local_ts(DAY1, 10))
    restored = StepTracker.from_dict(tracker.to_dict())
    assert restored.record(200, DAY1, local_ts(DAY1, 11)) == 40
    assert restored.steps_on(DAY1) == 100


def test_old_days_and_polls_are_pruned():
    tracker = StepTracker()
    tracker.record(0, date(2026, 1, 1), local_ts(date(2026, 1, 1), 9))
    tracker.record(50, date(2026, 1, 1), local_ts(date(2026, 1, 1), 10))
    tracker.record(60, DAY1, local_ts(DAY1, 9))
    assert "2026-01-01" not in tracker.days
    assert all(ts > local_ts(DAY1, 9) - 9 * 86400 for ts, _ in tracker.polls)
