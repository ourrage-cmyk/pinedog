#include <stdlib.h>
#include <string.h>

#include "minute_summary.h"

#define SECONDS_PER_MINUTE 60
#define MINUTE_SAMPLES (PD_SAMPLE_RATE_HZ * SECONDS_PER_MINUTE)

/* Integer vector magnitude in mg. Good enough for activity counting. */
static uint32_t magnitude_mg(int32_t x, int32_t y, int32_t z)
{
	uint64_t sq = (uint64_t)((int64_t)x * x) + (uint64_t)((int64_t)y * y) +
		      (uint64_t)((int64_t)z * z);
	uint32_t r = 0;
	uint64_t bit = (uint64_t)1 << 30;

	/* integer square root */
	while (bit > sq) {
		bit >>= 2;
	}
	while (bit != 0) {
		if (sq >= r + bit) {
			sq -= r + bit;
			r = (r >> 1) + bit;
		} else {
			r >>= 1;
		}
		bit >>= 2;
	}
	return r;
}

void pd_summary_reset(struct pd_summary *s, uint32_t minute)
{
	memset(s, 0, sizeof(*s));
	s->minute = minute;
}

bool pd_summary_push(struct pd_summary *s, int32_t x_mg, int32_t y_mg,
		     int32_t z_mg, const struct pd_config *cfg,
		     struct pd_record *out)
{
	uint32_t mag = magnitude_mg(x_mg, y_mg, z_mg);
	int32_t dyn = (int32_t)mag - 1000; /* remove gravity */
	int32_t hp;
	bool done = false;

	if (dyn < 0) {
		dyn = -dyn;
	}
	s->counts_sum += (uint32_t)dyn;
	if (mag > s->peak_mag_mg) {
		s->peak_mag_mg = (uint16_t)(mag > 65535 ? 65535 : mag);
	}

	/* Crude high-pass: remove slow drift so zero crossings track motion. */
	s->hp_state += ((int32_t)mag - 1000 - s->hp_state) / 16;
	hp = (int32_t)mag - 1000 - s->hp_state;
	if (hp > 2000) {
		hp = 2000;
	} else if (hp < -2000) {
		hp = -2000;
	}
	if (s->have_prev && ((hp >= 0) != (s->prev_hp >= 0))) {
		s->zero_crossings++;
	}
	s->prev_hp = (int16_t)hp;
	s->have_prev = 1;
	s->samples++;

	if (s->samples >= MINUTE_SAMPLES) {
		uint32_t counts = s->counts_sum / 1000; /* scaled to fit uint16 */
		/* Each zero crossing pair is one cycle; crossings/2 cycles in 60 s. */
		uint32_t cycles_per_s_x10 = (uint32_t)s->zero_crossings * 10 / 2 / 60;

		out->minute = s->minute;
		out->counts = (uint16_t)(counts > 65535 ? 65535 : counts);
		out->class = pd_classify(out->counts,
					 (uint8_t)(cycles_per_s_x10 > 255 ? 255 : cycles_per_s_x10),
					 cfg);
		out->crc = 0;
		done = true;
		pd_summary_reset(s, s->minute + 1);
	}
	return done;
}

uint8_t pd_classify(uint16_t counts, uint8_t cadence,
		    const struct pd_config *cfg)
{
	if (counts < cfg->rest_max) {
		return PD_CLASS_REST;
	}
	if (counts >= cfg->run_min && cadence >= cfg->run_cadence_min) {
		return PD_CLASS_RUN;
	}
	if (counts >= cfg->walk_min && cadence >= cfg->walk_cadence_min) {
		return PD_CLASS_WALK;
	}
	return PD_CLASS_LIGHT;
}

uint8_t pd_record_crc(const struct pd_record *rec)
{
	const uint8_t *p = (const uint8_t *)rec;
	uint8_t crc = 0;

	for (int i = 0; i < 7; i++) {
		crc ^= p[i];
		for (int b = 0; b < 8; b++) {
			crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
		}
	}
	return crc;
}
