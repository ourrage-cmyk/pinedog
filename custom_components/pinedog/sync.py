"""BLE pull of new records from a Pinedog watch. Needs Home Assistant at runtime."""

from __future__ import annotations

import asyncio
import time

from bleak import BleakClient
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .activity import Record
from .protocol import (
    ACK_UUID,
    RECORDS_UUID,
    REQUEST_UUID,
    STATUS_UUID,
    TIME_UUID,
    decode_chunk,
    decode_status,
    encode_u32,
    is_end_marker,
)

TRANSFER_TIMEOUT_S = 120


async def async_pull_records(
    hass: HomeAssistant, address: str, from_minute: int
) -> list[tuple[Record, bool]]:
    """Connect, sync the clock, download records from from_minute, then ack them.

    Returns (record, clock_synced) pairs. The watch keeps its records unless
    the end marker arrives, so a failed transfer loses nothing.
    """
    device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if device is None:
        raise ConnectionError(f"{address} is not in range")

    received: list[tuple[Record, bool]] = []
    finished = asyncio.Event()

    def on_records(_sender, data: bytearray) -> None:
        if is_end_marker(bytes(data)):
            finished.set()
            return
        received.extend(decode_chunk(bytes(data)))

    client = await establish_connection(BleakClient, device, "Pinedog", max_attempts=3)
    try:
        await client.write_gatt_char(TIME_UUID, encode_u32(int(time.time())), response=True)
        status = decode_status(bytes(await client.read_gatt_char(STATUS_UUID)))
        if status.pending == 0:
            return []

        await client.start_notify(RECORDS_UUID, on_records)
        await client.write_gatt_char(REQUEST_UUID, encode_u32(from_minute), response=True)
        await asyncio.wait_for(finished.wait(), timeout=TRANSFER_TIMEOUT_S)
        await client.stop_notify(RECORDS_UUID)

        if received:
            last = max(rec.minute for rec, _ in received)
            await client.write_gatt_char(ACK_UUID, encode_u32(last), response=True)
        return received
    finally:
        await client.disconnect()
