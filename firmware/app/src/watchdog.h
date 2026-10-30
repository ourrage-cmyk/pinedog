#ifndef PINEDOG_WATCHDOG_H
#define PINEDOG_WATCHDOG_H

/*
 * Hardware watchdog. If the firmware stops feeding it for 30 s, the chip
 * resets and boots again, and the flash log picks up where it left off.
 */
int watchdog_start(void);

/* Call on every sensor sample. Without these calls the watchdog resets the chip. */
void watchdog_mark_alive(void);

/* Logs the cause of the last reset, if the platform reports one. */
void watchdog_log_reset_cause(void);

#endif
