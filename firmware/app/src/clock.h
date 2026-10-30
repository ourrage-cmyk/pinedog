#ifndef PINEDOG_CLOCK_H
#define PINEDOG_CLOCK_H

#include <stdbool.h>
#include <stdint.h>

/* There is no RTC. Home Assistant sets the Unix time on each sync. */
void clock_set_unix(uint32_t unix_seconds);

/* Current minute since epoch, or uptime minutes if not yet synced. */
uint32_t clock_minute(void);
bool clock_synced(void);

#endif
