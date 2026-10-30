#ifndef PINEDOG_MINUTE_SUMMARY_H
#define PINEDOG_MINUTE_SUMMARY_H

#include <stdbool.h>
#include <stdint.h>

/* Activity classes stored per minute. */
enum pd_class {
	PD_CLASS_REST = 0,
	PD_CLASS_LIGHT = 1,
	PD_CLASS_WALK = 2,
	PD_CLASS_RUN = 3,
	PD_CLASS_NOT_WORN = 4, /* on the charger; excluded from totals by Home Assistant */
};

/*
 * One stored record. Packed to 8 bytes on flash. The last byte is a CRC-8
 * over the first seven, so a corrupted record is detected on read. Cadence is
 * used on the watch only, to pick the class, and is not stored.
 */
struct pd_record {
	uint32_t minute;   /* minutes since Unix epoch, or uptime if unsynced */
	uint16_t counts;   /* saturating activity count */
	uint8_t class;     /* class byte, see store.h */
	uint8_t crc;       /* CRC-8 of the other seven bytes */
} __attribute__((packed));

/* CRC-8 (poly 0x07, init 0) over the first seven bytes of a record. */
uint8_t pd_record_crc(const struct pd_record *rec);

/* Thresholds, tunable from Home Assistant via the Config characteristic. */
struct pd_config {
	uint16_t rest_max;     /* counts below this in a minute are rest */
	uint16_t walk_min;     /* counts at or above this may be walk */
	uint16_t run_min;      /* counts at or above this may be run */
	uint8_t walk_cadence_min; /* cadence*10 lower bound for walk */
	uint8_t run_cadence_min;  /* cadence*10 lower bound for run */
};

#define PD_SAMPLE_RATE_HZ 25

struct pd_summary {
	uint32_t minute;
	uint32_t counts_sum;
	uint16_t peak_mag_mg;
	uint16_t samples;
	uint16_t zero_crossings;
	uint8_t have_prev;
	int16_t prev_hp;
	int32_t hp_state;
};

void pd_summary_reset(struct pd_summary *s, uint32_t minute);

/* Accumulates one sample. Never closes a window: the caller closes it on the clock. */
void pd_summary_push(struct pd_summary *s, int32_t x_mg, int32_t y_mg, int32_t z_mg);

/*
 * Closes the current window into one record and starts the next at
 * next_minute. Always returns true; kept as bool for the call sites.
 */
bool pd_summary_flush(struct pd_summary *s, const struct pd_config *cfg,
		      uint32_t next_minute, struct pd_record *out);

/* Pure classification, exposed for tests. */
uint8_t pd_classify(uint16_t counts, uint8_t cadence,
		    const struct pd_config *cfg);

#endif
