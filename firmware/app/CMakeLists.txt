cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(pinedog)

target_sources(app PRIVATE
  src/main.c
  src/store.c
  src/ble_sync.c
  src/clock.c
  ../core/minute_summary.c
  ../core/ring_log.c
  ../core/journal.c
)
target_include_directories(app PRIVATE ../core)
