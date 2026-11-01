# Pinedog on stock InfiniTime

Pinedog tracks a dog's active time, sedentary time, and a daily activity score from a PineTime collar. This page covers the stock InfiniTime path: the watch keeps its normal firmware, nothing is flashed, and nothing is paired.

Status: **host-tested only.** The Bluetooth code has not run against a real collar on a Raspberry Pi. A separate test is checking that from a laptop. Treat the first install as a test.

See [STOCK_INFINITIME_ENTITIES.md](STOCK_INFINITIME_ENTITIES.md) for every entity and how it is calculated.

## What the watch can and cannot measure

The watch keeps no minute history that Home Assistant can read over BLE. Home Assistant only knows what it sees while connected. So all the learning happens in Home Assistant.

- **Sampling.** While the collar is in range, Home Assistant polls it at most every 10 minutes. Each poll samples motion for 60 s. That sample stands for the time since the previous poll, capped at 10 minutes. Longer gaps (collar out of range) count as unknown, not sedentary.
- **Advertisements.** The collar advertises constantly. Home Assistant uses those as the trigger, so a poll starts when the collar is near, and the schedule stops it polling more than once per 10 minutes.
- **Off-body time** is not detected. A collar taken off counts as sedentary until the next gap.
- **Sample rate.** The motion characteristic (`00030002`) sends about 10 samples per second with notifications on, so one 60 s window gives about 600 samples.
- **Connection timing.** On a real watch (InfiniTime 1.14.1) scan and connect took 5 to 6 s, and five connect cycles in a row all succeeded.
- **Radio time.** Each poll is roughly 5 to 6 s to connect plus 60 s of sampling, so about 70 s of radio per 10 minutes. Battery drain at that duty cycle is not measured yet. Check the battery entity over a week before changing the interval.

## Requirements and Bluetooth setup

- Raspberry Pi 4 running Home Assistant OS, with its **built-in Bluetooth** adapter. No ESPHome proxy is needed for one collar in the living room.
- Check the adapter: the Bluetooth integration in Home Assistant should list the Pi's built-in adapter.
- Check range: put the collar near the spot where the dog rests. If the "In range" entity stays off while the dog is nearby, the Pi is too far away.
- **Two dogs:** add the integration twice, once per collar. Each gets its own storage and its own baselines. One Pi can handle both.
- **Poor range:** add an ESPHome Bluetooth proxy near the dog's usual spot. This is only needed if the built-in adapter cannot hear the collar. Not needed to start.

## Pairing

- **Stock InfiniTime: no pairing.** Confirmed on a real watch (InfiniTime 1.14.1): the battery level and motion notifications work without a bond.
- Custom firmware (the Pinedog record protocol) asks you to press the watch button and pair in the config flow. Its pairing window lasts 60 seconds.

## How the learning works

- **Activity index.** Each poll's motion index is the spread of the acceleration magnitude over its 60 s sample. A still dog gives a near-zero value.
- **Active vs sedentary.** Uses the dog's own 30th percentile over the last 14 days, so a quiet dog's threshold is low and an active dog's is high. Until 30 intervals exist, a placeholder of 50 is used.
- **Short-term usual (14 days).** Compares today with the last 14 days, weighting recent days more. Shows as "Activity vs 14-day usual".
- **Long-term usual (never resets).** One weighted average per hour of the week, kept in Home Assistant. It learns at the end of each day, so today never teaches itself. Each hour learned counts half as much after about 8 weeks. Storage is fixed at 168 hours regardless of how long the dog is tracked. It shows as "Activity vs long-term usual", with "Long-term days learned" alongside. A day counts as learned after six worn hours.
- **Storage.** Stored in Home Assistant's `.storage`. The format is versioned, so an update upgrades saved data instead of discarding it.

Placeholders that need real dog data to tune: the 50 starting threshold, the 30% percentile, and the 115% and 85% bands.

## Install (manual)

This integration is a HACS custom repository. Add `https://github.com/ourrage-cmyk/pinedog` as a custom repository of type Integration, then install Pinedog and restart Home Assistant.

Manual install, if you prefer: copy `custom_components/pinedog/` into your Home Assistant config folder, then restart.

Then keep the collar on and near the Pi. A "Collar found" card appears under Settings, Devices and services. Confirm it.

## Limits

- **One connection at a time.** If a phone app holds the collar, Home Assistant may not connect. "In range" will show off.
- **Poll timing** is set in `stock_coordinator.py` (`MAX_INTERVAL_S`, `SAMPLE_SECONDS`). It is not a UI option yet.
- **Charging and heart rate** are not exposed by stock InfiniTime over BLE and are not included.

## Characteristics used

| Purpose | UUID | Format |
|---|---|---|
| Raw motion (used) | `00030002-78fc-48fe-8e23-433b3a1942d0` | 6 bytes, int16 x, y, z, little-endian, about 10 Hz on notify |
| Step count (not read) | `00030001-78fc-48fe-8e23-433b3a1942d0` | uint32 little-endian, read and notify |
| Battery level | `00002a19-0000-1000-8000-00805f9b34fb` | uint8 percent, read and notify |

The step count is on the watch but Pinedog does not read it, because steps are not a headline measure on a dog.

## Unverified on hardware

- Only one of two watches was visible during the first test, so two-collar setups are not yet tested.
- Whether motion notifications keep working while a phone is also connected.
- Whether Home Assistant connects reliably from the Pi's built-in adapter at the dog's usual spot.
- Battery drain at a 10-minute poll with a 60 s sample (about 70 s of radio per poll).
- The absolute scale of the motion index.
- The placeholder threshold and bands.
