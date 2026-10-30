# Host-side tests for the platform-independent firmware core.
# The Zephyr application build is added separately once the toolchain is set up.

CC ?= gcc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -g -Icore

test: build/test_core
	./build/test_core

build/test_core: test/test_core.c core/minute_summary.c core/ring_log.c core/journal.c
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ $^

# Bytes the watch sends for a known set of records, read by the Home Assistant loopback test.
fixture: build/wire_fixture
	./build/wire_fixture ../tests/ha/fixtures/wire_v2.bin

build/wire_fixture: test/wire_fixture.c core/minute_summary.c
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ $^

clean:
	rm -rf build

.PHONY: test clean fixture
