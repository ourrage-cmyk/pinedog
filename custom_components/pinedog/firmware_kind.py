"""Which firmware a collar runs, decided from its advertisement. Pure logic, no Home Assistant imports."""

from __future__ import annotations

from collections.abc import Iterable

from .const import FIRMWARE_PINEDOG
from .protocol import SERVICE_UUID


def detected_firmware(stored: str, service_uuids: Iterable[str] | None) -> str:
    """Return the firmware to use for a collar.

    A collar that advertises the Pinedog service is running Pinedog firmware, whatever the
    config entry says. The entry is often created while the watch still ran stock InfiniTime,
    and a re-flash would otherwise leave it on the stock path (polling, no store-and-sync).
    Otherwise keep what the entry says.
    """
    uuids = {u.lower() for u in service_uuids or ()}
    if SERVICE_UUID in uuids:
        return FIRMWARE_PINEDOG
    return stored
