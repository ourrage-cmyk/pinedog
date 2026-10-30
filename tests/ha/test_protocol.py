import struct
import sys
import types
from pathlib import Path

import pytest

# Load the pure modules without running the package __init__, which needs Home Assistant.
PKG_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"
_pkg = types.ModuleType("pinedog")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["pinedog"] = _pkg

from pinedog.protocol import (  # noqa: E402
    BATTERY_UNKNOWN, BOOT_SHIFT, END_MARKER, FLAG_CHARGING, FLAG_CLOCK_SYNCED,
    UNSYNCED_FLAG, crc8, decode_chunk, decode_status, encode_u32, is_end_marker,
)

STATUS = struct.Struct("<BBIIIBB")


def _status(version=2, flags=FLAG_CLOCK_SYNCED, pending=42, newest=26000000,
            uptime=3600, boot=5, battery=87):
    return STATUS.pack(version, flags, pending, newest, uptime, boot, battery)


def _record(minute, counts, cls_byte):
    """Packs one record with a correct CRC, as the firmware does."""
    covered = struct.pack("<IHB", minute, counts, cls_byte)
    return covered + bytes([crc8(covered)])


def test_crc8_matches_smbus_check_value():
    # CRC-8 (poly 0x07, init 0) of "123456789" is 0xF4, the standard check value.
    assert crc8(b"123456789") == 0xF4


def test_encode_u32_little_endian():
    assert encode_u32(0x01020304) == b"\x04\x03\x02\x01"


def test_decode_status_v2_fields():
    st = decode_status(_status(flags=FLAG_CLOCK_SYNCED | FLAG_CHARGING))
    assert st.clock_synced and st.charging and not st.power_present
    assert st.pending == 42 and st.battery_pct == 87
    assert st.uptime_s == 3600 and st.boot_id == 5
    assert st.newest_minute == 26000000


def test_decode_status_unknown_battery():
    assert decode_status(_status(battery=BATTERY_UNKNOWN)).battery_pct is None


def test_decode_status_rejects_other_version():
    with pytest.raises(ValueError):
        decode_status(_status(version=1))


def test_decode_status_rejects_wrong_length():
    with pytest.raises(ValueError):
        decode_status(_status()[:15])


def test_end_marker():
    assert is_end_marker(bytes([END_MARKER]))
    assert not is_end_marker(b"\x00" * 8)


def test_chunk_checks_crc_and_splits_class_bits():
    good = _record(100, 5, 1)
    unsynced = _record(7, 9, UNSYNCED_FLAG | (3 << BOOT_SHIFT) | 2)
    out = decode_chunk(good + unsynced)
    assert out[0].crc_ok and not out[0].unsynced and out[0].activity_class == 1
    assert out[1].unsynced and out[1].boot_id == 3 and out[1].activity_class == 2
    assert out[1].minute == 7 and out[1].crc_ok


def test_chunk_flags_a_bad_crc():
    bad = bytearray(_record(100, 5, 1))
    bad[2] ^= 0x10  # flip a bit in the counts field
    out = decode_chunk(bytes(bad))
    assert not out[0].crc_ok


def test_chunk_rejects_partial_record():
    with pytest.raises(ValueError):
        decode_chunk(b"\x00" * 9)


def test_sync_request_flag_in_manufacturer_data():
    from pinedog.protocol import sync_requested

    assert sync_requested({0xFFFF: bytes([0x01])})
    assert not sync_requested({0xFFFF: bytes([0x00])})
    assert not sync_requested({0x004C: bytes([0x01])})
    assert not sync_requested({})
