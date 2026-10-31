#!/usr/bin/env bash
# Packages a Zephyr build linked for the MCUboot app slot (see mcuboot.conf)
# as a Bluetooth DFU zip for the stock PineTime bootloader.
#
# Mirrors InfiniTime 1.16.1's CMake steps: imgtool.py create, then
# adafruit-nrfutil dfu genpkg --dev-type 0x0052. The image is unsigned; the
# stock bootloader checks only the SHA-256 TLV (BOOTUTIL_SIGN_* is not set).
#
# Usage: package-dfu.sh <zephyr.bin> <version> <outdir> <imgtool.py>
set -euo pipefail

BIN="$1"
VERSION="$2"
OUT="$3"
IMGTOOL="$4"

mkdir -p "$OUT"
NAME="pinedog-mcuboot-app-$VERSION"

# Zephyr's zephyr.bin starts at 0x8000 with 256 bytes of zero padding; the
# vector table starts at 0x8100. Drop the padding so the body starts at 0x8100,
# and build the image with a 256-byte header.
python3 - "$BIN" "$OUT/$NAME-body.bin" <<'PY'
import sys
data = open(sys.argv[1], "rb").read()
assert data[:256] == b"\x00" * 256, "expected 256 bytes of zero padding at 0x8000"
open(sys.argv[2], "wb").write(data[256:])
PY

python3 "$IMGTOOL" create --align 1 --version "$VERSION" --header-size 256 \
  --slot-size 475136 --pad-header "$OUT/$NAME-body.bin" "$OUT/$NAME-image.bin"

# The image starts at the app slot, 0x8000.
arm-none-eabi-objcopy -I binary -O ihex --change-addresses=0x8000 \
  "$OUT/$NAME-image.bin" "$OUT/$NAME-image.hex"

adafruit-nrfutil dfu genpkg --dev-type 0x0052 \
  --application "$OUT/$NAME-image.hex" "$OUT/$NAME-dfu.zip"
