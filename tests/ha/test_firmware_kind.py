import sys
import types
from pathlib import Path

# Load the pure modules without running the package __init__, which needs Home Assistant.
PKG_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "pinedog"
_pkg = types.ModuleType("pinedog")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["pinedog"] = _pkg

from pinedog.const import FIRMWARE_PINEDOG, FIRMWARE_STOCK  # noqa: E402
from pinedog.firmware_kind import detected_firmware  # noqa: E402
from pinedog.protocol import SERVICE_UUID  # noqa: E402


def test_pinedog_advertisement_upgrades_a_stock_entry():
    assert detected_firmware(FIRMWARE_STOCK, [SERVICE_UUID]) == FIRMWARE_PINEDOG


def test_service_uuid_match_ignores_case():
    assert detected_firmware(FIRMWARE_STOCK, [SERVICE_UUID.upper()]) == FIRMWARE_PINEDOG


def test_stock_advertisement_keeps_a_stock_entry():
    assert detected_firmware(FIRMWARE_STOCK, ["00001530-1212-efde-1523-785feabcd123"]) == FIRMWARE_STOCK


def test_no_advertisement_keeps_the_entry():
    assert detected_firmware(FIRMWARE_PINEDOG, None) == FIRMWARE_PINEDOG
    assert detected_firmware(FIRMWARE_STOCK, []) == FIRMWARE_STOCK


def test_stock_entry_upgrades_on_a_later_pinedog_advertisement():
    # The real case: the entry was made on stock InfiniTime, and the collar is re-flashed.
    # The Pinedog advertisement arrives after setup, alongside other advertised services.
    advertised = [SERVICE_UUID, "00001530-1212-efde-1523-785feabcd123"]
    assert detected_firmware(FIRMWARE_STOCK, advertised) == FIRMWARE_PINEDOG


def test_no_upgrade_when_nothing_is_advertised_yet():
    # Setup can run before the first advertisement is cached. The entry then stays stock
    # until a later advertisement carries the Pinedog service.
    assert detected_firmware(FIRMWARE_STOCK, None) == FIRMWARE_STOCK


def test_gatt_table_with_pinedog_service_upgrades_a_stock_entry():
    # Passive scans never see the scan response, so the upgrade reads the GATT table on connect.
    gatt = ["00001801-0000-1000-8000-00805f9b34fb", SERVICE_UUID]
    assert detected_firmware(FIRMWARE_STOCK, gatt) == FIRMWARE_PINEDOG


def test_gatt_table_of_stock_infinitime_keeps_the_stock_entry():
    gatt = ["00001801-0000-1000-8000-00805f9b34fb", "00001530-1212-efde-1523-785feabcd123"]
    assert detected_firmware(FIRMWARE_STOCK, gatt) == FIRMWARE_STOCK
