#ifndef PINEDOG_BLE_SYNC_H
#define PINEDOG_BLE_SYNC_H

#include <stdbool.h>
#include <stdint.h>

/* Advertising flag byte: asks Home Assistant to sync now. */
#define PD_ADV_FLAG_SYNC_REQUEST 0x01

/* The last transfer that was acked, for the screen. Kept in RAM only. */
struct pd_last_sync {
	bool valid;
	uint32_t records;
	uint32_t age_s;
};

/* Starts advertising and the GATT service. Call after bt_enable(). */
int ble_sync_init(void);

/*
 * Opens a sync window: fast advertising that asks Home Assistant to connect
 * now. Called on a button press. Closes by itself after the given seconds.
 */
void ble_sync_open_window(uint32_t seconds);
uint32_t ble_sync_window_left_s(void);

bool ble_sync_last(struct pd_last_sync *out);

#endif
