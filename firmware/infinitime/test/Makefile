# Host tests for the Pinedog store and core (no hardware, no InfiniTime sources).
CC ?= cc
CFLAGS ?= -std=gnu99 -Wall -Wextra -Werror -O1 -g
PD := ../pinedog

test_store: test_store.c $(PD)/pd_core.c $(PD)/pd_store.c $(PD)/pd_core.h $(PD)/pd_store.h
	$(CC) $(CFLAGS) -I$(PD) -o $@ test_store.c $(PD)/pd_core.c $(PD)/pd_store.c

run: test_store
	./test_store

clean:
	rm -f test_store

.PHONY: run clean
