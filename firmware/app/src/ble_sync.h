#ifndef PINEDOG_BLE_SYNC_H
#define PINEDOG_BLE_SYNC_H

#include <stdint.h>

/* Starts advertising and the GATT service. Call after bt_enable(). */
int ble_sync_init(void);

#endif
