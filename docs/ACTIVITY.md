# Activity pipeline: collect, quantify, learn, present

This explains why the activity numbers are computed the way they are. The
firmware is in `firmware/core/minute_summary.c`, the Home Assistant logic in
`custom_components/pinedog/activity.py`, and the tests in `tests/ha`.

Status: the Home Assistant part is implemented and tested on synthetic data.
The firmware collection changes below are recommendations. They have not been
built or measured on a PineTime, so the battery numbers are estimates.

## 1. Collect: BMA421 sampling

### What the current firmware does

`on_data_ready` runs once per sample, so the CPU wakes 25 times a second to read
the sensor and update the summary. The design doc assumes the CPU wakes about
once a second, draining the FIFO. The code does not do that yet. This is the
largest battery problem in the current firmware, and it is already listed as a
known gap in the PR.

### Recommended strategy

1. **Sample at 12.5 Hz instead of 25 Hz.** Dog gait (walk, trot, gallop) sits
   around 1 to 4 Hz, and the vector-magnitude signal used for counts has
   harmonics that stay mostly below 6 Hz. Half the samples per minute gives
   nearly the same counts. This has to be checked on real logs (see below)
   before it is adopted, and the BMA421 ODR options should be confirmed in its
   datasheet.
2. **Use the FIFO with a watermark.** Read the FIFO when it reaches a
   watermark, so the CPU wakes every few seconds instead of every sample. At
   12.5 Hz and 6 bytes per sample, a 1 KB FIFO (size to confirm in the
   datasheet) fills in about 13 s, so the wake interval is limited to roughly
   10 s. A full minute cannot be batched in the FIFO, so the per-minute
   summary has to run across FIFO reads.
3. **Keep a continuous sample stream, not duty cycling, for now.** Duty
   cycling (for example 10 s on, 20 s off) would save more current but biases
   the counts, because dog motion is bursty and the off-periods can miss
   bouts. We should quantify that bias before adopting it.
4. **Later option: any-motion interrupt as a gate.** While the sensor is in a
   low-power wait state, an any-motion interrupt could wake the CPU. Minutes
   with no interrupt would be recorded as rest with near-zero counts. This
   saves the most current when the dog is lying still, but it needs the bias
   measured first.

### Battery estimate (to measure)

| Change | Expected effect |
|---|---|
| Per-sample interrupt to FIFO watermark (about 25 wakes/s to about 0.1/s) | Removes most of the CPU wake cost. Probably a few µA. |
| 25 Hz to 12.5 Hz | Halves sensor conversions and FIFO bytes. Sensor current depends on the low-power mode, so the gain is uncertain. |
| Any-motion gating | Largest saving for a dog that rests most of the time. Not yet quantified. |

Measure with a power profiler on a real PineTime (for example a Nordic PPK2),
logging the average current for each firmware variant over at least one hour
of typical dog activity. Confirm counts agree between 25 Hz and 12.5 Hz by
logging both for one walk.

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
