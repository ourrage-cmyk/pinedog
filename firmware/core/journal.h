#ifndef PINEDOG_JOURNAL_H
#define PINEDOG_JOURNAL_H

#include <stdbool.h>
#include <stdint.h>

#include "ring_log.h"

/*
 * Checkpoint journal for the ring log.
 *
 * Every append and every ack writes one 16-byte checkpoint (head, count and a
 * sequence number, with a CRC) into the next free entry of the active journal
 * sector. Entries are only programmed, never rewritten. A sector is erased
 * only when the other sector is full, so there are always two sectors of
 * history. On boot the valid entry with the highest sequence number wins. A
 * torn entry fails its CRC and is ignored, so power loss at any point falls
 * back to the previous checkpoint and never to an empty ring.
 *
 * Sector wear: 256 entries per sector, one per minute, so each sector is
 * erased about every 8.5 hours. A 100k-cycle sector lasts decades.
 */
#define PD_JOURNAL_SECTORS 2
#define PD_JOURNAL_ENTRY_SIZE 16u
#define PD_JOURNAL_ENTRIES_PER_SECTOR (PD_LOG_SECTOR_SIZE / PD_JOURNAL_ENTRY_SIZE)

struct pd_journal {
	const struct pd_flash_ops *ops;
	uint32_t base;   /* first of the PD_JOURNAL_SECTORS sectors */
	uint32_t active; /* sector that receives new entries */
	uint32_t next;   /* next entry index in the active sector */
	uint32_t seq;    /* sequence number of the newest entry */
};

/*
 * Each entry also stores the boot counter (mod 256). The newest valid entry
 * gives the boot counter of the last run, so the next run is one higher.
 */

/*
 * Finds the newest valid checkpoint. Sets *found and, when found, *head and
 * *count. A blank or damaged journal is erased so writing can start.
 */
int pd_journal_open(struct pd_journal *j, const struct pd_flash_ops *ops,
		    uint32_t base, bool *found, uint32_t *head, uint32_t *count,
		    uint8_t *boot);

/* Programs one checkpoint. Erases the other sector first when this one is full. */
int pd_journal_write(struct pd_journal *j, uint32_t head, uint32_t count,
		    uint8_t boot);

#endif
