"""Versioned storage for per-dog data.

Bump STORE_VERSION and add a branch to _async_migrate_func for every change to the
saved shape. Old data is then upgraded in place instead of being lost.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.storage import Store

STORE_VERSION = 2  # v1: no long-term baseline. v2: adds "longterm".


class WoofStore(Store):
    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        data = dict(old_data or {})
        if old_major_version < 2:
            data.setdefault("longterm", None)
        return data
