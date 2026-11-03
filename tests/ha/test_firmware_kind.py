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
