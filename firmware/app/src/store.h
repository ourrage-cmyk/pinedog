#ifndef PINEDOG_STORE_H
#define PINEDOG_STORE_H

#include <stdbool.h>
#include <stdint.h>

#include "minute_summary.h"

/* Set in the class byte when the record was made before the clock was synced. */
#define PD_CLASS_UNSYNCED 0x80
#define PD_CLASS_MASK 0x03u /* bits 0..1: rest, light, walk, run */
/* Unsynced records carry boot id (mod 32) in bits 2..6 of the class byte. */
#define PD_BOOT_SHIFT 2
#define PD_BOOT_MASK 0x1Fu

/* Opens the storage partition and resumes the log from the last checkpoint. */
int store_init(void);

/* Appends one record. Caller must hold store_lock(). */
int store_append(const struct pd_record *rec);

/* Reads up to max records starting at index (0 is the oldest pending). */
int store_read(uint32_t index, struct pd_record *out, uint32_t max);

/* Releases the count oldest records, then checkpoints. */
void store_ack(uint32_t count);

/* Boot counter, incremented by store_init() on every boot. */
uint8_t store_boot_id(void);

uint32_t store_pending(void);
void store_lock(void);
void store_unlock(void);

/* Writes head and count to flash so a reboot resumes near the right place. */
void store_checkpoint(void);

#endif
