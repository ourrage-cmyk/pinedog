/*
 * GATT service that Home Assistant uses to pull the activity log.
 *
 * Every characteristic requires an encrypted link, so the peer must be paired
 * and bonded first (see pairing.c). Sync flow: HA connects, writes Time, reads
 * Status, writes Request (its payload is ignored), receives Records
 * notifications, then gets a single 0xEE byte as the end marker. HA persists
 * what it received, and only then writes Ack with the number of records it
 * stored. Nothing is acked unless HA says so, so a dropped link leaves every
 * record in flash for the next sync.
 *
 * Request takes a snapshot of the pending count. The watch streams exactly
 * that many records, oldest first, even if more arrive during the transfer.
 * Ack is a count, not a minute: uptime minutes restart at zero after a reboot,
 * so a minute ack could release records that were never sent. Because the
 * ring only removes from its tail, the first N records are the ones HA stored.
 *
 * Every pending record is sent, not only those from the requested minute.
 * Records that HA already stored are still acked, so they leave the ring, and
 * HA drops them by its own cursor.
 */
#include <errno.h>
#include <string.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include "battery.h"
#include "ble_sync.h"
#include "clock.h"
#include "pairing.h"
#include "store.h"

LOG_MODULE_REGISTER(pd_ble, LOG_LEVEL_INF);

#define PD_PROTOCOL_VERSION 2
#define PD_END_MARKER 0xEE
#define PD_MAX_BATCH 16 /* records per notification, 128 bytes */

/* Status flags. */
#define PD_FLAG_CLOCK_SYNCED (1 << 0)
#define PD_FLAG_CHARGING (1 << 1)
#define PD_FLAG_POWER_PRESENT (1 << 2)
#define PD_FLAG_PAIRING_OPEN (1 << 3)

#define PD_UUID(n) BT_UUID_INIT_128(BT_UUID_128_ENCODE(0x5d0f0000 + (n), \
	0x7e0d, 0x4a8b, 0x9d2a, 0x0a1e0c0d0000))

static struct bt_uuid_128 svc_uuid = PD_UUID(0x0);
static struct bt_uuid_128 time_uuid = PD_UUID(0x1);
static struct bt_uuid_128 status_uuid = PD_UUID(0x2);
static struct bt_uuid_128 request_uuid = PD_UUID(0x3);
static struct bt_uuid_128 records_uuid = PD_UUID(0x4);
static struct bt_uuid_128 ack_uuid = PD_UUID(0x5);

/* Protocol v2 status, 16 bytes. Must match protocol.py in custom_components. */
struct pd_status {
	uint8_t version;
	uint8_t flags;
	uint32_t pending;
	uint32_t newest_minute;
	uint32_t uptime_s;
	uint8_t boot_id;
	uint8_t battery_pct; /* 0xFF unknown */
} __attribute__((packed));

static struct bt_conn *stream_conn;
static struct k_work stream_work;
static struct k_work_delayable window_end_work;
static int64_t window_until_ms;

/* Last acked transfer, in RAM only. Shown on the screen after a button press. */
static struct {
	bool valid;
	uint32_t records;
	uint32_t uptime_s;
} last;

static ssize_t read_status(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			   void *buf, uint16_t len, uint16_t offset)
{
	struct pd_status st = {
		.version = PD_PROTOCOL_VERSION,
		.newest_minute = clock_minute(),
		.uptime_s = (uint32_t)(k_uptime_get() / 1000),
		.boot_id = store_boot_id(),
		.battery_pct = battery_percent(),
	};

	if (clock_synced()) {
		st.flags |= PD_FLAG_CLOCK_SYNCED;
	}
	if (battery_charging()) {
		st.flags |= PD_FLAG_CHARGING;
	}
	if (battery_power_present()) {
		st.flags |= PD_FLAG_POWER_PRESENT;
	}
	if (pairing_window_open()) {
		st.flags |= PD_FLAG_PAIRING_OPEN;
	}

	store_lock();
	st.pending = store_pending();
	store_unlock();
	return bt_gatt_attr_read(conn, attr, buf, len, offset, &st, sizeof(st));
}

static ssize_t write_time(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			  const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	uint32_t unix_s;

	ARG_UNUSED(conn);
	ARG_UNUSED(attr);
	ARG_UNUSED(flags);
	if (offset != 0 || len != sizeof(unix_s)) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}
	memcpy(&unix_s, buf, sizeof(unix_s));
	clock_set_unix(unix_s);
	LOG_INF("clock set from peer: %u", unix_s);
	return len;
}

/* Ack is the number of records from the oldest the peer has persisted. */
static ssize_t write_ack(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			 const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	uint32_t count;

	ARG_UNUSED(conn);
	ARG_UNUSED(attr);
	ARG_UNUSED(flags);
	if (offset != 0 || len != sizeof(count)) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}
	memcpy(&count, buf, sizeof(count));
	store_lock();
	store_ack(count);
	store_unlock();
	last.valid = true;
	last.records = count;
	last.uptime_s = (uint32_t)(k_uptime_get() / 1000);
	return len;
}

static int notify_retry(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			const void *data, uint16_t len)
{
	int rc;

	do {
		rc = bt_gatt_notify(conn, attr, data, len);
		if (rc == -ENOMEM) {
			k_sleep(K_MSEC(10));
		}
	} while (rc == -ENOMEM);
	return rc;
}

static ssize_t write_request(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			     const void *buf, uint16_t len, uint16_t offset, uint8_t flags);

BT_GATT_SERVICE_DEFINE(pinedog_svc,
	BT_GATT_PRIMARY_SERVICE(&svc_uuid),
	BT_GATT_CHARACTERISTIC(&time_uuid.uuid, BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_WRITE_ENCRYPT, NULL, write_time, NULL),
	BT_GATT_CHARACTERISTIC(&status_uuid.uuid, BT_GATT_CHRC_READ,
			       BT_GATT_PERM_READ_ENCRYPT, read_status, NULL, NULL),
	BT_GATT_CHARACTERISTIC(&request_uuid.uuid, BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_WRITE_ENCRYPT, NULL, write_request, NULL),
	BT_GATT_CHARACTERISTIC(&records_uuid.uuid, BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_NONE, NULL, NULL, NULL),
	BT_GATT_CCC(NULL, BT_GATT_PERM_READ_ENCRYPT | BT_GATT_PERM_WRITE_ENCRYPT),
	BT_GATT_CHARACTERISTIC(&ack_uuid.uuid, BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_WRITE_ENCRYPT, NULL, write_ack, NULL),
);

/*
 * Streams a snapshot of the pending records, oldest first. The snapshot is the
 * count pending when the Request arrived, so records logged during the transfer
 * wait for the next sync. Every record is sent, including ones with a bad
 * checksum; Home Assistant validates and counts them. Runs in the work queue.
 */
static void stream_records(struct k_work *work)
{
	struct pd_record batch[PD_MAX_BATCH];
	const struct bt_gatt_attr *attr;
	struct bt_conn *conn = stream_conn;
	uint16_t payload = bt_gatt_get_mtu(conn) - 3;
	uint32_t batch_max = payload / sizeof(struct pd_record);
	uint32_t index = 0;
	uint32_t snapshot;
	bool ok = true;

	ARG_UNUSED(work);
	attr = bt_gatt_find_by_uuid(pinedog_svc.attrs, pinedog_svc.attr_count,
				    &records_uuid.uuid);
	if (batch_max > PD_MAX_BATCH) {
		batch_max = PD_MAX_BATCH;
	}

	/* Fixed snapshot: records appended during the transfer wait for the next one. */
	store_lock();
	snapshot = store_pending();
	store_unlock();

	while (ok && index < snapshot) {
		uint32_t want = snapshot - index;
		int n;

		if (want > batch_max) {
			want = batch_max;
		}
		store_lock();
		n = store_read(index, batch, want);
		store_unlock();
		if (n <= 0) {
			LOG_ERR("log read failed at %u, stream aborted", index);
			ok = false;
			break;
		}
		if (notify_retry(conn, attr, batch, n * sizeof(struct pd_record))) {
			LOG_WRN("notify failed, stream aborted; records stay in flash");
			ok = false;
			break;
		}
		index += n;
	}

	if (ok) {
		/* End marker: 0xEE then the count sent, so Home Assistant can check it. */
		uint8_t end[1 + sizeof(uint32_t)];

		end[0] = PD_END_MARKER;
		memcpy(&end[1], &index, sizeof(index));
		notify_retry(conn, attr, end, sizeof(end));
	}
	LOG_INF("stream %s: %u of %u records", ok ? "complete" : "failed", index,
		snapshot);
	bt_conn_unref(conn);
	stream_conn = NULL;
}

static ssize_t write_request(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			     const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	ARG_UNUSED(attr);
	ARG_UNUSED(flags);
	/* The payload is ignored: a Request always streams the whole pending log. */
	if (offset != 0 || len > 4) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}
	if (stream_conn) {
		LOG_WRN("request refused: a stream is already running");
		return BT_GATT_ERR(BT_ATT_ERR_UNLIKELY);
	}
	store_lock();
	store_unlock();
	stream_conn = bt_conn_ref(conn);
	k_work_submit(&stream_work);
	return len;
}

/*
 * Manufacturer data with company id 0xFFFF (reserved for testing) and one flag
 * byte. Bit 0 asks Home Assistant to sync now, even inside its normal retry
 * interval. Only sent during a sync window, opened by a button press.
 */
static uint8_t sync_request_mfg[] = { 0xFF, 0xFF, PD_ADV_FLAG_SYNC_REQUEST };

static const struct bt_data ad_idle[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
	BT_DATA(BT_DATA_UUID128_ALL, svc_uuid.val, sizeof(svc_uuid.val)),
};

static const struct bt_data ad_window[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
	BT_DATA(BT_DATA_UUID128_ALL, svc_uuid.val, sizeof(svc_uuid.val)),
	BT_DATA(BT_DATA_MANUFACTURER_DATA, sync_request_mfg, sizeof(sync_request_mfg)),
};

static bool window_active(void)
{
	return k_uptime_get() < window_until_ms;
}

static void advertise(void)
{
	/* Idle: 2 s interval keeps the average radio cost low. Window: 100 ms, so a host sees it quickly. */
	bool fast = window_active();
	int rc;

	bt_le_adv_stop();
	if (fast) {
		rc = bt_le_adv_start(BT_LE_ADV_PARAM(BT_LE_ADV_OPT_CONN, 160, 160, NULL),
				     ad_window, ARRAY_SIZE(ad_window), NULL, 0);
	} else {
		rc = bt_le_adv_start(BT_LE_ADV_PARAM(BT_LE_ADV_OPT_CONN, 3200, 3200, NULL),
				     ad_idle, ARRAY_SIZE(ad_idle), NULL, 0);
	}
	if (rc && rc != -EALREADY) {
		LOG_ERR("advertising failed: %d", rc);
	} else {
		LOG_DBG("advertising (%s)", fast ? "sync window" : "idle");
	}
}

static void window_end(struct k_work *work)
{
	ARG_UNUSED(work);
	LOG_INF("sync window closed");
	advertise();
}

void ble_sync_open_window(uint32_t seconds)
{
	window_until_ms = k_uptime_get() + (int64_t)seconds * 1000;
	k_work_reschedule(&window_end_work, K_SECONDS(seconds));
	advertise();
	LOG_INF("sync window open for %u s", seconds);
}

uint32_t ble_sync_window_left_s(void)
{
	int64_t left = window_until_ms - k_uptime_get();

	return left > 0 ? (uint32_t)((left + 999) / 1000) : 0;
}

bool ble_sync_last(struct pd_last_sync *out)
{
	out->valid = last.valid;
	out->records = last.records;
	out->age_s = last.valid ? (uint32_t)(k_uptime_get() / 1000) - last.uptime_s : 0;
	return last.valid;
}

static void connected(struct bt_conn *conn, uint8_t err)
{
	ARG_UNUSED(conn);
	if (err) {
		LOG_WRN("connection failed: %u", err);
	} else {
		LOG_INF("connected");
	}
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
	ARG_UNUSED(conn);
	LOG_INF("disconnected, reason 0x%02x", reason);
	advertise();
}

BT_CONN_CB_DEFINE(conn_cb) = {
	.connected = connected,
	.disconnected = disconnected,
};

int ble_sync_init(void)
{
	k_work_init(&stream_work, stream_records);
	k_work_init_delayable(&window_end_work, window_end);
	advertise();
	return 0;
}
