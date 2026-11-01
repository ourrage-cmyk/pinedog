/*
 * Pinedog core: minute summary, record format and CRC.
 *
 * Ported from firmware/core/minute_summary.{h,c} (the Zephyr build). The logic
 * is the same. The InfiniTime build samples at 10 Hz, from the 100 ms motion
 * tick that stock InfiniTime already runs, and the BMA421 reports in 1024 per g
 * units, so the sample rate and gravity constants differ here.
 */
#ifndef PINEDOG_PD_CORE_H
#define PINEDOG_PD_CORE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Activity classes stored per minute (bits 0..2 of the class byte). */
enum pd_class {
  PD_CLASS_REST = 0,
  PD_CLASS_LIGHT = 1,
  PD_CLASS_WALK = 2,
  PD_CLASS_RUN = 3,
  PD_CLASS_NOT_WORN = 4, /* on the charger; Home Assistant leaves it out of totals */
};

#define PD_CLASS_MASK 0x07
#define PD_BOOT_SHIFT 3
#define PD_BOOT_MASK 0x0F
#define PD_UNSYNCED_FLAG 0x80 /* minute is uptime based: the clock was not set */

/* One stored record: 8 bytes, the last byte is CRC-8 over the first seven. */
struct pd_record {
  uint32_t minute; /* unix minutes when the clock is set, uptime minutes before */
  uint16_t counts; /* saturating activity count */
  uint8_t class_byte;
  uint8_t crc;
} __attribute__((packed));

uint8_t pd_record_crc(const struct pd_record* rec);

struct pd_config {
  uint16_t rest_max;        /* counts below this in a minute are rest */
  uint16_t walk_min;        /* counts at or above this may be walk */
  uint16_t run_min;         /* counts at or above this may be run */
  uint8_t walk_cadence_min; /* cadence * 10 lower bound for walk */
  uint8_t run_cadence_min;  /* cadence * 10 lower bound for run */
};

/* 10 Hz: the InfiniTime motion tick. Gravity in the BMA421 binary units (1024 per g). */
#define PD_SAMPLE_RATE_HZ 10
#define PD_GRAVITY_MG 1024

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

void pd_summary_reset(struct pd_summary* s, uint32_t minute);
void pd_summary_push(struct pd_summary* s, int32_t x_mg, int32_t y_mg, int32_t z_mg);
/* Closes the window into one record and starts the next at next_minute. */
bool pd_summary_flush(struct pd_summary* s, const struct pd_config* cfg, uint32_t next_minute, struct pd_record* out);
uint8_t pd_classify(uint16_t counts, uint8_t cadence, const struct pd_config* cfg);

#ifdef __cplusplus
}
#endif

#endif
