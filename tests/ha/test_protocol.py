import struct
import sys
from pathlib import Path

import pytest

import types

# Load the pure modules without running the package __init__, which needs Home Assistant.
PKG_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"
_pkg = types.ModuleType("pinedog")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["pinedog"] = _pkg

from pinedog.protocol import (  # noqa: E402
    BATTERY_UNKNOWN, CLASS_UNSYNCED_FLAG, END_MARKER, decode_chunk,
    decode_status, encode_u32, is_end_marker,
)


def test_encode_u32_little_endian():
    assert encode_u32(0x01020304) == b"\x04\x03\x02\x01"


def test_decode_status_fields():
    raw = struct.pack("<BBIIB", 1, 1, 42, 26000000, 87)
    st = decode_status(raw)
    assert st.synced and st.pending == 42 and st.battery_pct == 87
    assert st.newest_minute == 26000000


def test_decode_status_unknown_battery():
    raw = struct.pack("<BBIIB", 1, 0, 0, 0, BATTERY_UNKNOWN)
    assert decode_status(raw).battery_pct is None


def test_decode_status_rejects_other_version():
    with pytest.raises(ValueError):
        decode_status(struct.pack("<BBIIB", 2, 1, 0, 0, 0))


def test_end_marker():
    assert is_end_marker(bytes([END_MARKER]))
    assert not is_end_marker(b"\x00" * 8)


def test_chunk_unsynced_flag_is_split_out():
    synced = struct.pack("<IHBB", 100, 5, 1, 0)
    unsynced = struct.pack("<IHBB", 101, 9, 2 | CLASS_UNSYNCED_FLAG, 18)
    out = decode_chunk(synced + unsynced)
    assert out[0][1] is True and out[0][0].activity_class == 1
    assert out[1][1] is False and out[1][0].activity_class == 2
    assert out[1][0].cadence == 18
