#include "stm32h7xx_hal.h"

extern DMA_HandleTypeDef hdma_adc1;

void SysTick_Handler(void)          { HAL_IncTick(); }
void DMA1_Stream0_IRQHandler(void)  { HAL_DMA_IRQHandler(&hdma_adc1); }
void HardFault_Handler(void)        { for (;;) {} }
