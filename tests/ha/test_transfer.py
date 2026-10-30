import asyncio
import struct
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Load the pure modules without running the package __init__, which needs Home Assistant.
PKG_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"
_pkg = types.ModuleType("pinedog")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["pinedog"] = _pkg

from pinedog.protocol import CLASS_UNSYNCED_FLAG, END_MARKER  # noqa: E402
from pinedog.schedule import RETRY_INTERVAL, SUCCESS_INTERVAL, should_attempt  # noqa: E402
from pinedog.transfer import run_transfer  # noqa: E402

REC = struct.Struct("<IHBB")


def _status(pending: int) -> bytes:
    # version 1, synced 1, pending, newest minute, battery unknown
    return struct.pack("<BBIIB", 1, 1, pending, 0, 0xFF)


def _chunk(*recs: tuple[int, int]) -> bytes:
    """Packs (minute, class) pairs into one Records notification."""
    return b"".join(REC.pack(minute, 0, cls, 0) for minute, cls in recs)


class FakeLink:
    """Records the order of GATT operations so tests can check it."""

    def __init__(self, pending=3, chunks=None, end=True, ack_error=None):
        self.pending = pending
        self.chunks = chunks if chunks is not None else [_chunk((100, 1), (101, 2))]
        self.end = end
        self.ack_error = ack_error
        self.calls: list = []
        self._on_data = None

    async def write_time(self, unix_s):
        self.calls.append(("time", unix_s))

    async def read_status(self):
        self.calls.append(("status",))
        return _status(self.pending)

    async def subscribe(self, on_data):
        self.calls.append(("subscribe",))
        self._on_data = on_data

    async def unsubscribe(self):
        self.calls.append(("unsubscribe",))

    async def request(self, from_minute):
        self.calls.append(("request", from_minute))
        for chunk in self.chunks:
            self._on_data(chunk)
        if self.end:
            self._on_data(bytes([END_MARKER]))

    async def write_ack(self, minute):
        self.calls.append(("ack", minute))
        if self.ack_error:
            raise self.ack_error


def _run(link, persist, timeout_s=1.0):
    return asyncio.run(run_transfer(link, 500, 1_700_000_000, persist, timeout_s=timeout_s))


def test_persists_before_acking_with_highest_minute():
    link = FakeLink()
    persisted = []

    async def persist(pairs):
        link.calls.append(("persist", len(pairs)))
        persisted.extend(pairs)

    assert _run(link, persist) == 2
    names = [c[0] for c in link.calls]
    assert names.index("persist") < names.index("ack")
    assert link.calls[-1] == ("ack", 2)
    assert [rec.minute for rec, _ in persisted] == [100, 101]


def test_no_ack_when_persist_fails():
    link = FakeLink()

    async def persist(pairs):
        raise OSError("disk full")

    with pytest.raises(OSError):
        _run(link, persist)
    assert not any(c[0] == "ack" for c in link.calls)


def test_no_ack_when_end_marker_never_arrives():
    link = FakeLink(end=False)

    async def persist(pairs):
        raise AssertionError("must not persist a partial transfer")

    with pytest.raises(asyncio.TimeoutError):
        _run(link, persist, timeout_s=0.01)
    assert not any(c[0] == "ack" for c in link.calls)
    assert ("unsubscribe",) in link.calls


def test_ack_is_a_count_even_when_minutes_go_backwards():
    # After a reboot, uptime minutes restart at zero. A minute ack would
    # release the wrong records here. A count does not depend on minutes.
    link = FakeLink(chunks=[_chunk((900, 1), (3, 1), (4, 1))])

    async def persist(pairs):
        pass

    assert _run(link, persist) == 3
    assert link.calls[-1] == ("ack", 3)


def test_nothing_pending_skips_the_transfer():
    link = FakeLink(pending=0)

    async def persist(pairs):
        raise AssertionError("nothing to persist")

    assert _run(link, persist) == 0
    assert [c[0] for c in link.calls] == ["time", "status"]


def test_unsynced_records_are_persisted_and_acked():
    # Records made before the clock was set carry the unsynced bit. They must
    # still be acked, or they stay in the ring forever.
    link = FakeLink(chunks=[_chunk((7, CLASS_UNSYNCED_FLAG | 1))])
    seen = []

    async def persist(pairs):
        seen.extend(pairs)

    assert _run(link, persist) == 1
    assert seen[0][0].minute == 7
    assert seen[0][1] is False  # not synced, so the coordinator drops it
    assert link.calls[-1] == ("ack", 1)


def test_schedule_gates_attempts():
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    assert should_attempt(now, None, False)
    assert not should_attempt(now, now - timedelta(minutes=10), False)
    assert should_attempt(now, now - SUCCESS_INTERVAL, False)
    # After a failure, retry sooner, but not on every advertisement.
    assert not should_attempt(now, now - timedelta(seconds=30), True)
    assert should_attempt(now, now - RETRY_INTERVAL, True)
