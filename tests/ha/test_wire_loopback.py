"""Loopback: the bytes the firmware encoder writes are decoded and stored by HA.

fixtures/wire_v2.bin is written by `make -C firmware fixture` (test/wire_fixture.c),
which calls the same pd_record_crc() the watch uses. This test feeds those bytes
through the Home Assistant decoder and transfer logic, the same path a live sync
takes after the notifications arrive. The BLE radio and the Zephyr notify loop
are not covered here; they need the watch.
"""

import asyncio
import struct
import sys
import types
from datetime import timezone
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"
_pkg = types.ModuleType("pinedog")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["pinedog"] = _pkg

from pinedog.activity import LIGHT, NOT_WORN, WALK, daily_totals  # noqa: E402
from pinedog.protocol import decode_chunk  # noqa: E402
from pinedog.transfer import run_transfer  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "wire_v2.bin"
NOW_UNIX = 1_700_000_000
STATUS = struct.Struct("<BBIIIBB")


def _split():
    raw = FIXTURE.read_bytes()
    return raw[:24], raw[24:]  # three 8-byte records, then the end marker


class Replay:
    """A link that replays captured notifications, as the watch would send them."""

    def __init__(self, records: bytes, end: bytes, pending: int = 3):
        self.records, self.end = records, end
        self.pending = pending
        self.acks: list[int] = []
        self._on_data = None

    async def write_time(self, unix_s):
        pass

    async def read_status(self):
        return STATUS.pack(2, 0b1, self.pending, 28_333_333, 3600, 5, 87)

    async def subscribe(self, on_data):
        self._on_data = on_data

    async def unsubscribe(self):
        pass

    async def request(self):
        self._on_data(self.records)
        self._on_data(self.end)

    async def write_ack(self, count):
        self.acks.append(count)


def _transfer(records, end, pending=3):
    link = Replay(records, end, pending)
    stored = []

    async def persist(recs):
        stored.extend(recs)

    result = asyncio.run(run_transfer(link, NOW_UNIX, persist, timeout_s=1))
    return result, stored, link


def test_firmware_bytes_decode_and_store_end_to_end():
    records, end = _split()
    result, stored, link = _transfer(records, end)

    assert result.acked and result.corrupt == 0 and result.unplaced == 0
    assert link.acks == [3]
    assert [r.activity_class for r in stored] == [WALK, LIGHT, NOT_WORN]
    assert stored[0].minute == 28_000_000
    # Unsynced record from boot 5, uptime minute 10, placed against the sync time.
    assert stored[1].minute == (NOW_UNIX - (3600 - 10 * 60)) // 60


def test_not_worn_minutes_are_left_out_of_totals():
    records, end = _split()
    _, stored, _ = _transfer(records, end)
    totals = daily_totals(stored, timezone.utc).values()
    # Light and walk are active; walk is also walking. The NOT_WORN minute counts for nothing.
    assert sum(t.active_minutes for t in totals) == 2
    assert sum(t.sedentary_minutes for t in totals) == 0
    assert sum(t.walking_minutes for t in totals) == 1


def test_flipped_bit_on_the_wire_is_dropped_and_still_acked():
    records, end = _split()
    damaged = bytearray(records)
    damaged[2] ^= 0x01  # first record, counts field
    result, stored, link = _transfer(bytes(damaged), end)

    assert result.corrupt == 1
    assert len(stored) == 2
    assert link.acks == [3]  # the watch released all three; the bad one is not kept


def test_end_count_must_match_what_arrived():
    records, _ = _split()
    short_end = bytes([0xEE]) + struct.pack("<I", 2)  # watch says 2, sent 3
    result, stored, link = _transfer(records, short_end)

    assert not result.acked and stored == [] and link.acks == []
