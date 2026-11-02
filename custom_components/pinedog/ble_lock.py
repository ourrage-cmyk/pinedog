"""One lock for every Bluetooth connection the integration makes.

The Pi's built-in adapter has only a few connection slots. Two watches polling at once,
or a sync running while a poll starts, can run out of slots and fail. Holding this lock
for each connection means only one Pinedog connection is open at a time.
"""

from __future__ import annotations

import asyncio

BLE_LOCK = asyncio.Lock()
