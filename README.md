# Pinedog

> **Current version: integration 0.4.0.** Both collars run the InfiniTime build
> at commit `d47029c` (InfiniTime 1.14.1 with the Pinedog service). The SWD steps
> below apply only to the older v0.2.1 Zephyr image, and are not needed for the
> current collars. Do not flash v0.2.0: it never sends records to Home Assistant.

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
   latest version (0.4.0 or newer).
5. Restart Home Assistant (Settings → System → Restart).
6. Continue with [Step 6: pair the watch](#step-6-pair-the-watch). The watch
   still has to be flashed first (Steps 1–4).

## Update to version 0.4.0 with HACS

This update needs no flashing. Only Home Assistant changes.

1. In Home Assistant, open **HACS → Integrations → Pinedog**. Click the refresh
   icon at the top right if no update appears.
2. If it shows **Update**, click it, then **Download**. If not, open the ⋮ menu
   and choose **Redownload**, then pick version 0.4.0 or `main`.
3. Restart Home Assistant fully: Settings → System → Restart. Reloading the
   integration is not enough, because the new code loads only on restart.
4. Check it works: see [How to check it works](#how-to-check-it-works).

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

Without a button press, Home Assistant tries about every 30 minutes after a
success, or every 5 minutes after a failure. When a collar comes back into range
after being out of range for 5 minutes or more, for example after a run, it
syncs straight away. A dog that stays in range does not trigger a sync.

### Sync now

Each custom-firmware collar has a **Sync now** button. Press it to connect right
away, pull the stored records, and skip the retry schedule. The collar must be
in range. Home Assistant can only connect to a collar it has seen advertising
recently. If it cannot be reached, the button shows where the sync stopped:

| Stage | Meaning |
|---|---|
| not seen | No advertisement from the collar recently. Wake it and keep it near the Pi. |
| connect | Home Assistant could not open a connection. |
| GATT | A read, write or subscribe failed on the connection. |
| transfer | The stream did not finish, or fewer records arrived than the watch reported. Nothing was acknowledged. |
| clock | The Home Assistant clock is not set. |
| store | Home Assistant could not save the records. Nothing was acknowledged. |

The same service is available as `pinedog.sync_now`. Leave out the target to
sync every collar, or pass button entities. It returns the outcome per collar,
so you can call it from an automation or a script and read the result.

The collars sync one at a time, because the Raspberry Pi's Bluetooth chip has
few connection slots. A second collar waits for the first to finish.

## How to check it works

1. Settings → Devices & services → Pinedog: each collar has a **Sync now** button.
2. Developer tools → Actions: search for `pinedog.sync_now`. It should be listed.
3. Press **Sync now** on a collar. If it succeeds, **Last sync error** is empty.
   If it fails, the notification names the stage, and the same text appears in
   **Last sync error**.
4. Take a collar out of range for 5 minutes or more, then bring it back. Its
   **Last sync** should update on its own, without a button press.

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
| Pending count never falls | Press **Sync now**. The error names the stage where the transfer stops. The Home Assistant log for `pinedog` has the same detail. |
| No Sync now buttons after an update | Restart Home Assistant fully (Settings → System → Restart). A reload is not enough. |
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

The version lives in `custom_components/pinedog/manifest.json`. HACS offers the
latest GitHub release when one exists, and otherwise tracks the default branch.
Version 0.4.0 has no release tag yet, so HACS tracks `main` for it. To publish a
release, follow these steps:

1. Set `version` in `manifest.json` (for example `0.4.1`).
2. Merge to the default branch.
3. Tag and push: `git tag v0.4.1 && git push origin v0.4.1`.

`release.yml` checks that the tag matches the manifest and creates the release.
It attaches the firmware files in `firmware/release/`, so check that they match
the release before you publish.
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

## Pinedog (stock InfiniTime collar)

If your collar runs unmodified InfiniTime, no flashing or pairing is needed. See [docs/STOCK_INFINITIME.md](docs/STOCK_INFINITIME.md) for the Home Assistant setup, the Raspberry Pi Bluetooth setup, and what the watch can and cannot measure.
