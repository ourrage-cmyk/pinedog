"""One sync with a Pinedog watch, as pure logic.

The order of steps is the safety property here: records are persisted before
the watch is acked, and the watch is acked with a count, so it drops exactly
the records that were stored. Nothing in this module imports Bluetooth or Home
Assistant, so the order can be tested with a fake link.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from .activity import KNOWN_CLASSES, Record
from .protocol import Status, WireRecord, decode_chunk, decode_end_count, decode_status, is_end_marker

TRANSFER_TIMEOUT_S = 120
# Home Assistant has no RTC on a Pi. A clock before this is not set yet, so do not sync.
MIN_PLAUSIBLE_UNIX = 1_672_531_200  # 2023-01-01T00:00:00Z
# A record more than this many minutes ahead of the clock is treated as corrupt time.
FUTURE_SLACK_MINUTES = 5

PersistFn = Callable[[list[Record]], Awaitable[None]]


class Link(Protocol):
    """The GATT operations one sync needs. The BLE adapter implements this."""

    async def write_time(self, unix_s: int) -> None: ...

    async def read_status(self) -> bytes: ...

    async def subscribe(self, on_data: Callable[[bytes], None]) -> None: ...

    async def unsubscribe(self) -> None: ...

    async def request(self) -> None: ...

    async def write_ack(self, count: int) -> None: ...


class IncompleteTransfer(RuntimeError):
    """The watch sent fewer records than it had, so nothing was acked."""


class ClockError(RuntimeError):
    """Home Assistant's own clock is not set, so no record can be placed in time."""


@dataclass(frozen=True)
class TransferResult:
    status: Status | None
    received: int  # records the watch sent
    stored: int  # records persisted
    corrupt: int  # failed the CRC check or the end count, dropped
    unplaced: int  # could not be placed in time (unknown boot, or in the future)
    acked: bool = False  # False when the transfer was incomplete and nothing was acked


class RecordCollector:
    """Collects Records notifications until the end marker arrives."""

    def __init__(self) -> None:
        self.records: list[WireRecord] = []
        self.end_count: int | None = None
        self.finished = asyncio.Event()

    def feed(self, data: bytes) -> None:
        if is_end_marker(data):
            self.end_count = decode_end_count(data)
            self.finished.set()
            return
        self.records.extend(decode_chunk(data))


def place_unsynced(minute: int, boot_id: int, status: Status, sync_unix: int) -> int | None:
    """Unix minute for a record made before the clock was set, or None.

    Uptime minutes restart at zero on every boot, so a record can only be
    placed in time if it was made on the watch's current boot. The offset is
    the Unix time of boot, which is the sync time minus the uptime at sync.
    """
    if boot_id != status.boot_id or minute * 60 > status.uptime_s:
        return None
    start_unix = sync_unix - (status.uptime_s - minute * 60)
    return start_unix // 60


async def run_transfer(
    link: Link,
    now_unix: int,
    persist: PersistFn,
    timeout_s: float = TRANSFER_TIMEOUT_S,
) -> TransferResult:
    """Pull everything the watch still holds, store it, then ack it.

    The ack is the number of records the watch sent. The watch releases its
    oldest records by that count, so an ack never names a minute that could
    repeat after a reboot. If the link drops, the end marker never arrives, or
    persist() raises, the watch is not acked and keeps its records.
    """
    if now_unix < MIN_PLAUSIBLE_UNIX:
        raise ClockError("Home Assistant clock is not set, not syncing")
    await link.write_time(now_unix)
    status = decode_status(await link.read_status())
    if status.pending == 0:
        return TransferResult(status, 0, 0, 0, 0, acked=False)

    collector = RecordCollector()
    await link.subscribe(collector.feed)
    try:
        await link.request()
        await asyncio.wait_for(collector.finished.wait(), timeout=timeout_s)
    finally:
        await link.unsubscribe()

    wire = collector.records
    # The ack is a count of the oldest records. It is only safe when the watch
    # sent every record it had: all of them, and at least the pending count read
    # earlier. Anything else is a short or damaged stream, so nothing is acked.
    if collector.end_count != len(wire) or len(wire) < status.pending:
        return TransferResult(status, len(wire), 0, 0, 0, acked=False)

    records: list[Record] = []
    corrupt = unplaced = 0
    latest = now_unix // 60 + FUTURE_SLACK_MINUTES
    for rec in wire:
        if not rec.crc_ok or rec.activity_class not in KNOWN_CLASSES:
            corrupt += 1
            continue
        minute = rec.minute
        if rec.unsynced:
            placed = place_unsynced(rec.minute, rec.boot_id, status, now_unix)
            if placed is None:
                unplaced += 1
                continue
            minute = placed
        if minute > latest:
            # A clock error on the watch would otherwise move the dedupe cursor into the future.
            unplaced += 1
            continue
        records.append(Record(minute, rec.counts, rec.activity_class))

    # Durable on our side first. Acking before this point could lose records.
    await persist(records)
    await link.write_ack(len(wire))
    return TransferResult(status, len(wire), len(records), corrupt, unplaced, acked=True)
