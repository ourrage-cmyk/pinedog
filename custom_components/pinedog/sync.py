"""BLE adapter for a sync. The sequence itself lives in transfer.py."""

from __future__ import annotations

import logging
import time

from bleak import BleakClient
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .ble_lock import BLE_LOCK
from .protocol import ACK_UUID, RECORDS_UUID, REQUEST_UUID, STATUS_UUID, TIME_UUID, encode_u32
from .transfer import GattError, PersistFn, SyncFailed, TransferResult, describe, run_transfer, stage_failure

_LOGGER = logging.getLogger(__name__)


async def _gatt(operation):
    """Run one GATT operation, and name any failure as a GATT error."""
    try:
        return await operation
    except Exception as err:  # noqa: BLE001 - every bleak error is a GATT failure here
        raise GattError(describe(err)) from err


class BleakLink:
    """Implements transfer.Link on top of an open BleakClient."""

    def __init__(self, client: BleakClient) -> None:
        self._client = client

    async def write_time(self, unix_s: int) -> None:
        await _gatt(self._client.write_gatt_char(TIME_UUID, encode_u32(unix_s), response=True))

    async def read_status(self) -> bytes:
        return bytes(await _gatt(self._client.read_gatt_char(STATUS_UUID)))

    async def subscribe(self, on_data) -> None:
        def _callback(_sender, data: bytearray) -> None:
            on_data(bytes(data))

        await _gatt(self._client.start_notify(RECORDS_UUID, _callback))

    async def unsubscribe(self) -> None:
        # The link may already be gone when a transfer fails, so skip the call then.
        if self._client.is_connected:
            await _gatt(self._client.stop_notify(RECORDS_UUID))

    async def request(self) -> None:
        # The watch ignores the payload and streams every pending record.
        await _gatt(self._client.write_gatt_char(REQUEST_UUID, encode_u32(0), response=True))

    async def write_ack(self, count: int) -> None:
        await _gatt(self._client.write_gatt_char(ACK_UUID, encode_u32(count), response=True))


# A collar that has not advertised for this long is out of range. Trying to connect to it
# only ties up the Pi's few connection slots for about a minute before it fails.
MAX_ADVERTISEMENT_AGE_S = 60


def _device(hass: HomeAssistant, address: str):
    info = bluetooth.async_last_service_info(hass, address, connectable=True)
    if info is None:
        raise SyncFailed("not seen", "no advertisement from the collar; wake it and keep it near the Pi")
    age = time.monotonic() - info.time
    if age > MAX_ADVERTISEMENT_AGE_S:
        raise SyncFailed("not seen", f"last advertisement {int(age)} s ago; the collar is out of range")
    return info.device


async def _disconnect(client: BleakClient) -> None:
    try:
        await client.disconnect()
    except Exception as err:  # noqa: BLE001 - the transfer result is what matters
        _LOGGER.debug("Pinedog disconnect after sync: %s", describe(err))


async def async_pull_records(
    hass: HomeAssistant, address: str, persist: PersistFn
) -> TransferResult:
    """Connect, run one transfer, and disconnect. Failures raise SyncFailed with the stage."""
    async with BLE_LOCK:
        device = _device(hass, address)
        try:
            client = await establish_connection(BleakClient, device, "Pinedog", max_attempts=3)
        except Exception as err:  # noqa: BLE001
            raise SyncFailed("connect", describe(err)) from err
        try:
            return await run_transfer(BleakLink(client), int(time.time()), persist)
        except Exception as err:  # noqa: BLE001
            raise stage_failure(err) from err
        finally:
            await _disconnect(client)


async def async_pair(hass: HomeAssistant, address: str) -> None:
    """Bond with the watch. The watch only accepts pairing while its button window is open."""
    async with BLE_LOCK:
        device = _device(hass, address)
        client = await establish_connection(BleakClient, device, "Pinedog", max_attempts=3)
        try:
            await client.pair()
        finally:
            await _disconnect(client)
