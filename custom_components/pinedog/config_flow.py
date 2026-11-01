"""Finds a collar through Home Assistant's Bluetooth stack.

Custom firmware is recognised by its service and bonds with the watch. Stock InfiniTime
is recognised by its name or its DFU service, and needs no pairing.

Discovery only offers devices whose advertisements match the manifest. If a watch is not
offered, the user can pick it from the Bluetooth devices the adapter can hear.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .const import DOMAIN, FIRMWARE_PINEDOG, FIRMWARE_STOCK
from .protocol import SERVICE_UUID
from .sync import async_pair

_LOGGER = logging.getLogger(__name__)

# Nordic buttonless DFU service. InfiniTime advertises it, so it helps discovery find a
# stock watch even when the watch's advertised name is missing.
DFU_SERVICE_UUID = "00001530-1212-efde-1523-785feabcd123"


def _uuids(info: BluetoothServiceInfoBleak) -> set[str]:
    return {u.lower() for u in info.service_uuids or []}


def _firmware_for(info: BluetoothServiceInfoBleak) -> str:
    return FIRMWARE_PINEDOG if SERVICE_UUID in _uuids(info) else FIRMWARE_STOCK


def _looks_like_watch(info: BluetoothServiceInfoBleak) -> bool:
    uuids = _uuids(info)
    return (
        SERVICE_UUID in uuids
        or DFU_SERVICE_UUID in uuids
        or (info.name or "").startswith("InfiniTime")
    )


class PinedogConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: BluetoothServiceInfoBleak | None = None
        self._firmware = FIRMWARE_PINEDOG

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovered = discovery_info
        self._firmware = _firmware_for(discovery_info)
        self.context["title_placeholders"] = {"name": discovery_info.name or "Collar"}
        return await self.async_step_bluetooth_confirm()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a collar the adapter can hear, for watches that discovery does not offer."""
        seen = {
            i.address: i
            for i in bluetooth.async_discovered_service_info(self.hass, connectable=True)
        }
        if not seen:
            return self.async_abort(reason="no_devices_found")

        errors: dict[str, str] = {}
        if user_input is not None:
            address = (user_input.get("manual_address") or user_input["address"]).strip().upper()
            info = seen.get(address)
            if info is None:
                errors["base"] = "not_seen"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                self._discovered = info
                self._firmware = _firmware_for(info)
                self.context["title_placeholders"] = {"name": info.name or "Collar"}
                # Neither firmware needs pairing: the InfiniTime port has no bonding.
                return self._create(self._firmware, (user_input.get("dog_name") or "").strip() or None)

        # Likely watches first, then the strongest signal.
        ordered = sorted(
            seen.values(),
            key=lambda i: (not _looks_like_watch(i), -(i.rssi or -127)),
        )
        options = [
            selector.SelectOptionDict(value=i.address, label=f"{i.name or 'Unnamed'} ({i.address})")
            for i in ordered
        ]
        schema = vol.Schema(
            {
                vol.Required("address", default=ordered[0].address): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Optional("manual_address"): selector.TextSelector(),
                vol.Optional("dog_name"): selector.TextSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovered is not None
        if user_input is not None:
            return self._create(self._firmware)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovered.name or "Collar"},
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Bond with custom firmware. Its button opens a 60 second pairing window."""
        assert self._discovered is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await async_pair(self.hass, self._discovered.address)
            except Exception as err:  # noqa: BLE001 - any failure means the user retries
                _LOGGER.warning("Pinedog pairing failed: %s", err)
                errors["base"] = "pair_failed"
            else:
                return self._create(FIRMWARE_PINEDOG)
        return self.async_show_form(
            step_id="pair",
            data_schema=None,
            errors=errors,
            description_placeholders={"name": self._discovered.name or "Collar"},
        )

    def _create(self, firmware: str, dog_name: str | None = None) -> ConfigFlowResult:
        assert self._discovered is not None
        data: dict[str, Any] = {"address": self._discovered.address, "firmware": firmware}
        if dog_name:
            data["dog_name"] = dog_name
        return self.async_create_entry(
            title=dog_name or self._discovered.name or "Collar",
            data=data,
        )
