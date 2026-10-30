#include <stdint.h>
#include <string.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/display.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/printk.h>

#include "battery.h"
#include "ble_sync.h"
#include "clock.h"
#include "display.h"
#include "pairing.h"
#include "store.h"

LOG_MODULE_REGISTER(pd_display, LOG_LEVEL_INF);

/* Built-in 10x16 font from Zephyr's cfb sources, ASCII 32..126, vertically packed. */
extern const uint8_t cfb_font_1016[95][20];

#define SCREEN_W 240
#define LINE_H 16
#define LINE_SLOT 24 /* text rows are 24 px apart */
#define CHAR_W 10
#define CHARS_PER_LINE (SCREEN_W / CHAR_W)
#define LINES 10
#define REFRESH K_SECONDS(1)
#define DAY_MINUTES 1440

static const struct device *const panel = DEVICE_DT_GET(DT_CHOSEN(zephyr_display));
static const struct gpio_dt_spec backlight = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static struct k_work_delayable tick;
static int64_t off_at_ms;
static bool screen_on;
static uint32_t active_24h; /* counted once at wake, not on every refresh */
static bool active_valid;

/* One line of 16 rows of RGB565 pixels. White is 0xFFFF, black is 0x0000. */
static uint8_t frame[SCREEN_W * LINE_H * 2];

static void draw_text(uint16_t row, const char *text)
{
	struct display_buffer_descriptor desc = {
		.buf_size = sizeof(frame),
		.width = SCREEN_W,
		.height = LINE_H,
		.pitch = SCREEN_W,
	};

	memset(frame, 0, sizeof(frame));
	for (uint32_t i = 0; i < CHARS_PER_LINE && text[i]; i++) {
		unsigned char c = (unsigned char)text[i];

		if (c < 32 || c > 126) {
			c = '?';
		}
		const uint8_t *glyph = cfb_font_1016[c - 32];

		for (uint32_t col = 0; col < CHAR_W; col++) {
			uint16_t bits = glyph[col * 2] | (glyph[col * 2 + 1] << 8);
			uint32_t x = i * CHAR_W + col;

			for (uint32_t r = 0; r < LINE_H; r++) {
				if ((bits >> r) & 1) {
					uint32_t off = (r * SCREEN_W + x) * 2;

					frame[off] = 0xFF;
					frame[off + 1] = 0xFF;
				}
			}
		}
	}
	display_write(panel, 0, row * LINE_SLOT, &desc, frame);
}

static void render(void)
{
	char text[LINES][CHARS_PER_LINE + 1];
	struct pd_last_sync last;
	uint8_t pct = battery_percent();
	uint32_t pending;
	uint32_t up_s = (uint32_t)(k_uptime_get() / 1000);
	uint32_t window_s = ble_sync_window_left_s();
	int bonds = pairing_bond_count();

	store_lock();
	pending = store_pending();
	store_unlock();
	ble_sync_last(&last);

	snprintk(text[0], sizeof(text[0]), "PINEDOG");
	if (pct == PD_BATTERY_UNKNOWN) {
		snprintk(text[1], sizeof(text[1]), "BATTERY ??");
	} else {
		snprintk(text[1], sizeof(text[1]), "BATTERY %u%%%s", pct,
			 battery_charging() ? " CHARGING" : "");
	}
	snprintk(text[2], sizeof(text[2]), "PENDING %u RECORDS", pending);
	if (last.valid) {
		snprintk(text[3], sizeof(text[3]), "LAST SYNC %u RECORDS", last.records);
		snprintk(text[4], sizeof(text[4]), "SYNC AGO %u MIN", last.age_s / 60);
	} else {
		snprintk(text[3], sizeof(text[3]), "LAST SYNC NONE");
		snprintk(text[4], sizeof(text[4]), "SYNC AGO -");
	}
	if (clock_synced() && active_valid) {
		snprintk(text[5], sizeof(text[5]), "ACTIVE 24H %u MIN", active_24h);
	} else {
		snprintk(text[5], sizeof(text[5]), "ACTIVE 24H NO CLOCK");
	}
	snprintk(text[6], sizeof(text[6]), "CLOCK %s", clock_synced() ? "SET" : "NOT SET");
	snprintk(text[7], sizeof(text[7]), "BOOT %u UP %u S", store_boot_id(), up_s);
	snprintk(text[8], sizeof(text[8]), "BONDS %d %s", bonds, bonds ? "PAIRED" : "NOT PAIRED");
	if (window_s > 0) {
		snprintk(text[9], sizeof(text[9]), "SYNC WINDOW %u S", window_s);
	} else {
		snprintk(text[9], sizeof(text[9]), "SYNC WINDOW CLOSED");
	}

	for (uint16_t i = 0; i < LINES; i++) {
		draw_text(i, text[i]);
	}
}

static void tick_handler(struct k_work *work)
{
	ARG_UNUSED(work);
	if (k_uptime_get() >= off_at_ms) {
		screen_on = false;
		gpio_pin_set_dt(&backlight, 0);
		display_blanking_on(panel);
		LOG_INF("screen off");
		return;
	}
	render();
	k_work_reschedule(&tick, REFRESH);
}

void display_wake(uint32_t seconds)
{
	off_at_ms = k_uptime_get() + (int64_t)seconds * 1000;
	if (!screen_on) {
		/* Count the active minutes once per wake, not on every refresh. */
		active_24h = clock_synced()
			? store_active_since(clock_minute() - DAY_MINUTES)
			: 0;
		active_valid = clock_synced();
		screen_on = true;
		display_blanking_off(panel);
		gpio_pin_set_dt(&backlight, 1);
	}
	k_work_reschedule(&tick, K_NO_WAIT);
}

int display_init(void)
{
	int rc;

	if (!device_is_ready(panel)) {
		LOG_ERR("display not ready");
		return -ENODEV;
	}
	if (!gpio_is_ready_dt(&backlight)) {
		LOG_ERR("backlight not ready");
		return -ENODEV;
	}
	rc = gpio_pin_configure_dt(&backlight, GPIO_OUTPUT_INACTIVE);
	if (rc) {
		return rc;
	}
	/* Dark at boot: the screen only comes on after a button press. */
	rc = display_blanking_on(panel);
	if (rc) {
		return rc;
	}
	k_work_init_delayable(&tick, tick_handler);
	return 0;
}
