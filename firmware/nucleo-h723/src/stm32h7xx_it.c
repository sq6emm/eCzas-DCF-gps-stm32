#include "stm32h7xx_hal.h"

extern DMA_HandleTypeDef hdma_adc1;

void SysTick_Handler(void)          { HAL_IncTick(); }
void DMA1_Stream0_IRQHandler(void)  { HAL_DMA_IRQHandler(&hdma_adc1); }

/* a fault: note which and where (the stacked PC), then reset - running 24/7, a restart beats a silent
   hang; main reports the record at the next start */
uint32_t fault_rec[3] __attribute__((section(".noinit")));     /* FAULT_MAGIC, which (1..5), PC */
void fault_entry(const uint32_t *sp, uint32_t which)
{
    fault_rec[0] = 0xFA017ED0; fault_rec[1] = which; fault_rec[2] = sp[6];
    __DSB();
    NVIC_SystemReset();
}
#define FAULT_HANDLER(name, n) __attribute__((naked)) void name(void) \
    { __asm volatile("tst lr, #4\n ite eq\n mrseq r0, msp\n mrsne r0, psp\n movs r1, %0\n b fault_entry" :: "i"(n)); }
FAULT_HANDLER(HardFault_Handler, 1)
FAULT_HANDLER(MemManage_Handler, 2)
FAULT_HANDLER(BusFault_Handler, 3)
FAULT_HANDLER(UsageFault_Handler, 4)
FAULT_HANDLER(NMI_Handler, 5)
