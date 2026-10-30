/*
 * GATT service that Home Assistant uses to pull the activity log.
 *
 * Sync flow: HA connects, writes Time, reads Status, writes Request, receives
 * Records notifications, then gets a single 0xEE byte as the end marker. HA
 * writes Ack with the last minute it has stored and disconnects. Nothing is
 * acked unless HA says so, so a dropped link leaves every record in flash for
 * the next sync.
 *
 * The watch always streams every pending record, not only those from the
 * requested minute. Records that HA already stored are still acked, so they
 * leave the ring, and HA drops them by its own cursor. Filtering on the
 * watch would leave acked-but-unremoved records in the ring forever.
 */
#include <errno.h>
#include <string.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/kernel.h>

#include "ble_sync.h"
#include "clock.h"
#include "store.h"

#define PD_PROTOCOL_VERSION 1
#define PD_END_MARKER 0xEE
#define PD_MAX_BATCH 16 /* records per notification, 128 bytes */

#define PD_UUID(n) BT_UUID_INIT_128(BT_UUID_128_ENCODE(0x5d0f0000 + (n), \
	0x7e0d, 0x4a8b, 0x9d2a, 0x0a1e0c0d0000))

static struct bt_uuid_128 svc_uuid = PD_UUID(0x0);
static struct bt_uuid_128 time_uuid = PD_UUID(0x1);
static struct bt_uuid_128 status_uuid = PD_UUID(0x2);
static struct bt_uuid_128 request_uuid = PD_UUID(0x3);
static struct bt_uuid_128 records_uuid = PD_UUID(0x4);
static struct bt_uuid_128 ack_uuid = PD_UUID(0x5);

struct pd_status {
	uint8_t version;
	uint8_t synced;
	uint32_t pending;
	uint32_t newest_minute;
	uint8_t battery_pct; /* 0xFF until the ADC is wired up */
} __attribute__((packed));

static struct bt_conn *stream_conn;
static struct k_work stream_work;

static ssize_t read_status(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			   void *buf, uint16_t len, uint16_t offset)
{
	struct pd_status st = {
		.version = PD_PROTOCOL_VERSION,
		.synced = clock_synced(),
		.newest_minute = clock_minute(),
		.battery_pct = 0xFF,
	};

	store_lock();
	st.pending = store_pending();
	store_unlock();
	return bt_gatt_attr_read(conn, attr, buf, len, offset, &st, sizeof(st));
}

static ssize_t write_time(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			  const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	uint32_t unix_s;

	if (offset != 0 || len != sizeof(unix_s)) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}
	memcpy(&unix_s, buf, sizeof(unix_s));
	clock_set_unix(unix_s);
	return len;
}

static ssize_t write_ack(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			 const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	uint32_t minute;

	if (offset != 0 || len != sizeof(minute)) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}
	memcpy(&minute, buf, sizeof(minute));
	store_lock();
	store_ack(minute);
	store_unlock();
	return len;
}

/* Sends one notification, retrying while the stack is out of buffers. */
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
			     const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	/* The value is accepted for protocol compatibility and otherwise ignored. */
	if (offset != 0 || len != sizeof(uint32_t)) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}
	if (stream_conn) {
		return BT_GATT_ERR(BT_ATT_ERR_UNLIKELY);
	}
	stream_conn = bt_conn_ref(conn);
	k_work_submit(&stream_work);
	return len;
}

BT_GATT_SERVICE_DEFINE(pinedog_svc,
	BT_GATT_PRIMARY_SERVICE(&svc_uuid),
	BT_GATT_CHARACTERISTIC(&time_uuid.uuid, BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_WRITE, NULL, write_time, NULL),
	BT_GATT_CHARACTERISTIC(&status_uuid.uuid, BT_GATT_CHRC_READ,
			       BT_GATT_PERM_READ, read_status, NULL, NULL),
	BT_GATT_CHARACTERISTIC(&request_uuid.uuid, BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_WRITE, NULL, write_request, NULL),
	BT_GATT_CHARACTERISTIC(&records_uuid.uuid, BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_NONE, NULL, NULL, NULL),
	BT_GATT_CCC(NULL, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	BT_GATT_CHARACTERISTIC(&ack_uuid.uuid, BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_WRITE, NULL, write_ack, NULL),
);

/* Runs in the system work queue. */
static void stream_records(struct k_work *work)
{
	struct pd_record batch[PD_MAX_BATCH];
	const struct bt_gatt_attr *attr;
	struct bt_conn *conn = stream_conn;
	uint16_t payload = bt_gatt_get_mtu(conn) - 3;
	uint32_t batch_max = payload / sizeof(struct pd_record);
	uint32_t index = 0;
	bool ok = true;

	ARG_UNUSED(work);
	attr = bt_gatt_find_by_uuid(pinedog_svc.attrs, pinedog_svc.attr_count,
				    &records_uuid.uuid);
	if (batch_max > PD_MAX_BATCH) {
		batch_max = PD_MAX_BATCH;
	}

	while (ok) {
		int n;

		store_lock();
		n = store_read(index, batch, batch_max);
		store_unlock();
		if (n < 0) {
			ok = false;
			break;
		}
		if (n == 0) {
			break;
		}
		index += n;

		if (notify_retry(conn, attr, batch, n * sizeof(struct pd_record))) {
			ok = false;
		}
	}

	if (ok) {
		uint8_t end = PD_END_MARKER;

		notify_retry(conn, attr, &end, sizeof(end));
	}
	bt_conn_unref(conn);
	stream_conn = NULL;
}

static const struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
	BT_DATA(BT_DATA_UUID128_ALL, svc_uuid.val, sizeof(svc_uuid.val)),
};

static void advertise(void)
{
	/* 2 s interval keeps the average radio cost low. */
	int rc = bt_le_adv_start(BT_LE_ADV_PARAM(BT_LE_ADV_OPT_CONN,
						 3200, 3200, NULL),
				 ad, ARRAY_SIZE(ad), NULL, 0);

	if (rc && rc != -EALREADY) {
		printk("adv start failed: %d\n", rc);
	}
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
	ARG_UNUSED(conn);
	ARG_UNUSED(reason);
	advertise();
}

BT_CONN_CB_DEFINE(conn_cb) = {
	.disconnected = disconnected,
};

int ble_sync_init(void)
{
	k_work_init(&stream_work, stream_records);
	advertise();
	return 0;
}
