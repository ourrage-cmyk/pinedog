#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/hwinfo.h>
#include <zephyr/drivers/watchdog.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include "watchdog.h"

LOG_MODULE_REGISTER(pd_wdt, LOG_LEVEL_INF);

#define TIMEOUT_MS 30000
#define FEED_PERIOD K_SECONDS(5)

static const struct device *wdt = DEVICE_DT_GET(DT_ALIAS(watchdog0));
static int wdt_channel = -1;
static struct k_work_delayable feeder;

static void feed(struct k_work *work)
{
	ARG_UNUSED(work);
	if (wdt_channel >= 0) {
		wdt_feed(wdt, wdt_channel);
	}
	k_work_reschedule(&feeder, FEED_PERIOD);
}

int watchdog_start(void)
{
	struct wdt_timeout_cfg cfg = {
		.flags = WDT_FLAG_RESET_SOC,
		.window = {
			.min = 0,
			.max = TIMEOUT_MS,
		},
		.callback = NULL,
	};
	int rc;

	if (!device_is_ready(wdt)) {
		LOG_ERR("watchdog not ready");
		return -ENODEV;
	}
	wdt_channel = wdt_install_timeout(wdt, &cfg);
	if (wdt_channel < 0) {
		LOG_ERR("install timeout: %d", wdt_channel);
		return wdt_channel;
	}
	rc = wdt_setup(wdt, WDT_OPT_PAUSE_HALTED_BY_DBG);
	if (rc) {
		LOG_ERR("watchdog setup: %d", rc);
		return rc;
	}
	k_work_init_delayable(&feeder, feed);
	k_work_reschedule(&feeder, FEED_PERIOD);
	LOG_INF("watchdog armed, %d s timeout", TIMEOUT_MS / 1000);
	return 0;
}

void watchdog_log_reset_cause(void)
{
	uint32_t cause = 0;

	if (hwinfo_get_reset_cause(&cause) == 0) {
		LOG_INF("reset cause: 0x%08x", cause);
		hwinfo_clear_reset_cause();
	} else {
		LOG_WRN("reset cause unavailable");
	}
}
