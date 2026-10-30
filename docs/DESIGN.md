# Pinedog design

Turn a PineTime into a collar-mounted activity logger for a dog, synced to
Home Assistant over Bluetooth.

## Hardware facts that shape the design

| Part | What it means for us |
|---|---|
| nRF52832 (64 MHz Cortex-M4, 512 KB flash, 64 KB RAM) | Bluetooth Low Energy only. **No Wi-Fi.** |
| BMA421 accelerometer | Has a hardware FIFO, so the CPU can sleep while it samples. |
| 4 MB SPI NOR flash | Years of per-minute records fit easily. |
| 180 mAh battery | Stock InfiniTime gets ~1 week with the screen mostly off. A purpose-built firmware with no display, no heart rate and slow advertising should do 2 to 3 weeks (estimate, to be measured). |
| No battery-backed clock | Home Assistant sets the time on every sync. |

Everything that is not the accelerometer, flash, button, battery monitor and
radio stays powered down: heart-rate sensor, display backlight and panel,
touch controller, vibration motor.

## Pieces

```
 PineTime on collar                         Home Assistant
 ┌─────────────────────────┐   BLE GATT   ┌──────────────────────────────┐
 │ BMA421 FIFO @ 25 Hz     │ ───────────▶ │ pinedog custom integration   │
 │  → per-minute summary   │  (when in    │  (uses HA Bluetooth: built-in │
 │  → ring log in SPI flash│   range)     │   adapter or ESPHome proxies) │
 │ slow BLE advertising    │              │  → backfilled statistics      │
 └─────────────────────────┘              │  → daily sensors + baseline   │
                                          └──────────────────────────────┘
```

### 1. Firmware (`firmware/`, Zephyr RTOS)

A small Zephyr application instead of a stripped InfiniTime. Zephyr already
supports the PineTime board, with its BLE stack and a BMA4xx accelerometer
driver. The first version flashes the whole chip over SWD and replaces
InfiniTime (see `docs/FIRMWARE.md`). Over-the-air updates over the stock
InfiniTime bootloader are not used, because that needs signing keys we do not
have.

Sampling loop (see `docs/ACTIVITY.md` for the reasoning):

1. BMA421 runs at 12.5 Hz in normal mode with the FIFO enabled, ±2 g. The
   FIFO watermark is set to about 768 bytes, which is roughly 10 seconds of
   data.
2. The CPU wakes about 0.1 times a second (watermark interrupt), reads the
   FIFO in one burst, and goes back to sleep. Once a minute it also reads the
   on-chip step counter as an extra signal.
3. For each sample it computes the vector magnitude minus 1 g (gravity), and
   accumulates per-minute:
   - **activity count**: sum of |magnitude − 1 g| (the same idea as the
     "counts" used by ActiGraph and veterinary activity monitors)
   - **peak** magnitude
   - **cadence**: dominant periodicity of the signal over the minute, found by
     counting zero crossings of the band-passed signal
4. At the end of each minute it classifies the minute:
   - `rest`: counts below a low threshold
   - `light`: moving, but not rhythmic (sniffing, shifting, playing in place)
   - `walk`: rhythmic movement at walking cadence with moderate counts
   - `run`: rhythmic movement with high counts / higher cadence

   Thresholds live in a config characteristic so they can be tuned from Home
   Assistant after watching real data, without reflashing.

Per-minute record (8 bytes):

| Field | Type | Notes |
|---|---|---|
| minute | uint32 | minutes since Unix epoch |
| counts | uint16 | saturating |
| class | uint8 | 0 rest, 1 light, 2 walk, 3 run, 4 not worn (on charger) |
| cadence | uint8 | in 0.1 Hz units |

Every minute gets a record, including a quiet one (rest) and a minute on the
charger (class 4). Stillness is never a reason to skip a minute. The only
non-wear state is charging. Records are collected in RAM and flushed to flash
every 10 minutes. The log is a ring buffer in SPI flash (4 KB sectors,
erased one sector ahead of the write pointer), holding about a year before
wrapping. Unsynced data is never lost unless the dog is out of range for a
year.

Button: a short press lights the screen for 5 seconds with battery %, today's
active minutes and whether the last sync worked. Otherwise the display is off.

### 2. Bluetooth sync

- The watch advertises a Pinedog service UUID every 2 s (≈ 20 µA average).
  The advertisement carries battery % and the number of unsynced records, so
  Home Assistant knows whether a connection is worth making.
- Home Assistant connects when it sees the watch and there is anything to
  sync. It writes the current time, reads records after its last acknowledged
  position in 240-byte chunks (30 minutes per notification), then writes back
  the acknowledged position and disconnects. A full day syncs in a couple of
  seconds.
- No connection is held open, so the radio is idle except for the short
  advertising bursts.

GATT service `Pinedog`:

| Characteristic | Access | Purpose |
|---|---|---|
| Time | write | Unix time from Home Assistant |
| Status | read | battery, firmware version, oldest/newest record, unsynced count |
| Request | write | "send records starting at minute N" |
| Records | notify | packed 8-byte records |
| Ack | write | "everything up to minute N is stored on the HA side" |
| Config | read/write | classifier thresholds, advertising interval |

### 3. Home Assistant integration (`custom_components/pinedog/`)

A custom integration (installable through HACS) built on Home Assistant's own
Bluetooth stack, so it works with the HA host's built-in Bluetooth and with
ESPHome Bluetooth proxies if the collar needs better range at the door or in
the garden.

It imports every minute record into Home Assistant's long-term statistics with
the correct historical timestamps, so graphs show when the dog actually moved
even if the sync happened hours later.

Entities:

- Active time today (light + walk + run minutes)
- Sedentary time today (rest minutes)
- Walking time today (walk + run minutes)
- Motion today (sum of counts)
- Activity vs baseline: today's estimated full-day motion as a percent of the
  learned expectation for that weekday (100 = typical). See `docs/ACTIVITY.md`.
- Baseline status: `learning` until 7 valid days exist, then `waiting` (too
  little of today worn yet), `below`, `normal` or `above`
- Baseline confidence: how much of the expectation comes from data rather than
  the population prior
- Wear time today, so partly worn days are easy to spot
- Battery, last sync, unsynced records

Daily totals for the previous days are kept as statistics, so the standard
statistics graph card can show a week or month of active, sedentary and walking
time per day.

## Battery budget (estimate)

| Consumer | Average current |
|---|---|
| nRF52832 sleep with RTC | ~3 µA |
| BMA421 normal mode 12.5 Hz, FIFO (BMA400 table, to confirm) | ~3 to 8 µA |
| CPU wake about 0.1 times a second to drain FIFO | ~0.5 µA |
| BLE advertising every 2 s | ~20 µA |
| SPI flash in deep power-down, writes once per minute | ~3 µA |
| Syncs (a few seconds per hour) | ~5 µA |
| **Total** | **~40 µA** |

180 mAh / 40 µA ≈ 190 days on paper. Real PineTimes leak more than the
datasheets suggest (regulator, display controller in sleep, board leakage), so
the realistic target is **2 to 4 weeks**. We will measure with the battery
voltage reported at every sync.

## Physical notes

- The PineTime is splash resistant, not built for swimming. Avoid long swims.
- Mount it on the collar so the case sits flat against the side or underside
  of the neck. Orientation does not matter for the classifier because it uses
  vector magnitude.

## Build order

1. Firmware: storage ring, accelerometer driver and minute summariser, with
   unit tests on the host for the summariser and the ring buffer.
2. Firmware: BLE service and button/status screen.
3. Home Assistant integration with a fake device for testing.
4. Wear it for a week, then tune the classifier thresholds from real data.
