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

# The stream is judged by progress, not by total time. A collar that could not sync for
# days holds many thousands of records, and a fixed limit failed every sync of such a
# backlog, so the backlog only grew. The watch itself gives up after 30 s without progress.
STALL_TIMEOUT_S = 45
# Upper bound for one transfer, so a watch that trickles forever cannot hold the adapter.
TRANSFER_TIMEOUT_S = 1800
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


class SyncFailed(RuntimeError):
    """A sync that stopped at a known stage. str() is the one-line reason the UI shows.

    Stages, in the order a sync reaches them: "not seen" (no advertisement in range),
    "connect", "GATT" (a read, write or subscribe failed), "clock", "transfer" (no end
    of stream, or fewer records than the watch reported), "store" (our side failed
    before the ack). "error" is anything else.
    """

    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(f"{stage}: {detail}")
        self.stage = stage
        self.detail = detail


class IncompleteTransfer(SyncFailed):
    """The watch sent fewer records than it had, so nothing was acked."""

    def __init__(self, detail: str) -> None:
        super().__init__("transfer", detail)


class ClockError(SyncFailed):
    """Home Assistant's own clock is not set, so no record can be placed in time."""

    def __init__(self, detail: str) -> None:
        super().__init__("clock", detail)


class GattError(RuntimeError):
    """A GATT read, write or subscribe failed on the link."""


def describe(err: BaseException) -> str:
    """The message of an error, or its type name when it has none (asyncio timeouts have none)."""
    return str(err) or type(err).__name__


def stage_failure(err: BaseException) -> SyncFailed:
    """The SyncFailed for an error raised during a sync."""
    if isinstance(err, SyncFailed):
        return err
    if isinstance(err, GattError):
        return SyncFailed("GATT", describe(err))
    if isinstance(err, TimeoutError):
        return SyncFailed("transfer", "no end of stream: the watch stopped answering")
    return SyncFailed("error", describe(err))


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


async def _wait_for_stream(
    collector: RecordCollector, pending: int, stall_s: float, max_s: float
) -> None:
    """Wait for the end marker for as long as records keep arriving."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_s
    seen = -1
    while not collector.finished.is_set():
        got = len(collector.records)
        if got == seen:
            raise SyncFailed(
                "transfer", f"stream stalled after {got} of {pending} records, nothing acked"
            )
        if loop.time() >= deadline:
            raise SyncFailed(
                "transfer", f"stream not finished in {int(max_s)} s ({got} of {pending} records)"
            )
        seen = got
        try:
            await asyncio.wait_for(collector.finished.wait(), timeout=stall_s)
        except TimeoutError:
            pass


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
    timeout_s: float = STALL_TIMEOUT_S,
    max_s: float = TRANSFER_TIMEOUT_S,
) -> TransferResult:
    """Pull everything the watch still holds, store it, then ack it.

    The ack is the number of records the watch sent. The watch releases its
    oldest records by that count, so an ack never names a minute that could
    repeat after a reboot. If the link drops, the end marker never arrives, or
    persist() raises, the watch is not acked and keeps its records.

    timeout_s is how long the stream may make no progress. max_s bounds the whole stream.
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
        await _wait_for_stream(collector, status.pending, timeout_s, max_s)
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
    try:
        await persist(records)
    except Exception as err:  # noqa: BLE001 - name the stage, then let it propagate
        raise SyncFailed("store", describe(err)) from err
    await link.write_ack(len(wire))
    return TransferResult(status, len(wire), len(records), corrupt, unplaced, acked=True)
