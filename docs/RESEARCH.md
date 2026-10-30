# Sync research: portable loggers that sync later

How wearables and open-source projects handle the problems a PineTime collar
logger will hit: store now, sync later, never lose or double-count data.

Sources were read in October 2026. Where a claim could not be checked, it is
marked **unverified**. Vendor statements are quoted as the vendor's support
text, not as independent measurements.

## What the sources say

| Source | What it tells us |
|---|---|
| [Gadgetbridge sync docs](https://gadgetbridge.org/basics/features/sync/) | Activity data is fetched only when asked, or automatically on screen unlock with a minimum interval. Another app that syncs the device can remove the data. The page does not describe duplicate handling, acks, or time sync. |
| [Fitbit community thread, official reply](https://community.fitbit.com/t5/Product-Feedback/Allow-Offline-syncing-Store-data-locally/idc-p/2253508/highlight/true) | Fitbit has no offline store-and-forward. The moderator reply says there are no plans to add it. Its sync is phone-online, so it is not a model for us. |
| [Oura support: sync and storage](https://support.ouraring.com/hc/en-us/articles/360025428394) | Without a sync, Ring 5 holds about 3 days and Ring 4 / Gen3 about 7 days. Oura recommends a daily sync. Turning airplane mode off, which happens on recharging, starts a sync. The article does not say what happens when storage is full. |
| [WHOOP community thread](https://community.whoop.com/t/how-often-does-whoop-wearable-makes-connection-to-the-phone-to-synch-data/1987) | The strap keeps data when the phone is out of range, up to 14 days by one reply that reads as official. Syncs happen within about 30 ft of the phone. Retry and backoff behaviour was not answered. |
| [Garmin vivoactive 3 manual](https://www8.garmin.com/manuals/webhelp/vivoactive3/EN-US/GUID-EF643552-007C-4BDB-9EAF-B872E2FCCE84.html) | The device keeps up to 14 days of tracking data. "When the device memory is full, your oldest data is overwritten." |
| [Fitrockr: wearable sync methods](https://www.fitrockr.com/help-center/wearable-sync-methods-and-frequencies/) (third party) | Garmin's background sync timing is decided by the device from events. Wi-Fi background sync is enforced every 60 minutes. Most wearables record on-device and sync later. |
| [Zephyr NVS documentation](https://docs.zephyrproject.org/latest/services/storage/nvs/nvs.html) | Records are appended to sectors with CRC-protected metadata. Data is written before its metadata, and entries with missing or bad metadata are ignored at init. Data is copied before a sector erase. Lifetime is estimated from erase endurance and write rate. |
| [Silicon Labs summary of Apple guidance](https://docs.silabs.com/bluetooth/8.3.0/mobile-apps-suitable-connection-parameters) | Apple's Accessory Design Guidelines (section 49.6) give a minimum connection interval of 15 ms. The other values were not in the page. **Unverified** beyond that. Read the guideline directly before tuning. |
| Fi and FitBark collars | No usable source found about how they store data offline. **Unverified.** |

## Problems, what others do, and what we do

### 1. Store and forward, delete after ack

- **Others:** Garmin overwrites the oldest data when full. Oura holds 3 to 7 days and WHOOP 14. The data is removed only after the app has it.
- **Us:** Ring log of 8-byte records. Records are removed only on an explicit ack by minute.
- **Problem found:** the watch streamed only records after the requested minute. Records that the phone had already stored, and unsynced records from before the clock was set, were never sent, so never acked, so they stayed in the ring. A lost ack could leave them there indefinitely.
- **Fix in this PR:** the watch streams every pending record. Home Assistant drops what is at or below its cursor. Unsynced records are persisted-and-dropped but still acked.
- **Also found:** the Home Assistant side acked the watch before saving its own totals. A crash in between lost records permanently. The fix is to persist first, then ack.

### 2. Resumable and idempotent sync

- **Others:** Gadgetbridge does not document its duplicate handling. The behaviour we can rely on is what the sources imply: data is kept until the phone is sure it has it.
- **Us:** the phone keeps a cursor (last stored minute). Each transfer is a full resend of pending records, and the phone drops anything at or below the cursor.
- **Recommendation (later):** if records ever need to be unique beyond the minute, add a 16-bit sequence number. Minutes are unique as long as the clock is monotonic, and we only guarantee that once the clock is set.

### 3. Power loss and checkpoints

- **Others:** Zephyr NVS writes data before metadata, ignores entries with bad CRCs at init, and copies data before erasing. These are the rules to copy.
- **Us, before:** the head and count lived in one sector. Erasing it for each checkpoint left a window where the only checkpoint was gone. On boot the code then walked forward from the checkpoint and counted anything programmed as new. After the ring wrapped, that walked into stale records from the last lap, so the watch would resend old data.
- **Us, now:** a two-sector journal of 16-byte CRC-protected checkpoints (`firmware/core/journal.c`). A torn entry fails its CRC and is ignored. The newest valid entry wins. There is no walk-forward. The checkpoint is written after every append and every ack.
- **Also fixed:** a reboot in the middle of a sector erase could resume with a tail that pointed at erased flash. The tail is now moved and checkpointed before the erase.
- **Tests:** `firmware/test/test_core.c` covers torn entries, wrap across journal sectors, a ring wrapping twice with reboot, and a reboot during erase. All run on the host.

### 4. Flash wear and log rotation

- **Others:** NVS estimates lifetime as sector count × sector size × erase endurance divided by writes per minute × record size, and recommends more sectors when lifetime is short.
- **Us:** the journal erases one of its two sectors about every 8.5 hours (256 checkpoints per sector, one per minute). The ring erases one 4 KB sector per 512 records, also about every 8.5 hours at one record per minute. With a 100k-cycle endurance (**assumed, datasheet not checked**), both last decades.
- **Recommendation:** check the XT25F32B endurance figure before the build is final.

### 5. Clock and drift

- **Others:** the sources do not describe their clock handling. The phone or app sets the time at sync, which is what we do too.
- **Us:** Home Assistant writes Unix time at every sync. Records made before the first sync get uptime minutes and are dropped on the phone side.
- **Problem:** data from before the first sync of a boot is lost, and drift between syncs is not measured.
- **Recommendation:** store a time anchor (boot count plus last known time) in the journal, so data after a reboot can be placed roughly and not dropped. Check the board's low-frequency clock accuracy (**unverified**: PineTime is believed to use a 32.768 kHz crystal).

### 6. Timestamps after power loss

- **Us:** the minute after a reboot comes from uptime, so it is only correct once the clock is set. Records made before a sync cannot be placed in time.
- **Recommendation:** same as 5, a boot counter and anchor. Until then the data is dropped, which is the current behaviour.

### 7. Low-power advertising and connection parameters

- **Others:** WHOOP says out-of-range attempts do not drain the battery, but gives no detail (unverified). Gadgetbridge throttles auto-fetch by a minimum interval. Apple's guideline sets a 15 ms minimum connection interval.
- **Us:** advertising every 2 s, a connection only when the phone sees the advert, and a connection attempt gated by a schedule: 30 minutes after success, 5 minutes after failure. This is in `custom_components/pinedog/schedule.py` and is tested.
- **Not done:** the advert does not yet carry the pending count and battery, which the design already describes. Without it the phone connects whenever it sees the watch and the schedule allows. Adding it would cut connections further.
- **Recommendation:** put pending count and battery in manufacturer data (update it with `bt_le_adv_update_data`). Request a connection interval near the Apple minimum only during a sync, and let the central choose otherwise.

### 8. Bonding, reconnect and security

- **Others:** the sources say little about how wearables authenticate sync. Data ownership sits with the cloud account.
- **Us:** Time, Request and Ack are written without encryption or pairing. Anyone in range can set the clock or ack away records.
- **Recommendation:** LE Secure Connections bonding, with the write characteristics requiring encryption (`BT_GATT_PERM_WRITE_ENCRYPT`) and bond storage (`CONFIG_BT_SETTINGS`). Test the Home Assistant pairing flow first, since bleak and BlueZ handle pairing differently per host.
- **Not done in this PR:** no hardware, and pairing changes the reconnect flow.

### 9. Battery reporting and low-battery alerts

- **Us:** the Status characteristic has a battery byte, but it is always 0xFF because the ADC is not wired.
- **Recommendation:** read the ADC at each sync and in the advert. Alert in Home Assistant below 20%. Remaining life can be estimated from the discharge curve after a week of real data.

### 10. Data compaction

- **Others:** Garmin and Oura keep summaries on the device. We do not need that: 11.5 KB per day is small against 4 MB, and Home Assistant keeps daily statistics.
- **Recommendation:** none now. Revisit only if the ring must hold more than a year.

### 11. Firmware update

- **Others:** Gadgetbridge's Huami support updates over the air. Our firmware replaces InfiniTime and has no bootloader.
- **Recommendation:** MCUboot with a signing key, so updates work over BLE. Until then, updates are SWD only (`docs/FIRMWARE.md`).

### 12. Failure recovery

- **Covered now:** the watch acks only after the phone has stored records. The phone acks only after persisting. A missing end marker, a timeout, or a dropped link means no ack. Every failure path leaves the data in place.
- **Not covered:** the watch has no watchdog yet. Another thread is building it.

## Changes in this PR

- `firmware/core/journal.c`, `journal.h`: checkpoint journal, replacing walk-forward recovery.
- `firmware/core/ring_log.c`, `ring_log.h`: tail is moved and checkpointed before an erase. `pd_log_peek_slot` is removed.
- `firmware/app/src/store.c`: uses the journal. The last two sectors are reserved for it.
- `firmware/app/src/ble_sync.c`: streams every pending record and documents why.
- `firmware/test/test_core.c`: journal and reboot tests.
- `custom_components/pinedog/transfer.py`: the sync sequence, with persist before ack. No Bluetooth or Home Assistant imports.
- `custom_components/pinedog/sync.py`: BLE adapter for the transfer.
- `custom_components/pinedog/coordinator.py`: persists and dedupes by cursor, and uses the retry schedule.
- `custom_components/pinedog/schedule.py`: connection attempt schedule.
- `tests/ha/test_transfer.py`: order of persist and ack, failure paths, unsynced records, schedule.
- `docs/DESIGN.md`: sync and checkpoint paragraphs updated.

## Next steps, in order

1. Advert with pending count and battery, so the phone connects only when there is data.
2. Battery ADC and a low-battery alert.
3. Bonding with encrypted writes.
4. Boot counter and time anchor, so pre-sync data is kept.
5. Check the flash endurance and the clock accuracy against datasheets.
6. Measure current on hardware, then adjust the advert interval and connection parameters.
