"""When to try a BLE sync. Pure logic, no Home Assistant imports."""

from __future__ import annotations

from datetime import datetime, timedelta

SUCCESS_INTERVAL = timedelta(minutes=30)
RETRY_INTERVAL = timedelta(minutes=5)


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



def synced_recently(now: datetime, last_sync: datetime | None, window: timedelta) -> bool:
    """True when this watch synced successfully within the window, so it can be skipped.

    Stock collars use the motion cap as the window. Any longer gap between syncs is
    credited as unknown, not as motion, so a skip must never stretch the gap past the cap.
    """
    if last_sync is None:
        return False
    return now - last_sync < window
