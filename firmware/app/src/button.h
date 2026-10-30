#ifndef PINEDOG_BUTTON_H
#define PINEDOG_BUTTON_H

/*
 * The watch's button wakes it. A press turns the display on, opens a pairing
 * window, and opens a sync window so Home Assistant connects promptly. Without
 * a press the display stays off.
 */
int button_init(void);

#endif
