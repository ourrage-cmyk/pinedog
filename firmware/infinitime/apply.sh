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
   "$here"/pinedog/PinedogName.h \
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

# Give the MAIN task more stack. Pinedog's Tick runs inside MAIN, and stock MAIN has only
# 25 words free on the watch (the System Info "MAI" row). Our LittleFS calls push it past
# that, so it overflows and the watchdog resets the watch. 350 -> 500 words (+600 bytes of heap).
systemtask="$target/src/systemtask/SystemTask.cpp"
grep -q 'xTaskCreate(SystemTask::Process, "MAIN", 350, this, 1, &taskHandle)' "$systemtask" \
  || { echo "unexpected MAIN task creation in $systemtask" >&2; exit 1; }
sed -i 's/xTaskCreate(SystemTask::Process, "MAIN", 350, this, 1, &taskHandle)/xTaskCreate(SystemTask::Process, "MAIN", 500, this, 1, \&taskHandle)/' "$systemtask"

# Slim the image. Only the user apps and watch faces listed here are compiled in; the core
# screens (Settings, System Info, Firmware update) are not in these lists and stay. Set as
# normal variables at the top of the apps CMakeLists, which the upstream if(DEFINED) reads.
apps_cm="$target/src/displayapp/apps/CMakeLists.txt"
grep -q '^if(DEFINED ENABLE_USERAPPS)' "$apps_cm" \
  || { echo "unexpected apps CMakeLists in $apps_cm" >&2; exit 1; }
{
  printf '%s\n' 'set(ENABLE_USERAPPS "Apps::Steps, Apps::Timer, Apps::Alarm, Apps::StopWatch")'
  printf '%s\n' 'set(ENABLE_WATCHFACES "WatchFace::Digital")'
  cat "$apps_cm"
} > "$apps_cm.tmp" && mv "$apps_cm.tmp" "$apps_cm"

# Give this build a distinct Device Information firmware revision, so a flashed Pinedog
# image can be told from stock 1.14.1 over BLE. PINEDOG_REV (the commit) sets the suffix.
rev="${PINEDOG_REV:-dev}"; rev="${rev:0:7}"
dis="$target/src/components/ble/DeviceInformationService.h"
grep -q 'static constexpr const char\* fwRevision = Version::VersionString();' "$dis" \
  || { echo "unexpected fwRevision in $dis" >&2; exit 1; }
sed -i "s|static constexpr const char\* fwRevision = Version::VersionString();|static constexpr const char* fwRevision = \"1.14.1-pd-$rev\";|" "$dis"

# Show the dog name on the System Info screen, so the two watches can be told apart.
# One label, added after the screen is created. Assert each anchor matches exactly once.
python3 - "$target" <<'PY'
import sys
path = sys.argv[1] + "/src/displayapp/screens/SystemInfo.cpp"
s = open(path).read()
import re
pat = re.compile(r"SystemInfo::CreateScreen1\(\)\s*\{\n")
found = pat.findall(s)
assert len(found) == 1, "SystemInfo::CreateScreen1 not found once: %d" % len(found)
s = pat.sub(lambda m: m.group(0) + """  {
    // Pinedog: the dog name, so two watches can be told apart.
    lv_obj_t* dogLabel = lv_label_create(lv_scr_act(), nullptr);
    lv_label_set_text_fmt(dogLabel, "Dog: %s (boot step %u)", Pinetime::Pinedog::DogName(), static_cast<unsigned>(Pinetime::Pinedog::LastBootStep()));
    lv_obj_align(dogLabel, lv_scr_act(), LV_ALIGN_IN_TOP_LEFT, 0, 0);
  }
""", s, count=1)
s = '#include "components/pinedog/PinedogName.h"\n' + s
open(path, "w").write(s)
PY

echo "Pinedog port applied to $(git -C "$target" describe --tags --always 2>/dev/null || echo "$target")"
