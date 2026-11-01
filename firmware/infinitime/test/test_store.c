/*
 * Host tests for the Pinedog store and core. Build and run with:
 *   make -C firmware/infinitime/test
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pd_core.h"
#include "pd_store.h"

/* ---- RAM filesystem with the same semantics as the store expects ---- */

#define MAX_FILES 128
#define MAX_FILE_BYTES (8u * 1024u * 1024u)

struct ram_file {
  int used;
  char name[32];
  uint8_t* data;
  uint32_t len;
};

static struct ram_file files[MAX_FILES];
static int fail_next_append = 0;

static struct ram_file* find(const char* path) {
  for (int i = 0; i < MAX_FILES; i++) {
    if (files[i].used && strcmp(files[i].name, path) == 0) {
      return &files[i];
    }
  }
  return NULL;
}

static struct ram_file* create(const char* path) {
  for (int i = 0; i < MAX_FILES; i++) {
    if (!files[i].used) {
      files[i].used = 1;
      snprintf(files[i].name, sizeof(files[i].name), "%s", path);
      files[i].data = calloc(1, MAX_FILE_BYTES);
      files[i].len = 0;
      return &files[i];
    }
  }
  return NULL;
}

static int r_append(void* ctx, const char* path, const void* buf, uint32_t len) {
  struct ram_file* f;
  (void)ctx;
  if (fail_next_append) {
    fail_next_append = 0;
    return -1;
  }
  f = find(path);
  if (!f) {
    f = create(path);
  }
  if (!f || f->len + len > MAX_FILE_BYTES) {
    return -1;
  }
  memcpy(f->data + f->len, buf, len);
  f->len += len;
  return 0;
}

static int r_read(void* ctx, const char* path, uint32_t off, void* buf, uint32_t len) {
  struct ram_file* f;
  uint32_t n;
  (void)ctx;
  f = find(path);
  if (!f) {
    return -1;
  }
  if (off >= f->len) {
    return 0;
  }
  n = f->len - off;
  if (n > len) {
    n = len;
  }
  memcpy(buf, f->data + off, n);
  return (int)n;
}

static int r_size(void* ctx, const char* path) {
  struct ram_file* f;
  (void)ctx;
  f = find(path);
  return f ? (int)f->len : -1;
}

static int r_truncate(void* ctx, const char* path, uint32_t len) {
  struct ram_file* f;
  (void)ctx;
  f = find(path);
  if (!f || len > f->len) {
    return -1;
  }
  f->len = len;
  return 0;
}

static int r_replace(void* ctx, const char* path, const void* buf, uint32_t len) {
  struct ram_file* f;
  (void)ctx;
  f = find(path);
  if (!f) {
    f = create(path);
  }
  if (!f) {
    return -1;
  }
  memcpy(f->data, buf, len);
  f->len = len;
  return 0;
}

static int r_remove(void* ctx, const char* path) {
  struct ram_file* f;
  (void)ctx;
  f = find(path);
  if (!f) {
    return -1;
  }
  free(f->data);
  f->used = 0;
  return 0;
}

static const struct pd_fs ram_fs = {
  .ctx = NULL,
  .append = r_append,
  .read = r_read,
  .size = r_size,
  .truncate = r_truncate,
  .replace = r_replace,
  .remove = r_remove,
};

static void ram_reset(void) {
  for (int i = 0; i < MAX_FILES; i++) {
    if (files[i].used) {
      free(files[i].data);
    }
    files[i].used = 0;
  }
}

static int seg_count(void) {
  int n = 0;
  for (int i = 0; i < MAX_FILES; i++) {
    if (files[i].used && strncmp(files[i].name, "/pinedog/s", 10) == 0) {
      n++;
    }
  }
  return n;
}

/* ---- helpers ---- */

static int failures = 0;
#define CHECK(cond)                                                       \
  do {                                                                    \
    if (!(cond)) {                                                        \
      printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);              \
      failures++;                                                         \
    }                                                                     \
  } while (0)

static void make_record(struct pd_record* r, uint32_t i) {
  r->minute = 1000000u + i;
  r->counts = (uint16_t)(i * 3);
  r->class_byte = (uint8_t)(i % 5);
  r->crc = pd_record_crc(r);
}

static void append_range(struct pd_store* s, uint32_t from, uint32_t to) {
  struct pd_record batch[5];
  uint32_t n = 0;
  for (uint32_t i = from; i < to; i++) {
    make_record(&batch[n++], i);
    if (n == 5) {
      CHECK(pd_store_append(s, batch, n) == 0);
      n = 0;
    }
  }
  if (n) {
    CHECK(pd_store_append(s, batch, n) == 0);
  }
}

static void check_range(struct pd_store* s, uint32_t from, uint32_t to) {
  struct pd_record r;
  struct pd_record want;
  for (uint32_t i = from; i < to; i++) {
    CHECK(pd_store_read(s, i, &r, 1) == 1);
    make_record(&want, i);
    CHECK(memcmp(&r, &want, sizeof(r)) == 0);
  }
}

/* ---- tests ---- */

static void test_append_read_across_days(void) {
  struct pd_store s;
  ram_reset();
  CHECK(pd_store_open(&s, &ram_fs) == 0);
  append_range(&s, 0, 3000); /* spans three segments */
  CHECK(s.written == 3000);
  CHECK(pd_store_pending(&s) == 3000);
  check_range(&s, 0, 3000);
  CHECK(seg_count() == 3);
  printf("ok append_read_across_days\n");
}

static void test_reopen_keeps_records_and_boot_count(void) {
  struct pd_store s;
  ram_reset();
  CHECK(pd_store_open(&s, &ram_fs) == 0);
  append_range(&s, 0, 2000);
  uint8_t boot_before = s.boot;

  CHECK(pd_store_open(&s, &ram_fs) == 0);
  CHECK(s.written == 2000);
  CHECK(s.acked == 0);
  CHECK(s.boot == (uint8_t)(boot_before + 1));
  check_range(&s, 0, 2000);
  printf("ok reopen_keeps_records_and_boot_count\n");
}

static void test_ack_drops_segments_and_is_idempotent(void) {
  struct pd_store s;
  ram_reset();
  CHECK(pd_store_open(&s, &ram_fs) == 0);
  append_range(&s, 0, 3000);

  CHECK(pd_store_ack(&s, 1500) == 0);
  CHECK(s.acked == 1500);
  CHECK(seg_count() == 2); /* segment 0 is fully acked and gone */
  check_range(&s, 1500, 3000);

  /* Repeating the same ack changes nothing. */
  CHECK(pd_store_ack(&s, 1500) == 0);
  CHECK(s.acked == 1500);

  /* Ack past the end is clamped to what was stored. */
  CHECK(pd_store_ack(&s, 999999) == 0);
  CHECK(s.acked == 3000);
  CHECK(pd_store_pending(&s) == 0);

  /* Reopen after a full ack: nothing pending, and new records append cleanly. */
  CHECK(pd_store_open(&s, &ram_fs) == 0);
  CHECK(s.written == 3000);
  CHECK(pd_store_pending(&s) == 0);
  append_range(&s, 3000, 3010);
  CHECK(pd_store_pending(&s) == 10);
  check_range(&s, 3000, 3010);
  printf("ok ack_drops_segments_and_is_idempotent\n");
}

static void test_ack_exact_day_boundary(void) {
  struct pd_store s;
  ram_reset();
  CHECK(pd_store_open(&s, &ram_fs) == 0);
  append_range(&s, 0, PD_SEG_RECORDS); /* exactly one full segment */
  CHECK(pd_store_ack(&s, PD_SEG_RECORDS) == 0);
  CHECK(seg_count() == 0);
  CHECK(pd_store_open(&s, &ram_fs) == 0);
  CHECK(s.written == PD_SEG_RECORDS);
  CHECK(pd_store_pending(&s) == 0);
  append_range(&s, PD_SEG_RECORDS, PD_SEG_RECORDS + 4);
  check_range(&s, PD_SEG_RECORDS, PD_SEG_RECORDS + 4);
  printf("ok ack_exact_day_boundary\n");
}

static void test_torn_tail_is_dropped(void) {
  struct pd_store s;
  ram_reset();
  CHECK(pd_store_open(&s, &ram_fs) == 0);
  append_range(&s, 0, 100);
  /* Simulate a power cut halfway through a record. */
  struct ram_file* f = find("/pinedog/s00000000");
  CHECK(f != NULL);
  f->len += 3;

  CHECK(pd_store_open(&s, &ram_fs) == 0);
  CHECK(s.written == 100);
  append_range(&s, 100, 105);
  check_range(&s, 0, 105);
  printf("ok torn_tail_is_dropped\n");
}

static void test_failed_append_does_not_advance(void) {
  struct pd_store s;
  struct pd_record r;
  ram_reset();
  CHECK(pd_store_open(&s, &ram_fs) == 0);
  append_range(&s, 0, 10);
  make_record(&r, 10);
  fail_next_append = 1;
  CHECK(pd_store_append(&s, &r, 1) < 0);
  CHECK(s.written == 10);
  append_range(&s, 10, 12);
  check_range(&s, 0, 12);
  printf("ok failed_append_does_not_advance\n");
}

static void test_damaged_meta_starts_from_zero(void) {
  struct pd_store s;
  struct pd_record r;
  uint8_t junk[16] = {0};
  ram_reset();
  CHECK(pd_store_open(&s, &ram_fs) == 0);
  append_range(&s, 0, 20);
  CHECK(pd_store_ack(&s, 10) == 0);
  /* Corrupt the cursor. The store must not trust it. */
  memset(junk, 0xAA, sizeof(junk));
  CHECK(ram_fs.replace(NULL, "/pinedog/meta", junk, sizeof(junk)) == 0);
  CHECK(pd_store_open(&s, &ram_fs) == 0);
  CHECK(s.acked == 0); /* records come back as pending: a resend, never a loss */
  CHECK(s.written == 20);
  (void)r;
  printf("ok damaged_meta_starts_from_zero\n");
}

static void test_classify_and_crc(void) {
  struct pd_config cfg = {.rest_max = 50, .walk_min = 300, .run_min = 1200, .walk_cadence_min = 15, .run_cadence_min = 30};
  CHECK(pd_classify(10, 40, &cfg) == PD_CLASS_REST);
  CHECK(pd_classify(100, 40, &cfg) == PD_CLASS_LIGHT);
  CHECK(pd_classify(400, 20, &cfg) == PD_CLASS_WALK);
  CHECK(pd_classify(1500, 35, &cfg) == PD_CLASS_RUN);
  struct pd_record r = {.minute = 1, .counts = 2, .class_byte = 3, .crc = 0};
  uint8_t c = pd_record_crc(&r);
  r.crc = c;
  CHECK(pd_record_crc(&r) == c);
  printf("ok classify_and_crc\n");
}

static void test_summary_scales_sparse_window(void) {
  struct pd_summary s;
  struct pd_record out;
  struct pd_config cfg = {.rest_max = 50, .walk_min = 300, .run_min = 1200, .walk_cadence_min = 15, .run_cadence_min = 30};
  pd_summary_reset(&s, 42);
  /* 30 samples of 100 mg of motion, out of a 600-sample minute: must not read as rest. */
  for (int i = 0; i < 30; i++) {
    pd_summary_push(&s, 1024 + 100, 0, 0);
  }
  pd_summary_flush(&s, &cfg, 43, &out);
  CHECK(out.minute == 42);
  CHECK(out.counts > 0);
  CHECK((out.class_byte & PD_CLASS_MASK) != PD_CLASS_REST);
  printf("ok summary_scales_sparse_window\n");
}

int main(void) {
  test_append_read_across_days();
  test_reopen_keeps_records_and_boot_count();
  test_ack_drops_segments_and_is_idempotent();
  test_ack_exact_day_boundary();
  test_torn_tail_is_dropped();
  test_failed_append_does_not_advance();
  test_damaged_meta_starts_from_zero();
  test_classify_and_crc();
  test_summary_scales_sparse_window();
  ram_reset();
  if (failures) {
    printf("%d failure(s)\n", failures);
    return 1;
  }
  printf("all store and core tests passed\n");
  return 0;
}
