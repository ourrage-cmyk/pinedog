import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load the pure modules without running the package __init__, which needs Home Assistant.
PKG_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"
_pkg = types.ModuleType("pinedog")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["pinedog"] = _pkg

from pinedog.schedule import TURN_WINDOW, synced_recently  # noqa: E402

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def test_never_synced_goes_first():
    assert not synced_recently(NOW, None)


def test_synced_inside_window_is_skipped():
    assert synced_recently(NOW, NOW - timedelta(minutes=10))
    assert synced_recently(NOW, NOW - timedelta(minutes=29, seconds=59))


def test_synced_outside_window_gets_its_turn():
    assert not synced_recently(NOW, NOW - TURN_WINDOW)
    assert not synced_recently(NOW, NOW - timedelta(minutes=45))


def test_turn_window_is_thirty_minutes():
    assert TURN_WINDOW == timedelta(minutes=30)
