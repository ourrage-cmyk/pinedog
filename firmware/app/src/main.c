/*
 * Pinedog firmware for the first-generation PineTime.
 *
 * The BMA421 raises a data-ready interrupt at 25 Hz. Each sample feeds the
 * per-minute summariser, and a finished minute is stored in the external flash
 * log with a checksum. Home Assistant pulls the log over an encrypted,
 * bonded Bluetooth link, and the button opens a pairing window.
 *
 * There is no real-time clock. Records logged before the first clock sync
 * after a boot carry uptime minutes and a boot id, so Home Assistant can place
 * them in time once it has synced.
 */
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include "battery.h"
#include "button.h"
#include "display.h"
#include "ble_sync.h"
#include "clock.h"
#include "minute_summary.h"
#include "pairing.h"
#include "store.h"
#include "watchdog.h"

LOG_MODULE_REGISTER(pinedog, LOG_LEVEL_INF);

#define ACCEL_NODE DT_NODELABEL(bma421)
#define STATUS_PERIOD K_MINUTES(10)

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

#define WINDOW_PERIOD K_SECONDS(60)

static struct pd_summary summary;
static struct k_mutex summary_lock;
static struct k_work_delayable status_log;
static struct k_work_delayable window_tick;

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

	ARG_UNUSED(trig);
	if (sensor_sample_fetch_chan(dev, SENSOR_CHAN_ACCEL_XYZ)) {
		return;
	}
	if (sensor_channel_get(dev, SENSOR_CHAN_ACCEL_XYZ, xyz)) {
		return;
	}
	k_mutex_lock(&summary_lock, K_FOREVER);
	pd_summary_push(&summary, to_mg(&xyz[0]), to_mg(&xyz[1]), to_mg(&xyz[2]));
	k_mutex_unlock(&summary_lock);
}

/*
 * Closes one window every minute by the clock. Every window is logged, even
 * if the watch did not move: an empty window is rest, and a sparse window is
 * scaled up, so quiet sleeping dogs still show up as sedentary time. Nothing
 * here depends on motion.
 */
static void close_window(struct k_work *work)
{
	struct pd_record rec;

	ARG_UNUSED(work);
	k_mutex_lock(&summary_lock, K_FOREVER);
	pd_summary_flush(&summary, &cfg, clock_minute(), &rec);
	k_mutex_unlock(&summary_lock);

	/* On the charger the minute is NOT_WORN; Home Assistant leaves it out of totals. */
	if (battery_charging()) {
		rec.class = PD_CLASS_NOT_WORN;
	}
	if (!clock_synced()) {
		/* Keep the boot id so Home Assistant can place the record later. */
		rec.class = (rec.class & PD_CLASS_MASK) | PD_CLASS_UNSYNCED |
			    ((store_boot_id() & PD_BOOT_MASK) << PD_BOOT_SHIFT);
	}
	rec.crc = pd_record_crc(&rec);
	store_lock();
	store_append(&rec);
	store_unlock();
	k_work_reschedule(&window_tick, WINDOW_PERIOD);
}

static void log_status(struct k_work *work)
{
	ARG_UNUSED(work);
	store_lock();
	uint32_t pending = store_pending();
	store_unlock();

	LOG_INF("status: uptime %u s, boot %u, clock %s, pending %u, battery %u%%%s",
		(uint32_t)(k_uptime_get() / 1000), store_boot_id(),
		clock_synced() ? "synced" : "unsynced", pending, battery_percent(),
		battery_charging() ? ", charging" : "");
	k_work_reschedule(&status_log, STATUS_PERIOD);
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

	watchdog_log_reset_cause();
	rc = watchdog_start();
	if (rc) {
		LOG_ERR("watchdog not armed: %d", rc);
	}

	rc = store_init();
	if (rc) {
		LOG_ERR("store init failed: %d", rc);
		return rc;
	}

	rc = battery_init();
	if (rc) {
		LOG_ERR("battery init failed: %d", rc);
	}

	if (!device_is_ready(accel)) {
		LOG_ERR("accelerometer not ready");
		return -ENODEV;
	}
	sensor_attr_set(accel, SENSOR_CHAN_ACCEL_XYZ,
			SENSOR_ATTR_SAMPLING_FREQUENCY, &odr);
	sensor_attr_set(accel, SENSOR_CHAN_ACCEL_XYZ,
			SENSOR_ATTR_FULL_SCALE, &range);
	rc = sensor_trigger_set(accel, &trig, on_data_ready);
	if (rc) {
		LOG_ERR("trigger set failed: %d", rc);
		return rc;
	}

	rc = bt_enable(NULL);
	if (rc) {
		LOG_ERR("bt_enable failed: %d", rc);
		return rc;
	}
	rc = pairing_init();
	if (rc) {
		LOG_ERR("pairing init failed: %d", rc);
		return rc;
	}
	ble_sync_init();
	rc = button_init();
	if (rc) {
		LOG_ERR("button init failed: %d", rc);
	}
	rc = display_init();
	if (rc) {
		LOG_ERR("display init failed: %d", rc);
	}

	pd_summary_reset(&summary, clock_minute());
	k_mutex_init(&summary_lock);
	k_work_init_delayable(&window_tick, close_window);
	k_work_reschedule(&window_tick, WINDOW_PERIOD);
	k_work_init_delayable(&status_log, log_status);
	k_work_reschedule(&status_log, K_SECONDS(30));
	LOG_INF("pinedog started, boot %u, %u records pending",
		store_boot_id(), store_pending());
	return 0;
}
