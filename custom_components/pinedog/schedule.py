"""When to try a BLE sync. Pure logic, no Home Assistant imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

SUCCESS_INTERVAL = timedelta(minutes=30)
RETRY_INTERVAL = timedelta(minutes=5)
# A collar silent for this long has left range. Its return triggers a sync.
AWAY_INTERVAL = timedelta(minutes=5)
# Never start a return sync sooner than this after the last attempt (edge-of-range flicker).
RETURN_MIN_GAP = timedelta(minutes=5)


def should_attempt(
    now: datetime,
    last_attempt: datetime | None,
    last_failed: bool,
    success_interval: timedelta = SUCCESS_INTERVAL,
    retry_interval: timedelta = RETRY_INTERVAL,
) -> bool:
    """Gate connection attempts.

    Each attempt costs the watch a connection and costs us time, and a dog out
    of range generates advertisements all day. After a success, wait the full
    interval. After a failure, retry sooner, but never on every advertisement.
    """
    if last_attempt is None:
        return True
    interval = retry_interval if last_failed else success_interval
    return now - last_attempt >= interval


def should_sync_on_return(
    now: datetime,
    last_seen: datetime | None,
    last_attempt: datetime | None,
    away: timedelta = AWAY_INTERVAL,
    min_gap: timedelta = RETURN_MIN_GAP,
) -> bool:
    """True when the collar has just come back into range after being away.

    A dog that stays in range keeps advertising, so it never counts as a return.
    A dog that goes out and comes back does, and its records sync at once. The
    minimum gap stops a collar at the edge of range from syncing on every flicker.
    """
    if last_seen is not None and now - last_seen < away:
        return False
    return last_attempt is None or now - last_attempt >= min_gap


# A collar whose last good sync is older than this is stale. It gets the radio first and
# is retried every STALE_RETRY_INTERVAL instead of every RETRY_INTERVAL.
STALE_AFTER = timedelta(hours=1)
STALE_RETRY_INTERVAL = timedelta(minutes=1)
# While a stale collar is at home and waiting for a sync, the others hold back, unless
# their own last sync is older than this. So a stale collar cannot block the rest forever.
YIELD_LIMIT = timedelta(hours=2)
# A collar heard within this long is at home, so it is worth holding the radio for.
AT_HOME_WINDOW = timedelta(minutes=10)


def is_stale(now: datetime, last_sync: datetime | None, stale_after: timedelta = STALE_AFTER) -> bool:
    return last_sync is None or now - last_sync >= stale_after


def retry_interval_for(now: datetime, last_sync: datetime | None) -> timedelta:
    """How soon to try again after a failed attempt. Stale collars are retried much sooner."""
    return STALE_RETRY_INTERVAL if is_stale(now, last_sync) else RETRY_INTERVAL


@dataclass(frozen=True)
class Candidate:
    """One collar as the scheduler sees it at this moment."""

    key: str
    last_sync: datetime | None
    due: bool  # the collar's own schedule (or a request) wants a sync now
    reachable: bool  # advertised a few seconds ago, so a connection can start now
    last_heard: datetime | None  # last advertisement, to tell at home from away


def _staleness(now: datetime, c: Candidate) -> timedelta:
    # Never synced counts as the stalest of all.
    return timedelta.max if c.last_sync is None else now - c.last_sync


def pick_next(
    now: datetime,
    candidates: list[Candidate],
    yield_limit: timedelta = YIELD_LIMIT,
    at_home: timedelta = AT_HOME_WINDOW,
) -> str | None:
    """The collar to sync now, or None.

    The collar that has gone longest without a sync always goes first. When that collar is
    stale, due and at home but just not reachable this second (it advertises only every few
    minutes while its screen sleeps), the others wait for it, so a quick sync of the fresh
    collar does not hold the radio at the moment the stale one is heard. A collar that has
    itself gone YIELD_LIMIT without a sync stops waiting.
    """
    ordered = sorted(candidates, key=lambda c: _staleness(now, c), reverse=True)
    waiting_for: Candidate | None = None
    for c in ordered:
        if not c.due:
            continue
        if waiting_for is not None and _staleness(now, c) < yield_limit:
            continue
        if c.reachable:
            return c.key
        if (
            waiting_for is None
            and is_stale(now, c.last_sync)
            and c.last_heard is not None
            and now - c.last_heard <= at_home
        ):
            waiting_for = c
    return None
