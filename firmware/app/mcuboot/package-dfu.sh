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

python3 "$IMGTOOL" create --align 1 --version "$VERSION" --header-size 32 \
  --slot-size 475136 --pad-header "$BIN" "$OUT/$NAME-image.bin"

# The image starts at the app slot, 0x8000.
arm-none-eabi-objcopy -I binary -O ihex --change-addresses=0x8000 \
  "$OUT/$NAME-image.bin" "$OUT/$NAME-image.hex"

adafruit-nrfutil dfu genpkg --dev-type 0x0052 \
  --application "$OUT/$NAME-image.hex" "$OUT/$NAME-dfu.zip"
