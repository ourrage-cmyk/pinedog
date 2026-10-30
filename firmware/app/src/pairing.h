#ifndef PINEDOG_PAIRING_H
#define PINEDOG_PAIRING_H

#include <stdbool.h>

/*
 * Pairing is only accepted while a pairing window is open. The window opens
 * when the watch's button is pressed and closes after 60 s or after a
 * successful bond. Bonds are kept in flash, so the watch only needs pairing
 * once.
 */
int pairing_init(void);
bool pairing_window_open(void);

#endif
