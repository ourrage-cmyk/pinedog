#pragma once

/*
 * Pinedog store-and-sync service for InfiniTime (protocol v2, see
 * docs/SYNC_PROTOCOL.md).
 *
 * The motion tick feeds one accelerometer sample per 100 ms into a per-minute
 * summary. Each closed minute becomes an 8-byte record in a LittleFS-backed
 * store, which keeps it until Home Assistant acknowledges it. Home Assistant
 * connects, reads Status, asks for a transfer, stores what it receives, and
 * then acknowledges the count. Only that acknowledgement removes records.
 *
 * Everything that touches the filesystem or the summary runs in the system
 * task (Tick and OnMotion). The GATT callbacks only set atomics.
 */

#define min // workaround: nimble's min/max macros conflict with libstdc++
#define max
#include <host/ble_gap.h>
#undef max
#undef min

#include <atomic>
#include <cstdint>

#include "pd_core.h"
#include "pd_store.h"

namespace Pinetime {
  namespace Controllers {
    class FS;
    class DateTime;
    class Battery;
  }

  namespace Pinedog {

    // 5d0f0000-7e0d-4a8b-9d2a-0a1e0c0d0000 (same base as firmware/app, so Home Assistant needs no change)
    inline constexpr ble_uuid128_t kServiceUuid {.u = {.type = BLE_UUID_TYPE_128},
                                                 .value = {0x00, 0x00, 0x0d, 0x0c, 0x1e, 0x0a, 0x2a, 0x9d,
                                                           0x8b, 0x4a, 0x0d, 0x7e, 0x00, 0x00, 0x0f, 0x5d}};

    class PinedogService {
    public:
      PinedogService(Controllers::FS& fs, Controllers::DateTime& dateTime, Controllers::Battery& battery);
      PinedogService(const PinedogService&) = delete;
      PinedogService& operator=(const PinedogService&) = delete;

      /* Registers the GATT service. Call after the NimBLE controller is initialised. */
      void Init();
      /* Opens the record store. Call after the filesystem is mounted. */
      void Start();

      /* Called from the 100 ms motion tick with the accelerometer sample (1024 per g). */
      void OnMotion(int16_t x, int16_t y, int16_t z);
      /* Called from the 100 ms motion tick: flushes, applies Time/Ack, sends a stream. */
      void Tick();
      /* True when this tick may write or read flash: a batch flush, a stream, or a time/ack/request. */
      bool FlashWorkDue() const;

      /* GATT entry point, used by the characteristic callbacks. */
      int OnAccess(uint16_t connHandle, uint16_t attrHandle, struct ble_gatt_access_ctxt* ctxt);

    private:
      enum class Stream : uint8_t { Idle, Streaming, Done };

      void CloseWindow(bool synced);
      uint32_t CurrentMinute(bool& synced) const;
      void FlushBatch();
      uint8_t BootId() const;
      void StartStream(uint16_t connHandle);
      void PumpStream();
      void SaveName();
      void LoadName();
      void OpenStore();

      Controllers::FS& fs;
      Controllers::DateTime& dateTime;
      Controllers::Battery& battery;

      pd_store store {};
      bool storeReady = false;
      bool storeOpenTried = false;
      pd_config config {50, 300, 1200, 15, 30};
      pd_summary summary {};
      bool windowOpen = false;
      bool windowSynced = false;
      pd_record batch[16] {}; // kBatchRecords flushes; the rest is headroom while the flash refuses writes
      uint8_t batchCount = 0;

      // Self-confirm and remote validate. The gate counts ticks between checks.
      bool ackedThisBoot = false;
      uint32_t gateTicks = 0;
      std::atomic_bool validatePending {false};
      // Dog name: written over BLE into nameIncoming, saved to LittleFS by the system task.
      std::atomic_bool namePending {false};
      char nameIncoming[16] {};
      std::atomic<uint8_t> nameIncomingLen {0};
      char nameSaved[16] {'P', 'i', 'n', 'e', 'd', 'o', 'g'};
      uint8_t nameSavedLen = 7;

      // Set by GATT callbacks (NimBLE host context), read in Tick().
      std::atomic_bool timePending {false};
      std::atomic<uint32_t> timeValue {0};
      std::atomic_bool requestPending {false};
      std::atomic<uint16_t> requestConn {0};
      std::atomic_bool ackPending {false};
      std::atomic<uint32_t> ackValue {0};
      std::atomic<uint16_t> ackConn {0};

      // Published for Status reads.
      std::atomic<uint32_t> statusPending {0};
      std::atomic<uint32_t> statusNewest {0};
      std::atomic<uint8_t> statusFlags {0};
      std::atomic<uint8_t> statusBattery {0xFF};

      // Stream state, owned by the system task.
      Stream stream = Stream::Idle;
      uint16_t streamConn = 0;
      uint32_t streamStart = 0;
      uint32_t streamCount = 0;
      uint32_t streamNext = 0;
      uint32_t stalledTicks = 0;
      uint32_t newestMinute = 0;

      uint16_t timeHandle = 0;
      uint16_t statusHandle = 0;
      uint16_t requestHandle = 0;
      uint16_t recordsHandle = 0;
      uint16_t ackHandle = 0;
      uint16_t validateHandle = 0;
      uint16_t nameHandle = 0;
      struct ble_gatt_chr_def characteristics[8];
      struct ble_gatt_svc_def services[2];
    };
  }
}
