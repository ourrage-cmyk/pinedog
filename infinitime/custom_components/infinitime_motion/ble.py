"""Bluetooth side: one short connection that reads steps, battery and a motion sample.

Uses only standard reads and notifications on stock InfiniTime. No pairing, no writes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .motion import (
    BATTERY_LEVEL_UUID,
    MOTION_VALUES_UUID,
    STEP_COUNT_UUID,
    decode_battery,
    decode_motion,
    decode_step_count,
)


@dataclass
class WatchReading:
    steps: int
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
    """Connect, read steps and battery, sample motion for a few seconds, disconnect.

    Battery and motion are optional: if either fails, the step count is still returned.
    """
    client = await establish_connection(
        BleakClient, _device(hass, address), "InfiniTime", max_attempts=3
    )
    try:
        steps = decode_step_count(await client.read_gatt_char(STEP_COUNT_UUID))

        battery: int | None = None
        try:
            battery = decode_battery(await client.read_gatt_char(BATTERY_LEVEL_UUID))
        except (BleakError, ValueError):
            pass

        samples: list[tuple[int, int, int]] = []
        if sample_seconds > 0:
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

        return WatchReading(steps=steps, battery_pct=battery, motion_samples=samples)
    finally:
        await client.disconnect()
