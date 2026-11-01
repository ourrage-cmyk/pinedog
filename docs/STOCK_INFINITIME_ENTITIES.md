# Pinedog entities on stock InfiniTime

Goal: per dog, active time, sedentary time, a daily activity score, and whether today is more or less than that dog's usual. The long-term usual keeps improving for as long as the dog is tracked.

Source data (InfiniTime 1.14.1, confirmed on a real watch):

| Characteristic | UUID | Format | Use |
|---|---|---|---|
| Motion values | `00030002-78fc-48fe-8e23-433b3a1942d0` | 6 bytes, int16 x, y, z LE, read + notify, about 10 Hz | Activity index per poll, from about 600 samples in 60 s |
| Battery level | `00002a19-0000-1000-8000-00805f9b34fb` | uint8 percent, read | Battery |

## Entities

| Entity | Type | Unit | Device class | How it is calculated |
|---|---|---|---|---|
| Active time today | sensor | min | none (total) | Poll intervals whose motion index is at or above the dog's active threshold |
| Sedentary time today | sensor | min | none (total) | Poll intervals below the threshold. Gaps over 10 min are not counted |
| Activity score today | sensor | none | none (total) | Sum of motion index × seconds over the day |
| Activity vs 14-day usual | sensor | % | none | Short-term: today against the 14-day baseline (`compute_baseline`) |
| Compared to usual | sensor | none | none | Status from the 14-day baseline: `learning`, `below`, `normal` or `above` |
| Activity vs long-term usual | sensor | % | none | Today so far against the long-term usual at the same hours of the week. Shows after 7 learned days |
| Long-term days learned | sensor | days | none (diagnostic) | Days with at least six worn hours, counted since the dog was first tracked. Never resets |
| Battery | sensor | % | battery | Battery level as reported |
| Last sync | sensor | timestamp | timestamp (diagnostic) | Time of the last successful poll |
| In range | binary_sensor | none | connectivity | Stock firmware only. On if the last poll reached the collar |
| Charge soon | binary_sensor | none | battery | On at or below 20 % battery |

Custom firmware exposes the same daily entities from its record sync, plus charging, walking time, wear time and unsynced records. Stock firmware cannot report charging or walking.

## Dropped

- Steps: a human pedometer is not reliable on a dog. Steps are not read.
- Charging: not exposed by stock InfiniTime over BLE.
- Heart rate: off by design.

## Unverified on hardware

- Whether motion notifications keep working while a phone is also connected.
- The absolute scale of the motion index.
- The 30% threshold, the 115% and 85% bands, and the 50 starting threshold.
