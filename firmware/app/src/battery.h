#ifndef PINEDOG_BATTERY_H
#define PINEDOG_BATTERY_H

#include <stdbool.h>
#include <stdint.h>

#define PD_BATTERY_UNKNOWN 0xFF

int battery_init(void);

/* Last measured percentage, or PD_BATTERY_UNKNOWN before the first reading. */
uint8_t battery_percent(void);
bool battery_charging(void);
bool battery_power_present(void);

#endif
