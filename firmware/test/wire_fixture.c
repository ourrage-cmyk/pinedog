/*
 * Writes the bytes the watch sends over the Records characteristic for a
 * known set of records, so Home Assistant's decoder can be tested against the
 * real firmware encoder (tests/ha/test_wire_loopback.py).
 *
 * Output: records as 8-byte packed notifications, then the end marker
 * 0xEE followed by the record count (u32, little-endian).
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "minute_summary.h"

#define NOT_WORN_CLASS PD_CLASS_NOT_WORN
#define UNSYNCED 0x80
#define BOOT_SHIFT 3

static void put(FILE *f, const struct pd_record *rec)
{
	fwrite(rec, sizeof(*rec), 1, f);
}

int main(int argc, char **argv)
{
	FILE *f;
	struct pd_record recs[3];
	uint32_t count = 3;
	uint8_t end[5] = { 0xEE, 0, 0, 0, 0 };

	if (argc != 2) {
		fprintf(stderr, "usage: %s OUT\n", argv[0]);
		return 2;
	}
	memset(recs, 0, sizeof(recs));
	/* Synced walk minute, about 2023-11-14 in Unix minutes. */
	recs[0].minute = 28000000;
	recs[0].counts = 500;
	recs[0].class = PD_CLASS_WALK;
	/* Unsynced light minute from boot 5, uptime minute 10. */
	recs[1].minute = 10;
	recs[1].counts = 120;
	recs[1].class = PD_CLASS_LIGHT | UNSYNCED | (5 << BOOT_SHIFT);
	/* Charging minute: not worn. */
	recs[2].minute = 28000001;
	recs[2].counts = 0;
	recs[2].class = NOT_WORN_CLASS;
	for (int i = 0; i < 3; i++) {
		recs[i].crc = pd_record_crc(&recs[i]);
	}

	f = fopen(argv[1], "wb");
	if (!f) {
		perror("fopen");
		return 1;
	}
	for (int i = 0; i < 3; i++) {
		put(f, &recs[i]);
	}
	memcpy(&end[1], &count, sizeof(count));
	fwrite(end, sizeof(end), 1, f);
	fclose(f);
	return 0;
}
