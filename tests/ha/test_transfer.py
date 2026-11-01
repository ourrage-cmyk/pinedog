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

from pinedog.protocol import BOOT_SHIFT, UNSYNCED_FLAG, crc8  # noqa: E402
from pinedog.schedule import RETRY_INTERVAL, SUCCESS_INTERVAL, should_attempt  # noqa: E402
from pinedog.transfer import ClockError, place_unsynced, run_transfer  # noqa: E402
from pinedog.protocol import decode_status  # noqa: E402

STATUS = struct.Struct("<BBIIIBB")
SYNC_UNIX = 1_700_000_000


def _status(pending: int, uptime: int = 3600, boot: int = 5) -> bytes:
    return STATUS.pack(2, 1, pending, 0, uptime, boot, 0xFF)


def _record(minute: int, cls_byte: int, counts: int = 10, bad_crc: bool = False) -> bytes:
    covered = struct.pack("<IHB", minute, counts, cls_byte)
    crc = crc8(covered) ^ (0x01 if bad_crc else 0)
    return covered + bytes([crc])


def _chunk(*records: bytes) -> bytes:
    return b"".join(records)


class FakeLink:
    """Records the order of GATT operations so tests can check it."""

    def __init__(self, pending=None, chunks=None, end=True, ack_error=None, end_count=None):
        self.chunks = chunks if chunks is not None else [_chunk(_record(100, 1), _record(101, 2))]
        total = sum(len(c) // 8 for c in self.chunks)
        self.pending = total if pending is None else pending
        self.end_count = total if end_count is None else end_count
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

    async def request(self):
        self.calls.append(("request",))
        for chunk in self.chunks:
            self._on_data(chunk)
        if self.end:
            self._on_data(bytes([0xEE]) + struct.pack("<I", self.end_count))

    async def write_ack(self, count):
        self.calls.append(("ack", count))
        if self.ack_error:
            raise self.ack_error


def _run(link, persist, timeout_s=1.0):
    return asyncio.run(run_transfer(link, SYNC_UNIX, persist, timeout_s=timeout_s))


def test_persists_before_acking_with_the_record_count():
    link = FakeLink()
    persisted = []

    async def persist(records):
        link.calls.append(("persist", len(records)))
        persisted.extend(records)

    result = _run(link, persist)
    assert result.received == 2 and result.stored == 2
    names = [c[0] for c in link.calls]
    assert names.index("persist") < names.index("ack")
    assert link.calls[-1] == ("ack", 2)
    assert [r.minute for r in persisted] == [100, 101]


def test_no_ack_when_persist_fails():
    link = FakeLink()

    async def persist(records):
        raise OSError("disk full")

    with pytest.raises(OSError):
        _run(link, persist)
    assert not any(c[0] == "ack" for c in link.calls)


def test_no_ack_when_end_marker_never_arrives():
    link = FakeLink(end=False)

    async def persist(records):
        raise AssertionError("must not persist a partial transfer")

    with pytest.raises(asyncio.TimeoutError):
        _run(link, persist, timeout_s=0.01)
    assert not any(c[0] == "ack" for c in link.calls)
    assert ("unsubscribe",) in link.calls


def test_ack_is_a_count_even_when_minutes_go_backwards():
    # After a reboot, uptime minutes restart at zero. The ack is a count, so
    # it does not depend on the minute values the watch sends.
    link = FakeLink(
        chunks=[_chunk(_record(900, 1), _record(3, 1), _record(4, 1))],
        pending=3,
    )

    async def persist(records):
        pass

    assert _run(link, persist).received == 3
    assert link.calls[-1] == ("ack", 3)


def test_corrupt_records_are_acked_but_not_stored():
    link = FakeLink(chunks=[_chunk(_record(100, 1), _record(101, 1, bad_crc=True))])
    seen = []

    async def persist(records):
        seen.extend(records)

    result = _run(link, persist)
    assert [r.minute for r in seen] == [100]
    assert result.corrupt == 1
    assert link.calls[-1] == ("ack", 2)  # released from the watch, not kept forever


def test_end_count_mismatch_is_not_acked():
    link = FakeLink(pending=2, end_count=3)

    async def persist(records):
        raise AssertionError("must not persist an inconsistent stream")

    result = _run(link, persist)
    assert not result.acked
    assert not any(c[0] == "ack" for c in link.calls)


def test_clock_not_set_refuses_to_sync():
    link = FakeLink()

    async def persist(records):
        raise AssertionError("no sync with an unset clock")

    with pytest.raises(ClockError):
        asyncio.run(run_transfer(link, 0, persist, timeout_s=0.1))
    assert link.calls == []


def test_future_dated_record_is_not_stored():
    # A watch with a wrong clock must not move the dedupe cursor into the future.
    link = FakeLink(chunks=[_chunk(_record(SYNC_UNIX // 60 + 10_000, 1), _record(100, 1))])
    seen = []

    async def persist(records):
        seen.extend(records)

    result = _run(link, persist)
    assert [r.minute for r in seen] == [100]
    assert result.unplaced == 1 and result.acked


def test_nothing_pending_skips_the_transfer():
    link = FakeLink(pending=0)

    async def persist(records):
        raise AssertionError("nothing to persist")

    assert _run(link, persist).received == 0
    assert [c[0] for c in link.calls] == ["time", "status"]


def test_unsynced_record_on_current_boot_is_placed_in_unix_time():
    # Watch uptime 3600 s at sync. A record from uptime minute 10 started
    # 3600 - 600 = 3000 s before the sync.
    cls_byte = UNSYNCED_FLAG | (5 << BOOT_SHIFT) | 1
    link = FakeLink(chunks=[_chunk(_record(10, cls_byte))])
    seen = []

    async def persist(records):
        seen.extend(records)

    _run(link, persist)
    assert seen[0].minute == (SYNC_UNIX - 3000) // 60
    assert seen[0].activity_class == 1
    assert link.calls[-1] == ("ack", 1)


def test_unsynced_record_from_an_older_boot_is_acked_but_not_stored():
    cls_byte = UNSYNCED_FLAG | (4 << BOOT_SHIFT) | 1  # boot 4, watch is on boot 5
    link = FakeLink(chunks=[_chunk(_record(10, cls_byte))])

    async def persist(records):
        assert records == []

    result = _run(link, persist)
    assert result.unplaced == 1 and result.stored == 0
    assert link.calls[-1] == ("ack", 1)


def test_place_unsynced_rejects_minute_past_uptime():
    st = decode_status(_status(pending=1, uptime=600))
    assert place_unsynced(11, 5, st, SYNC_UNIX) is None


def test_schedule_gates_attempts():
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    assert should_attempt(now, None, False)
    assert not should_attempt(now, now - timedelta(minutes=10), False)
    assert should_attempt(now, now - SUCCESS_INTERVAL, False)
    # After a failure, retry sooner, but not on every advertisement.
    assert not should_attempt(now, now - timedelta(seconds=30), True)
    assert should_attempt(now, now - RETRY_INTERVAL, True)


def test_short_stream_is_not_acked():
    """Status says 5 records pending but only 2 arrived before the end marker.

    Ack is a count of the oldest records, so acking 2 after a lost middle
    chunk would drop the wrong records on the watch. HA must not ack a stream
    that is shorter than the pending count it read.
    """
    link = FakeLink(pending=5)  # default chunks carry 2 records

    async def persist(records):
        pass

    _run(link, persist)
    assert not any(c[0] == "ack" for c in link.calls)
