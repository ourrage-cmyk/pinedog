"""A collar that comes back into range syncs at once. Pure logic, no Home Assistant."""

import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"
_pkg = types.ModuleType("pinedog")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["pinedog"] = _pkg

from pinedog.schedule import AWAY_INTERVAL, RETURN_MIN_GAP, should_sync_on_return  # noqa: E402

NOW = datetime(2026, 11, 3, 22, 0, 0)


def test_staying_in_range_is_not_a_return():
    # Seen 10 seconds ago: the dog never left, so no sync.
    assert not should_sync_on_return(NOW, NOW - timedelta(seconds=10), None)


def test_coming_back_after_being_away_syncs_at_once():
    # Silent for 20 minutes, last sync 2 hours ago: a return, so sync now.
    last_seen = NOW - timedelta(minutes=20)
    last_attempt = NOW - timedelta(hours=2)
    assert should_sync_on_return(NOW, last_seen, last_attempt)


def test_just_out_of_the_away_window_is_not_yet_away():
    last_seen = NOW - AWAY_INTERVAL + timedelta(seconds=1)
    assert not should_sync_on_return(NOW, last_seen, None)


def test_edge_of_range_flicker_does_not_sync_repeatedly():
    # Away long enough, but a sync just ran: wait for the minimum gap.
    last_seen = NOW - timedelta(minutes=20)
    last_attempt = NOW - timedelta(minutes=1)
    assert not should_sync_on_return(NOW, last_seen, last_attempt)
    assert should_sync_on_return(NOW, last_seen, NOW - RETURN_MIN_GAP)


def test_first_sight_after_start_counts_as_return():
    # No advertisement seen since HA started: treat it as a return.
    assert should_sync_on_return(NOW, None, None)
