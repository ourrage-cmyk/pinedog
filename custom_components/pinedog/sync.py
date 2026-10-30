"""BLE adapter for a sync. The sequence itself lives in transfer.py."""

from __future__ import annotations

import time

from bleak import BleakClient
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .protocol import ACK_UUID, RECORDS_UUID, REQUEST_UUID, STATUS_UUID, TIME_UUID, encode_u32
from .transfer import PersistFn, TransferResult, run_transfer


class BleakLink:
    """Implements transfer.Link on top of an open BleakClient."""

    def __init__(self, client: BleakClient) -> None:
        self._client = client

    async def write_time(self, unix_s: int) -> None:
        await self._client.write_gatt_char(TIME_UUID, encode_u32(unix_s), response=True)

    async def read_status(self) -> bytes:
        return bytes(await self._client.read_gatt_char(STATUS_UUID))

    async def subscribe(self, on_data) -> None:
        def _callback(_sender, data: bytearray) -> None:
            on_data(bytes(data))

        await self._client.start_notify(RECORDS_UUID, _callback)

    async def unsubscribe(self) -> None:
        # The link may already be gone when a transfer fails, so skip the call then.
        if self._client.is_connected:
            await self._client.stop_notify(RECORDS_UUID)

    async def request(self) -> None:
        # The watch ignores the payload and streams every pending record.
        await self._client.write_gatt_char(REQUEST_UUID, encode_u32(0), response=True)

    async def write_ack(self, count: int) -> None:
        await self._client.write_gatt_char(ACK_UUID, encode_u32(count), response=True)


def _device(hass: HomeAssistant, address: str):
    device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if device is None:
        raise ConnectionError(f"{address} is not in range")
    return device


async def async_pull_records(
    hass: HomeAssistant, address: str, persist: PersistFn
) -> TransferResult:
    """Connect, run one transfer, and disconnect."""
    client = await establish_connection(BleakClient, _device(hass, address), "Pinedog", max_attempts=3)
    try:
        return await run_transfer(BleakLink(client), int(time.time()), persist)
    finally:
        await client.disconnect()


async def async_pair(hass: HomeAssistant, address: str) -> None:
    """Bond with the watch. The watch only accepts pairing while its button window is open."""
    client = await establish_connection(BleakClient, _device(hass, address), "Pinedog", max_attempts=3)
    try:
        await client.pair()
    finally:
        await client.disconnect()
