#!/usr/bin/env bash
# Applies the Pinedog store-and-sync port to an InfiniTime checkout.
#
#   apply.sh <infinitime-dir>
#
# The checkout must be InfiniTime at the commit in UPSTREAM, unmodified. The
# script copies the Pinedog sources into src/components/pinedog and applies
# glue.patch, which only touches the handful of existing files that need a hook.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="${1:?usage: apply.sh <infinitime-dir>}"

mkdir -p "$target/src/components/pinedog"
cp "$here"/pinedog/pd_core.c "$here"/pinedog/pd_core.h \
   "$here"/pinedog/pd_store.c "$here"/pinedog/pd_store.h \
   "$here"/pinedog/PinedogService.cpp "$here"/pinedog/PinedogService.h \
   "$target/src/components/pinedog/"

git -C "$target" apply --check "$here/glue.patch"
git -C "$target" apply "$here/glue.patch"

# Trim the FreeRTOS heap by 2 KB. The main app overflows the 64 KB RAM region
# by about 0.4 KB on the image's toolchain; the stock tree overflows too, so this
# is the RAM every 1.14.1 build on this image needs. Fail loudly if upstream's
# line is not the one we expect, so the trim can never silently not apply.
heap="$target/src/FreeRTOSConfig.h"
grep -q '^#define configTOTAL_HEAP_SIZE[[:space:]]*(1024 \* 40)$' "$heap" \
  || { echo "unexpected configTOTAL_HEAP_SIZE in $heap" >&2; exit 1; }
sed -i 's/^\(#define configTOTAL_HEAP_SIZE[[:space:]]*\)(1024 \* 40)$/\1(1024 * 38)/' "$heap"

echo "Pinedog port applied to $(git -C "$target" describe --tags --always 2>/dev/null || echo "$target")"
