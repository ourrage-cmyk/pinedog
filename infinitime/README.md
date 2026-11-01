# InfiniTime Motion for Home Assistant

Tracks a dog's active time, sedentary time, and daily activity score from a stock InfiniTime watch over Bluetooth. The watch keeps its normal firmware: nothing is flashed and nothing is paired. Over time it learns each dog's own usual pattern, so "more or less than usual" becomes more accurate.

Status: **host-tested only.** The Bluetooth code has not run against a real watch or a live Home Assistant. Treat the first install as a test.

See [ENTITIES.md](ENTITIES.md) for every entity and how it is calculated.

## What the watch can and cannot measure

The watch keeps no minute history that Home Assistant can read over BLE. Home Assistant only knows what it sees while connected.

- **Polling.** Home Assistant connects every 5 minutes and samples motion for 60 s. That sample stands for the time since the last poll, up to 10 minutes. Longer gaps are unknown and count toward neither active nor sedentary time.
- **Accuracy depends on connection frequency.** Shorter polls give finer active and sedentary totals. The default trades that against battery.
- **Battery.** Each poll holds the radio for about a minute. This has not been measured. Expect it to cost noticeably more than the stock idle use. Check the battery entity over a week before changing the interval.
- **Off-body time** is not detected. A watch taken off counts as sedentary until the next gap.
- **Continuous mode** (keeping one connection open and receiving notifications) would give finer data but cost more battery. It is not used by default.

## How the learning works

- Each poll's motion index is the spread of the acceleration magnitude over its 60 s sample. A still dog gives a near-zero value.
- Active vs sedentary uses the dog's own 30th percentile over the last 14 days. A quiet dog's threshold is low; an active dog's is high.
- "Usual" compares today's score so far with the median of the past 14 days at the same hour. It needs 3 past days. "Days learned" shows how many days it has.

Placeholders that need real dog data to tune: the 50 starting threshold, the 30 % percentile, and the 115 % and 85 % bands.

## Install (manual)

This integration sits in a subfolder, not at the root of `custom_components/`, so HACS does not install it. Copy it by hand:

1. Copy `infinitime/custom_components/infinitime_motion/` into your Home Assistant config folder as `custom_components/infinitime_motion/`. On Home Assistant OS, use the Samba or SSH add-on.
2. Restart Home Assistant.
3. Keep the watch on and within range of the Raspberry Pi. An "InfiniTime watch found" card should appear under Settings, Devices and services. Confirm it.

No pairing is needed.

## Limits

- **One connection at a time.** If a phone app holds the watch, Home Assistant may fail to connect. "Connected" will show off.
- **Changing the poll interval** requires editing `POLL_INTERVAL` and `SAMPLE_SECONDS` in `coordinator.py`. It is not a UI option yet.
- **Charging and heart rate** are not exposed by stock InfiniTime over BLE.

## Unverified on hardware

- The motion characteristic's behaviour, sample rate, and whether it works without a phone.
- Whether Home Assistant can connect while a phone is also near.
- Battery use at this poll rate.
- The absolute scale of the motion index, and whether the default threshold is sensible for any dog.
