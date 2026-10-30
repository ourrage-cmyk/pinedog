/*
 * Battery level from the PineTime's LiPo through the voltage divider on AIN7.
 *
 * The voltage-to-percent curve and the charging pins come from InfiniTime
 * (src/components/battery/BatteryController.cpp and src/drivers/PinMap.h).
 * The level is published with the standard Battery Service (0x180F) so any
 * Bluetooth client can read it, including Home Assistant.
 */
#include <zephyr/bluetooth/services/bas.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include "battery.h"

LOG_MODULE_REGISTER(pd_battery, LOG_LEVEL_INF);

#define READ_PERIOD K_MINUTES(5)

/* PineTime pins, active low. */
#define PIN_CHARGING 12
#define PIN_POWER_PRESENT 19

static const struct device *vbatt =
	DEVICE_DT_GET(DT_COMPAT_GET_ANY_STATUS_OKAY(voltage_divider));
static const struct device *gpio0 = DEVICE_DT_GET(DT_NODELABEL(gpio0));

/* Voltage (mV) to percent, as in InfiniTime's LinearApproximation table. */
static const struct {
	uint16_t mv;
	uint8_t pct;
} curve[] = {
	{3500, 0}, {3616, 3}, {3723, 22}, {3776, 48}, {3979, 79}, {4180, 100},
};

static uint8_t percent;
static bool charging;
static bool power_present;
static bool first;
static struct k_work_delayable reader;

static uint8_t mv_to_percent(uint16_t mv)
{
	const size_t n = ARRAY_SIZE(curve);

	if (mv <= curve[0].mv) {
		return curve[0].pct;
	}
	if (mv >= curve[n - 1].mv) {
		return curve[n - 1].pct;
	}
	for (size_t i = 1; i < n; i++) {
		if (mv <= curve[i].mv) {
			uint32_t span_mv = curve[i].mv - curve[i - 1].mv;
			uint32_t span_pct = curve[i].pct - curve[i - 1].pct;
			uint32_t off = mv - curve[i - 1].mv;

			return curve[i - 1].pct + (off * span_pct) / span_mv;
		}
	}
	return curve[n - 1].pct;
}

static void read_pins(void)
{
	charging = gpio_pin_get_raw(gpio0, PIN_CHARGING) == 0;
	power_present = gpio_pin_get_raw(gpio0, PIN_POWER_PRESENT) == 0;
}

static void read_battery(struct k_work *work)
{
	struct sensor_value v;
	uint8_t new_pct;
	int mv;

	ARG_UNUSED(work);
	read_pins();

	if (!device_is_ready(vbatt) || sensor_sample_fetch(vbatt) ||
	    sensor_channel_get(vbatt, SENSOR_CHAN_VOLTAGE, &v)) {
		LOG_ERR("battery read failed");
	} else {
		/* SENSOR_CHAN_VOLTAGE is in volts; the divider output is already halved. */
		mv = v.val1 * 1000 + v.val2 / 1000;
		new_pct = mv_to_percent(mv * 2);

		/* While charging, the reading is high, so cap it below full. */
		if (charging && new_pct > 99) {
			new_pct = 99;
		}
		if (power_present && !charging && new_pct >= 99) {
			new_pct = 100;
		}
		if (first || new_pct != percent) {
			LOG_INF("battery %u%% (%d mV, charging %d, power %d)",
				new_pct, mv * 2, charging, power_present);
			percent = new_pct;
			bt_bas_set_battery_level(percent);
		}
		first = false;
	}
	k_work_reschedule(&reader, READ_PERIOD);
}

int battery_init(void)
{
	int rc;

	if (!device_is_ready(gpio0)) {
		LOG_ERR("gpio0 not ready");
		return -ENODEV;
	}
	rc = gpio_pin_configure(gpio0, PIN_CHARGING, GPIO_INPUT);
	rc |= gpio_pin_configure(gpio0, PIN_POWER_PRESENT, GPIO_INPUT);
	if (rc) {
		LOG_ERR("charging pins: %d", rc);
		return rc;
	}

	percent = PD_BATTERY_UNKNOWN;
	first = true;
	k_work_init_delayable(&reader, read_battery);
	k_work_reschedule(&reader, K_SECONDS(1));
	return 0;
}

uint8_t battery_percent(void)
{
	return percent;
}

bool battery_charging(void)
{
	return charging;
}

bool battery_power_present(void)
{
	return power_present;
}
