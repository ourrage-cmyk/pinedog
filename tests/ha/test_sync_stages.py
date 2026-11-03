"""Each failed sync names the stage it stopped at. Pure logic, no Home Assistant."""

import asyncio
import struct
import sys
import types
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"
_pkg = types.ModuleType("pinedog")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["pinedog"] = _pkg

from pinedog.protocol import crc8  # noqa: E402
from pinedog.transfer import (  # noqa: E402
    ClockError,
    GattError,
    IncompleteTransfer,
    MIN_PLAUSIBLE_UNIX,
    SyncFailed,
    run_transfer,
    stage_failure,
)

STATUS = struct.Struct("<BBIIIBB")
NOW = MIN_PLAUSIBLE_UNIX + 1000


class StallingLink:
    """Answers Status with three pending records, then never sends a stream."""

    def __init__(self, pending: int = 3) -> None:
        self._pending = pending

    async def write_time(self, unix_s: int) -> None:
        return None

    async def read_status(self) -> bytes:
        return STATUS.pack(2, 1, self._pending, 0, 3600, 5, 0xFF)

    async def subscribe(self, on_data) -> None:
        return None

    async def unsubscribe(self) -> None:
        return None

    async def request(self) -> None:
        return None

    async def write_ack(self, count: int) -> None:
        raise AssertionError("nothing may be acked")


async def _persist_ok(records) -> None:
    return None


def test_gatt_error_is_named_gatt():
    failure = stage_failure(GattError("write rejected"))
    assert failure.stage == "GATT"
    assert str(failure) == "GATT: write rejected"


def test_timeout_is_named_transfer_with_a_reason():
    # asyncio timeouts carry no message, so the stage must say what happened.
    failure = stage_failure(asyncio.TimeoutError())
    assert failure.stage == "transfer"
    assert "no end of stream" in failure.detail


def test_existing_stage_errors_keep_their_stage():
    assert stage_failure(ClockError("clock not set")).stage == "clock"
    assert isinstance(IncompleteTransfer("got 1 of 3 records, nothing acked"), SyncFailed)
    assert str(IncompleteTransfer("got 1 of 3 records, nothing acked")) == (
        "transfer: got 1 of 3 records, nothing acked"
    )


def test_unknown_error_is_named_error_with_its_type():
    failure = stage_failure(ValueError())
    assert failure.stage == "error"
    assert failure.detail == "ValueError"


def test_stalled_stream_fails_as_transfer_and_acks_nothing():
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(run_transfer(StallingLink(), NOW, _persist_ok, timeout_s=0.05))


class FullStreamLink(StallingLink):
    """Streams one valid record and the end marker, so the transfer reaches persist."""

    def __init__(self) -> None:
        super().__init__(pending=1)
        self.acked = None
        self._on_data = None

    async def subscribe(self, on_data) -> None:
        self._on_data = on_data

    async def request(self) -> None:
        covered = struct.pack("<IHB", NOW // 60 - 5, 40, 1)
        self._on_data(covered + bytes([crc8(covered)]))
        self._on_data(bytes([0xEE]) + struct.pack("<I", 1))

    async def write_ack(self, count: int) -> None:
        self.acked = count


def test_store_failure_is_named_store_and_nothing_is_acked():
    async def failing_persist(records) -> None:
        raise OSError("flash write refused")

    link = FullStreamLink()
    with pytest.raises(SyncFailed) as info:
        asyncio.run(run_transfer(link, NOW, failing_persist))
    assert info.value.stage == "store"
    assert "flash write refused" in info.value.detail
    assert link.acked is None
