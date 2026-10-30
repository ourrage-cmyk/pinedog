# Activity pipeline: collect, quantify, learn, present

This explains why the activity numbers are computed the way they are. The
firmware is in `firmware/core/minute_summary.c`, the Home Assistant logic in
`custom_components/pinedog/activity.py`, and the tests in `tests/ha`.

Status: the Home Assistant part is implemented and tested on synthetic data.
The firmware collection changes below are recommendations. They have not been
built or measured on a PineTime, so the battery numbers are estimates.

## 1. Collect: BMA421 sampling

### What the stock watch does

InfiniTime's `Bma421::Process()` reads the sensor in a task that runs about
10 times a second. It configures the accelerometer at 100 Hz, ±2 g, normal
mode with averaging, and enables the on-chip step counter. It does not use the
FIFO, the watermark or any interrupts. The step count comes from the sensor's
own counter register, and the motion controller only consumes the values. So
the stock watch gets about a week from polling the sensor 10 times a second
while the rest of the system sleeps. Its power budget is dominated by the
display, heart-rate and BLE, not the accelerometer.

### What the current firmware does

`on_data_ready` runs once per sample, so the CPU wakes 25 times a second to
read the sensor and update the summary. The design doc describes a
watermark wake about once a second, so the code and the design disagree. The
PR already lists this as a known gap.

### Sensor facts used here

The BMA421 datasheet was not retrieved in this session. The figures below come
from the BMA400 datasheet, which is the same family, and must be checked
against the BMA421 datasheet before the firmware is written:

- FIFO: 1024 bytes, with a watermark interrupt when the unread count reaches
  the watermark. (BMA400; confirm for BMA421.)
- Normal mode ODR: 12.5 to 800 Hz. Low-power mode is fixed at 25 Hz.
- Current (BMA400 table, depends on oversampling setting): normal mode 3.5 to
  14.5 µA, low-power mode 0.85 to 1.35 µA.
- Step counter: the whole device draws about 4 µA with it running.
  Activity recognition and any-motion current are not given in that table.

### Recommended scheme

1. **Sample at 12.5 Hz in normal mode with the FIFO enabled.** Dog gait sits
   around 1 to 4 Hz, so 12.5 Hz (Nyquist 6.25 Hz) keeps the counts. This
   needs confirming on logs, which is listed below.
2. **Set the FIFO watermark to about 768 bytes.** At 12.5 Hz with 6 bytes per
   sample that is about 10 seconds of data per read. The CPU wakes about 0.1
   times a second, reads the burst, and goes back to sleep. That replaces the
   25 wakes a second in the current code.
3. **Run the per-minute summary over the FIFO batches.** Each minute still
   produces one record. Records are collected in RAM and flushed to the SPI
   flash every 10 minutes, so the flash is powered about 6 times an hour.
4. **Read the on-chip step counter once a minute as an extra signal.** It is
   two register reads, and it costs almost nothing. It is tuned for human gait,
   so on a dog it is a hint, not a count. Use it only if logs show it tracks
   walking.
5. **Hold off on duty cycling and any-motion gating.** Both save current when
   the dog is still, but they change the counts and bias the baseline. Measure
   first, and revisit only if the battery target is missed.
6. **Test low-power mode at 25 Hz.** Its current is lower than normal mode in
   the BMA400 table. It is worth one comparison on logs: if the counts match
   normal mode and the FIFO works in that mode, it is the cheaper option.

### Battery estimate

The accelerometer and its CPU wakes are a small part of the budget. The
arithmetic:

- 180 mAh over 1 week is about 1.07 mA average. Over 2 weeks it is about
  0.54 mA. The design target of 2 to 4 weeks therefore allows an average of
  roughly 0.2 to 0.5 mA, well above the 55 µA sum in `DESIGN.md`. The real
  limits are board leakage and the radio, not the accelerometer.

Estimates for this design (to be measured):

| Consumer | Current now | Recommended | Notes |
|---|---|---|---|
| Sensor, normal mode 25 Hz | ~5 to 15 µA | ~3 to 8 µA at 12.5 Hz | BMA400 table, oversampling dependent |
| CPU wakes (25/s, ~20 µs each) | ~2 µA | ~0.1 µA | Wake overhead, not the bus transfers |
| Bus transfers and FIFO reads | ~ same | ~ same | Sample count halves, so this drops too |
| Step counter, once a minute | - | <0.5 µA | Two register reads per minute |
| Flash writes | once a minute | every 10 minutes | Fewer power-ups |

The sensor bus transfers do not fall with batching, because each sample still
needs reading. Batching mainly removes wake overhead. Halving the ODR is the
bigger saving on the sensor side.

Measure with a power profiler on a real PineTime (for example a Nordic PPK2),
logging average current for each variant over at least one hour of typical
dog activity. Confirm counts agree between 25 Hz and 12.5 Hz, and between
normal and low-power mode, by logging both for one walk.

## 2. Quantify: per-minute metrics

Each minute record has:

- **counts**: the sum over the minute of |‖a‖ − 1 g|, in units of 1/1000 g per
  sample (saturating at 65535). This is a mean amplitude deviation (MAD) of the
  vector magnitude, scaled by the number of samples. It removes gravity and
  ignores direction, so the collar's orientation does not matter.
- **class**: rest, light, walk or run, from counts and cadence thresholds
  (see `pd_classify`). The thresholds are guesses and have not been calibrated.
- **cadence**: zero-crossing rate of the high-passed magnitude, in 0.1 Hz.

Established alternatives to consider when we store raw per-minute MAD or
ENMO (Euclidean norm minus one g, clipped at zero, van Hees et al. 2013) in
the future. Both are used in human and animal accelerometry. I have not
checked dog-specific validation studies in this session, so the choice of
metric and the threshold values are open items.

Calibrating the classes needs labelled data: a video of the dog for 30 to 60
minutes across rest, sniffing, walking and running, matched to minute records.
Then we can measure a confusion matrix and move the thresholds. The config
characteristic lets us do that without reflashing.

## 3. Learn: the rolling baseline

The aim is a baseline that gets more accurate as data arrives, is robust to
odd days, and gives a usable answer from the first week.

### How a day is measured

For each day, the integration takes the minutes that were recorded (active and
sedentary minutes, so watch-off time is excluded) and scales them to a full
day:

    full_day_counts = motion_counts × 1440 / worn_minutes

This keeps a partly worn day comparable with a fully worn one. Days with fewer
than 6 hours of wear are skipped.

### How the expectation is calculated

Working on the log scale, which suits motion data (it is skewed and spans
orders of magnitude):

1. **Age weighting.** Each day has weight 0.5^(age / 14 days), so the last
   two weeks dominate and older days fade. The window is 60 days.
2. **Robust centre.** The centre is a weighted median, not a mean. One extreme
   day has no effect on it. The spread is the median absolute deviation,
   with a floor of 0.25 log units so a run of identical days does not make the
   status over-confident.
3. **Prior shrinkage.** The estimate is pulled toward a population guess of
   100 counts per minute. The prior is worth one day of data, so it fades
   quickly. The guess should be replaced with a value from real data.
4. **Weekday.** The same calculation runs on that weekday's history only,
   with a longer half-life (56 days) because weekly patterns need a longer
   memory. It is then shrunk toward the all-day estimate with a weight of two
   days. A consistent Sunday walk therefore shows up after about eight weeks.
5. **Missing days.** A missing day contributes nothing. Nothing else is
   assumed about it, so gaps only reduce the sample.

### What the sensors report

- `percent`: today's full-day estimate as a percent of the expectation.
  100 is typical. Percent is reported from the first valid day.
- `status`: `learning` until 7 valid days exist. Then `waiting` (less than
  60 minutes of wear today), `below` or `above` when more than one spread from
  the expectation, or `normal`.
- `confidence`: n_eff / (n_eff + 1), where n_eff is the sum of the day
  weights. It rises toward 1 as data accumulates.

### Tested behaviour

`tests/ha/test_activity.py` covers: learning until seven valid days; shrinkage
during warm-up; confidence growing with data; convergence on steady motion;
normal, below and above bands; partly worn days scaling to the same value; days
with too little wear being ignored; outlier days (very high and zero) not
moving the baseline; missing days; the 60-day window; the weekday effect; and
the waiting status.

A synthetic run (91 days, 15% missing days, random watch-off, Saturday walks
at 1.6× the usual level, and a two-day illness) gave a status of `normal`
from day 14 onward, and `percent` between 99 and 101 on the weekdays checked.
On Saturdays the percent read 136 to 149 because the weekday effect was only
partly learned after 91 days. Real data will show whether the weekday step is
worth its complexity.

## 4. Present: Home Assistant

Entities are in `custom_components/pinedog/sensor.py`. Sensors with a
`state_class` feed Home Assistant's long-term statistics from the time they
are first set. Backfilling statistics for days synced late is not implemented
yet. It needs a live Home Assistant to test, and it is the next step.

A sample dashboard is in `docs/dashboard.yaml`.

## Open items

- Measure current on hardware for each collection option (section 1).
- Move the firmware to FIFO-watermark reads and decide the ODR (12.5 Hz or
  25 Hz) from logged data.
- Calibrate class thresholds from labelled dog video (section 2).
- Replace the population prior with the dog's own data after a few weeks.
- Import backfilled statistics for late-synced days (section 4).
- Check dog-specific validation literature for metric and thresholds.
