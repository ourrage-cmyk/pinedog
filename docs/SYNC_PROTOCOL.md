# Pinedog sync protocol (v2, InfiniTime build)

This is the protocol between the collar and Home Assistant. The InfiniTime port
keeps the same UUIDs, record format and Status layout as the Zephyr firmware
(`docs/FIRMWARE.md`), so the integration only needs to know the differences
listed in "Changes from the Zephyr build" below.

## Service

Base UUID `5d0f0000-7e0d-4a8b-9d2a-0a1e0c0d0000`. The service UUID is in the
scan response of the watch's advertising, next to the name `InfiniTime`.

| Characteristic | UUID | Access | Payload |
|---|---|---|---|
| Time | `5d0f0001-…` | write | u32 LE, unix seconds |
| Status | `5d0f0002-…` | read | 16 bytes, see below |
| Request | `5d0f0003-…` | write | payload ignored |
| Records | `5d0f0004-…` | notify | packed 8-byte records, and one end marker |
| Ack | `5d0f0005-…` | write | u32 LE, number of records stored |

### Status (16 bytes, little-endian)

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | version, `2` |
| 1 | 1 | flags: bit 0 clock set, bit 1 charging, bit 2 power present, bit 3 pairing (always 0) |
| 2 | 4 | pending: records on flash and not yet acknowledged |
| 6 | 4 | newest minute stored (0 if none) |
| 10 | 4 | uptime, seconds |
| 14 | 1 | boot id (mod 256) |
| 15 | 1 | battery percent (0xFF if unknown) |

## Records

Eight bytes each, the same layout as `pd_record` in `firmware/infinitime/pinedog/pd_core.h`.

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | minute: unix minutes when the clock is set, uptime minutes before |
| 4 | 2 | counts: activity, saturating |
| 6 | 1 | class byte: bits 0 to 2 class (0 rest, 1 light, 2 walk, 3 run, 4 not worn), bits 3 to 6 boot id, bit 7 unsynced (minute is uptime based) |
| 7 | 1 | CRC-8 (poly 0x07, init 0) over bytes 0 to 6 |

One record per minute, including quiet minutes. Minutes on the charger are
"not worn" (class 4).

Motion is sampled at 10 Hz from the 100 ms tick that InfiniTime already runs.
Counts are the sum of |magnitude − 1 g|, scaled to a full minute. The
thresholds are the same as the Zephyr build (`rest_max` 50, `walk_min` 300,
`run_min` 1200, cadence 1.5 and 3.0 Hz).

## Sync flow

1. Home Assistant sees the advertisement, connects, and reads Status. If
   `pending` is zero, it disconnects.
2. It writes Time (unix seconds) if the clock flag is off or the watch is more
   than a few seconds off.
3. It writes Request. The watch first writes its RAM batch to flash, then takes a
   snapshot of `pending` and streams exactly that many records. Each Records
   notification carries 1 or 2 records.
4. After the last record, the watch sends an end marker: byte `0xEE`, then the
   u32 LE count of records streamed. The end marker is always 5 bytes, so it
   cannot be mistaken for a record.
5. Home Assistant stores every record it received and checks its CRC. Then it
   writes Ack with the number of records it stored, counted from the start of
   the snapshot.
6. The watch removes those records from flash. It only does this after the end
   marker, and only once per snapshot.
7. Home Assistant disconnects.

### Why this is safe to retry

- Records leave the watch only on an Ack, and only after Home Assistant has
  the records. An Ack that never arrives means nothing is dropped.
- A repeated Ack, or an Ack that arrives after the snapshot was already
  applied, does nothing.
- If the connection drops mid-stream, the watch gives up after 30 s without
  progress. The next Request starts a new snapshot from the same point, so
  records are sent again. Home Assistant drops anything it already has, using
  its own minute cursor.
- A new Request always restarts the snapshot. A stale stream cannot block a
  new sync.
- Acks are counts, not minutes: uptime minutes restart after a reboot, so a
  minute-based ack would be ambiguous.

### Storage on the watch

Records are kept in LittleFS, under `/pinedog/`, in one file per day of records
(`s<n>`, 1440 records, 11.5 KB). A small `meta` file holds the ack cursor and
is replaced atomically. At boot the store finds the newest day, drops a
partial record left by a power cut, and removes files that an interrupted ack
left behind.

The store keeps up to 60 days. Past that, the oldest unacknowledged records
are dropped. The RAM batch holds up to 4 minutes, and is written to flash
every 5 minutes or on each Request. A power cut loses at most that batch.

## Changes from the Zephyr build (`firmware/app`)

- Advertising: the Pinedog UUID is in the scan response, not the advertisement,
  so the sync-window advertising (company id 0xFFFF) is not in this build.
  Home Assistant connects on its normal schedule.
- No pairing or encryption. Requiring an encrypted link would need bonding,
  and InfiniTime pairs with a passkey shown on the watch, which Home Assistant
  cannot enter, so it would block automatic sync. Instead, the watch only
  accepts an Ack from the same connection that sent the Request. A stray write
  from another device is ignored. This is not cryptographic: a device that can
  open the same connection can still ack. The Request is open, so a device in
  range can make the watch stream records, but cannot remove them.
- Ack is only accepted after the end marker, and only once per snapshot.
- Config (classifier thresholds over BLE) is not implemented, as in the
  Zephyr build.
- Storage is LittleFS files instead of a raw ring with a checkpoint journal,
  so the InfiniTime build relies on LittleFS for power-loss safety, and does
  not need its own flash layout.

## Wire details for the client

Use this section to write a client. Everything is little-endian.

| Step | Write or read | Bytes | Notes |
|---|---|---|---|
| Discover | scan | service `5d0f0000-…` in the scan response | name `InfiniTime` |
| Connect | GATT | ATT MTU as negotiated, default 23 | notifications carry 1 or 2 records (8 or 16 bytes) plus the 5-byte end marker |
| Read Status | read `…0002` | 16 | layout above |
| Time | write `…0001` | 4: u32 unix seconds | optional; only if flag bit 0 is clear or drift is large |
| Request | write `…0003` | any, ignored | starts a snapshot; restarts any earlier one |
| Records | notify `…0004` | n × 8, or 5 | end marker is `0xEE` then u32 count |
| Ack | write `…0005` | 4: u32 count | count of records stored from the snapshot start; send once, after the end marker |

Client rules:
- Store records before writing Ack. Check each record's CRC-8; keep the minute cursor to drop duplicates on resend.
- The end-marker count must equal the number of records received. If it does not, do not Ack.
- If the link drops before the end marker, reconnect and Request again. Do not Ack a partial snapshot.
- Ack only on the connection that sent Request. Other connections are ignored.
- Writes to Time, Request and Ack use write-with-response. Notifications are not acknowledged by the client.
- Timeouts: the watch gives up a stream after 30 s without a notification it could send.

## Pairing and bonding (not used yet)

Stock InfiniTime 1.14.1 does not configure a bond store. Bonds are not kept across a reboot, so a pairing made today would stop working on the next watch reboot. A persistent store is needed before pairing can be required. It is not in this change.

## Testing status

Host tests cover the store (append, reopen, ack, day boundaries, torn tail,
damaged cursor) and the summary and classifier: `make -C firmware/infinitime/test run`.
The BLE flow, flash wear and battery use have not been tested on a watch.
