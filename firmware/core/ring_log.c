#include <string.h>

#include "ring_log.h"

#define RECS_PER_SECTOR (PD_LOG_SECTOR_SIZE / PD_LOG_REC_SIZE)

static uint32_t rec_addr(const struct pd_log *log, uint32_t idx)
{
	return log->base + idx * PD_LOG_REC_SIZE;
}

bool pd_log_needs_erase(const struct pd_log *log)
{
	return log->head % RECS_PER_SECTOR == 0;
}

/*
 * When head enters a new sector, that sector is erased, which destroys every
 * record in it. Any unacked record in the sector is dropped first by moving
 * the tail past the sector, so the oldest data is discarded explicitly rather
 * than read back as erased flash.
 */
void pd_log_drop_for_next(struct pd_log *log)
{
	if (!pd_log_needs_erase(log)) {
		return;
	}
	while (log->count > 0 &&
	       (log->tail + log->capacity - log->head) % log->capacity <
		       RECS_PER_SECTOR) {
		log->tail = (log->tail + 1) % log->capacity;
		log->count--;
	}
}

/* Called before writing slot head. */
static int prepare_slot(struct pd_log *log)
{
	if (!pd_log_needs_erase(log)) {
		return 0;
	}
	pd_log_drop_for_next(log);
	return log->ops->erase_sector(log->ops->ctx, rec_addr(log, log->head));
}

int pd_log_init(struct pd_log *log, const struct pd_flash_ops *ops,
		uint32_t base, uint32_t size)
{
	if (size == 0 || size % PD_LOG_SECTOR_SIZE) {
		return -1;
	}
	memset(log, 0, sizeof(*log));
	log->ops = ops;
	log->base = base;
	log->size = size;
	log->capacity = size / PD_LOG_REC_SIZE;
	return 0;
}

int pd_log_append(struct pd_log *log, const struct pd_record *rec)
{
	int rc = prepare_slot(log);

	if (rc) {
		return rc;
	}
	rc = log->ops->program(log->ops->ctx, rec_addr(log, log->head), rec,
			       PD_LOG_REC_SIZE);
	if (rc) {
		return rc;
	}
	log->head = (log->head + 1) % log->capacity;
	log->count++;
	return 0;
}

int pd_log_read(struct pd_log *log, uint32_t idx, struct pd_record *out,
		uint32_t max)
{
	uint32_t n = 0;

	while (n < max && idx + n < log->count) {
		uint32_t slot = (log->tail + idx + n) % log->capacity;
		int rc = log->ops->read(log->ops->ctx, rec_addr(log, slot),
					&out[n], PD_LOG_REC_SIZE);
		if (rc) {
			return rc;
		}
		n++;
	}
	return (int)n;
}

void pd_log_ack_count(struct pd_log *log, uint32_t n)
{
	if (n > log->count) {
		n = log->count;
	}
	log->tail = (log->tail + n) % log->capacity;
	log->count -= n;
}

uint32_t pd_log_pending(const struct pd_log *log)
{
	return log->count;
}

void pd_log_restore(struct pd_log *log, uint32_t head, uint32_t count)
{
	log->head = head % log->capacity;
	log->count = count > log->capacity ? log->capacity : count;
	log->tail = (log->head + log->capacity - log->count) % log->capacity;
}
