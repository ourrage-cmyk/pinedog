import struct
import sys
from datetime import date, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"))

from activity import (  # noqa: E402
    LIGHT, REST, RUN, WALK, RECORD_SIZE, DailyTotals, Record,
    compute_baseline, daily_totals, decode_records,
)

UTC = timezone.utc


def pack(minute, counts, cls, cadence=0):
    return struct.pack("<IHBB", minute, counts, cls, cadence)


def test_decode_roundtrip():
    payload = pack(1000, 500, WALK, 18) + pack(1001, 3, REST)
    recs = decode_records(payload)
    assert recs == [Record(1000, 500, WALK, 18), Record(1001, 3, REST, 0)]
    assert RECORD_SIZE == 8


def test_decode_rejects_partial_record():
    with pytest.raises(ValueError):
        decode_records(b"\x00" * 9)


def test_daily_totals_split_by_day_and_class():
    day0 = 20000 * 1440  # midnight UTC, as minutes
    recs = [
        Record(day0 + 0, 0, REST, 0),
        Record(day0 + 1, 400, WALK, 18),
        Record(day0 + 2, 1500, RUN, 30),
        Record(day0 + 3, 100, LIGHT, 0),
        Record(day0 + 1440, 50, REST, 0),
    ]
    totals = daily_totals(recs, UTC)
    d0 = totals[date(2024, 10, 4)]
    assert d0.active_minutes == 3
    assert d0.sedentary_minutes == 1
    assert d0.walking_minutes == 2
    assert d0.motion_counts == 2000
    assert totals[date(2024, 10, 5)].sedentary_minutes == 1


TODAY = date(2026, 10, 30)  # a Friday


def _day(days_ago, motion, worn=1440):
    """A day with `worn` minutes of wear and `motion` total counts."""
    from datetime import timedelta

    return DailyTotals(TODAY - timedelta(days=days_ago), worn, 0, 0, motion)


def _steady(n, motion, worn=1440):
    return [_day(i, motion, worn) for i in range(1, n + 1)]


def test_baseline_learning_until_seven_valid_days():
    today = DailyTotals(TODAY, 600, 840, 0, 50_000)
    six = compute_baseline(today, _steady(6, 50_000))
    assert six.status == "learning"
    assert six.expected_counts is not None  # estimate is still shown
    assert compute_baseline(today, _steady(7, 50_000)).status == "normal"


def test_baseline_warm_up_is_shrunk_toward_prior():
    # One day of data: the expectation sits between the prior and that day,
    # and confidence is low.
    one = compute_baseline(DailyTotals(TODAY, 1440, 0, 0, 0), _steady(3, 200_000))
    prior = 100 * 1440
    assert prior < one.expected_counts < 200_000
    assert one.confidence < 0.8


def test_confidence_grows_with_data():
    today = DailyTotals(TODAY, 1440, 0, 0, 0)
    few = compute_baseline(today, _steady(3, 200_000))
    many = compute_baseline(today, _steady(40, 200_000))
    assert many.confidence > few.confidence > 0
    assert many.confidence > 0.9


def test_converges_to_steady_motion():
    today = DailyTotals(TODAY, 600, 840, 0, 200_000)
    base = compute_baseline(today, _steady(40, 200_000))
    # The prior is worth one day, so after ~40 days it still pulls about 5%.
    assert base.expected_counts == pytest.approx(200_000, rel=0.07)
    assert base.percent == pytest.approx(100, rel=0.07)


def test_bands_follow_daily_motion():
    hist = _steady(30, 200_000)
    below = compute_baseline(DailyTotals(TODAY, 1440, 0, 0, 50_000), hist)
    above = compute_baseline(DailyTotals(TODAY, 1440, 0, 0, 800_000), hist)
    normal = compute_baseline(DailyTotals(TODAY, 1440, 0, 0, 200_000), hist)
    assert below.status == "below"
    assert above.status == "above"
    assert normal.status == "normal"


def test_partly_worn_days_are_scaled_to_full_day():
    # Same dog, but one history day was worn only 12 h. Its counts are half
    # the full-day total, so it should not drag the baseline down.
    full = _steady(30, 200_000)
    half_worn = full[:-1] + [_day(30, 100_000, worn=720)]
    today = DailyTotals(TODAY, 600, 840, 0, 200_000)
    a = compute_baseline(today, full).expected_counts
    b = compute_baseline(today, half_worn).expected_counts
    assert b == pytest.approx(a, rel=0.02)


def test_days_with_too_little_wear_are_skipped():
    hist = _steady(30, 200_000)
    # Ten days of barely any wear, with huge counts that would be wrong
    # if they were scaled up.
    noisy = [_day(i, 5_000, worn=30) for i in range(31, 41)]
    today = DailyTotals(TODAY, 600, 840, 0, 200_000)
    assert compute_baseline(today, hist + noisy).expected_counts == pytest.approx(
        compute_baseline(today, hist).expected_counts
    )


def test_outlier_days_do_not_move_baseline():
    clean = compute_baseline(DailyTotals(TODAY, 1440, 0, 0, 200_000), _steady(30, 200_000))
    hist = _steady(30, 200_000)
    hist[10] = _day(11, 40_000_000)  # a day of extreme motion
    hist[20] = _day(21, 0)  # a day the collar recorded no motion at all
    dirty = compute_baseline(DailyTotals(TODAY, 1440, 0, 0, 200_000), hist)
    assert dirty.expected_counts == pytest.approx(clean.expected_counts, rel=0.01)


def test_missing_days_only_reduce_the_sample():
    hist = [d for i, d in enumerate(_steady(30, 200_000)) if i % 3]  # every third day missing
    base = compute_baseline(DailyTotals(TODAY, 1440, 0, 0, 200_000), hist)
    assert base.status == "normal"
    assert base.days_learned == len(hist)


def test_history_older_than_window_is_ignored():
    recent = _steady(30, 200_000)
    old = [_day(i, 9_000_000) for i in range(61, 120)]
    today = DailyTotals(TODAY, 1440, 0, 0, 200_000)
    assert compute_baseline(today, recent + old).expected_counts == pytest.approx(
        compute_baseline(today, recent).expected_counts
    )


def test_weekday_expectation_learns_a_regular_walk_day():
    # Eight weeks where Sundays are three times as active as other days.
    hist = []
    for i in range(1, 57):
        day = TODAY - __import__("datetime").timedelta(days=i)
        hist.append(DailyTotals(day, 1440, 0, 0, 600_000 if day.weekday() == 6 else 200_000))
    sunday = date(2026, 11, 1)  # a Sunday
    assert sunday.weekday() == 6
    today_sun = DailyTotals(sunday, 600, 840, 0, 0)
    base = compute_baseline(today_sun, hist)
    assert base.expected_counts > 1.5 * 200_000
    assert base.expected_counts < 2.5 * 200_000


def test_today_with_little_wear_is_waiting():
    base = compute_baseline(DailyTotals(TODAY, 10, 5, 0, 900), _steady(30, 200_000))
    assert base.status == "waiting"
    assert base.percent is None


def test_percent_uses_full_day_estimate():
    # 60 minutes of wear with 5000 counts is 120,000 counts over a full day.
    base = compute_baseline(DailyTotals(TODAY, 60, 0, 0, 5_000), _steady(30, 200_000))
    assert base.percent == pytest.approx(100 * 120_000 / base.expected_counts)
