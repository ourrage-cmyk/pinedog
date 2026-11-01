# Home Assistant entities for stock InfiniTime

Source data (InfiniTime `main`, read October 2026):

| Characteristic | UUID | Format | Notes |
|---|---|---|---|
| Step count | `00030100-78fc-48fe-8e23-433b3a1942d0` | uint32 LE, read + notify | Cumulative counter |
| Motion values | `00030200-78fc-48fe-8e23-433b3a1942d0` | int16 x, y, z LE, read + notify | Raw accelerometer, scale unverified |
| Battery level | `00002a19-0000-1000-8000-00805f9b34fb` | uint8 percent, read + notify | Standard Battery service |

Not exposed over BLE by stock InfiniTime: charging state, heart rate (off by design), per-minute history.

| Entity | Type | Unit | Device class | How it is calculated | Source |
|---|---|---|---|---|---|
| Steps today | sensor | steps | none (total) | Sum of step deltas since local midnight. A lower reading counts as a counter reset | Step count |
| Steps last hour | sensor | steps | none | Step count now minus the reading about 60 min ago, from stored polls. Resolution is one poll interval | Step count, history |
| Active intervals today | sensor | intervals | none | Count of 15-min poll intervals with at least 30 steps. Not minutes: polling cannot see minutes | Step count, history |
| Steps vs 7-day baseline | sensor | % | none | Today's steps divided by the median of the last 7 full days, times 100. Unknown until 3 days exist | Step count, history |
| Motion index | sensor | none | none | Standard deviation of the acceleration magnitude over a 5 s sample per poll. Relative only | Motion values |
| Battery | sensor | % | battery | Battery level as reported | Battery level |
| Connected | binary_sensor | none | connectivity | On if the last poll reached the watch | Connection result |
| Last seen | sensor | none | timestamp | Time of the last successful poll | Connection result |

Dropped, with reason:

- Charging: no standard characteristic. Would need an InfiniTime change.
- Heart rate: off by design.
- Minute-level active time: needs per-minute history on the watch, which stock InfiniTime does not keep for BLE.

Unverified on hardware: notification rate of the motion characteristic, whether the step counter resets on watch reboot, and whether a phone app blocks the connection.
