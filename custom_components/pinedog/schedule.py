"""When to try a BLE sync. Pure logic, no Home Assistant imports."""

from __future__ import annotations

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
