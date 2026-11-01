# Home Assistant entities for a dog collar on stock InfiniTime

Goal: per dog, active time, sedentary time, a daily activity score, and whether the day was more or less than that dog's usual. The comparison improves as data builds up.

## What the watch can and cannot give

- The watch sends only what is asked for over BLE. It keeps no per-minute history for BLE.
- Home Assistant sees the watch only while it is connected. Each poll samples motion for 60 s. That sample stands for the time since the previous poll, capped at 10 min. Longer gaps count as unknown, not sedentary.
- Accuracy therefore depends on how often Home Assistant connects. The default is every 5 minutes. Between polls the dog's time is unknown.
- Off-body time is not detected. A watch taken off counts as sedentary until the next gap.

Source data (InfiniTime `main`, read October 2026):

| Characteristic | UUID | Format | Use |
|---|---|---|---|
| Motion values | `00030200-78fc-48fe-8e23-433b3a1942d0` | int16 x, y, z LE, read + notify | Activity index per poll |
| Battery level | `00002a19-0000-1000-8000-00805f9b34fb` | uint8 percent, read | Battery |

## Headline entities

| Entity | Type | Unit | Device class | How it is calculated |
|---|---|---|---|---|
| Active time today | sensor | min | none (total) | Sum of poll intervals whose motion index is at or above the dog's active threshold |
| Sedentary time today | sensor | min | none (total) | Sum of poll intervals below the threshold. Gaps over 10 min are excluded |
| Activity score today | sensor | none | none (total) | Sum of motion index × seconds across the day. A single number for how much the dog moved |
| Activity vs usual | sensor | % | none | Today's score so far as a percent of the median score at the same hour over the past 14 days |
| Compared to usual | sensor | none | none | `more` above 115 %, `less` below 85 %, otherwise `typical`. `learning` until 3 days exist |
| Days learned | sensor | days | none | Number of past days (up to 14) that have data for the comparison. Confidence grows with this |
| Battery | sensor | % | battery | Battery level as reported |
| Connected | binary_sensor | none | connectivity | On if the last poll reached the watch |
| Last seen | sensor | none | timestamp | Time of the last successful poll |

## How the dog's own thresholds are learned

- Active vs sedentary uses the dog's own history, not fixed human cut-offs. The threshold is the 30th percentile of the dog's motion index over the last 14 days, so the quietest 30 % of its history counts as sedentary.
- Until 30 intervals exist, a fixed placeholder of 50 is used. The placeholder is not tuned on real dog data.
- The comparison uses the same hour of day, because a dog's day is not flat. Hour-of-day history is what makes it "usual" for this dog at this time.

## Dropped

- Steps: a human pedometer is not reliable on a dog. Steps are not read.
- Charging: not exposed by stock InfiniTime over BLE.
- Heart rate: off by design.

## Unverified on hardware

- The motion characteristic's notification and read behaviour, and its sample rate.
- The absolute scale of the motion index. It is only compared against the dog's own history.
- Whether a connection succeeds while a phone is also connected.
- Battery use at the default 5-minute poll with a 60 s sample.
- The 30 % threshold, the 115 % and 85 % bands, and the 50 placeholder. These need real data to tune.
