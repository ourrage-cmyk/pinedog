#include "components/pinedog/PinedogService.h"
#include "components/pinedog/PinedogName.h"

#include <chrono>
#include <cstring>

#include <host/ble_gatt.h>
#include <host/ble_hs_mbuf.h>
#include <nrf_log.h>
#include <os/os_mbuf.h>
#include <nrf.h>

#include "components/battery/BatteryController.h"
#include "components/datetime/DateTimeController.h"
#include "components/fs/FS.h"
#include "components/firmwarevalidator/FirmwareValidator.h"

using namespace Pinetime::Pinedog;

namespace Pinetime {
  namespace Pinedog {
    namespace {
      // Copy of the saved dog name for other screens. Only the system task writes it.
      char gDogName[17] = "Pinedog";
    }
    const char* DogName() {
      return gDogName;
    }
    uint32_t LastBootStep() {
      return NRF_POWER->GPREGRET; // survives a watchdog reset, so it shows where the last boot stopped
    }
  }
}

namespace {
  constexpr uint8_t kProtocolVersion = 2;
  constexpr uint8_t kEndMarker = 0xEE;
  constexpr uint32_t kBatchRecords = 5;          // flash write every 5 minutes: fewer erases
  constexpr uint32_t kStallTicks = 300;          // 30 s without progress: give up the stream
  constexpr uint32_t kRecordsPerTick = 16;       // 8 notifications of 2 records per 100 ms tick
  constexpr uint32_t kMinValidUnix = 1767225600; // 2026-01-01: earlier means the clock was never set
  constexpr uint32_t kMaxPendingRecords = 60 * PD_SEG_RECORDS; // about 60 days; older records go first
  constexpr uint8_t kFlagClockSynced = 1 << 0;
  constexpr uint8_t kFlagCharging = 1 << 1;
  constexpr uint8_t kFlagPowerPresent = 1 << 2;

  // Characteristic UUIDs: 5d0f000n-7e0d-4a8b-9d2a-0a1e0c0d0000, little-endian for NimBLE.
  constexpr ble_uuid128_t CharUuid(uint8_t n) {
    return ble_uuid128_t {.u = {.type = BLE_UUID_TYPE_128},
                          .value = {0x00, 0x00, 0x0d, 0x0c, 0x1e, 0x0a, 0x2a, 0x9d, 0x8b, 0x4a, 0x0d, 0x7e, n, 0x00, 0x0f, 0x5d}};
  }
  constexpr ble_uuid128_t timeUuid {CharUuid(0x01)};
  constexpr ble_uuid128_t statusUuid {CharUuid(0x02)};
  constexpr ble_uuid128_t requestUuid {CharUuid(0x03)};
  constexpr ble_uuid128_t recordsUuid {CharUuid(0x04)};
  constexpr ble_uuid128_t ackUuid {CharUuid(0x05)};
  constexpr ble_uuid128_t validateUuid {CharUuid(0x06)};
  constexpr ble_uuid128_t nameUuid {CharUuid(0x07)};

  // Filesystem adapter for the store. Each call opens, uses and closes its file.
  // LittleFS commits on close, which is the sync point the store relies on.
  int FsAppend(void* ctx, const char* path, const void* buf, uint32_t len) {
    auto* fs = static_cast<Pinetime::Controllers::FS*>(ctx);
    lfs_file_t file;
    if (fs->FileOpen(&file, path, LFS_O_WRONLY | LFS_O_CREAT | LFS_O_APPEND) < 0) {
      return -1;
    }
    int written = fs->FileWrite(&file, static_cast<const uint8_t*>(buf), len);
    int closed = fs->FileClose(&file);
    return (written == static_cast<int>(len) && closed >= 0) ? 0 : -1;
  }

  int FsRead(void* ctx, const char* path, uint32_t offset, void* buf, uint32_t len) {
    auto* fs = static_cast<Pinetime::Controllers::FS*>(ctx);
    lfs_file_t file;
    if (fs->FileOpen(&file, path, LFS_O_RDONLY) < 0) {
      return -1;
    }
    int n = -1;
    if (fs->FileSeek(&file, offset) >= 0) {
      n = fs->FileRead(&file, static_cast<uint8_t*>(buf), len);
    }
    fs->FileClose(&file);
    return n;
  }

  int FsSize(void* ctx, const char* path) {
    auto* fs = static_cast<Pinetime::Controllers::FS*>(ctx);
    lfs_info info {};
    if (fs->Stat(path, &info) < 0) {
      return -1;
    }
    return static_cast<int>(info.size);
  }

  int FsTruncate(void* ctx, const char* path, uint32_t len) {
    auto* fs = static_cast<Pinetime::Controllers::FS*>(ctx);
    lfs_file_t file;
    if (fs->FileOpen(&file, path, LFS_O_RDWR) < 0) {
      return -1;
    }
    int rc = fs->FileTruncate(&file, len);
    fs->FileClose(&file);
    return rc;
  }

  int FsReplace(void* ctx, const char* path, const void* buf, uint32_t len) {
    auto* fs = static_cast<Pinetime::Controllers::FS*>(ctx);
    const char* tmp = "/pinedog/tmp";
    lfs_file_t file;
    if (fs->FileOpen(&file, tmp, LFS_O_WRONLY | LFS_O_CREAT | LFS_O_TRUNC) < 0) {
      return -1;
    }
    int written = fs->FileWrite(&file, static_cast<const uint8_t*>(buf), len);
    int closed = fs->FileClose(&file);
    if (written != static_cast<int>(len) || closed < 0) {
      return -1;
    }
    return fs->Rename(tmp, path); // LittleFS rename replaces the target
  }

  int FsRemove(void* ctx, const char* path) {
    auto* fs = static_cast<Pinetime::Controllers::FS*>(ctx);
    return fs->FileDelete(path);
  }

  int OnAccessCallback(uint16_t connHandle, uint16_t attrHandle, struct ble_gatt_access_ctxt* ctxt, void* arg) {
    return static_cast<PinedogService*>(arg)->OnAccess(connHandle, attrHandle, ctxt);
  }
}

PinedogService::PinedogService(Controllers::FS& fs, Controllers::DateTime& dateTime, Controllers::Battery& battery)
  : fs {fs}, dateTime {dateTime}, battery {battery} {
}

void PinedogService::Init() {
  characteristics[0] = {.uuid = &timeUuid.u, .access_cb = OnAccessCallback, .arg = this,
                        .flags = BLE_GATT_CHR_F_WRITE, .val_handle = &timeHandle};
  characteristics[1] = {.uuid = &statusUuid.u, .access_cb = OnAccessCallback, .arg = this,
                        .flags = BLE_GATT_CHR_F_READ, .val_handle = &statusHandle};
  characteristics[2] = {.uuid = &requestUuid.u, .access_cb = OnAccessCallback, .arg = this,
                        .flags = BLE_GATT_CHR_F_WRITE, .val_handle = &requestHandle};
  characteristics[3] = {.uuid = &recordsUuid.u, .access_cb = OnAccessCallback, .arg = this,
                        .flags = BLE_GATT_CHR_F_NOTIFY, .val_handle = &recordsHandle};
  characteristics[4] = {.uuid = &ackUuid.u, .access_cb = OnAccessCallback, .arg = this,
                        .flags = BLE_GATT_CHR_F_WRITE, .val_handle = &ackHandle};
  characteristics[5] = {.uuid = &validateUuid.u, .access_cb = OnAccessCallback, .arg = this,
                        .flags = BLE_GATT_CHR_F_WRITE, .val_handle = &validateHandle};
  characteristics[6] = {.uuid = &nameUuid.u, .access_cb = OnAccessCallback, .arg = this,
                        .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_WRITE, .val_handle = &nameHandle};
  characteristics[7] = {0};

  services[0] = {.type = BLE_GATT_SVC_TYPE_PRIMARY, .uuid = &kServiceUuid.u, .characteristics = characteristics};
  services[1] = {0};

  int res = ble_gatts_count_cfg(services);
  if (res != 0) {
    NRF_LOG_ERROR("pinedog: gatt count failed %d", res);
    return;
  }
  res = ble_gatts_add_svcs(services);
  if (res != 0) {
    NRF_LOG_ERROR("pinedog: gatt add failed %d", res);
  }
}

void PinedogService::Start() {
  // Boot must not depend on the filesystem. The store opens from Tick, a few seconds
  // after boot, through OpenStore().
}

void PinedogService::OpenStore() {
  storeOpenTried = true;
  NRF_POWER->GPREGRET = 0x10; // before the filesystem work
  pd_fs ops {};
  ops.ctx = &fs;
  ops.append = FsAppend;
  ops.read = FsRead;
  ops.size = FsSize;
  ops.truncate = FsTruncate;
  ops.replace = FsReplace;
  ops.remove = FsRemove;

  fs.DirCreate("/pinedog"); // fails harmlessly if it exists
  storeReady = pd_store_open(&store, &ops) == 0;
  if (!storeReady) {
    NRF_LOG_ERROR("pinedog: store open failed");
    NRF_POWER->GPREGRET = 0x12;
    return;
  }
  statusPending.store(pd_store_pending(&store));
  LoadName();
  NRF_POWER->GPREGRET = 0x11; // store open and name loaded
}

void PinedogService::SaveName() {
  lfs_file_t file;
  if (fs.FileOpen(&file, "/pinedog/name", LFS_O_WRONLY | LFS_O_CREAT | LFS_O_TRUNC) < 0) {
    return;
  }
  const uint8_t len = nameIncomingLen.load();
  fs.FileWrite(&file, reinterpret_cast<const uint8_t*>(nameIncoming), len);
  fs.FileClose(&file);
  std::memcpy(nameSaved, nameIncoming, len);
  nameSavedLen = len;
  std::memcpy(gDogName, nameIncoming, len);
  gDogName[len] = '\0';
}

void PinedogService::LoadName() {
  // Keeps the default "Pinedog" when no name has been saved yet.
  lfs_file_t file;
  if (fs.FileOpen(&file, "/pinedog/name", LFS_O_RDONLY) < 0) {
    return;
  }
  const int n = fs.FileRead(&file, reinterpret_cast<uint8_t*>(nameSaved), sizeof(nameSaved));
  fs.FileClose(&file);
  if (n > 0) {
    nameSavedLen = static_cast<uint8_t>(n);
    std::memcpy(gDogName, nameSaved, nameSavedLen);
    gDogName[nameSavedLen] = '\0';
  }
}

uint8_t PinedogService::BootId() const {
  return static_cast<uint8_t>(store.boot & PD_BOOT_MASK);
}

void PinedogService::OnMotion(int16_t x, int16_t y, int16_t z) {
  if (!storeReady) {
    return;
  }
  const auto unixSeconds =
    std::chrono::duration_cast<std::chrono::seconds>(dateTime.CurrentDateTime().time_since_epoch()).count();
  const bool synced = unixSeconds >= static_cast<int64_t>(kMinValidUnix);
  const uint32_t minute = synced ? static_cast<uint32_t>(unixSeconds / 60)
                                 : static_cast<uint32_t>(dateTime.Uptime().count() / 60);

  if (!windowOpen) {
    pd_summary_reset(&summary, minute);
    windowOpen = true;
    windowSynced = synced;
  } else if (minute != summary.minute) {
    CloseWindow(windowSynced);
    pd_summary_reset(&summary, minute);
    windowSynced = synced;
  }
  pd_summary_push(&summary, x, y, z);

  const bool charging = battery.IsCharging();
  statusFlags.store(static_cast<uint8_t>((synced ? kFlagClockSynced : 0) | (charging ? kFlagCharging : 0) |
                                         (battery.IsPowerPresent() ? kFlagPowerPresent : 0)));
  statusBattery.store(battery.PercentRemaining());
}

void PinedogService::CloseWindow(bool synced) {
  pd_record rec {};
  pd_summary_flush(&summary, &config, summary.minute, &rec); // rec.minute is the closed minute
  uint8_t cls = rec.class_byte & PD_CLASS_MASK;
  if (battery.IsCharging()) {
    cls = PD_CLASS_NOT_WORN; // on the charger: Home Assistant leaves it out of totals
  }
  rec.class_byte = static_cast<uint8_t>(cls | (BootId() << PD_BOOT_SHIFT) | (synced ? 0 : PD_UNSYNCED_FLAG));
  rec.crc = pd_record_crc(&rec);

  batch[batchCount++] = rec;
  if (batchCount >= kBatchRecords) {
    FlushBatch();
  }
}

void PinedogService::FlushBatch() {
  if (batchCount == 0 || !storeReady) {
    return;
  }
  if (pd_store_append(&store, batch, batchCount) == 0) {
    newestMinute = batch[batchCount - 1].minute;
    statusNewest.store(newestMinute);
    batchCount = 0;
  }
  statusPending.store(pd_store_pending(&store));
}

void PinedogService::StartStream(uint16_t connHandle) {
  // Records still in RAM are written first, so the snapshot holds everything up to now.
  FlushBatch();
  streamConn = connHandle;
  streamStart = store.acked;
  streamCount = pd_store_pending(&store);
  streamNext = streamStart;
  stalledTicks = 0;
  stream = Stream::Streaming;
}

void PinedogService::PumpStream() {
  uint32_t sent = 0;
  while (streamNext < streamStart + streamCount && sent < kRecordsPerTick) {
    pd_record recs[2];
    const uint32_t want = (streamStart + streamCount - streamNext) < 2 ? (streamStart + streamCount - streamNext) : 2;
    const int got = pd_store_read(&store, streamNext, recs, want);
    if (got <= 0) {
      stream = Stream::Idle; // the store cannot give us the snapshot any more
      return;
    }
    // Records go out exactly as they are on flash. Home Assistant checks each CRC.
    auto* om = ble_hs_mbuf_from_flat(recs, static_cast<uint16_t>(got * sizeof(pd_record)));
    if (om == nullptr || ble_gattc_notify_custom(streamConn, recordsHandle, om) != 0) {
      break; // link buffers are busy: try again on the next tick
    }
    streamNext += static_cast<uint32_t>(got);
    sent += static_cast<uint32_t>(got);
    stalledTicks = 0;
  }

  if (streamNext >= streamStart + streamCount) {
    uint8_t end[5] = {kEndMarker, 0, 0, 0, 0};
    std::memcpy(end + 1, &streamCount, sizeof(streamCount));
    auto* om = ble_hs_mbuf_from_flat(end, sizeof(end));
    if (om != nullptr && ble_gattc_notify_custom(streamConn, recordsHandle, om) == 0) {
      stream = Stream::Done; // waiting for the Ack
    }
  } else if (sent == 0 && ++stalledTicks > kStallTicks) {
    stream = Stream::Idle;
  }
}

void PinedogService::Tick() {
  if (!storeReady) {
    if (!storeOpenTried && dateTime.Uptime().count() >= 10) {
      OpenStore();
    }
    return;
  }

  if (timePending.exchange(false)) {
    const auto t = std::chrono::seconds(timeValue.load());
    dateTime.SetCurrentTime(std::chrono::time_point<std::chrono::system_clock, std::chrono::nanoseconds>(t));
  }

  if (ackPending.exchange(false) && stream == Stream::Done && ackConn.load() == streamConn) {
    // Only the connection that asked for the stream may acknowledge it. The count is relative
    // to that snapshot. Repeats are harmless: once applied the stream is Idle, and the store
    // clamps to what was stored.
    if (pd_store_ack(&store, streamStart + ackValue.load()) == 0) {
      ackedThisBoot = true;
    }
    stream = Stream::Idle;
  }

  if (requestPending.exchange(false)) {
    // A new Request always restarts the snapshot, so a dead connection cannot wedge the log.
    StartStream(requestConn.load());
  }

  if (stream == Stream::Streaming) {
    PumpStream();
  } else if (pd_store_pending(&store) > kMaxPendingRecords) {
    // Only when no snapshot is being read: dropping segments under a stream would break it.
    (void)pd_store_ack(&store, store.written - kMaxPendingRecords);
  }

  if (namePending.exchange(false)) {
    SaveName();
  }
  if (validatePending.exchange(false)) {
    // The same routine as Settings > Firmware > Validate, triggered over BLE.
    Controllers::FirmwareValidator validator;
    validator.Validate();
  }
  // Self-confirm: after one full ack cycle this boot and an hour of uptime, confirm the
  // image. A bad image never gets here or never acks, so it still rolls back on reboot.
  if (ackedThisBoot && ++gateTicks >= 600) {
    gateTicks = 0;
    Controllers::FirmwareValidator validator;
    if (!validator.IsValidated() && dateTime.Uptime().count() >= 3600) {
      validator.Validate();
    }
  }

  if (batchCount >= kBatchRecords) {
    FlushBatch();
  }
  statusPending.store(pd_store_pending(&store));
}

int PinedogService::OnAccess(uint16_t connHandle, uint16_t attrHandle, struct ble_gatt_access_ctxt* ctxt) {
  if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR && attrHandle == statusHandle) {
    // Status, 16 bytes: version, flags, pending, newest minute, uptime, boot id, battery.
    uint8_t status[16] = {0};
    const uint32_t pending = statusPending.load();
    const uint32_t newest = statusNewest.load();
    const uint32_t uptime = static_cast<uint32_t>(dateTime.Uptime().count());
    status[0] = kProtocolVersion;
    status[1] = statusFlags.load();
    std::memcpy(status + 2, &pending, 4);
    std::memcpy(status + 6, &newest, 4);
    std::memcpy(status + 10, &uptime, 4);
    status[14] = BootId();
    status[15] = statusBattery.load();
    int res = os_mbuf_append(ctxt->om, status, sizeof(status));
    return (res == 0) ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
  }

  if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR && attrHandle == nameHandle) {
    int res = os_mbuf_append(ctxt->om, nameSaved, nameSavedLen);
    return (res == 0) ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
  }

  if (ctxt->op != BLE_GATT_ACCESS_OP_WRITE_CHR) {
    return BLE_ATT_ERR_UNLIKELY;
  }

  const uint16_t len = OS_MBUF_PKTLEN(ctxt->om);
  if (attrHandle == requestHandle) {
    // The payload is ignored: a Request always streams the whole pending log.
    requestConn.store(connHandle);
    requestPending.store(true);
    return 0;
  }

  if (attrHandle == validateHandle) {
    validatePending.store(true);
    return 0;
  }
  if (attrHandle == nameHandle) {
    // The name is held in nameIncoming until the system task saves it. A second write
    // that lands during the save can mix bytes; the next write fixes it.
    if (len == 0 || len > sizeof(nameIncoming)) {
      return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }
    os_mbuf_copydata(ctxt->om, 0, len, nameIncoming);
    nameIncomingLen.store(static_cast<uint8_t>(len));
    namePending.store(true);
    return 0;
  }

  if (attrHandle == timeHandle || attrHandle == ackHandle) {
    if (len < 4) {
      return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }
    uint32_t word = 0;
    os_mbuf_copydata(ctxt->om, 0, sizeof(word), &word); // little-endian on the wire
    if (attrHandle == timeHandle) {
      timeValue.store(word);
      timePending.store(true);
    } else {
      ackValue.store(word);
      ackConn.store(connHandle);
      ackPending.store(true);
    }
    return 0;
  }
  return BLE_ATT_ERR_UNLIKELY;
}
