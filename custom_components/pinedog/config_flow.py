"""Discovers a Pinedog watch through Home Assistant's Bluetooth stack and bonds with it."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN
from .sync import async_pair

_LOGGER = logging.getLogger(__name__)


class PinedogConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovered = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name or "Pinedog"}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovered is not None
        if user_input is not None:
            return await self.async_step_pair()
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovered.name or "Pinedog"},
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Bond with the watch. Its button opens a 60 second pairing window."""
        assert self._discovered is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await async_pair(self.hass, self._discovered.address)
            except Exception as err:  # noqa: BLE001 - any failure means the user retries
                _LOGGER.warning("Pinedog pairing failed: %s", err)
                errors["base"] = "pair_failed"
            else:
                return self.async_create_entry(
                    title=self._discovered.name or "Pinedog",
                    data={"address": self._discovered.address},
                )
        return self.async_show_form(
            step_id="pair",
            data_schema=None,
            errors=errors,
            description_placeholders={"name": self._discovered.name or "Pinedog"},
        )
