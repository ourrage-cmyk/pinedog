#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include "pairing.h"

LOG_MODULE_REGISTER(pd_pairing, LOG_LEVEL_INF);

#define WINDOW_LENGTH K_SECONDS(60)

static const struct gpio_dt_spec button = GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios);
static struct gpio_callback button_cb;
static struct k_work_delayable window_close;
static volatile bool window_open_flag;

static void close_window(struct k_work *work)
{
	ARG_UNUSED(work);
	window_open_flag = false;
	LOG_INF("pairing window closed");
}

static void button_pressed(const struct device *dev, struct gpio_callback *cb,
			   uint32_t pins)
{
	ARG_UNUSED(dev);
	ARG_UNUSED(cb);
	ARG_UNUSED(pins);

	window_open_flag = true;
	k_work_reschedule(&window_close, WINDOW_LENGTH);
	LOG_INF("pairing window open for 60 s");
}

static enum bt_security_err pairing_accept(struct bt_conn *conn,
					   const struct bt_conn_pairing_feat *const feat)
{
	ARG_UNUSED(feat);

	if (!window_open_flag) {
		LOG_WRN("pairing refused: press the watch button to open pairing");
		return BT_SECURITY_ERR_PAIR_NOT_ALLOWED;
	}
	LOG_INF("pairing accepted");
	ARG_UNUSED(conn);
	return BT_SECURITY_ERR_SUCCESS;
}

static struct bt_conn_auth_cb auth_cb = {
	.pairing_accept = pairing_accept,
};

static void pairing_complete(struct bt_conn *conn, bool bonded)
{
	ARG_UNUSED(conn);
	LOG_INF("pairing complete, bonded: %d", bonded);
	window_open_flag = false;
	k_work_cancel_delayable(&window_close);
}

static void pairing_failed(struct bt_conn *conn, enum bt_security_err reason)
{
	ARG_UNUSED(conn);
	LOG_WRN("pairing failed: %d", reason);
}

static void bond_deleted(uint8_t id, const bt_addr_le_t *peer)
{
	ARG_UNUSED(id);
	ARG_UNUSED(peer);
	LOG_WRN("bond deleted by peer");
}

static struct bt_conn_auth_info_cb auth_info_cb = {
	.pairing_complete = pairing_complete,
	.pairing_failed = pairing_failed,
	.bond_deleted = bond_deleted,
};

int pairing_init(void)
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
	gpio_init_callback(&button_cb, button_pressed, BIT(button.pin));
	gpio_add_callback(button.port, &button_cb);

	k_work_init_delayable(&window_close, close_window);
	rc = bt_conn_auth_cb_register(&auth_cb);
	if (rc) {
		return rc;
	}
	return bt_conn_auth_info_cb_register(&auth_info_cb);
}

bool pairing_window_open(void)
{
	return window_open_flag;
}
