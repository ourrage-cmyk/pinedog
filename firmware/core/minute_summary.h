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
};

/* One stored record. Packed to 8 bytes on flash. */
struct pd_record {
	uint32_t minute;   /* minutes since Unix epoch */
	uint16_t counts;   /* saturating activity count */
	uint8_t class;     /* enum pd_class */
	uint8_t cadence;   /* steps per second * 10, 0 if not rhythmic */
} __attribute__((packed));

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

/*
 * Feed one accelerometer sample in milli-g (x, y, z).
 * Returns the completed record when the minute rolls over, otherwise false.
 */
bool pd_summary_push(struct pd_summary *s, int32_t x_mg, int32_t y_mg,
		     int32_t z_mg, const struct pd_config *cfg,
		     struct pd_record *out);

/* Pure classification, exposed for tests. */
uint8_t pd_classify(uint16_t counts, uint8_t cadence,
		    const struct pd_config *cfg);

#endif
