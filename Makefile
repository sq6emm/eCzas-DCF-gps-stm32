# NUCLEO-H723ZG e-CzasPL receiver (direct sampling + the unchanged eCzas core from ../src/core)
#   make                        normal build, 115200 baud text output
#   make CFLAGS_EXTRA=-DAUDIO_DUMP   also streams the core's 10 kHz input (921600 baud, tools/nucleo_logger.py)
# LIB must hold CMSIS_5, cmsis_device_h7 and stm32h7xx_hal_driver (see README.md).
LIB  ?= lib
ECZAS = ../src/core
HAL   = $(LIB)/stm32h7xx_hal_driver
DEV   = $(LIB)/cmsis_device_h7
CORE  = $(LIB)/CMSIS_5/CMSIS/Core/Include
CC    = arm-none-eabi-gcc
CPU   = -mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard
CFLAGS = $(CFLAGS_EXTRA) $(CPU) -O2 -g -Wall -ffunction-sections -fdata-sections -DSTM32H723xx -DUSE_HAL_DRIVER \
         -Isrc -I$(ECZAS) -I$(HAL)/Inc -I$(DEV)/Include -I$(CORE)
LDFLAGS = $(CPU) -T STM32H723ZG.ld --specs=nano.specs --specs=nosys.specs -Wl,--gc-sections -Wl,-Map=build/rx.map -Wl,--print-memory-usage
HALSRC = hal hal_cortex hal_rcc hal_rcc_ex hal_pwr hal_pwr_ex hal_gpio hal_dma hal_dma_ex hal_adc hal_adc_ex \
         hal_uart hal_uart_ex hal_tim hal_tim_ex hal_flash hal_flash_ex
SRC = $(wildcard src/*.c) $(ECZAS)/dsp.c $(ECZAS)/frame.c $(ECZAS)/timekeeper.c $(ECZAS)/sintab.c $(DEV)/Source/Templates/system_stm32h7xx.c $(foreach m,$(HALSRC),$(HAL)/Src/stm32h7xx_$(m).c)
OBJ = $(patsubst %.c,build/%.o,$(notdir $(SRC))) build/startup.o
vpath %.c src $(ECZAS) $(HAL)/Src $(DEV)/Source/Templates
all: build/rx.bin
build/%.o: %.c | build
	$(CC) $(CFLAGS) -c $< -o $@
build/startup.o: $(DEV)/Source/Templates/gcc/startup_stm32h723xx.s | build
	$(CC) $(CPU) -c $< -o $@
build/rx.elf: $(OBJ) STM32H723ZG.ld
	$(CC) $(LDFLAGS) $(OBJ) -lm -o $@
build/rx.bin: build/rx.elf
	arm-none-eabi-objcopy -O binary $< $@
	arm-none-eabi-size $<
build:
	mkdir -p build
flash: build/rx.bin
	st-flash --reset write build/rx.bin 0x08000000
clean:
	rm -rf build
.PHONY: all flash clean
