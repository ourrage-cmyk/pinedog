#ifndef PINEDOG_RING_LOG_H
#define PINEDOG_RING_LOG_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "minute_summary.h"

/* Flash access, provided by the board layer (SPI NOR on PineTime). */
struct pd_flash_ops {
	int (*read)(void *ctx, uint32_t addr, void *buf, size_t len);
	int (*erase_sector)(void *ctx, uint32_t addr); /* 4 KB sector */
	int (*program)(void *ctx, uint32_t addr, const void *buf, size_t len);
	void *ctx;
};

#define PD_LOG_SECTOR_SIZE 4096u
#define PD_LOG_REC_SIZE sizeof(struct pd_record)

/*
 * Ring of fixed-size records over a flash region.
 * The region is a whole number of sectors. Head is the next write slot,
 * tail is the oldest record not yet acknowledged by Home Assistant.
 * Oldest records are overwritten when the ring is full.
 */
struct pd_log {
	const struct pd_flash_ops *ops;
	uint32_t base;
	uint32_t size;      /* bytes, multiple of PD_LOG_SECTOR_SIZE */
	uint32_t capacity;  /* records */
	uint32_t head;      /* record index, 0..capacity-1 */
	uint32_t tail;      /* record index, 0..capacity-1 */
	uint32_t count;     /* records between tail and head */
};

int pd_log_init(struct pd_log *log, const struct pd_flash_ops *ops,
		uint32_t base, uint32_t size);
int pd_log_append(struct pd_log *log, const struct pd_record *rec);
/* Read up to max records starting at record index idx (oldest-relative). */
int pd_log_read(struct pd_log *log, uint32_t idx, struct pd_record *out,
		uint32_t max);
/* Mark everything before minute (inclusive) as synced, frees ring space. */
void pd_log_ack_upto(struct pd_log *log, uint32_t minute);
uint32_t pd_log_pending(const struct pd_log *log);
/* Resume after reboot with the head and count saved at the last checkpoint. */
void pd_log_restore(struct pd_log *log, uint32_t head, uint32_t count);
/*
 * True when the next append erases a sector. Callers must then checkpoint
 * after pd_log_drop_for_next() and before pd_log_append(). Otherwise a reboot
 * during the erase would resume with a tail that points at erased flash.
 */
bool pd_log_needs_erase(const struct pd_log *log);
/* Moves the tail past the records that the next erase would destroy. */
void pd_log_drop_for_next(struct pd_log *log);

#endif
