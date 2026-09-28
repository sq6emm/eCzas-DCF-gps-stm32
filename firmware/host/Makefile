# Host tests of the coherent receiver (firmware/common) with the eCzas core from the submodule.
CORE   = ../../eczas/Firmware/src/core
COMMON = ../common
CFLAGS ?= -O2 -g -Wall -Wextra -Wno-unused-parameter -I$(COMMON) -I$(CORE)
SRC    = $(COMMON)/coh.c $(COMMON)/ecz.c $(CORE)/frame.c $(CORE)/timekeeper.c
cohsim: cohsim.c $(SRC) $(wildcard $(COMMON)/*.h)
	$(CC) $(CFLAGS) -o $@ cohsim.c $(SRC) -lm
all: cohsim dcfsim dcfminsim
clean:
	rm -f cohsim dcfsim dcfminsim
dcfsim: dcfsim.c $(COMMON)/coh.c $(COMMON)/dcf.c $(wildcard $(COMMON)/*.h)
	$(CC) $(CFLAGS) -o $@ dcfsim.c $(COMMON)/coh.c $(COMMON)/dcf.c -lm
dcfminsim: dcfminsim.c $(COMMON)/coh.c $(COMMON)/dcf.c $(COMMON)/dcfbits.c $(wildcard $(COMMON)/*.h)
	$(CC) $(CFLAGS) -o $@ dcfminsim.c $(COMMON)/coh.c $(COMMON)/dcf.c $(COMMON)/dcfbits.c -lm
