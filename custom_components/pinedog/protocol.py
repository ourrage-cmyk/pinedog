"""Wire format for the Pinedog BLE sync. Must match firmware/app/src/ble_sync.c."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .activity import KNOWN_CLASSES, RECORD_SIZE, Record, decode_records

SERVICE_UUID = "5d0f0000-7e0d-4a8b-9d2a-0a1e0c0d0000"
TIME_UUID = "5d0f0001-7e0d-4a8b-9d2a-0a1e0c0d0000"
STATUS_UUID = "5d0f0002-7e0d-4a8b-9d2a-0a1e0c0d0000"
REQUEST_UUID = "5d0f0003-7e0d-4a8b-9d2a-0a1e0c0d0000"
RECORDS_UUID = "5d0f0004-7e0d-4a8b-9d2a-0a1e0c0d0000"
ACK_UUID = "5d0f0005-7e0d-4a8b-9d2a-0a1e0c0d0000"

PROTOCOL_VERSION = 1
END_MARKER = 0xEE
CLASS_UNSYNCED_FLAG = 0x80
BATTERY_UNKNOWN = 0xFF

_STATUS = struct.Struct("<BBIIB")  # version, synced, pending, newest_minute, battery


@dataclass(frozen=True)
class Status:
    version: int
    synced: bool
    pending: int
    newest_minute: int
    battery_pct: int | None


def encode_u32(value: int) -> bytes:
    return struct.pack("<I", value)


def decode_status(data: bytes) -> Status:
    if len(data) != _STATUS.size:
        raise ValueError(f"status is {len(data)} bytes, expected {_STATUS.size}")
    version, synced, pending, newest, battery = _STATUS.unpack(data)
    if version != PROTOCOL_VERSION:
        raise ValueError(f"unsupported protocol version {version}")
    return Status(
        version=version,
        synced=bool(synced),
        pending=pending,
        newest_minute=newest,
        battery_pct=None if battery == BATTERY_UNKNOWN else battery,
    )


def is_end_marker(data: bytes) -> bool:
    return len(data) == 1 and data[0] == END_MARKER


def decode_chunk(data: bytes) -> list[tuple[Record, bool]]:
    """Decode one Records notification.

    Returns (record, clock_synced) pairs. The unsynced flag is removed from the
    class field. Records made before the clock was synced are returned with
    clock_synced=False so the caller can drop them.
    """
    if len(data) % RECORD_SIZE:
        raise ValueError(f"records chunk of {len(data)} bytes is not a multiple of {RECORD_SIZE}")
    out = []
    for rec in decode_records(data):
        synced = not (rec.activity_class & CLASS_UNSYNCED_FLAG)
        cls = rec.activity_class & ~CLASS_UNSYNCED_FLAG
        if cls not in KNOWN_CLASSES:
            raise ValueError(f"unknown activity class {cls} at minute {rec.minute}")
        out.append((Record(rec.minute, rec.counts, cls, rec.cadence), synced))
    return out
