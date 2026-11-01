#!/usr/bin/env bash
# Applies the Pinedog store-and-sync port to an InfiniTime checkout.
#
#   apply.sh <infinitime-dir>
#
# The checkout must be InfiniTime at the tag in UPSTREAM, unmodified. The
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
echo "Pinedog port applied to $(git -C "$target" describe --tags --always 2>/dev/null || echo "$target")"
