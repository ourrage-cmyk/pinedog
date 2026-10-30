#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "journal.h"
#include "minute_summary.h"
#include "ring_log.h"

static const struct pd_config cfg = {
	.rest_max = 50,
	.walk_min = 300,
	.run_min = 1200,
	.walk_cadence_min = 15,
	.run_cadence_min = 30,
};

/* Fake flash in RAM, erase sets 0xff, program ANDs bits like NOR. */
#define FAKE_SIZE (4 * PD_LOG_SECTOR_SIZE)
static uint8_t fake[FAKE_SIZE];

static int f_read(void *c, uint32_t a, void *b, size_t l)
{
	(void)c;
	memcpy(b, &fake[a], l);
	return 0;
}
static int f_erase(void *c, uint32_t a)
{
	(void)c;
	memset(&fake[a], 0xff, PD_LOG_SECTOR_SIZE);
	return 0;
}
static int f_prog(void *c, uint32_t a, const void *b, size_t l)
{
	const uint8_t *p = b;
	(void)c;
	for (size_t i = 0; i < l; i++) {
		fake[a + i] &= p[i];
	}
	return 0;
}
static const struct pd_flash_ops ops = { f_read, f_erase, f_prog, NULL };

static void test_classify(void)
{
	assert(pd_classify(10, 0, &cfg) == PD_CLASS_REST);
	assert(pd_classify(100, 0, &cfg) == PD_CLASS_LIGHT);
	assert(pd_classify(400, 20, &cfg) == PD_CLASS_WALK);
	assert(pd_classify(2000, 40, &cfg) == PD_CLASS_RUN);
	assert(pd_classify(2000, 5, &cfg) == PD_CLASS_LIGHT);
}

static void test_summary_minute_rollover(void)
{
	struct pd_summary s;
	struct pd_record r;
	int done = 0;

	pd_summary_reset(&s, 1000);
	for (int i = 0; i < PD_SAMPLE_RATE_HZ * 60; i++) {
		/* still device: 1 g on z, no motion */
		done += pd_summary_push(&s, 0, 0, 1000, &cfg, &r);
	}
	assert(done == 1);
	assert(r.minute == 1000);
	assert(r.counts == 0);
	assert(r.class == PD_CLASS_REST);
	assert(s.minute == 1001);
}

static void test_log_ring(void)
{
	struct pd_log log;
	struct pd_record in, out[4];

	assert(pd_log_init(&log, &ops, 0, FAKE_SIZE) == 0);
	/* capacity = 16384 / 8 = 2048 records; push a few and read back */
	for (uint32_t i = 0; i < 5; i++) {
		in.minute = 100 + i;
		in.counts = (uint16_t)i;
		in.class = PD_CLASS_LIGHT;
		in.crc = 0;
		assert(pd_log_append(&log, &in) == 0);
	}
	assert(pd_log_pending(&log) == 5);
	assert(pd_log_read(&log, 1, out, 4) == 4);
	assert(out[0].minute == 101 && out[3].minute == 104);

	/* Count-based ack releases the three oldest records. */
	pd_log_ack_count(&log, 3);
	assert(pd_log_pending(&log) == 2);
	assert(pd_log_read(&log, 0, out, 4) == 2);
	assert(out[0].minute == 103);

	/* Acking more than is pending is clamped and leaves an empty ring. */
	pd_log_ack_count(&log, 50);
	assert(pd_log_pending(&log) == 0);

	/* The ring still accepts appends after it has been emptied. */
	in.minute = 200;
	assert(pd_log_append(&log, &in) == 0);
	assert(pd_log_read(&log, 0, out, 1) == 1 && out[0].minute == 200);
}

static void test_log_overflow_keeps_newest(void)
{
	struct pd_log log;
	struct pd_record in, oldest, newest;
	uint32_t cap, total, pending;

	assert(pd_log_init(&log, &ops, 0, FAKE_SIZE) == 0);
	cap = log.capacity;
	total = cap + 10;
	for (uint32_t i = 0; i < total; i++) {
		in.minute = i;
		in.counts = 0;
		in.class = 0;
		in.crc = 0;
		assert(pd_log_append(&log, &in) == 0);
	}
	/* Sector-granular erase may drop up to one sector of the oldest data. */
	pending = pd_log_pending(&log);
	assert(pending <= cap && pending > cap - PD_LOG_SECTOR_SIZE / PD_LOG_REC_SIZE);
	assert(pd_log_read(&log, 0, &oldest, 1) == 1);
	assert(pd_log_read(&log, pending - 1, &newest, 1) == 1);
	/* Retained records are contiguous and the newest one is intact. */
	assert(newest.minute == total - 1);
	assert(oldest.minute == total - pending);
}

static void test_log_restore(void)
{
	struct pd_log log;
	struct pd_record in, out;

	assert(pd_log_init(&log, &ops, 0, FAKE_SIZE) == 0);
	for (uint32_t i = 0; i < 20; i++) {
		in.minute = 500 + i;
		in.counts = 0;
		in.class = 0;
		in.crc = 0;
		assert(pd_log_append(&log, &in) == 0);
	}
	/* Simulate a reboot: a new log object resumes from head and count. */
	struct pd_log resumed;
	assert(pd_log_init(&resumed, &ops, 0, FAKE_SIZE) == 0);
	pd_log_restore(&resumed, 20, 20);
	assert(pd_log_pending(&resumed) == 20);
	assert(pd_log_read(&resumed, 19, &out, 1) == 1);
	assert(out.minute == 519);
	/* New appends continue after the restored head. */
	in.minute = 520;
	assert(pd_log_append(&resumed, &in) == 0);
	assert(pd_log_read(&resumed, 20, &out, 1) == 1);
	assert(out.minute == 520);
}

/* Blank flash reads 0xff, as NOR does after erase. */
static void fake_reset(void)
{
	memset(fake, 0xff, sizeof(fake));
}

static void test_journal_roundtrip(void)
{
	struct pd_journal j;
	bool found;
	uint8_t boot;
	uint32_t head, count;

	fake_reset();
	assert(pd_journal_open(&j, &ops, 0, &found, &head, &count, &boot) == 0);
	assert(!found);
	assert(pd_journal_write(&j, 5, 3, 1) == 0);
	assert(pd_journal_write(&j, 9, 7, 1) == 0);

	assert(pd_journal_open(&j, &ops, 0, &found, &head, &count, &boot) == 0);
	assert(found && head == 9 && count == 7);
	/* Writes after a reopen continue the sequence and the same sector. */
	assert(pd_journal_write(&j, 10, 8, 1) == 0);
	assert(pd_journal_open(&j, &ops, 0, &found, &head, &count, &boot) == 0);
	assert(found && head == 10 && count == 8 && j.seq == 3);
}

static void test_journal_torn_entry_falls_back(void)
{
	struct pd_journal j;
	bool found;
	uint8_t boot;
	uint32_t head, count;
	uint32_t newest;

	fake_reset();
	assert(pd_journal_open(&j, &ops, 0, &found, &head, &count, &boot) == 0);
	assert(pd_journal_write(&j, 1, 1, 1) == 0);
	assert(pd_journal_write(&j, 2, 2, 1) == 0);
	/* Damage the newest entry's head field, as a torn write would. */
	newest = (j.next - 1) * PD_JOURNAL_ENTRY_SIZE + 4;
	fake[newest] ^= 0x01;

	assert(pd_journal_open(&j, &ops, 0, &found, &head, &count, &boot) == 0);
	assert(found && head == 1 && count == 1);
	/* The next write must use a fresh entry, not the damaged one. */
	assert(pd_journal_write(&j, 3, 3, 1) == 0);
	assert(pd_journal_open(&j, &ops, 0, &found, &head, &count, &boot) == 0);
	assert(found && head == 3 && count == 3);
}

static void test_journal_wraps_sectors(void)
{
	struct pd_journal j;
	bool found;
	uint8_t boot;
	uint32_t head, count;
	const uint32_t writes = 3 * PD_JOURNAL_ENTRIES_PER_SECTOR + 17;

	fake_reset();
	assert(pd_journal_open(&j, &ops, 0, &found, &head, &count, &boot) == 0);
	for (uint32_t i = 0; i < writes; i++) {
		assert(pd_journal_write(&j, i % 2048, i % 2000, 1) == 0);
	}
	assert(pd_journal_open(&j, &ops, 0, &found, &head, &count, &boot) == 0);
	assert(found);
	assert(head == (writes - 1) % 2048);
	assert(count == (writes - 1) % 2000);
	assert(j.seq == writes);
}

/* Mirrors store_append(): checkpoint the tail move before the erase, then again after the append. */
static int checkpointed_append(struct pd_log *log, struct pd_journal *j,
			       const struct pd_record *rec)
{
	int rc;

	if (pd_log_needs_erase(log)) {
		pd_log_drop_for_next(log);
		rc = pd_journal_write(j, log->head, log->count, 1);
		assert(rc == 0);
	}
	rc = pd_log_append(log, rec);
	if (rc) {
		return rc;
	}
	return pd_journal_write(j, log->head, log->count, 1);
}

static void test_ring_with_journal_survives_reboot(void)
{
	/* Ring in sectors 0-1, journal in sectors 2-3. */
	const uint32_t ring_size = 2 * PD_LOG_SECTOR_SIZE;
	const uint32_t journal_base = ring_size;
	struct pd_log log, resumed;
	struct pd_journal j, jr;
	struct pd_record in, out;
	bool found;
	uint8_t boot;
	uint32_t head, count, pending, total = 2500;

	fake_reset();
	assert(pd_log_init(&log, &ops, 0, ring_size) == 0);
	assert(pd_journal_open(&j, &ops, journal_base, &found, &head, &count, &boot) == 0);
	for (uint32_t i = 0; i < total; i++) {
		in.minute = 1000 + i;
		in.counts = 0;
		in.class = PD_CLASS_WALK;
		in.crc = 0;
		assert(checkpointed_append(&log, &j, &in) == 0);
	}

	/* Reboot. */
	assert(pd_log_init(&resumed, &ops, 0, ring_size) == 0);
	assert(pd_journal_open(&jr, &ops, journal_base, &found, &head, &count, &boot) == 0);
	assert(found);
	pd_log_restore(&resumed, head, count);
	pending = pd_log_pending(&resumed);
	assert(pending == pd_log_pending(&log));
	assert(pd_log_read(&resumed, pending - 1, &out, 1) == 1);
	assert(out.minute == 1000 + total - 1);
	assert(pd_log_read(&resumed, 0, &out, 1) == 1);
	assert(out.minute == 1000 + total - pending);
}

static void test_reboot_during_erase_keeps_tail_valid(void)
{
	const uint32_t ring_size = 2 * PD_LOG_SECTOR_SIZE;
	const uint32_t journal_base = ring_size;
	struct pd_log log, resumed;
	struct pd_journal j, jr;
	struct pd_record in, out;
	bool found;
	uint8_t boot;
	uint32_t head, count, pending;
	uint32_t cap = ring_size / PD_LOG_REC_SIZE;

	fake_reset();
	assert(pd_log_init(&log, &ops, 0, ring_size) == 0);
	assert(pd_journal_open(&j, &ops, journal_base, &found, &head, &count, &boot) == 0);
	for (uint32_t i = 0; i < cap; i++) {
		in.minute = i;
		in.counts = 0;
		in.class = 0;
		in.crc = 0;
		assert(checkpointed_append(&log, &j, &in) == 0);
	}
	/* Next append erases a sector. Power fails right after the tail-move checkpoint. */
	assert(pd_log_needs_erase(&log));
	pd_log_drop_for_next(&log);
	assert(pd_journal_write(&j, log.head, log.count, 1) == 0);

	assert(pd_log_init(&resumed, &ops, 0, ring_size) == 0);
	assert(pd_journal_open(&jr, &ops, journal_base, &found, &head, &count, &boot) == 0);
	pd_log_restore(&resumed, head, count);
	pending = pd_log_pending(&resumed);
	assert(pending == cap - PD_LOG_SECTOR_SIZE / PD_LOG_REC_SIZE);
	/* Every record the resumed log reports is intact, not erased flash. */
	assert(pd_log_read(&resumed, 0, &out, 1) == 1);
	assert(out.minute == cap - pending);
	assert(pd_log_read(&resumed, pending - 1, &out, 1) == 1);
	assert(out.minute == cap - 1);
}

int main(void)
{
	test_classify();
	test_summary_minute_rollover();
	test_log_ring();
	test_log_overflow_keeps_newest();
	test_log_restore();
	test_journal_roundtrip();
	test_journal_torn_entry_falls_back();
	test_journal_wraps_sectors();
	test_ring_with_journal_survives_reboot();
	test_reboot_during_erase_keeps_tail_valid();
	printf("all core tests passed\n");
	return 0;
}
