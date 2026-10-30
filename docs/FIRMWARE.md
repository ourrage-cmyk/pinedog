# Firmware: build and flash (first-generation PineTime)

This covers the Zephyr app in `firmware/app`. It was built and linked
against Zephyr v4.4.0 for board `pinetime_devkit0`. It has not been run on a
watch yet. Flashing and the first BLE sync are the first hardware test.

## What the image does

- Samples the BMA421 at 25 Hz with the data-ready interrupt.
- Summarises each minute (activity counts, cadence, class) and stores one
  8-byte record in the external 4 MB flash, in a 1 MB log partition.
- Advertises as `Pinedog` every 2 s. Home Assistant connects, sets the time,
  downloads new records and acks them. Nothing is acked unless Home
  Assistant confirms it has stored them.

## Important: this replaces the stock firmware

The image is standalone. It overwrites the InfiniTime bootloader and the
InfiniTime app, so the watch stops showing the time. That's intended for
this project. It also means **no over-the-air updates for now**. Later
versions can be flashed with an SWD debugger, or the image can be moved to
an MCUboot setup with signing.

To return to the normal watch, flash InfiniTime again with the same
debugger. The original firmware is not kept on the watch.

## Known gaps in this version

- Battery level is reported as 0xFF (unknown). The voltage divider needs an
  ADC read that isn't wired up yet.
- The button does nothing. There is no status screen, and the display is
  never turned on.
- Classifier thresholds (`main.c`) are untested guesses and need tuning
  from real wear. They are compile-time constants for now.
- Records logged before the first time sync after a reboot are flagged
  (`class` bit 0x80). Home Assistant drops those. A reboot during the day
  can lose data until the next sync, so it is worth noting.
- The sensor interrupt wakes the CPU 25 times a second. That's simple and
  correct, but it will cost battery. The BMA4xx FIFO would cut the wake-ups
  to about one a second. This is the first battery optimisation to do after
  measuring.

## Set up the toolchain (once)

```sh
mkdir -p ~/zephyr-ws && cd ~/zephyr-ws
git clone --depth 1 --branch v4.4.0 https://github.com/zephyrproject-rtos/zephyr.git
python3 -m venv .venv && . .venv/bin/activate
pip install -r zephyr/scripts/requirements-base.txt west
west init -l zephyr
west update --narrow -o=--depth=1 hal_nordic cmsis_6
sudo apt-get install gcc-arm-none-eabi libnewlib-arm-none-eabi device-tree-compiler
```

## Build

```sh
cd ~/pinedog/firmware/app
. ~/zephyr-ws/.venv/bin/activate
./build.sh
```

The image is `~/zephyr-ws/build-app/zephyr/zephyr.hex`. Expected size: about
131 KB of 512 KB flash and about 31 KB of 64 KB RAM.

## Flash

You need an SWD debugger. A J-Link (or a J-Link-compatible probe) works best
with the PineTime's SWD pads, and a Raspberry Pi with an SWD adapter can
also work. To connect, you'll need to open the watch's back, or use the
pogo-pin pads on the board. There is a PineTime SWD guide on the Pine64
wiki.

```sh
west flash -d ~/zephyr-ws/build-app --runner jlink
```

If the flash fails with a protection error, the nRF52832 may have APPROTECT
set. Recover with `nrfjprog --recover` (this erases the chip, which is fine
here) and flash again.

## Pair with Home Assistant

Once the watch is running, the status button on the Home Assistant side
should see a device named `Pinedog`. The integration itself is not written
yet (see `docs/DESIGN.md`).
