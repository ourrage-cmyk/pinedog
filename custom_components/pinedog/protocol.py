"""Wire format for the Pinedog BLE sync.

Must match firmware/app/src/ble_sync.c, firmware/app/src/store.h and
firmware/core/minute_summary.c. Pure logic, no Home Assistant imports.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .activity import unpack_raw

SERVICE_UUID = "5d0f0000-7e0d-4a8b-9d2a-0a1e0c0d0000"
TIME_UUID = "5d0f0001-7e0d-4a8b-9d2a-0a1e0c0d0000"
STATUS_UUID = "5d0f0002-7e0d-4a8b-9d2a-0a1e0c0d0000"
REQUEST_UUID = "5d0f0003-7e0d-4a8b-9d2a-0a1e0c0d0000"
RECORDS_UUID = "5d0f0004-7e0d-4a8b-9d2a-0a1e0c0d0000"
ACK_UUID = "5d0f0005-7e0d-4a8b-9d2a-0a1e0c0d0000"

PROTOCOL_VERSION = 2
END_MARKER = 0xEE
CLASS_MASK = 0x03  # bits 0..1: REST, LIGHT, WALK, RUN
BOOT_SHIFT = 2  # bits 2..6: boot id mod 32, set on unsynced records
BOOT_MASK = 0x1F
UNSYNCED_FLAG = 0x80  # bit 7: made before the clock was set
BATTERY_UNKNOWN = 0xFF

FLAG_CLOCK_SYNCED = 1 << 0
FLAG_CHARGING = 1 << 1
FLAG_POWER_PRESENT = 1 << 2
FLAG_PAIRING_OPEN = 1 << 3

# version, flags, pending, newest_minute, uptime_s, boot_id, battery_pct (16 bytes)
_STATUS = struct.Struct("<BBIIIBB")


@dataclass(frozen=True)
class Status:
    version: int
    flags: int
    pending: int
    newest_minute: int
    uptime_s: int
    boot_id: int
    battery_pct: int | None

    @property
    def clock_synced(self) -> bool:
        return bool(self.flags & FLAG_CLOCK_SYNCED)

    @property
    def charging(self) -> bool:
        return bool(self.flags & FLAG_CHARGING)

    @property
    def power_present(self) -> bool:
        return bool(self.flags & FLAG_POWER_PRESENT)

    @property
    def pairing_open(self) -> bool:
        return bool(self.flags & FLAG_PAIRING_OPEN)


@dataclass(frozen=True)
class WireRecord:
    """One record as the watch sent it, before any placement or validation."""

    minute: int  # unix minute if synced, uptime minute if unsynced
    counts: int
    activity_class: int
    boot_id: int
    unsynced: bool
    crc_ok: bool


def encode_u32(value: int) -> bytes:
    return struct.pack("<I", value)


def crc8(data: bytes) -> int:
    """CRC-8, polynomial 0x07, init 0 (SMBus). Same routine as pd_record_crc()."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def decode_status(data: bytes) -> Status:
    if len(data) != _STATUS.size:
        raise ValueError(f"status is {len(data)} bytes, expected {_STATUS.size}")
    version, flags, pending, newest, uptime, boot, battery = _STATUS.unpack(data)
    if version != PROTOCOL_VERSION:
        raise ValueError(f"unsupported protocol version {version}")
    return Status(
        version=version,
        flags=flags,
        pending=pending,
        newest_minute=newest,
        uptime_s=uptime,
        boot_id=boot & BOOT_MASK,
        battery_pct=None if battery == BATTERY_UNKNOWN else battery,
    )


def is_end_marker(data: bytes) -> bool:
    return len(data) == 1 and data[0] == END_MARKER


def decode_chunk(data: bytes) -> list[WireRecord]:
    """Decode one Records notification and check each record's CRC."""
    out = []
    for minute, counts, cls_byte, crc in unpack_raw(data):
        covered = struct.pack("<IHB", minute, counts, cls_byte)  # the CRC covers these 7 bytes
        out.append(
            WireRecord(
                minute=minute,
                counts=counts,
                activity_class=cls_byte & CLASS_MASK,
                boot_id=(cls_byte >> BOOT_SHIFT) & BOOT_MASK,
                unsynced=bool(cls_byte & UNSYNCED_FLAG),
                crc_ok=crc8(covered) == crc,
            )
        )
    return out
