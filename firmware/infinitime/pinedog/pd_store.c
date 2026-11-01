#include <stdio.h>
#include <string.h>

#include "pd_store.h"

#define META_PATH "/pinedog/meta"
#define META_TMP_PATH "/pinedog/meta.tmp"
#define DIR_PATH "/pinedog"
#define MAGIC 0x314d4450u /* "PDM1" little endian */
#define MAX_SCAN_SEGMENTS 4096u

static void seg_path(uint32_t seg, char* out, size_t len) {
  snprintf(out, len, "/pinedog/s%08lx", (unsigned long)seg);
}

static void meta_encode(const struct pd_store* s, uint8_t* buf) {
  uint32_t magic = MAGIC;

  memset(buf, 0, PD_META_SIZE);
  memcpy(buf + 0, &magic, 4);
  memcpy(buf + 4, &s->oldest_seg, 4);
  memcpy(buf + 8, &s->acked, 4);
  buf[12] = s->boot;
  buf[15] = 0;
  for (uint32_t i = 0; i < PD_META_SIZE - 1; i++) {
    buf[15] = (uint8_t)(buf[15] + buf[i]);
  }
}

static int meta_save(struct pd_store* s) {
  uint8_t buf[PD_META_SIZE];
  meta_encode(s, buf);
  return s->fs.replace(s->fs.ctx, META_PATH, buf, sizeof(buf)) < 0 ? -1 : 0;
}

static int meta_load(struct pd_store* s) {
  uint8_t buf[PD_META_SIZE];
  uint32_t magic;
  uint8_t sum = 0;

  if (s->fs.read(s->fs.ctx, META_PATH, 0, buf, sizeof(buf)) != (int)sizeof(buf)) {
    return -1;
  }
  for (uint32_t i = 0; i < PD_META_SIZE - 1; i++) {
    sum = (uint8_t)(sum + buf[i]);
  }
  memcpy(&magic, buf, 4);
  if (magic != MAGIC || sum != buf[15]) {
    return -1;
  }
  memcpy(&s->oldest_seg, buf + 4, 4);
  memcpy(&s->acked, buf + 8, 4);
  s->boot = buf[12];
  return 0;
}

int pd_store_open(struct pd_store* s, const struct pd_fs* fs) {
  char path[32];
  uint32_t seg;
  int size;

  s->fs = *fs;
  s->oldest_seg = 0;
  s->acked = 0;
  s->written = 0;
  s->boot = 0;
  (void)meta_load(s); /* a missing or damaged cursor starts from zero */

  /* Find the newest segment, starting from the oldest one. */
  seg_path(s->oldest_seg, path, sizeof(path));
  size = s->fs.size(s->fs.ctx, path);
  if (size < 0) {
    /* No data on flash: the next append creates the segment for the cursor. */
    s->oldest_seg = s->acked / PD_SEG_RECORDS;
    s->written = s->acked;
  } else {
    uint32_t newest = s->oldest_seg;
    for (uint32_t i = 0; i < MAX_SCAN_SEGMENTS; i++) {
      seg_path(newest + 1, path, sizeof(path));
      if (s->fs.size(s->fs.ctx, path) < 0) {
        break;
      }
      newest++;
    }
    seg_path(newest, path, sizeof(path));
    size = s->fs.size(s->fs.ctx, path);
    if ((uint32_t)size % sizeof(struct pd_record) != 0) {
      /* A power cut left a partial record. Drop it so appends stay aligned. */
      size = (int)(((uint32_t)size / sizeof(struct pd_record)) * sizeof(struct pd_record));
      if (s->fs.truncate(s->fs.ctx, path, (uint32_t)size) < 0) {
        return -1;
      }
    }
    s->written = newest * PD_SEG_RECORDS + (uint32_t)size / sizeof(struct pd_record);
  }

  if (s->acked > s->written) {
    s->acked = s->written; /* cannot acknowledge what was never stored */
  }

  /* Leftovers of an ack that was cut short: segments below the cursor. */
  for (seg = s->oldest_seg; seg-- > 0;) {
    seg_path(seg, path, sizeof(path));
    if (s->fs.size(s->fs.ctx, path) < 0) {
      break;
    }
    (void)s->fs.remove(s->fs.ctx, path);
  }

  s->boot = (uint8_t)(s->boot + 1);
  return meta_save(s);
}

int pd_store_append(struct pd_store* s, const struct pd_record* recs, uint32_t n) {
  uint32_t done = 0;

  while (done < n) {
    char path[32];
    uint32_t seg = (s->written) / PD_SEG_RECORDS;
    uint32_t in_seg = s->written % PD_SEG_RECORDS;
    uint32_t run = PD_SEG_RECORDS - in_seg;
    uint32_t left = n - done;

    if (run > left) {
      run = left;
    }
    seg_path(seg, path, sizeof(path));
    if (s->fs.append(s->fs.ctx, path, &recs[done], run * sizeof(struct pd_record)) < 0) {
      return -1;
    }
    done += run;
    s->written += run;
  }
  return 0;
}

int pd_store_read(struct pd_store* s, uint32_t index, struct pd_record* out, uint32_t max) {
  char path[32];
  uint32_t seg;
  uint32_t in_seg;
  uint32_t run;
  int got;

  if (index >= s->written || max == 0) {
    return 0;
  }
  seg = index / PD_SEG_RECORDS;
  in_seg = index % PD_SEG_RECORDS;
  run = PD_SEG_RECORDS - in_seg;
  if (run > max) {
    run = max;
  }
  if (run > s->written - index) {
    run = s->written - index;
  }
  seg_path(seg, path, sizeof(path));
  got = s->fs.read(s->fs.ctx, path, in_seg * sizeof(struct pd_record), out, run * sizeof(struct pd_record));
  if (got < 0) {
    return -1;
  }
  return got / (int)sizeof(struct pd_record);
}

int pd_store_ack(struct pd_store* s, uint32_t upto) {
  uint32_t old_oldest = s->oldest_seg;
  uint32_t new_oldest;
  char path[32];

  if (upto > s->written) {
    upto = s->written;
  }
  if (upto <= s->acked) {
    return 0;
  }
  new_oldest = upto / PD_SEG_RECORDS;

  /* Persist the cursor first. Only then delete the segments it covers. */
  s->acked = upto;
  s->oldest_seg = new_oldest;
  if (meta_save(s) < 0) {
    return -1;
  }
  for (uint32_t seg = old_oldest; seg < new_oldest; seg++) {
    seg_path(seg, path, sizeof(path));
    (void)s->fs.remove(s->fs.ctx, path);
  }
  return 0;
}
