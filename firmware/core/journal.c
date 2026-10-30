#include <errno.h>
#include <stddef.h>
#include <string.h>

#include "journal.h"

struct pd_ckpt {
	uint32_t seq;
	uint32_t head;
	uint32_t count;
	uint32_t crc; /* over seq, head and count */
};

_Static_assert(sizeof(struct pd_ckpt) == PD_JOURNAL_ENTRY_SIZE,
	       "checkpoint entry must be 16 bytes");

/* Bitwise CRC-32 (IEEE). Only a few dozen bytes per call, so speed does not matter. */
static uint32_t crc32(const void *data, size_t len)
{
	const uint8_t *p = data;
	uint32_t crc = 0xFFFFFFFFu;

	for (size_t i = 0; i < len; i++) {
		crc ^= p[i];
		for (int b = 0; b < 8; b++) {
			crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
		}
	}
	return ~crc;
}

static uint32_t entry_addr(const struct pd_journal *j, uint32_t sector,
			   uint32_t idx)
{
	return j->base + sector * PD_LOG_SECTOR_SIZE + idx * PD_JOURNAL_ENTRY_SIZE;
}

static bool is_blank(const uint8_t *raw)
{
	for (size_t i = 0; i < PD_JOURNAL_ENTRY_SIZE; i++) {
		if (raw[i] != 0xFF) {
			return false;
		}
	}
	return true;
}

static bool entry_valid(const struct pd_ckpt *e)
{
	if (e->seq == 0 || e->seq == 0xFFFFFFFFu) {
		return false;
	}
	return e->crc == crc32(e, offsetof(struct pd_ckpt, crc));
}

static int erase_sector(const struct pd_journal *j, uint32_t sector)
{
	return j->ops->erase_sector(j->ops->ctx,
				    j->base + sector * PD_LOG_SECTOR_SIZE);
}

int pd_journal_open(struct pd_journal *j, const struct pd_flash_ops *ops,
		    uint32_t base, bool *found, uint32_t *head, uint32_t *count)
{
	struct pd_ckpt best = { 0 };
	bool have_best = false;
	uint32_t best_sector = 0;
	uint32_t used[PD_JOURNAL_SECTORS] = { 0 };

	j->ops = ops;
	j->base = base;
	j->active = 0;
	j->next = 0;
	j->seq = 0;
	*found = false;
	*head = 0;
	*count = 0;

	for (uint32_t s = 0; s < PD_JOURNAL_SECTORS; s++) {
		for (uint32_t i = 0; i < PD_JOURNAL_ENTRIES_PER_SECTOR; i++) {
			uint8_t raw[PD_JOURNAL_ENTRY_SIZE];
			struct pd_ckpt e;

			if (ops->read(ops->ctx, entry_addr(j, s, i), raw,
				      sizeof(raw))) {
				return -EIO;
			}
			if (!is_blank(raw)) {
				used[s] = i + 1;
			}
			memcpy(&e, raw, sizeof(e));
			if (entry_valid(&e) && (!have_best || e.seq > best.seq)) {
				best = e;
				have_best = true;
				best_sector = s;
			}
		}
	}

	if (!have_best) {
		/* Nothing valid: start over with clean sectors. */
		for (uint32_t s = 0; s < PD_JOURNAL_SECTORS; s++) {
			int rc = erase_sector(j, s);

			if (rc) {
				return rc;
			}
		}
		return 0;
	}

	*found = true;
	*head = best.head;
	*count = best.count;
	j->seq = best.seq;
	j->active = best_sector;
	j->next = used[best_sector];
	return 0;
}

int pd_journal_write(struct pd_journal *j, uint32_t head, uint32_t count)
{
	struct pd_ckpt e = {
		.seq = j->seq + 1,
		.head = head,
		.count = count,
	};
	int rc;

	if (j->next == PD_JOURNAL_ENTRIES_PER_SECTOR) {
		uint32_t other = (j->active + 1) % PD_JOURNAL_SECTORS;

		/* The active sector holds the newest checkpoint, so erasing the other is safe. */
		rc = erase_sector(j, other);
		if (rc) {
			return rc;
		}
		j->active = other;
		j->next = 0;
	}

	e.crc = crc32(&e, offsetof(struct pd_ckpt, crc));
	/* Advance even on failure: a torn entry must never be programmed over. */
	j->seq = e.seq;
	rc = j->ops->program(j->ops->ctx, entry_addr(j, j->active, j->next), &e,
			     sizeof(e));
	j->next++;
	return rc;
}
