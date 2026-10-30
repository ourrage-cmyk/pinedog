#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include "ble_sync.h"
#include "button.h"
#include "display.h"
#include "pairing.h"

LOG_MODULE_REGISTER(pd_button, LOG_LEVEL_INF);

#define DEBOUNCE_MS 250
#define WINDOW_S 60
#define DISPLAY_ON_S 30

static const struct gpio_dt_spec button = GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios);
static struct gpio_callback button_cb;
static struct k_work press_work;
static int64_t last_press_ms = -DEBOUNCE_MS;

/* Runs in the system work queue, not in the interrupt, so it may use the flash and SPI. */
static void press_handler(struct k_work *work)
{
	ARG_UNUSED(work);
	pairing_open_window();
	ble_sync_open_window(WINDOW_S);
	display_wake(DISPLAY_ON_S);
	LOG_INF("button: display on, sync window and pairing open");
}

static void button_pressed(const struct device *dev, struct gpio_callback *cb,
			   uint32_t pins)
{
	int64_t now = k_uptime_get();

	ARG_UNUSED(dev);
	ARG_UNUSED(cb);
	ARG_UNUSED(pins);
	if (now - last_press_ms < DEBOUNCE_MS) {
		return;
	}
	last_press_ms = now;
	k_work_submit(&press_work);
}

int button_init(void)
{
	int rc;

	if (!gpio_is_ready_dt(&button)) {
		LOG_ERR("button not ready");
		return -ENODEV;
	}
	rc = gpio_pin_configure_dt(&button, GPIO_INPUT);
	if (rc) {
		return rc;
	}
	rc = gpio_pin_interrupt_configure_dt(&button, GPIO_INT_EDGE_TO_ACTIVE);
	if (rc) {
		return rc;
	}
	k_work_init(&press_work, press_handler);
	gpio_init_callback(&button_cb, button_pressed, BIT(button.pin));
	gpio_add_callback(button.port, &button_cb);
	return 0;
}
