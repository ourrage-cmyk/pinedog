#include <errno.h>
#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/sys/printk.h>

#include "journal.h"
#include "ring_log.h"
#include "store.h"

static const struct flash_area *fa;
static struct pd_log log;
static struct pd_journal journal;
static uint8_t boot_id;
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

/*
 * The last PD_JOURNAL_SECTORS sectors of the partition hold the checkpoint
 * journal. The rest is the record ring.
 */
int store_init(void)
{
	uint32_t ring_size;
	uint32_t head = 0, count = 0;
	uint8_t boot = 0;
	bool found;
	int rc;

	rc = flash_area_open(FIXED_PARTITION_ID(storage_partition), &fa);
	if (rc) {
		return rc;
	}

	ring_size = fa->fa_size - PD_JOURNAL_SECTORS * PD_LOG_SECTOR_SIZE;
	ops.ctx = (void *)fa;
	rc = pd_log_init(&log, &ops, 0, ring_size);
	if (rc) {
		return rc;
	}
	rc = pd_journal_open(&journal, &ops, ring_size, &found, &head, &count, &boot);
	if (rc) {
		return rc;
	}
	if (found) {
		pd_log_restore(&log, head, count);
	}
	/* Each boot takes the next id, so unsynced records can be placed in time later. */
	boot_id = (boot + 1) & PD_BOOT_MASK;
	return pd_journal_write(&journal, log.head, log.count, boot_id) ? -EIO : 0;
}

uint8_t store_boot_id(void)
{
	return boot_id;
}

static void checkpoint_locked(void)
{
	if (pd_journal_write(&journal, log.head, log.count, boot_id)) {
		printk("checkpoint write failed\n");
	}
}

int store_append(const struct pd_record *rec)
{
	int rc;

	if (pd_log_needs_erase(&log)) {
		pd_log_drop_for_next(&log);
		checkpoint_locked();
	}
	rc = pd_log_append(&log, rec);
	if (rc) {
		return rc;
	}
	checkpoint_locked();
	return 0;
}

int store_read(uint32_t index, struct pd_record *out, uint32_t max)
{
	return pd_log_read(&log, index, out, max);
}

void store_ack(uint32_t count)
{
	pd_log_ack_count(&log, count);
	checkpoint_locked();
}

uint32_t store_pending(void)
{
	return pd_log_pending(&log);
}

/*
 * Walks back from the newest record in chunks, so the lock is held only for
 * one read at a time and logging is never blocked for long. Unsynced records
 * carry uptime minutes, not unix minutes, so they are skipped.
 */
uint32_t store_active_since(uint32_t minute)
{
	struct pd_record batch[16];
	uint32_t total = 0;
	uint32_t end;

	store_lock();
	end = pd_log_pending(&log);
	store_unlock();

	while (end > 0) {
		uint32_t n = end < 16 ? end : 16;
		uint32_t from = end - n;
		int got;

		store_lock();
		got = pd_log_read(&log, from, batch, n);
		store_unlock();
		if (got <= 0) {
			break;
		}
		for (int i = got - 1; i >= 0; i--) {
			if (batch[i].class & PD_CLASS_UNSYNCED) {
				continue;
			}
			if (batch[i].minute < minute) {
				return total;
			}
			const uint8_t cls = batch[i].class & PD_CLASS_MASK;
			if (cls >= PD_CLASS_LIGHT && cls <= PD_CLASS_RUN) {
				total++;
			}
		}
		end = from;
	}
	return total;
}

void store_checkpoint(void)
{
	checkpoint_locked();
}

void store_lock(void)
{
	k_mutex_lock(&store_mutex, K_FOREVER);
}

void store_unlock(void)
{
	k_mutex_unlock(&store_mutex);
}
