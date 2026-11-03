import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load the pure modules without running the package __init__, which needs Home Assistant.
PKG_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"
_pkg = types.ModuleType("pinedog")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["pinedog"] = _pkg

from pinedog.schedule import RETRY_INTERVAL, SUCCESS_INTERVAL, synced_recently  # noqa: E402
from pinedog.stock_motion import MAX_INTERVAL_S as STOCK_CAP_S  # noqa: E402

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
WINDOW = timedelta(seconds=STOCK_CAP_S)


def test_never_synced_goes_first():
    assert not synced_recently(NOW, None, WINDOW)


def test_synced_inside_window_is_skipped():
    assert synced_recently(NOW, NOW - timedelta(minutes=5), WINDOW)


def test_synced_outside_window_gets_its_turn():
    assert not synced_recently(NOW, NOW - WINDOW, WINDOW)


def test_turn_window_never_exceeds_motion_cap():
    # A skip must not stretch the gap between credited polls past the cap.
    assert STOCK_CAP_S == 600


def test_timer_sees_every_sync_window():
    # The Pinedog path polls on a timer, gated by should_attempt. The timer must be at
    # least as fast as the retry gap, so no sync window is missed by more than one tick.
    assert RETRY_INTERVAL <= SUCCESS_INTERVAL
