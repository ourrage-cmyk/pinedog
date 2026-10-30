#ifndef PINEDOG_PAIRING_H
#define PINEDOG_PAIRING_H

#include <stdbool.h>

/*
 * Pairing is only accepted while a pairing window is open. The window is
 * opened by a button press (see button.c) and closes after 60 s or after a
 * successful bond. Bonds are kept in flash, so the watch only needs pairing
 * once.
 */
int pairing_init(void);
void pairing_open_window(void);
bool pairing_window_open(void);
int pairing_bond_count(void);

#endif
