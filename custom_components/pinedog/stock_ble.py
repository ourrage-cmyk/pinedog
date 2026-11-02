"""Bluetooth side: one short connection that reads battery and a motion sample.

Standard reads and notifications only. No pairing, no writes, no step counter.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .ble_lock import BLE_LOCK
from .stock_motion import BATTERY_LEVEL_UUID, MOTION_VALUES_UUID, decode_battery, decode_motion


@dataclass
class WatchReading:
    battery_pct: int | None
    motion_samples: list[tuple[int, int, int]]


def _device(hass: HomeAssistant, address: str):
    device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if device is None:
        raise ConnectionError(f"{address} is not in range")
    return device


async def async_read_watch(
    hass: HomeAssistant, address: str, sample_seconds: float
) -> WatchReading:
    """Connect, sample motion for a few seconds, read battery, disconnect.

    Battery and motion are each optional: if one fails, the other is still returned.
    """
    async with BLE_LOCK:
        return await _read_locked(hass, address, sample_seconds)


async def _read_locked(
    hass: HomeAssistant, address: str, sample_seconds: float
) -> WatchReading:
    client = await establish_connection(
        BleakClient, _device(hass, address), "InfiniTime", max_attempts=3
    )
    try:
        samples: list[tuple[int, int, int]] = []

        def _on_motion(_sender, data: bytearray) -> None:
            try:
                samples.append(decode_motion(bytes(data)))
            except ValueError:
                pass

        try:
            await client.start_notify(MOTION_VALUES_UUID, _on_motion)
            await asyncio.sleep(sample_seconds)
            await client.stop_notify(MOTION_VALUES_UUID)
        except BleakError:
            samples = []

        battery: int | None = None
        try:
            battery = decode_battery(await client.read_gatt_char(BATTERY_LEVEL_UUID))
        except (BleakError, ValueError):
            pass

        return WatchReading(battery_pct=battery, motion_samples=samples)
    finally:
        await client.disconnect()
