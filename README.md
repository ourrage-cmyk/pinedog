# Pinedog

> **Do not flash v0.2.0.** It never sends the records to Home Assistant, so no
> data syncs. Use **v0.2.1** (`firmware/release/`). Its changes are listed in
> `docs/FIRMWARE.md`.

Turns a first-generation PineTime into a dog activity logger. The watch
records one motion summary per minute, stores it on the watch, and hands it to
Home Assistant over Bluetooth when the two are in range. Home Assistant shows
active, sedentary and walking time per day, a 7-day baseline, and the
collar's battery.

> **Status: untested on hardware.** The firmware and the Home Assistant
> integration are built and unit-tested on a computer. Nothing has been
> flashed to a watch or run against a live Home Assistant yet. Read
> [What is not verified](#what-is-not-verified) before you flash.

The firmware image replaces InfiniTime on the watch. It has no clock face,
no heart-rate sensor, and no over-the-air updates. Flashing it is one-way
unless you keep a backup, so follow the backup step.

## Install the Home Assistant integration with HACS

The integration is not in the default HACS list. Add this repository as a
custom repository:

1. In Home Assistant, open **HACS** (Community Store).
2. Open the menu (⋮) at the top right and choose **Custom repositories**.
3. Paste `https://github.com/ourrage-cmyk/pinedog`, set the category to
   **Integration**, and click **Add**.
4. Search for **Pinedog** in HACS, open it, and click **Download**. Choose the
   latest version (v0.2.1 or newer).
5. Restart Home Assistant (Settings → System → Restart).
6. Continue with [Step 6: pair the watch](#step-6-pair-the-watch). The watch
   still has to be flashed first (Steps 1–4).

HACS needs Home Assistant 2025.1 or later and the Bluetooth integration. Home
Assistant also needs a working Bluetooth adapter; see the list below.

Manual install, if HACS is not available: copy `custom_components/pinedog`
into your Home Assistant `config/custom_components/` folder and restart.

## What you need

| Item | Notes |
|---|---|
| A first-generation PineTime | Not the PineTime Pro or dev kit. |
| An SWD programmer | Nordic nRF52 DK (PCA10040), or a Segger J-Link. The DK's built-in debugger works. |
| Four pogo pins or thin jumper wires | To reach the SWD pads on the watch's board. |
| A computer with nRF Command Line Tools | Provides `nrfjprog`. Install from Nordic's website. |
| Home Assistant with Bluetooth | Tested on Core 2026.10.2 on a Raspberry Pi 4. The Pi's built-in Bluetooth is assumed. |
| The release files | `firmware/release/` in this repo, with `SHA256SUMS`. |

**SWD pads.** This guide does not list the exact pad positions, because I could
not confirm them from the sources available here. Check the Pine64 wiki's
PineTime pinout before you open the watch. The pads need the four signals
SWDIO, SWCLK, GND and 3V3 (or VTG on the DK).

## Step 1: check the release file

From the folder with the release files:

```sh
sha256sum -c SHA256SUMS
```

Both lines must say `OK`. If not, do not flash.

## Step 2: back up the stock firmware

This is the step that keeps the watch recoverable. It reads the whole
internal flash (bootloader, InfiniTime, and settings) into a file.

```sh
nrfjprog --readcode stock-backup.hex
```

Keep `stock-backup.hex` somewhere safe. It is the only way back to exactly
the watch you have now. The external SPI flash, which holds watch faces and
the boot logo, is not in this backup.

## Step 3: flash Pinedog

```sh
nrfjprog --program pinedog-pinetime-v0.2.1.hex --chiperase --verify --reset
```

- `--chiperase` erases internal flash only. The external SPI flash, where
  Pinedog keeps its records, is not touched.
- `--verify` reads the image back and compares it.

The screen stays dark after a reset. That is expected.

## Step 4: return to InfiniTime (if you want)

Pinedog has no way to go back over Bluetooth. To restore your original watch:

```sh
nrfjprog --program stock-backup.hex --chiperase --verify --reset
```

If you have no backup, use InfiniTime's own SWD guide
(`doc/SWD.md` in the InfiniTime repository). It flashes the bootloader at
`0x0000` and the application at `0x8000` from the InfiniTime release files.

## Step 5: install the Home Assistant integration

Use HACS (see [above](#install-the-home-assistant-integration-with-hacs)), or copy
`custom_components/pinedog` into `config/custom_components/` by hand. Then restart
Home Assistant (Settings → System → Restart).

Keep the watch in the same room as the Home Assistant Bluetooth adapter at first.
Within about a minute, Settings → Devices & services shows **Pinedog collar found**.

## Step 6: pair the watch

Pairing is needed once. The watch refuses it unless you press its button
first.

1. In Home Assistant, click **Configure** on the discovered collar, then
   confirm.
2. The next screen says *Pair the collar*. Press the watch button now. The
   screen turns on and a 60-second pairing window opens.
3. Submit the form in Home Assistant within 60 seconds.

If you see *Pairing failed*, press the button again and submit again. The
watch does not accept pairing outside a window opened by the button.

## Step 7: the first sync

1. Press the watch button. The screen comes on for 30 seconds and shows the
   status page. The watch also opens a 60-second sync window.
2. Home Assistant sees the request in the advertisement and connects. Look at
   the **Unsynced records** sensor. It should fall to 0.
3. Check **Last sync error**. It should be empty.

Without a button press, Home Assistant only tries about every 30 minutes after a
success, or every 5 minutes after a failure.

## What you see on the watch

The screen is off unless you press the button. A press shows:

```
PINEDOG
BATTERY 87% CHARGING        battery percent; CHARGING while on the charger
PENDING 124 RECORDS         records the watch still holds
LAST SYNC 42 RECORDS        last transfer that was acked (RAM, reset on reboot)
SYNC AGO 15 MIN             time since that transfer
ACTIVE 24H 312 MIN          active minutes in the last 24 hours (clock must be set)
CLOCK SET                   CLOCK NOT SET until the first sync
BOOT 5 UP 3600 S            boot count and uptime, for debugging
BONDS 1 PAIRED              bonded phones or hubs
SYNC WINDOW 45 S            time left before the sync window closes
```

The screen turns itself off after 30 seconds. Pressing the button again turns
it on and refreshes the values.

## What Home Assistant gets

| Entity | Meaning |
|---|---|
| Active time today | Minutes with light, walk or run activity. Charging minutes are left out. |
| Sedentary time today | Minutes at rest. A quiet dog is still counted here. |
| Walking time today | Minutes classed as walk or run. |
| Motion today | Sum of activity counts. |
| Activity vs baseline | Compared with the last 7 days, once there is enough history. |
| Battery | Percent, as reported by the watch. |
| Charging | On while the watch is on its charger. |
| Charge soon | On at 20 % or below, when not charging. |
| Unsynced records | Records the watch still holds. |
| Last sync error | The last failure, empty after a good sync. |

Every minute of the day is recorded, including quiet minutes. Charging minutes
are recorded as not worn and left out of the totals.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Nothing on the screen after a press | The release file may not be flashed. Check Step 3 for errors. A dim or blank screen also points to the display driver. Restore your backup and report the failure. |
| No Pinedog device in Home Assistant | The watch must be advertising. Press the button for a sync window. Check the Bluetooth adapter in Settings → Devices. |
| Pairing failed | Press the button, then submit within 60 seconds. |
| Last sync error says insufficient encryption | The watch is not bonded to this Home Assistant. Repeat Step 6. |
| Pending count never falls | The transfer is failing before the ack. Look at Last sync error and the Home Assistant log for `pinedog`. |
| Clock says NOT SET | Normal until the first successful sync. |
| Watch resets often | Look at the boot count on the screen. The watchdog resets the chip if it hangs. Report the number and when it changed. |

## Recovering a bricked watch

If the watch shows nothing and does not respond to the button, it may have
crashed in a bad state. Use the SWD connection and Step 4 to flash the backup.
A backup taken in Step 2 always restores the old behaviour.

## What is not verified

Everything below is still to be checked on a real watch:

- Flashing, boot, and the screen (font, orientation, backlight pin).
- The button, the 30-second screen timeout, and the sync window.
- Charging detection (pins P0.12 and P0.19, taken from the InfiniTime source,
  not measured on this board).
- The battery voltage curve.
- Bluetooth bonding and `client.pair()` in BlueZ on the Raspberry Pi.
- Record CRCs and the transfer over the air.
- Battery life. The sensor wakes the CPU 25 times a second, which is almost
  certainly too much. Measure for a week before trusting any figure.
- The activity thresholds. They are guesses and need tuning on real data.

## License

MIT (see `LICENSE`). Zephyr is Apache-2.0 and is compatible.

The battery voltage-to-percent table and the charging and power pins in
`firmware/app/src/battery.c` match InfiniTime's values, which are in its GPL-3.0
source (`BatteryController.cpp`, `PinMap.h`). The code here is written from
scratch; the table values are measurements of the same LiPo and divider, and
are not copied from InfiniTime's code. If you need a stricter reading, the owner
should check that before reusing the image commercially. The stock firmware
images are not included in this repo.

## GitHub repo settings (optional)

The repository description and topics are optional. HACS shows them, but they
are not needed to install or use the integration from a custom repository. The
validation workflow skips them, and brand assets, for that reason.

## Releasing a version

The version lives in `custom_components/pinedog/manifest.json`. HACS installs a
GitHub release, so each version needs a tag with the same number:

1. Set `version` in `manifest.json` (for example `0.2.2`).
2. Merge to the default branch.
3. Tag and push: `git tag v0.2.2 && git push origin v0.2.2`.

`release.yml` checks that the tag matches the manifest and creates the release.
`validate.yml` runs HACS and hassfest checks, plus the host tests, on every push.

## Repository layout

| Path | Contents |
|---|---|
| `firmware/app/` | Zephyr application for the PineTime. |
| `firmware/core/` | Pure C logic, tested on a computer. |
| `firmware/release/` | Built image, ELF file, and checksums. |
| `custom_components/pinedog/` | Home Assistant integration (installed by HACS). |
| `hacs.json` | HACS metadata. |
| `.github/workflows/` | Validation and release automation. |
| `tests/ha/` | Python tests for the integration. |
| `docs/DESIGN.md` | System design. |
| `docs/FIRMWARE.md` | Firmware reference and known gaps. |
| `docs/RESEARCH.md` | Notes on storage and the design choices behind them. |
