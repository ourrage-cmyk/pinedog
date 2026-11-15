# Pinedog

Pinedog turns a first-generation PineTime into a dog activity collar. The watch
reads its accelerometer, keeps one motion summary per minute, and hands those
summaries to Home Assistant over Bluetooth when the collar is in range. Home
Assistant turns them into daily active, sedentary and walking time, a usual
pattern for the dog, and the collar's battery level.

The collar has no heart-rate sensor, no GPS and no step counter in use. The
screen stays off while the collar is worn. Everything below comes from the
accelerometer alone.

## What you get

| Entity | What it means |
|---|---|
| Active time today | Minutes classed as light, walk or run. |
| Sedentary time today | Minutes classed as rest. |
| Walking time today | Minutes classed as walk or run. |
| Wear time today | Active plus sedentary minutes. Charging minutes are not counted. |
| Motion today | Sum of the minute activity counts for the day. |
| Activity vs 14-day usual | Today so far, scaled to a full day, as a percent of this dog's usual. 100 is typical. |
| Activity vs baseline | `learning`, `waiting`, `below`, `normal` or `above`, compared with the 14-day usual. |
| Baseline confidence | How much of the 14-day usual comes from this dog's own data. |
| Activity vs long-term usual | Today so far, as a percent of the usual for the same hours of the week. |
| Long-term days learned | Days that have taught the long-term usual. |
| Battery | Charge percent reported by the collar. |
| Charging | On while the collar is on its charger. |
| Charge soon | On at 20 % or less while not charging. |
| Unsynced records | Minutes the collar holds that Home Assistant has not stored yet. |
| Last sync | When the last sync succeeded. |
| Last sync error | The last failure, with the stage where it stopped. Empty after a good sync. |
| Sync now (button) | Connects to the collar at once and pulls its stored records. |
| Reset learning (button) | Starts the dog's usual pattern again from now. |
| `pinedog.sync_now` (service) | The same sync as the button, for automations. Returns the outcome per collar. |

## How the numbers are made

The accelerometer measures acceleration along three axes, and nothing else. Every
number above is derived from that. Some steps are direct measurements. Others are
rules, or estimates that improve as data arrives. Each step below says which.

### 1. The collar: a reading every 100 ms (measured)

The collar reads the accelerometer ten times a second. Each reading gives a total
acceleration, the vector length of the three axes, in units of gravity (g). A dog
standing or lying still gives about 1 g, whatever way the collar is turned,
because gravity is the only steady force. Movement pushes that length above and
below 1 g. The watch uses only how far the length strays from 1 g, so the
collar's orientation does not matter.

### 2. The collar: one summary per minute (measured, then rules)

For each minute the collar works out three things.

- **Counts** (the movement amount). The distance from 1 g is added up over the
  minute's readings and scaled to a full minute, so a minute with a few readings
  is not read as rest. Roughly, a count of 50 means the collar strayed from 1 g by
  about 0.08 g on average, and a count of 1200 means about 2 g on average. Counts
  saturate at 65 535.
- **Rhythm** (cadence). The collar counts how often the movement swings back
  through its average, and turns that into cycles per second. It is a rough
  stand-in for step rate.
- **Class**, from fixed rules:

  | Class | Rule |
  |---|---|
  | Rest | counts below 50 |
  | Light | everything else that is not walk or run |
  | Walk | counts at least 300 and rhythm at least 1.5 cycles per second |
  | Run | counts at least 1200 and rhythm at least 3 cycles per second |

  A minute with large counts but no clear rhythm is light. A minute with no
  readings at all is recorded as rest.

  These thresholds are fixed guesses. They have not yet been checked against
  video of this dog.

- **Not worn.** Any minute spent on the charger is recorded as not worn. Not-worn
  minutes are left out of every total.

Each minute becomes one 8-byte record. The collar keeps records until Home
Assistant confirms it has stored them, and holds about 60 days at most.

### 3. Home Assistant: day totals (direct sums)

Home Assistant adds up each day's records in its own time zone:

- Active = light, walk and run minutes.
- Sedentary = rest minutes.
- Walking = walk and run minutes.
- Motion = the sum of the minute counts.

Sedentary does not mean "not worn". A dog asleep all day gives about 1 440
sedentary minutes. A collar left lying still off the dog, and not on the charger,
also looks like rest, so keep it on the dog.

### 4. The 14-day usual: what "normal" means for this dog (estimate)

The usual is the expected full-day motion for this dog, learned from its own
recent days:

1. **Full-day figure.** Each past day with at least 6 hours of wear becomes
   `motion × 1 440 ÷ worn minutes`. A day worn for 12 hours is scaled up to a
   full day, so partly worn days can be compared.
2. **Log scale.** The figures are worked on a logarithmic scale, because motion
   varies over a wide range.
3. **Recent days count more.** A day counts half as much as the day after it
   for every 14 days of age. Only the last 14 days are used.
4. **Robust centre.** The centre is a weighted median, not an average. One odd day,
   such as a bath, a vet visit or a broken collar, does not move it much. The
   spread is the median absolute deviation, with a floor of 0.25 on the log
   scale, so a run of identical days does not look too certain.
5. **Starting guess.** Until the dog has data, the estimate is pulled toward a
   generic guess of 100 counts a minute. That guess is worth one day, so it
   fades after the first real day.
6. **Weekday adjustment.** The same calculation is repeated on that weekday's
   history, and blended into the all-days figure. With only 14 days of history
   there are at most two past days of any one weekday, so this adjustment is weak
   for now.

From that expected value:

- **Activity vs 14-day usual** is today's full-day figure divided by the expected
  value, times 100. Today's figure is extrapolated from the wear so far, so it is
  an estimate early in the day.
- **Status** stays `learning` until seven valid days exist, and `waiting` until
  there is an hour of wear today. After that it is `below`, `normal` or `above`
  depending on whether today's figure is more than one spread away from the
  usual. With the minimum spread, `normal` covers roughly 78 % to 128 % of the
  usual.
- **Baseline confidence** is the share of the estimate that comes from data
  rather than the starting guess. It is 50 % after one full day, and it levels off
  near 90 % because only 14 days are used.

### 5. The long-term usual: same hours, every week (estimate)

The long-term usual is kept separately, so it is not reset by the 14-day window.

- There is one slot for each hour of the week, 168 in all. Each finished day
  adds its motion for every hour that had at least 30 minutes of wear.
- Values are stored on a log scale and averaged with a half-life of eight weeks.
  The usual can change with the seasons, but slowly.
- **Activity vs long-term usual** compares today's hours so far with the usual
  for those same hours of the week. Only hours with at least 30 minutes of wear
  today, and at least one earlier observation, are compared. It appears after
  seven days with at least six worn hours each.

### What is measured and what is estimated

| Measured or recorded directly | Estimated or derived |
|---|---|
| Acceleration readings, and the minute counts from them | Rest, light, walk or run: fixed rules applied to counts and rhythm |
| Rhythm (cycles per second) | Walking versus other active time: rhythm is a rough proxy |
| Charging state and the collar's battery percent | Full-day figures, the usual, the percents, the status and the confidence |
| Sync times, errors and the unsynced count | The long-term usual |

### What the sensor cannot tell

- It does not know where the dog is, or what its heart rate is.
- Car rides, being carried, a rough play session, or a collar knocked against
  something all look like motion. They can count as light, walk or run.
- A dog lying still on a sofa and a collar lying still on a table look the same.
- Thresholds are rules, not calibration against this dog. Treat the numbers as a
  consistent index for this dog over time, not as calories or distance.

## Install

### 1. The collar: Pinedog firmware

The collar needs the Pinedog build of InfiniTime 1.14.1. Its Bluetooth firmware
revision starts with `1.14.1-pd`. The build is a DFU zip that installs over
Bluetooth, so no programmer is needed. The full steps are in
[docs/PHONE_INSTALL.md](docs/PHONE_INSTALL.md). In short:

1. Get the DFU zip. In the repository's Actions tab, open the latest successful
   run of **InfiniTime store-and-sync DFU** and download the artifact
   `pinedog-infinitime-dfu`. Unzip it once, keep the inner
   `pinedog-infinitime-…-dfu.zip`, and check it against `SHA256SUMS`.
2. Charge the collar to at least 50 %. Disconnect any other app from it, such as
   Gadgetbridge, because the watch accepts one Bluetooth connection at a time.
3. Keep the stock InfiniTime DFU zip so you can roll back.
4. In nRF Connect (Android or iPhone), connect to `InfiniTime`, tap **DFU**,
   choose **Distribution packet (ZIP)** and select the zip. Wait for the
   transfer to finish and for the watch to restart.
5. On the watch, open **Settings → Firmware** and tap **Validate**. If you do not
   validate, the bootloader reverts to the previous firmware on the next reboot.

Do not install the `.hex` files in `firmware/release/` or `release/`. They are
an older build that needs an SWD programmer and overwrites the bootloader.

Collars on unmodified InfiniTime also work, with fewer features. See
[Stock InfiniTime collars](#stock-infinitime-collars) below.

### 2. Home Assistant: the integration

Home Assistant 2025.1 or later, with the Bluetooth integration.

1. In HACS, open the menu (⋮) and choose **Custom repositories**. Add
   `https://github.com/ourrage-cmyk/pinedog` with the category **Integration**.
2. Search for **Pinedog**, open it and choose **Download**.
3. Restart Home Assistant fully (**Settings → System → Restart**). Reloading the
   integration is not enough, because the new code loads only on restart.
4. Within about a minute of the collar being in range, **Pinedog** appears under
   **Settings → Devices & services**. Configure it and name the dog.

To update later, use HACS in the same way, then restart Home Assistant fully.
Manual install is possible too: copy `custom_components/pinedog` into your
`config/custom_components/` folder and restart.

### 3. Bluetooth on the Home Assistant host

- The built-in Bluetooth of a Raspberry Pi 4 works. Keep the collar within a few
  metres of the adapter at first.
- The adapter has few connection slots, so collars sync one at a time. A second
  collar waits for the first to finish.
- A collar that is resting sends only occasional advertisements, so an at-home
  sync can start several minutes after its scheduled time.
- No pairing is needed.

## Sync behaviour

Home Assistant checks every minute whether a collar is in range.

- **At home.** After a successful sync, the next automatic attempt is 30 minutes
  later.
- **After a failure.** The next attempt is 5 minutes later.
- **Coming back.** A collar that has been out of range for 5 minutes or more
  syncs as soon as it is seen again, provided the last attempt was at least 5
  minutes ago. A dog that goes out on a run and comes home gets its records in
  Home Assistant straight away.
- **Sync now.** The button and the `pinedog.sync_now` service ignore the schedule.
  They fail at once if a sync is already running.

Records only move after Home Assistant has stored them. Nothing is lost if the
link drops part way: the collar resends from where Home Assistant left off.

### Reset learning

Reset learning clears the dog's daily totals, the 14-day usual and the long-term
usual. Learning starts again from that moment. Today's totals restart from zero
too, so they count only minutes recorded after the reset. Records the collar made
earlier and has not yet sent are skipped when they arrive. Use it after days of
wrong data, for example when the collar was not worn.

## Troubleshooting

**Last sync error** names the stage where a sync stopped:

| Stage | Meaning |
|---|---|
| not seen | No advertisement from the collar recently. Keep it in range of the adapter. |
| connect | Home Assistant could not open a connection. |
| GATT | A read, write or subscribe failed on the connection. |
| transfer | The stream stopped, or fewer records arrived than the collar reported. Nothing was acknowledged, so nothing was lost. |
| clock | The Home Assistant clock is not set. |
| store | Home Assistant could not save the records. Nothing was acknowledged. |

| Symptom | What to do |
|---|---|
| Unsynced records do not fall | Press **Sync now** and read the stage in the error. |
| Buttons or the service are missing after an update | Restart Home Assistant fully. |
| Sync keeps failing at "not seen" | Check the collar is awake and in range, and that the adapter is working. |
| Usual shows `learning` | Normal for the first week. |

## Stock InfiniTime collars

A collar on unmodified InfiniTime can be read too. It is polled instead of
keeping a record queue, so some things are missing:

- No walking time, no unsynced count, and no Sync now or Reset learning buttons.
- Sedentary and active time are set by a rule, not measured. Once the collar has
  30 readings, the quietest 30 % of its own readings count as sedentary. So about
  a third of the time is sedentary by design until more data is available.
- It has an **In range** sensor, which is on when the last poll reached the collar.

See [docs/STOCK_INFINITIME.md](docs/STOCK_INFINITIME.md) for setup.

## Known limits

- Battery life has not yet been measured for this build.
- The thresholds in the table above are fixed guesses and have not been tuned on
  this dog.
- The collar's Bluetooth link is not paired or encrypted. Anyone in Bluetooth
  range who can open that connection could read the records, so keep the
  collar's link to your own Home Assistant host.

For developers, the sync wire format is in
[docs/SYNC_PROTOCOL.md](docs/SYNC_PROTOCOL.md) and the firmware port is described in
[firmware/infinitime/README.md](firmware/infinitime/README.md).

## License

MIT (see `LICENSE`). InfiniTime is GPL-3.0 and the firmware build includes it.
