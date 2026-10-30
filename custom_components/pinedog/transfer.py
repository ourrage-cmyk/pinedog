"""One sync with a Pinedog watch, as pure logic.

The order of steps is the safety property here: records are persisted before
the watch is acked, and the watch is only acked with records that were
persisted. Nothing in this module imports Bluetooth or Home Assistant, so the
order can be tested with a fake link.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from .activity import Record
from .protocol import decode_chunk, decode_status, is_end_marker

TRANSFER_TIMEOUT_S = 120

Pairs = list[tuple[Record, bool]]
PersistFn = Callable[[Pairs], Awaitable[None]]


class Link(Protocol):
    """The GATT operations one sync needs. The BLE adapter implements this."""

    async def write_time(self, unix_s: int) -> None: ...

    async def read_status(self) -> bytes: ...

    async def subscribe(self, on_data: Callable[[bytes], None]) -> None: ...

    async def unsubscribe(self) -> None: ...

    async def request(self, from_minute: int) -> None: ...

    async def write_ack(self, minute: int) -> None: ...


class RecordCollector:
    """Collects Records notifications until the end marker arrives."""

    def __init__(self) -> None:
        self.pairs: Pairs = []
        self.finished = asyncio.Event()

    def feed(self, data: bytes) -> None:
        if is_end_marker(data):
            self.finished.set()
            return
        self.pairs.extend(decode_chunk(data))


async def run_transfer(
    link: Link,
    from_minute: int,
    now_unix: int,
    persist: PersistFn,
    timeout_s: float = TRANSFER_TIMEOUT_S,
) -> int:
    """Pull everything the watch still holds, store it, then ack it.

    Returns the number of records received. If the link drops, the end marker
    never arrives, or persist() raises, the watch is not acked and keeps its
    records for the next sync.
    """
    await link.write_time(now_unix)
    status = decode_status(await link.read_status())
    if status.pending == 0:
        return 0

    collector = RecordCollector()
    await link.subscribe(collector.feed)
    try:
        await link.request(from_minute)
        await asyncio.wait_for(collector.finished.wait(), timeout=timeout_s)
    finally:
        await link.unsubscribe()

    pairs = collector.pairs
    if not pairs:
        return 0
    # Durable on our side first. Acking before this point could lose records.
    await persist(pairs)
    await link.write_ack(max(rec.minute for rec, _ in pairs))
    return len(pairs)
