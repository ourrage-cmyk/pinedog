#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/storage/flash_map.h>

#include "ring_log.h"
#include "store.h"

#define META_MAGIC 0x50444C47 /* "PDLG" */
#define CHECKPOINT_EVERY 60   /* appends, about hourly */

struct meta {
	uint32_t magic;
	uint32_t head;
	uint32_t count;
} __attribute__((packed));

static const struct flash_area *fa;
static struct pd_log log;
static uint32_t meta_off;
static uint32_t appends_since_checkpoint;
static K_MUTEX_DEFINE(store_mutex);

static int fa_read(void *ctx, uint32_t addr, void *buf, size_t len)
{
	return flash_area_read(ctx, addr, buf, len);
}

static int fa_erase(void *ctx, uint32_t addr)
{
	return flash_area_erase(ctx, addr, PD_LOG_SECTOR_SIZE);
}

static int fa_program(void *ctx, uint32_t addr, const void *buf, size_t len)
{
	return flash_area_write(ctx, addr, buf, len);
}

/* ctx is set to the flash area in store_init(). */
static struct pd_flash_ops ops = {
	.read = fa_read,
	.erase_sector = fa_erase,
	.program = fa_program,
};

/* The last sector of the partition holds the checkpoint, the rest is the ring. */
static int read_meta(struct meta *m)
{
	return flash_area_read(fa, meta_off, m, sizeof(*m));
}

int store_init(void)
{
	uint32_t ring_size;
	struct meta m;
	uint32_t head = 0, count = 0;
	int rc;

	rc = flash_area_open(FIXED_PARTITION_ID(storage_partition), &fa);
	if (rc) {
		return rc;
	}

	ring_size = fa->fa_size - PD_LOG_SECTOR_SIZE;
	meta_off = ring_size;
	ops.ctx = (void *)fa;
	rc = pd_log_init(&log, &ops, 0, ring_size);
	if (rc) {
		return rc;
	}

	if (read_meta(&m) == 0 && m.magic == META_MAGIC) {
		head = m.head;
		count = m.count;
	}
	pd_log_restore(&log, head, count);

	/*
	 * Records written after the last checkpoint are still in flash. Walk
	 * forward from the checkpoint over slots that were programmed.
	 */
	for (;;) {
		struct pd_record r;

		if (pd_log_pending(&log) >= log.capacity) {
			break;
		}
		if (pd_log_peek_slot(&log, log.head, &r)) {
			break;
		}
		if (r.minute == 0xFFFFFFFF) {
			break;
		}
		pd_log_restore(&log, (log.head + 1) % log.capacity, pd_log_pending(&log) + 1);
	}
	return 0;
}

int store_append(const struct pd_record *rec)
{
	int rc = pd_log_append(&log, rec);

	if (rc) {
		return rc;
	}
	if (++appends_since_checkpoint >= CHECKPOINT_EVERY) {
		store_checkpoint();
	}
	return 0;
}

int store_read(uint32_t index, struct pd_record *out, uint32_t max)
{
	return pd_log_read(&log, index, out, max);
}

void store_ack(uint32_t minute)
{
	pd_log_ack_upto(&log, minute);
	store_checkpoint();
}

uint32_t store_pending(void)
{
	return pd_log_pending(&log);
}

void store_checkpoint(void)
{
	struct meta m = {
		.magic = META_MAGIC,
		.head = log.head,
		.count = log.count,
	};

	appends_since_checkpoint = 0;
	if (flash_area_erase(fa, meta_off, PD_LOG_SECTOR_SIZE)) {
		return;
	}
	flash_area_write(fa, meta_off, &m, sizeof(m));
}

void store_lock(void)
{
	k_mutex_lock(&store_mutex, K_FOREVER);
}

void store_unlock(void)
{
	k_mutex_unlock(&store_mutex);
}
