# Firmware reference (Pinedog v0.2.0, PineTime)

Technical reference for the Zephyr app in `firmware/app`. For the step-by-step
guide to flashing the watch, see [`README.md`](../README.md).

**Status: built, not run on hardware.** The image links for board
`pinetime_devkit0` (Zephyr v4.4.0, nRF52832). Host tests cover the pure logic.
Nothing in this document has been checked on a real watch yet. See
"Not yet verified" below.

## What the image does

| Area | Behaviour |
|---|---|
| Sampling | BMA421 at 25 Hz, ±4 g, data-ready interrupt. The CPU wakes for every sample. |
| Minute windows | A window closes every 60 s by the clock. Each window is one record. A window with no samples is rest. A sparse window is scaled up to a full minute. Nothing waits for motion. |
| Classes | `0` rest, `1` light, `2` walk, `3` run, `4` NOT_WORN (on the charger). Thresholds are compile-time guesses in `main.c`. |
| Charging | While the charger is connected, every window is NOT_WORN. Home Assistant excludes those minutes from all totals. |
| Storage | 8-byte records in the external 4 MB SPI flash (XT25F32B). Ring log of about 88 days of minutes. Checkpoints go to a two-sector journal. |
| Button | A press (debounced 250 ms) turns the screen on for 30 s, opens a 60 s pairing window, and opens a 60 s sync window with fast advertising. |
| Screen | Off at boot. On for 30 s after a press, then off again. Shows 10 lines of status (see below). |
| Bluetooth | Advertises `Pinedog` every 2 s when idle, every 100 ms in a sync window. Every characteristic needs an encrypted, bonded link. |
| Sync | Home Assistant writes Time, reads Status, writes Request, receives Records, and writes Ack with the record count. The watch releases exactly that many oldest records. |
| Battery | Voltage divider on AIN7, InfiniTime curve, reported as a percentage in Status. Charge pin P0.12, power-present pin P0.19 (both active low). |
| Watchdog | Hardware watchdog, 30 s timeout, fed every 5 s. Reset cause is logged at boot. |

## Record format (8 bytes, little-endian, packed)

| Offset | Field | Notes |
|---|---|---|
| 0 | `minute` (u32) | Unix minute when the clock is set. Uptime minute otherwise. |
| 4 | `counts` (u16) | Sum of \|magnitude − 1 g\| in mg, divided by 1000, saturating. |
| 6 | `class` (u8) | Bits 0–2: class (0–4). Bits 3–6: boot id mod 16. Bit 7: unsynced. |
| 7 | `crc` (u8) | CRC-8, polynomial 0x07, init 0, over bytes 0–6. |

Home Assistant rejects a record whose CRC fails and acks it so the watch
frees the space. It counts those records in the dropped-records diagnostics.

## Status characteristic (version 2, 16 bytes)

| Offset | Field |
|---|---|
| 0 | version (2) |
| 1 | flags: bit 0 clock set, bit 1 charging, bit 2 power present, bit 3 pairing window open |
| 2 | pending records (u32) |
| 6 | newest minute (u32) |
| 10 | uptime seconds (u32) |
| 14 | boot id mod 16 (u8) |
| 15 | battery percent (u8), 0xFF unknown |

## Advertising

- Idle: service UUID `5d0f0000-7e0d-4a8b-9d2a-0a1e0c0d0000`, 2 s interval.
- Sync window (after a button press): same UUID, 100 ms interval, plus manufacturer
  data with company id `0xFFFF` (reserved for testing) and one flag byte. Bit 0
  asks Home Assistant to connect now, even inside its normal retry interval.

## Screen (10 lines, 10 × 16 px font)

```
PINEDOG
BATTERY 87% CHARGING
PENDING 124 RECORDS
LAST SYNC 42 RECORDS
SYNC AGO 15 MIN
ACTIVE 24H 312 MIN
CLOCK SET
BOOT 5 UP 3600 S
BONDS 1 PAIRED
SYNC WINDOW 45 S
```

- `LAST SYNC` and `SYNC AGO` come from RAM. They reset on reboot.
- `ACTIVE 24H` counts synced records with class light, walk or run in the last
  1440 minutes. It is computed once per button press, so the screen does not
  scan flash every second. It shows `NO CLOCK` until the clock is set.
- `BOOT` is the boot id that tags unsynced records.

## Storage layout

External flash, 4 MB:

| Range | Size | Use |
|---|---|---|
| `0x000000`–`0x2FFFFF` | 3 MB | Not used by the firmware |
| `0x300000`–`0x3F7FFF` | 992 KB | Record ring (leaving 8 KB for the journal) |
| `0x3F8000`–`0x3FFFFF` | 32 KB | `settings` (Bluetooth bonds, NVS) |

Ring capacity: (992 KB − 8 KB) / 8 bytes = 125,952 records = about 87.5 days of
minutes at one record per minute. Records only leave the ring when Home Assistant
acks them, so a long absence from Home Assistant means the oldest records are
dropped once the ring is full.

## Clock recovery

There is no battery-backed clock. Home Assistant sets the time on every sync.
Records made before the first sync after a boot are tagged unsynced, with
uptime minutes and the boot id. Home Assistant places such a record in time as

    real_time = sync_unix − (uptime_at_sync − record_minute × 60)

and only when the record's boot id matches the watch's current boot. Records from
an earlier boot cannot be placed, so they are dropped and counted. Boot ids wrap
every 16 boots.

## Build

```sh
cd ~/pinedog/firmware/app
. ~/zephyr-ws/.venv/bin/activate
./build.sh
```

`build.sh` passes `-DDTC_OVERLAY_FILE=boards/pinetime_devkit0.overlay`. Without
that flag, the storage and settings partitions are not applied.

Output: `~/zephyr-ws/build-app/zephyr/zephyr.hex`. Last measured size: 225,728 B
flash of 512 KB (43 %), 46,280 B RAM of 64 KB (71 %).

Host tests (no hardware):

```sh
cd ~/pinedog/firmware && make test
cd ~/pinedog && python3 -m pytest tests/ha
```

Release files are in `firmware/release/` with `SHA256SUMS`.

## Known gaps and risks

- **Power is not measured.** The sensor wakes the CPU 25 times a second, so
  battery life will be well below the design target until the BMA4xx FIFO and
  a lower sample rate are used. Measure over a week before trusting any figure.
- **Thresholds are guesses** (`main.c`). They are compile-time constants.
- **The stock bootloader is overwritten.** This image replaces InfiniTime and has
  no MCUboot. Over-the-air updates are not possible. Recovery needs SWD.
- **Battery and charging pins** come from the InfiniTime source and have not been
  checked on this board.
- **Pairing via BlueZ** (`client.pair()` in the HA integration) has not been tested.
- **Button and screen** have not been run on hardware. The font comes from
  Zephyr's cfb table and must be checked on the glass.
- **The sync window** depends on Home Assistant seeing the 0xFFFF flag. The HA
  side reads it in `custom_components/pinedog`. Check the diagnostic values
  after a press.

## Not yet verified on hardware

Everything above. In particular: flashing, boot, the screen, the button, the
charging detection, the battery curve, BLE bonding, the sync window, the
record CRCs over real radio, and battery life.
