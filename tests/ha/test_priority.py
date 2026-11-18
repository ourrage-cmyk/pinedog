"""The collar that has gone longest without a sync goes first. Pure logic, no Home Assistant."""

import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"
_pkg = types.ModuleType("pinedog")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["pinedog"] = _pkg

from pinedog.schedule import (  # noqa: E402
    RETRY_INTERVAL,
    STALE_RETRY_INTERVAL,
    YIELD_LIMIT,
    Candidate,
    pick_next,
    retry_interval_for,
)

NOW = datetime(2026, 11, 18, 17, 0, 0)
M = timedelta(minutes=1)


def _c(key, synced_ago, due=True, reachable=True, heard_ago=timedelta(seconds=5)):
    return Candidate(
        key,
        None if synced_ago is None else NOW - synced_ago,
        due,
        reachable,
        None if heard_ago is None else NOW - heard_ago,
    )


def test_the_stalest_reachable_collar_goes_first():
    kida = _c("kida", 2 * M)
    bridget = _c("bridget", 19 * 60 * M)
    assert pick_next(NOW, [kida, bridget]) == "bridget"


def test_never_synced_is_stalest():
    assert pick_next(NOW, [_c("kida", 19 * 60 * M), _c("new", None)]) == "new"


def test_a_fresh_collar_waits_while_a_stale_one_at_home_is_between_adverts():
    kida = _c("kida", 40 * M)
    bridget = _c("bridget", 19 * 60 * M, reachable=False, heard_ago=3 * M)
    assert pick_next(NOW, [kida, bridget]) is None


def test_a_stale_collar_that_is_away_does_not_block_the_other():
    kida = _c("kida", 40 * M)
    bridget = _c("bridget", 19 * 60 * M, reachable=False, heard_ago=3 * 60 * M)
    assert pick_next(NOW, [kida, bridget]) == "kida"


def test_waiting_has_a_limit():
    kida = _c("kida", YIELD_LIMIT)
    bridget = _c("bridget", 19 * 60 * M, reachable=False, heard_ago=3 * M)
    assert pick_next(NOW, [kida, bridget]) == "kida"


def test_a_collar_that_is_not_due_is_skipped():
    kida = _c("kida", 40 * M)
    bridget = _c("bridget", 19 * 60 * M, due=False)
    assert pick_next(NOW, [kida, bridget]) == "kida"


def test_stale_collars_are_retried_sooner():
    assert retry_interval_for(NOW, NOW - 19 * 60 * M) == STALE_RETRY_INTERVAL
    assert retry_interval_for(NOW, None) == STALE_RETRY_INTERVAL
    assert retry_interval_for(NOW, NOW - 10 * M) == RETRY_INTERVAL
