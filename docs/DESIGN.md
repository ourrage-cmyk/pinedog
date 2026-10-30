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

Sampling loop:

1. BMA421 runs at 25 Hz, ±4 g, in low-power mode with the FIFO enabled.
2. The CPU wakes about once a second (FIFO watermark interrupt), drains the
   samples, and goes back to sleep.
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

   Thresholds are compile-time constants in v0.2.0. The plan is a config
   characteristic so they can be tuned from Home Assistant without reflashing
   (not implemented yet).

Per-minute record (8 bytes, see `docs/FIRMWARE.md` for the exact layout):

| Field | Type | Notes |
|---|---|---|
| minute | uint32 | unix minute when the clock is set, uptime minute before |
| counts | uint16 | saturating |
| class | uint8 | bits 0–2: 0 rest, 1 light, 2 walk, 3 run, 4 not worn (charging); bits 3–6 boot id mod 16; bit 7 unsynced |
| crc | uint8 | CRC-8 over the other seven bytes |

Cadence is used on the watch to pick the class and is not stored.

Every minute is logged, even when the dog is still. The window closes on the
clock, so a quiet dog is rest, not missing data. Charging minutes are written
as not worn, and Home Assistant leaves them out of all totals.

That is about 11.5 KB per day. The log is a ring buffer in the external SPI
flash, in 992 KB of the 4 MB chip (4 KB sectors, erased one sector ahead of the
write pointer). It holds about 88 days of minutes before wrapping. Records only
leave the ring when Home Assistant acks them.

The head and count are checkpointed after every append and every ack. The
checkpoints go into a two-sector journal of 16-byte CRC-protected entries
(`firmware/core/journal.c`). On boot the newest valid entry wins, so a power
cut never leaves the watch with an empty or stale ring. See
`docs/RESEARCH.md` for the reasons.

Button: a press turns the screen on for 30 seconds with battery, pending records,
last sync result, boot id, active minutes in the last 24 hours, and pairing
state. It also opens a 60-second pairing window and a sync window, in which
Home Assistant is asked to connect promptly. The screen is off at all other
times, including boot.

### 2. Bluetooth sync

- The watch advertises a Pinedog service UUID every 2 s (≈ 20 µA average).
  After a button press it advertises every 100 ms for 60 s, with a sync-request
  flag in manufacturer data (company id 0xFFFF, reserved for testing). Home
  Assistant then connects without waiting for its normal retry interval.
- Home Assistant connects when it sees the watch and there is anything to
  sync. It writes the current time, requests the records, and receives every
  pending record in notifications sized to the link MTU (up to 16 records
  each). It stores them, and only then writes back the highest minute it
  stored and disconnects. A full day syncs in a couple of seconds.
- The watch streams all pending records, not only those after the requested
  minute. Acks are counts, not minutes, because uptime minutes restart after a
  reboot. Home Assistant drops anything at or below its own cursor, so a lost
  ack causes a resend but never a double count, and the watch still removes
  the records it has been acked.
- Home Assistant does not retry a failed connection on every advertisement.
  It waits 5 minutes after a failure and 30 minutes after a success
  (`custom_components/pinedog/schedule.py`).
- No connection is held open, so the radio is idle except for the short
  advertising bursts.

GATT service `Pinedog`:

| Characteristic | Access | Purpose |
|---|---|---|
| Time | write | Unix time from Home Assistant |
| Status | read | version 2, flags, pending, newest minute, uptime, boot id, battery (16 bytes) |
| Request | write | "start a transfer": the watch snapshots its pending count and streams exactly that many records |
| Records | notify | packed 8-byte records |
| Ack | write | "I stored the N oldest records" (a count, sent only after storing; the watch drops its N oldest) |
| Config | read/write | planned, not implemented: classifier thresholds |

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
- Activity vs baseline (today's motion as % of the 7-day rolling average at the
  same time of day)
- Exercise status: `below`, `normal` or `above` baseline, once 7 days of data
  exist (`learning` until then)
- Battery, last sync, unsynced records

Daily totals for the previous days are kept as statistics, so the standard
statistics graph card can show a week or month of active, sedentary and walking
time per day.

## Battery budget (estimate)

| Consumer | Average current |
|---|---|
| nRF52832 sleep with RTC | ~3 µA |
| BMA421 low-power 25 Hz | ~15 µA |
| Waking once a second to drain FIFO | ~10 µA |
| BLE advertising every 2 s | ~20 µA |
| SPI flash in deep power-down, writes once per minute | ~3 µA |
| Syncs (a few seconds per hour) | ~5 µA |
| **Total** | **~55 µA** |

180 mAh / 55 µA ≈ 130 days on paper. Real PineTimes leak more than the
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
