#ifndef PINEDOG_DISPLAY_H
#define PINEDOG_DISPLAY_H

/*
 * The screen is off unless the button was pressed. A press turns it on for a
 * fixed time and shows status and debug values. It is off at boot.
 */
int display_init(void);
void display_wake(uint32_t seconds);

#include <stdint.h>

#endif
