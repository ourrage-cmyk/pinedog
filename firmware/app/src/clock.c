#include <zephyr/kernel.h>

#include "clock.h"

static bool synced;
static int64_t base_unix_s; /* Unix seconds at uptime zero */

void clock_set_unix(uint32_t unix_seconds)
{
	base_unix_s = (int64_t)unix_seconds - k_uptime_get() / 1000;
	synced = true;
}

uint32_t clock_minute(void)
{
	int64_t up_s = k_uptime_get() / 1000;

	if (!synced) {
		return (uint32_t)(up_s / 60);
	}
	return (uint32_t)((base_unix_s + up_s) / 60);
}

bool clock_synced(void)
{
	return synced;
}
