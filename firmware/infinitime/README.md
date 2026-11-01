# InfiniTime port: store-and-sync

A port of the Pinedog logger and sync service into InfiniTime 1.16.1. The
result is a standard MCUboot DFU zip, which installs over Bluetooth on a stock
PineTime. No SWD and no bootloader changes.

| Path | What it is |
|---|---|
| `UPSTREAM` | the InfiniTime tag and commit this port is built against |
| `pinedog/` | new sources: core summary and record code, record store, BLE service |
| `glue.patch` | edits to existing InfiniTime files (CMake, main, SystemTask, FS, advertising) |
| `apply.sh` | copies `pinedog/` into an InfiniTime checkout and applies the patch |
| `test/` | host tests for the store and core: `make -C test run` |

Build: `.github/workflows/infinitime-dfu.yml` does this in CI and attaches the
DFU zip as an artifact. Locally: check out InfiniTime at the commit in
`UPSTREAM`, run `apply.sh <checkout>`, then build with the InfiniTime docker
image as its README describes.

The protocol is in `docs/SYNC_PROTOCOL.md`. Install steps are in
`docs/PHONE_INSTALL.md`.
