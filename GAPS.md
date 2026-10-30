# Pinedog gap analysis

What a project of this scope needs, what is already covered, and what to do first.

**Sources:** root `DESIGN.md` and `FIRMWARE.md` in the project files, the code in PR #1 (branch `claude/project-thread-vh6j92`), and the official docs for PineTime SWD and HA statistics. Nothing here has been run on hardware.

**Key:** ✅ covered · ◐ partly · ✖ missing
**Priority:** **P0** before the collar goes on a dog · **P1** before the first week-long wear test · **P2** later

## 1. Fix these inconsistencies first

1. **Bootloader strategy.** `DESIGN.md` says the image installs over the air from stock InfiniTime through MCUboot, and the recovery firmware stays usable. `FIRMWARE.md` says the image overwrites the bootloader and app, and OTA is off. These cannot both be true. The choice decides how you recover a bad flash and how future updates ship. Pick one and update both docs.
2. **Log capacity.** `DESIGN.md` says the log holds about a year. `FIRMWARE.md` says the log partition is 1 MB. At 8 bytes per minute, 1 MB holds about 91 days (1,048,576 ÷ (8 × 1440)). Either the claim or the partition size is wrong.
3. **Where `DESIGN.md` lives.** It is at the repo root in the project files and at `docs/DESIGN.md` in PR #1. Choose one location.

## 2. Dog safety and hardware

| | Item | Status | Pri | Notes |
|---|---|---|---|---|
| ✖ | Collar holder or enclosure | Missing | P0 | No design for the mount. Needs a breakaway point, a shape that doesn't snag, and no small parts a dog could chew off and swallow. |
| ✖ | Battery safety | Missing | P0 | A LiPo against a dog's neck. Use a protected cell, never charge while the collar is on the dog, check daily for swelling or heat, and retire a damaged cell. |
| ✖ | Skin and fit | Missing | P0 | Two-finger fit check, daily neck check for rubbing and moisture under the case, and a short trial on the dog before a full week. |
| ◐ | Waterproofing | Partly | P1 | The design says splash resistant only. Still needed: protection for the magnetic charging contacts, and a rule that the dog does not swim with it. |
| ✖ | Spares and battery life | Missing | P1 | Keep a spare watch and charger. Cells lose capacity with cycles, so plan a replacement interval. |
| ✖ | Regulatory | Missing | P2 | Only matters if the device is ever shared or sold: radio certification and battery shipping rules. |

## 3. Recovery and flashing

| | Item | Status | Pri | Notes |
|---|---|---|---|---|
| ✖ | Back up the stock firmware | Missing | P0 | `FIRMWARE.md` says the original is not kept. Before the first flash, dump the full flash over SWD (`nrfjprog --readcode`) and keep the InfiniTime release image on hand. |
| ◐ | SWD access | Partly | P0 | `FIRMWARE.md` covers it, but the pad or pogo-pin layout is not documented. Pine64 lists GND, SWDCLK, SWDIO and 3.3 V. Build a fixture or document an opening procedure. Watches shipped after 20 Sep 2020 are already unlocked, and `nrfjprog --recover` erases the flash. |
| ✖ | Unbrick drill | Missing | P0 | Run the whole flash, recover and re-flash cycle on a spare watch first. |
| ✖ | Return to InfiniTime | Missing | P2 | Write the exact steps and which release image to use. |

## 4. Firmware: data integrity and power

| | Item | Status | Pri | Notes |
|---|---|---|---|---|
| ✖ | Records have no checksum | Missing | P0 | Nothing in `firmware/` checks a CRC. A power loss mid-write can leave a partial record that syncs as valid data. Add a per-record CRC or a valid marker. |
| ✖ | Watchdog | Missing | P1 | No hardware watchdog is configured. Add the nRF52 WDT and feed it from the main loop. |
| ◐ | Records before the clock is set | Partly | P1 | Records made before the first sync are flagged, and Home Assistant drops them. A reboot during the day loses those minutes. Store time since boot and anchor it at the next time write instead. |
| ◐ | Battery level | Partly | P1 | Reported as 0xFF until the ADC is wired. This is the main target (at least a week per charge), so it has to be measured. |
| ✖ | Measured current | Missing | P1 | The 55 µA budget is an estimate. Measure average current with a power profiler (for example Nordic's Power Profiler Kit II) for advertising, sampling and sync. |
| ◐ | Sampling method | Partly | P1 | `FIRMWARE.md` says the firmware wakes 25 times a second, while `DESIGN.md` specifies the FIFO. Move to the FIFO watermark before measuring battery. |
| ✖ | Clock source | Missing | P2 | Confirm timekeeping uses the 32.768 kHz crystal. An RC clock can drift about 250 ppm, which is roughly 2.5 minutes a week. |
| ✖ | Flash wear and power loss | Missing | P2 | Erasing is rare (one ring pass is about 91 days), so wear is not a concern. Test the erase-ahead logic and an interrupted write on the bench. |
| ◐ | Version handshake | Partly | P2 | Status has a version byte. Define what Home Assistant does on a mismatch. |

## 5. Bluetooth

| | Item | Status | Pri | Notes |
|---|---|---|---|---|
| ✖ | Write security | Missing | P0 | `ble_sync.c` gives Time, Request and Ack write permission with no encryption or pairing. Any nearby client can send an Ack and delete unsynced records, or set the clock. Require LE Secure Connections with bonding. A passkey shown on the watch screen on button press works well. |
| ✖ | Bonding loss | Missing | P1 | Plan the re-pair procedure for reinstalling Home Assistant, changing the adapter, or a watch reset. |
| ◐ | Range | Partly | P1 | The design mentions ESPHome proxies. Measure real range at the door and in the garden before relying on it. |
| ◐ | Pi Bluetooth reliability | Partly | P1 | The Pi 4 built-in adapter shares its radio with Wi-Fi. Plan a USB adapter or proxy as a fallback, and watch for failed connections. |

## 6. Home Assistant integration

| | Item | Status | Pri | Notes |
|---|---|---|---|---|
| ✅ | Config flow, Bluetooth discovery, pull with end marker, daily totals, 7-day baseline, protocol and activity tests | Covered | — | In PR #1. |
| ✖ | Ack before save | Missing | P0 | `sync.py` writes the Ack before `coordinator.py` saves the records. A crash between the two loses data on both sides. Save first, then ack. |
| ✖ | Long-term statistics are hourly | Missing | P1 | Statistics store hourly values, so minute detail cannot live there. Keep per-minute data in the integration's own store and export hourly statistics. The design implies minute resolution, so update it. |
| ✖ | Sync-flow tests | Missing | P1 | The tests cover pure functions only. Add a fake BLE client that tests disconnects mid-transfer, duplicate records and ack ordering. |
| ✖ | Translations and options | Missing | P1 | Add `strings.json` and translations for the config flow, plus an options flow for thresholds. |
| ✖ | Reauth and diagnostics | Missing | P1 | Add reauth for re-pairing, and a redacted diagnostics download. |
| ✖ | HACS packaging | Missing | P2 | Add `hacs.json`, fill in `codeowners` and `issue_tracker` in the manifest, and tag releases. |
| ✖ | Dashboards and notifications | Missing | P2 | For example: "no walk logged today" or "battery below 20%". |
| ✖ | Multiple dogs | Missing | P2 | Each collar needs its own config entry and device, with its own thresholds and baseline. |

## 7. Data and classifier

| | Item | Status | Pri | Notes |
|---|---|---|---|---|
| ✖ | Ground truth | Missing | P0 | Nothing yet collects labelled data. Film two or three sessions per activity class and label the minutes against the video timestamps. |
| ✖ | Classifier validation | Missing | P1 | Thresholds are untested guesses. Hold out one week and report precision and recall per class against the video labels. |
| ✖ | Per-dog calibration | Missing | P1 | Counts depend on dog size and how tight the collar is. Plan per-dog thresholds and a short calibration walk. |
| ◐ | Placement | Partly | P2 | Vector magnitude removes the orientation problem, but head shakes and neck movement may dominate on a collar. Check on the real dog. |
| ✖ | Optional GPS | Missing | P2 | Not needed for the goal, but record the trade-off (battery and size) in the design. |

## 8. Repo, docs, licensing, CI and release

| | Item | Status | Pri | Notes |
|---|---|---|---|---|
| ✖ | LICENSE | Missing | P0 | The repo has none. Zephyr and MCUboot are Apache-2.0. InfiniTime is GPL-3.0, so copying any of its code changes the licence. Check Nordic's HAL terms too. |
| ✖ | README | Missing | P1 | It is one line. Add an overview with links to the design and firmware docs. |
| ✖ | CI | Missing | P1 | No workflow. Run `make -C firmware test` and `pytest tests/ha` on every PR. |
| ✖ | Release process | Missing | P1 | Tag firmware and integration versions, publish the `.hex` with a checksum, and keep a changelog. |
| ◐ | Operating guide | Partly | P1 | `FIRMWARE.md` covers build and flash. Add a guide for wearing, charging, syncing and troubleshooting. |

## 9. Testing

| | Item | Status | Pri | Notes |
|---|---|---|---|---|
| ✅ | Host tests | Covered | — | `firmware/test` and `tests/ha`. |
| ✖ | Bench test plan | Missing | P1 | Cover power loss mid-write, reboot, out-of-range sync and a full flash cycle. |
| ✖ | Pilot pass criteria | Missing | P1 | Define before the week: battery drop per day, sync success rate, and maximum data gap. |
| ✖ | Hardware-in-the-loop tests | Missing | P2 | Automate the BLE sync against a real watch. |

## 10. Covered already

- Goals, hardware constraints, and the sensor and record design (`DESIGN.md`)
- Build and flash instructions and known gaps (`FIRMWARE.md`)
- Per-minute summariser and ring log with host tests (`firmware/core`)
- Zephyr app that samples, stores and serves records over BLE (`firmware/app`)
- Home Assistant integration with config flow, sync, daily totals and baseline (`custom_components/pinedog`)

## 11. Recommended order

1. Settle the bootloader strategy and fix the log-capacity claim.
2. Back up the stock firmware and rehearse recovery on a spare watch.
3. Fix data integrity: save before ack, add record checksums, and add the watchdog.
4. Require BLE pairing for writes.
5. Wire the battery ADC and measure current. This is the test of the one-week target.
6. Design the collar holder and the battery rules, then trial it on the dog for a few hours.
7. Film labelled sessions, tune the thresholds, and validate on a held-out week.
8. Add the HA sync-flow tests, translations, reauth, diagnostics, CI and a licence.
9. Run the week-long pilot against the pass criteria.
10. Then decide on OTA with MCUboot, multiple dogs, dashboards and notifications.
