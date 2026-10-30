/*
 * Pinedog firmware for the first-generation PineTime.
 *
 * The BMA421 raises a data-ready interrupt at 25 Hz. Each sample feeds the
 * per-minute summariser, and a finished minute is stored in the flash log.
 * Home Assistant pulls the log over BLE when the dog comes home.
 */
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>

#include "ble_sync.h"
#include "clock.h"
#include "minute_summary.h"
#include "store.h"

#define ACCEL_NODE DT_NODELABEL(bma421)

/*
 * Thresholds are starting points, not calibrated. The counts are mg of
 * deviation from gravity summed over a minute, divided by 1000.
 */
static const struct pd_config cfg = {
	.rest_max = 50,
	.walk_min = 300,
	.run_min = 1200,
	.walk_cadence_min = 15,
	.run_cadence_min = 30,
};

static struct pd_summary summary;

/* Converts a sensor value in m/s^2 to milli-g. */
static int32_t to_mg(const struct sensor_value *v)
{
	int64_t micro = (int64_t)v->val1 * 1000000 + v->val2;

	return (int32_t)(micro * 1000 / 9806650);
}

static void on_data_ready(const struct device *dev,
			  const struct sensor_trigger *trig)
{
	struct sensor_value xyz[3];
	struct pd_record rec;

	ARG_UNUSED(trig);
	if (sensor_sample_fetch_chan(dev, SENSOR_CHAN_ACCEL_XYZ)) {
		return;
	}
	if (sensor_channel_get(dev, SENSOR_CHAN_ACCEL_XYZ, xyz)) {
		return;
	}

	if (!pd_summary_push(&summary, to_mg(&xyz[0]), to_mg(&xyz[1]),
			     to_mg(&xyz[2]), &cfg, &rec)) {
		return;
	}

	/* The record is for the minute that just ended. */
	rec.minute = clock_minute() - 1;
	if (!clock_synced()) {
		rec.class |= PD_CLASS_UNSYNCED;
	}
	store_lock();
	if (store_append(&rec)) {
		printk("log append failed\n");
	}
	store_unlock();
}

int main(void)
{
	const struct device *accel = DEVICE_DT_GET(ACCEL_NODE);
	struct sensor_value odr = { .val1 = 25, .val2 = 0 };
	struct sensor_value range = { .val1 = 39, .val2 = 200000 }; /* ~4 g */
	struct sensor_trigger trig = {
		.type = SENSOR_TRIG_DATA_READY,
		.chan = SENSOR_CHAN_ACCEL_XYZ,
	};
	int rc;

	rc = store_init();
	if (rc) {
		printk("store init failed: %d\n", rc);
		return rc;
	}

	if (!device_is_ready(accel)) {
		printk("accelerometer not ready\n");
		return -ENODEV;
	}
	sensor_attr_set(accel, SENSOR_CHAN_ACCEL_XYZ,
			SENSOR_ATTR_SAMPLING_FREQUENCY, &odr);
	sensor_attr_set(accel, SENSOR_CHAN_ACCEL_XYZ,
			SENSOR_ATTR_FULL_SCALE, &range);
	rc = sensor_trigger_set(accel, &trig, on_data_ready);
	if (rc) {
		printk("trigger set failed: %d\n", rc);
		return rc;
	}

	rc = bt_enable(NULL);
	if (rc) {
		printk("bt_enable failed: %d\n", rc);
		return rc;
	}
	ble_sync_init();

	pd_summary_reset(&summary, clock_minute());
	printk("pinedog started, %u records pending\n", store_pending());
	return 0;
}
