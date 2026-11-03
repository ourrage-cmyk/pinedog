/*
 * Pinedog record store on top of a small filesystem interface.
 *
 * Records are kept in one file per day of records ("segments"), in a LittleFS
 * directory. Record index i lives in segment i / PD_SEG_RECORDS at offset
 * (i % PD_SEG_RECORDS) * 8. Indexes are absolute, counted from the first record
 * ever written, so they never restart on reboot.
 *
 * Acknowledged records are dropped by deleting whole segments that end before
 * the acknowledged index. The ack cursor lives in a small "meta" file that is
 * replaced atomically (write to a temp name, then rename). LittleFS guarantees
 * the rename, so a power cut leaves either the old or the new cursor, never a
 * torn one.
 */
#ifndef PINEDOG_PD_STORE_H
#define PINEDOG_PD_STORE_H

#include <stdint.h>

#include "pd_core.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PD_SEG_RECORDS 1440u /* one day of minutes */
#define PD_META_SIZE 16u

/*
 * Filesystem operations the store needs. Each returns >= 0 on success, < 0 on
 * error. The implementation syncs data before returning from append, replace
 * and truncate.
 */
struct pd_fs {
  void* ctx;
  /* Creates the file if missing, appends len bytes, syncs. */
  int (*append)(void* ctx, const char* path, const void* buf, uint32_t len);
  /* Reads up to len bytes at offset. Returns the number of bytes read, or < 0. */
  int (*read)(void* ctx, const char* path, uint32_t offset, void* buf, uint32_t len);
  /* Returns the file size, or -1 if the file does not exist. */
  int (*size)(void* ctx, const char* path);
  /* Shrinks the file to len bytes. */
  int (*truncate)(void* ctx, const char* path, uint32_t len);
  /* Replaces the file content atomically. */
  int (*replace)(void* ctx, const char* path, const void* buf, uint32_t len);
  int (*remove)(void* ctx, const char* path);
};

struct pd_store {
  struct pd_fs fs;
  uint32_t oldest_seg; /* first segment that may still hold unacked records */
  uint32_t acked;      /* absolute count of records acknowledged (and dropped) */
  uint32_t written;    /* absolute count of records on flash */
  uint8_t boot;        /* boot counter, mod 256 */
  uint8_t boot_unsaved; /* boot counter changed since it was last saved */
};

/*
 * Loads the cursor, finds the newest segment, repairs a torn tail, removes
 * leftovers of an interrupted ack, and bumps the boot counter.
 */
int pd_store_open(struct pd_store* s, const struct pd_fs* fs);

/* Appends n records. Advances written only for records that were stored. */
int pd_store_append(struct pd_store* s, const struct pd_record* recs, uint32_t n);

/* Reads up to max records from absolute index i. Returns how many were read (0 at end). */
int pd_store_read(struct pd_store* s, uint32_t index, struct pd_record* out, uint32_t max);

/* Marks records below upto as acknowledged and drops fully acked segments. */
int pd_store_ack(struct pd_store* s, uint32_t upto);

static inline uint32_t pd_store_pending(const struct pd_store* s) {
  return s->written - s->acked;
}

#ifdef __cplusplus
}
#endif

#endif
