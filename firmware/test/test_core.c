#include <assert.h>
#include <stdio.h>
#include <string.h>

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
		in.cadence = 0;
		assert(pd_log_append(&log, &in) == 0);
	}
	assert(pd_log_pending(&log) == 5);
	assert(pd_log_read(&log, 1, out, 4) == 4);
	assert(out[0].minute == 101 && out[3].minute == 104);

	pd_log_ack_upto(&log, 102);
	assert(pd_log_pending(&log) == 2);
	assert(pd_log_read(&log, 0, out, 4) == 2);
	assert(out[0].minute == 103);
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
		in.cadence = 0;
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
		in.cadence = 0;
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

int main(void)
{
	test_classify();
	test_summary_minute_rollover();
	test_log_ring();
	test_log_overflow_keeps_newest();
	test_log_restore();
	printf("all core tests passed\n");
	return 0;
}
