import json
import sys
import types
from datetime import date, datetime, timedelta
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"
_pkg = types.ModuleType("pinedog")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["pinedog"] = _pkg

from pinedog.longterm import MIN_LEARNED_DAYS, LongTerm  # noqa: E402

START = date(2026, 10, 1)  # a Thursday


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def learn_day(lt: LongTerm, day: date, hours, value: float, worn: float = 3600) -> None:
    for h in hours:
        lt.observe(at(day, h, 30), value, worn)
    # An observation at the next midnight commits the last hour of this day.
    nxt = day + timedelta(days=1)
    lt.observe(at(nxt, 0, 0), 0.0, 0.0)


def test_day_counts_as_learned_after_six_worn_hours():
    lt = LongTerm()
    learn_day(lt, START, range(8, 14), 100.0)
    assert lt.days_learned == 1


def test_unworn_hours_teach_nothing():
    lt = LongTerm()
    learn_day(lt, START, range(8, 20), 100.0, worn=60)
    assert lt.days_learned == 0
    assert all(w == 0.0 for w in lt.weight)


def test_no_comparison_until_enough_learned_days():
    lt = LongTerm()
    for i in range(MIN_LEARNED_DAYS - 1):
        learn_day(lt, START + timedelta(days=i), range(8, 14), 100.0)
    today = START + timedelta(days=MIN_LEARNED_DAYS - 1)
    learn_day(lt, today, range(8, 10), 200.0)
    assert lt.comparison(at(today, 10, 30)) is None


def test_comparison_is_percent_of_the_usual_at_the_same_hours():
    lt = LongTerm()
    for i in range(MIN_LEARNED_DAYS + 1):
        learn_day(lt, START + timedelta(days=i), range(8, 14), 100.0)
    today = START + timedelta(days=MIN_LEARNED_DAYS + 1)
    # Today's 08:00 and 09:00 are double the usual 100 each. 10:00 has no data, so it is skipped.
    for h in (8, 9):
        lt.observe(at(today, h, 30), 200.0, 3600)
    pct = lt.comparison(at(today, 10, 30))
    assert pct is not None
    assert abs(pct - 200.0) < 1.0


def test_round_trip_keeps_learning_and_buckets():
    lt = LongTerm()
    for i in range(3):
        learn_day(lt, START + timedelta(days=i), range(8, 14), 50.0)
    restored = LongTerm.from_dict(lt.to_dict())
    assert restored.days_learned == lt.days_learned
    assert restored.mean == lt.mean
    assert restored.weight == lt.weight


def test_corrupt_shape_starts_over_instead_of_misindexing():
    restored = LongTerm.from_dict({"mean": [0.0] * 5, "weight": [0.0] * 5, "days_learned": 9})
    assert restored.days_learned == 0


def test_state_stays_bounded_over_years():
    lt = LongTerm()
    for i in range(30):
        learn_day(lt, START + timedelta(days=i), range(8, 14), 10.0)
    size_after_month = len(json.dumps(lt.to_dict()))
    for i in range(30, 365):
        learn_day(lt, START + timedelta(days=i), range(8, 14), 10.0)
    assert len(json.dumps(lt.to_dict())) <= size_after_month + 50
    assert lt.days_learned == 365
