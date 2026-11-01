# InfiniTime Motion for Home Assistant

Reads steps, battery and a short motion sample from a stock InfiniTime watch over Bluetooth. The watch keeps its normal firmware: nothing is flashed and nothing is paired.

Status: **host-tested only.** The Bluetooth code has not run against a real watch or a live Home Assistant. Treat the first install as a test.

## Entities

See [ENTITIES.md](ENTITIES.md) for how each value is calculated.

| Entity | Notes |
|---|---|
| Steps today | Sum of step deltas since local midnight |
| Steps last hour | From stored polls, so resolution is one poll interval |
| Active intervals today | Polls with at least 30 steps. Counts intervals, not minutes |
| Steps vs 7-day baseline | Percent of the median of the previous 7 days. Appears after 3 days of data |
| Battery | Standard Battery service |
| Motion index | Spread of a 5 s raw accelerometer sample per poll. Relative only |
| Connected | Whether the last poll reached the watch |
| Last seen | Time of the last successful poll |

## Install (manual)

This integration sits in a subfolder, not at the root of `custom_components/`, so HACS does not install it. Copy it by hand:

1. Copy `infinitime/custom_components/infinitime_motion/` into your Home Assistant config folder as `custom_components/infinitime_motion/`. On a Raspberry Pi running Home Assistant OS, use the Samba or SSH add-on.
2. Restart Home Assistant.
3. Keep the watch on and within range of the Pi. Home Assistant should show an "InfiniTime watch found" card under Settings, Devices and services. Confirm it.

No pairing is needed. Home Assistant reads the watch every 15 minutes, while the watch is in range.

## Limits

- **One connection at a time.** While a phone app is connected, Home Assistant may fail to connect. Close the app on the phone, or disable its Bluetooth sync, if the sensors show "Connected: off".
- **No history on the watch.** Steps are only known at each poll. Steps taken while the watch is out of range are added at the next successful poll, so they are counted, but the timing is only as fine as the poll interval.
- **Step counter resets.** A lower counter reading is treated as a reset. Steps taken between the last poll and a watch reboot may be lost.
- **First day.** Steps before Home Assistant first sees the watch are unknown.
- **Battery.** Polling every 15 minutes with a 5 s motion sample keeps radio time short, but the battery effect is not measured yet.
- **Charging and heart rate** are not exposed by stock InfiniTime over BLE and are not included.

## Unverified on hardware

- The notification rate of the motion characteristic, and whether it runs without a phone.
- Whether the watch accepts a connection from Home Assistant while it is advertising to a phone.
- The absolute scale of the motion values. The motion index is only compared against itself.
- Battery use with this polling schedule.
