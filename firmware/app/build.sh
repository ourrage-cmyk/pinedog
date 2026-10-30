#!/usr/bin/env bash
# Builds the Pinedog app for the first-generation PineTime with Zephyr.
#
# Requirements: see docs/FIRMWARE.md. Set ZEPHYR_WS to the west workspace
# (default: $HOME/zephyr-ws) and ARM_GCC_PREFIX to the directory with
# arm-none-eabi-gcc (default: /usr/bin).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ZEPHYR_WS="${ZEPHYR_WS:-$HOME/zephyr-ws}"
export ZEPHYR_BASE="$ZEPHYR_WS/zephyr"
export ZEPHYR_TOOLCHAIN_VARIANT=cross-compile
export CROSS_COMPILE="${ARM_GCC_PREFIX:-/usr/bin}/arm-none-eabi-"

cd "$ZEPHYR_WS"
west build -p auto -b pinetime_devkit0 -d "$ZEPHYR_WS/build-app" "$HERE" "$@"
echo "Image: $ZEPHYR_WS/build-app/zephyr/zephyr.hex"
