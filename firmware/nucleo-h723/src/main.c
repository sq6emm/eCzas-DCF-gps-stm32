/*
 * e-CzasPL 225 kHz receiver on the NUCLEO-H723ZG (M2): direct sampling.
 *
 *   A0 (PA3) --ADC1 16 bit, 1 Msps (TIM6)--> DMA --> mixer at ~225 kHz (e-CzasPL)
 *   A1 (PC0) --ADC2, same instants (dual regular simultaneous)--> mixer at 77.5 kHz (DCF77);
 *   build with -DDCF_ON_A0 to take DCF77 from A0 as before
 *   --> sum of 100 samples = 10 kHz complex --> shifted to a 1 kHz tone
 *   --> the eCzas firmware core, unchanged (dsp.c, frame.c, timekeeper.c)
 *
 * Clock: the board has no HSE crystal (the ST-LINK MCO wanders +-700 ppm), so
 * the CPU runs on HSI (~+6500 ppm, wandering ~100 ppm) and the 32.768 kHz LSE
 * crystal (X2) is the reference: TIM16 captures every 8th LSE edge. Every ADC
 * sample is 200 timer ticks, so the TRUE time of any sample follows by
 * interpolation between captures. The mixer phase is set to -2 pi F t_true at
 * every 5 ms block (phase-locked, so clock wander cannot turn into carrier
 * phase noise), and the decimator sums exactly 100 us of true time per output.
 * An outer loop keeps the carrier at 1 kHz for the core (its own loop only
 * follows +-40 Hz); an FFT search over +-450 Hz finds the carrier at start
 * and after 30 s without lock.
 *
 * Input circuit: doc/nucleo_225_77kHz_input.pdf (two tuned rods: 225 kHz on A0,
 * 77.5 kHz on A1, one shared decoupled 1.65 V bias node).
 * Output: ST-LINK virtual COM port (USART3), 115200 8N1; with -DAUDIO_DUMP
 * 921600 baud plus binary packets of the core's 10 kHz input.
 */
#include "stm32h7xx_hal.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "coh.h"
#include "ecz.h"
#include "dcf.h"
#include "dcfbits.h"
#include "efc.h"
#include "spec.h"
#ifndef EFC_DCF_CN0_MIN
#define EFC_DCF_CN0_MIN 0.0f        /* DCF77 steers the OCXO only in minutes with at least this C/N0 [dB-Hz] */
#endif
#include "frame.h"
#include "timekeeper.h"

#ifndef USE_MCO
#define USE_HSI                           /* ST-LINK MCO wanders +-700 ppm; HSI is steadier */
#endif

#define FS_NOM_HZ    1000000.0
#ifndef FS_GUESS_HZ
#define FS_GUESS_HZ  1009590.0            /* measured from the carrier on 27 Sep 2026 */
#endif
#define BLOCK        5000                 /* ADC samples per DMA half: 5 ms */
#define DECIM        100                  /* 1 Msps -> 10 kHz */
#define F_CARRIER    225000.0

/* DMA ring of 32-bit words: ADC1 (A0) in bits 15:0, ADC2 (A1) in bits 31:16 (dual mode, DAMDF = 10).
   6 blocks = 30 ms of slack (the 10-min DCF77 evaluation takes ~16 ms); 120 KB as the old 16-bit ring */
#define RING_BLK 6
static uint32_t adc_buf[RING_BLK * BLOCK] __attribute__((aligned(32)));
static volatile uint32_t dma_wraps;
static volatile uint32_t overruns, dma_halves;
static float adc_mean1, adc_mean2;          /* ADC1 (A0) and ADC2 (A1) means, for STATUS */
static uint32_t adc_min1 = 65535, adc_max1, adc_min2 = 65535, adc_max2;   /* per STATUS period */
static uint32_t max_lag, pl_bad, max_blk_cyc; static uint64_t busy_cyc;

ADC_HandleTypeDef hadc1, hadc2;
DMA_HandleTypeDef hdma_adc1;
TIM_HandleTypeDef htim6;
UART_HandleTypeDef huart3;
#ifdef AUDIO_DUMP                       /* stream the core's 10 kHz input as binary packets */
#define RX_UART_BAUD 921600
#else
#define RX_UART_BAUD 115200
#endif

static tk_t tk;
static frame_info_t last_fi;
static int have_last_fi;
static uint32_t n_heard, n_decoded, n_conf, n_rej;

/* ---------------------------------------------------------------- output */
/* interrupt-driven TX ring, so printing never stalls the signal path */
#define TXR 16384
static uint8_t txr[TXR];
static volatile uint32_t tx_head, tx_tail, tx_drops;
static void uart_write(const void *d, uint32_t n)
{
    const uint8_t *p = d;
    if (TXR - 1 - (tx_head - tx_tail) < n) { tx_drops++; return; }   /* all or nothing */
    for (uint32_t i = 0; i < n; i++) txr[(tx_head + i) % TXR] = p[i];
    __DMB(); tx_head += n;
    USART3->CR1 |= USART_CR1_TXEIE_TXFNFIE;
}
void USART3_IRQHandler(void)
{
    while ((USART3->ISR & USART_ISR_TXE_TXFNF) && tx_tail != tx_head) { USART3->TDR = txr[tx_tail % TXR]; tx_tail++; }
    if (tx_tail == tx_head) USART3->CR1 &= ~USART_CR1_TXEIE_TXFNFIE;
}
static void uart_puts(const char *s) { uart_write(s, strlen(s)); }
static const char *f1(char *b, double v, int plus)
{
    long t = lround(v * 10);
    sprintf(b, "%s%ld.%ld", t < 0 ? "-" : (plus ? "+" : ""), labs(t) / 10, labs(t) % 10);
    return b;
}
static const char *f3(char *b, double v)     /* 3 decimals (the printf here has no %f) */
{
    long long t = llround(v * 1000);
    unsigned long long a = t < 0 ? (unsigned long long)-t : (unsigned long long)t;
    sprintf(b, "%s%lu.%03lu", t < 0 ? "-" : "+", (unsigned long)(a / 1000), (unsigned long)(a % 1000));
    return b;
}
static uint64_t n2k;                      /* 2 kHz samples since start: the common time base */
static void put_line(const char *tag, const char *msg)
{
    char b[480];
    unsigned long s10 = (unsigned long)(n2k / 200);
    snprintf(b, sizeof b, "[%7lu.%lu] %-7s %s\r\n", s10 / 10, s10 % 10, tag, msg);
    uart_puts(b);
}
static void date_str(char *b, uint32_t sec, int8_t tz)
{
    tk_date_t d;
    tk_to_date(sec, &d);
    sprintf(b, "%04u-%02u-%02u %02u:%02u:%02u UTC", d.year, d.mon, d.day, d.hour, d.min, d.sec);
    (void)tz;
}

/* ---------------------------------------------------------------- hardware (as the probe) */
static void clock_init(void)
{
    RCC_OscInitTypeDef o = {0};
    RCC_ClkInitTypeDef c = {0};
    HAL_PWREx_ConfigSupply(PWR_LDO_SUPPLY);
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);
    while (!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) {}
#ifdef USE_HSI
    o.OscillatorType = RCC_OSCILLATORTYPE_NONE;      /* skip HSE: fall through to HSI below */
    if (1) goto use_hsi;
#endif
    o.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    o.HSEState = RCC_HSE_BYPASS;
    o.PLL.PLLState = RCC_PLL_ON;
    o.PLL.PLLSource = RCC_PLLSOURCE_HSE;
    o.PLL.PLLM = 1; o.PLL.PLLN = 100; o.PLL.PLLP = 2; o.PLL.PLLQ = 4; o.PLL.PLLR = 2;
    o.PLL.PLLRGE = RCC_PLL1VCIRANGE_3; o.PLL.PLLVCOSEL = RCC_PLL1VCOWIDE; o.PLL.PLLFRACN = 0;
    if (HAL_RCC_OscConfig(&o) != HAL_OK) {
#ifdef USE_HSI
    use_hsi:
#endif
        o.OscillatorType = RCC_OSCILLATORTYPE_HSI;
        o.HSIState = RCC_HSI_DIV1; o.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
        o.PLL.PLLState = RCC_PLL_ON; o.PLL.PLLSource = RCC_PLLSOURCE_HSI;
        o.PLL.PLLM = 4; o.PLL.PLLN = 50; o.PLL.PLLP = 2; o.PLL.PLLQ = 4; o.PLL.PLLR = 2;   /* 16 MHz -> 800 -> 400 */
        o.PLL.PLLRGE = RCC_PLL1VCIRANGE_3; o.PLL.PLLVCOSEL = RCC_PLL1VCOWIDE; o.PLL.PLLFRACN = 0;
        HAL_RCC_OscConfig(&o);
    }
    c.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2 |
                  RCC_CLOCKTYPE_D3PCLK1 | RCC_CLOCKTYPE_D1PCLK1;
    c.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK; c.SYSCLKDivider = RCC_SYSCLK_DIV1;
    c.AHBCLKDivider = RCC_HCLK_DIV2;
    c.APB3CLKDivider = RCC_APB3_DIV2; c.APB1CLKDivider = RCC_APB1_DIV2;
    c.APB2CLKDivider = RCC_APB2_DIV2; c.APB4CLKDivider = RCC_APB4_DIV2;
    HAL_RCC_ClockConfig(&c, FLASH_LATENCY_2);
    RCC_PeriphCLKInitTypeDef p = {0};
    p.PeriphClockSelection = RCC_PERIPHCLK_ADC;
#ifdef USE_HSI
    p.PLL2.PLL2M = 4; p.PLL2.PLL2N = 9;
#else
    p.PLL2.PLL2M = 1; p.PLL2.PLL2N = 18;
#endif
    p.PLL2.PLL2P = 4; p.PLL2.PLL2Q = 2; p.PLL2.PLL2R = 2;
    p.PLL2.PLL2RGE = RCC_PLL2VCIRANGE_3; p.PLL2.PLL2VCOSEL = RCC_PLL2VCOMEDIUM; p.PLL2.PLL2FRACN = 0;
    p.AdcClockSelection = RCC_ADCCLKSOURCE_PLL2;
    HAL_RCCEx_PeriphCLKConfig(&p);
}

static void gpio_uart_init(void)
{
    GPIO_InitTypeDef g = {0};
    __HAL_RCC_GPIOA_CLK_ENABLE(); __HAL_RCC_GPIOB_CLK_ENABLE(); __HAL_RCC_GPIOD_CLK_ENABLE();
    g.Pin = GPIO_PIN_0 | GPIO_PIN_14; g.Mode = GPIO_MODE_OUTPUT_PP;   /* LD1 green = e-CzasPL, LD3 red = OCXO (see README) */
    HAL_GPIO_Init(GPIOB, &g);
    __HAL_RCC_GPIOE_CLK_ENABLE();
    g.Pin = GPIO_PIN_1; g.Mode = GPIO_MODE_OUTPUT_PP;                 /* LD2 yellow = DCF77 (see README) */
    HAL_GPIO_Init(GPIOE, &g);
    g.Pin = GPIO_PIN_3; g.Mode = GPIO_MODE_ANALOG; g.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOA, &g);
    __HAL_RCC_USART3_CLK_ENABLE();
    g.Pin = GPIO_PIN_8 | GPIO_PIN_9; g.Mode = GPIO_MODE_AF_PP; g.Pull = GPIO_PULLUP;
    g.Speed = GPIO_SPEED_FREQ_LOW; g.Alternate = GPIO_AF7_USART3;
    HAL_GPIO_Init(GPIOD, &g);
    huart3.Instance = USART3;
    huart3.Init.BaudRate = RX_UART_BAUD; huart3.Init.WordLength = UART_WORDLENGTH_8B;
    huart3.Init.StopBits = UART_STOPBITS_1; huart3.Init.Parity = UART_PARITY_NONE;
    huart3.Init.Mode = UART_MODE_TX_RX; huart3.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    huart3.Init.OverSampling = UART_OVERSAMPLING_16;
    HAL_UART_Init(&huart3);
    HAL_NVIC_SetPriority(USART3_IRQn, 2, 0); HAL_NVIC_EnableIRQ(USART3_IRQn);
}

static void adc_init(void)
{
    __HAL_RCC_ADC12_CLK_ENABLE(); __HAL_RCC_DMA1_CLK_ENABLE(); __HAL_RCC_TIM6_CLK_ENABLE();
    hdma_adc1.Instance = DMA1_Stream0;
    hdma_adc1.Init.Request = DMA_REQUEST_ADC1;
    hdma_adc1.Init.Direction = DMA_PERIPH_TO_MEMORY;
    hdma_adc1.Init.PeriphInc = DMA_PINC_DISABLE; hdma_adc1.Init.MemInc = DMA_MINC_ENABLE;
    hdma_adc1.Init.PeriphDataAlignment = DMA_PDATAALIGN_WORD;     /* ADC12 common data register: both ADCs */
    hdma_adc1.Init.MemDataAlignment = DMA_MDATAALIGN_WORD;
    hdma_adc1.Init.Mode = DMA_CIRCULAR; hdma_adc1.Init.Priority = DMA_PRIORITY_HIGH;
    hdma_adc1.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
    HAL_DMA_Init(&hdma_adc1);
    __HAL_LINKDMA(&hadc1, DMA_Handle, hdma_adc1);
    HAL_NVIC_SetPriority(DMA1_Stream0_IRQn, 1, 0);
    HAL_NVIC_EnableIRQ(DMA1_Stream0_IRQn);
    hadc1.Instance = ADC1;
    hadc1.Init.ClockPrescaler = ADC_CLOCK_ASYNC_DIV1;
    hadc1.Init.Resolution = ADC_RESOLUTION_16B;
    hadc1.Init.ScanConvMode = ADC_SCAN_DISABLE;
    hadc1.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
    hadc1.Init.LowPowerAutoWait = DISABLE;
    hadc1.Init.ContinuousConvMode = DISABLE;
    hadc1.Init.NbrOfConversion = 1;
    hadc1.Init.DiscontinuousConvMode = DISABLE;
    hadc1.Init.ExternalTrigConv = ADC_EXTERNALTRIG_T6_TRGO;
    hadc1.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_RISING;
    hadc1.Init.ConversionDataManagement = ADC_CONVERSIONDATA_DMA_CIRCULAR;
    hadc1.Init.Overrun = ADC_OVR_DATA_OVERWRITTEN;
    hadc1.Init.LeftBitShift = ADC_LEFTBITSHIFT_NONE;
    hadc1.Init.OversamplingMode = DISABLE;
    HAL_ADC_Init(&hadc1);
    HAL_ADCEx_Calibration_Start(&hadc1, ADC_CALIB_OFFSET_LINEARITY, ADC_SINGLE_ENDED);
    ADC_ChannelConfTypeDef ch = {0};
    ch.Channel = ADC_CHANNEL_15; ch.Rank = ADC_REGULAR_RANK_1;
    ch.SamplingTime = ADC_SAMPLETIME_8CYCLES_5;
    ch.SingleDiff = ADC_SINGLE_ENDED; ch.OffsetNumber = ADC_OFFSET_NONE;
    HAL_ADC_ConfigChannel(&hadc1, &ch);
    /* ADC2 (slave): A1 = PC0 = INP10, converted at the same trigger as ADC1 */
    hadc2 = hadc1; hadc2.Instance = ADC2; hadc2.DMA_Handle = NULL;
    HAL_ADC_Init(&hadc2);
    HAL_ADCEx_Calibration_Start(&hadc2, ADC_CALIB_OFFSET_LINEARITY, ADC_SINGLE_ENDED);
    ch.Channel = ADC_CHANNEL_10;
    HAL_ADC_ConfigChannel(&hadc2, &ch);
    ADC_MultiModeTypeDef mm = {0};
    mm.Mode = ADC_DUALMODE_REGSIMULT;
    mm.DualModeData = ADC_DUALMODEDATAFORMAT_32_10_BITS;      /* CDR = ADC2 << 16 | ADC1 */
    mm.TwoSamplingDelay = ADC_TWOSAMPLINGDELAY_1CYCLE;
    HAL_ADCEx_MultiModeConfigChannel(&hadc1, &mm);
    htim6.Instance = TIM6;
    htim6.Init.Prescaler = 0; htim6.Init.Period = 199;
    htim6.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim6.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
    HAL_TIM_Base_Init(&htim6);
    TIM_MasterConfigTypeDef m = {0};
    m.MasterOutputTrigger = TIM_TRGO_UPDATE; m.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
    HAL_TIMEx_MasterConfigSynchronization(&htim6, &m);
    HAL_ADCEx_MultiModeStart_DMA(&hadc1, adc_buf, RING_BLK * BLOCK);
    HAL_TIM_Base_Start(&htim6);
}
void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *h) { (void)h; dma_halves++; }
void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *h)     { (void)h; dma_halves++; dma_wraps++; }

static uint64_t samples_written(void)      /* total ADC samples the DMA has stored */
{
    static uint64_t last;
    uint32_t w, w2, ndtr;
    do { w = dma_wraps; ndtr = __HAL_DMA_GET_COUNTER(&hdma_adc1); w2 = dma_wraps; } while (w != w2);
    uint64_t t = (uint64_t)w * (RING_BLK * BLOCK) + (RING_BLK * BLOCK - ndtr);
    if (t < last) t += RING_BLK * BLOCK;    /* wrapped, interrupt not served yet */
    last = t;
    return t;
}

/* ---------------------------------------------------------------- LSE reference */
/* TIM16 counts the timer clock (nominally 200 MHz, derived from the drifting
   ST-LINK clock); its TI1 is the 32.768 kHz watch crystal (LSE), captured every
   8th edge. The sum of capture intervals over 4096 captures = timer ticks per
   LSE second, i.e. the true timer clock frequency. */
TIM_HandleTypeDef htim16;
#ifdef OCXO_REF
/* Reference = external 10 MHz OCXO on PA0 (D32, CN10 pin 29; 5 V HCMOS through 1k/2k):
   TIM2 counts it (ETR, external clock mode 2), updates every 2500 counts (4 kHz, TRGO) and
   TIM3 - clocked like TIM6 - captures those updates (IC1 on TRC, internal trigger from TIM2),
   exactly like TIM16 captures the LSE otherwise. EFC: DAC1 channel 2 on PA5 (D13). */
#define REF_TIM      TIM3
#define REF_CAP_S    (2500.0 / 10.0e6)    /* seconds between captures */
#define REF_NAME     "OCXO"
#ifndef LSE_WIN
#define LSE_WIN 4000                     /* captures per measurement: 1 s */
#endif
#ifndef EFC_INIT
#define EFC_INIT 2253                    /* DAC code at start: this OCXO locked at ~2253 (28 Sep) */
#endif
#ifndef EFC_SLOPE
#define EFC_SLOPE 0.816e-9               /* measured 28 Sep (ppb per code); 0 = calibrate at start */
#endif
#else
#define REF_TIM      TIM16
#define REF_CAP_S    (8.0 / 32768.0)
#define REF_NAME     "LSE"
#endif
#ifndef LSE_WIN
#define LSE_WIN 4096                     /* captures per measurement: 4096 = 1 s, 512 = 1/8 s */
#endif
#define LSE_TPS_NOM (200000000.0 * LSE_WIN * REF_CAP_S)
static volatile uint32_t lse_last, lse_sum, lse_cnt, lse_tps, lse_seq;
static volatile uint32_t lse_log[64]; static volatile int lse_log_n;
static volatile uint64_t lse_tot_ticks, lse_tot_caps;   /* running totals for per-block rate */
#define CAPR 512                           /* ring of capture tick counts (125 ms) */
static volatile uint64_t cap_tick[CAPR];
#ifdef OCXO_REF
/* GPS PPS (u-blox LEA-M8T TIMEPULSE) on PC8 = TIM3_CH3: the same counter that timestamps the OCXO,
   so the pulse lands on the samples' own time base (5 ns steps). Nothing connected = no captures. */
static volatile uint64_t pps_tick; static volatile uint32_t pps_seq;
static double pps_tt; static int pps_new;   /* the last pulse in true time (capture units), not yet reported */
#endif
static int lse_ok;
#ifdef OCXO_REF
static TIM_HandleTypeDef htim2, htim3;
static int ocxo_itr = -1;
static efc_t efc;                          /* EFC steering from the carriers (common/efc.c) */
static void efc_set(uint32_t code)
{
    DAC1->DHR12R2 = code & 0xFFF;
}
static void ocxo_init(void)
{
    /* EFC: DAC1 channel 2 on PA5 (analog by default), buffered, mid-scale */
    __HAL_RCC_DAC12_CLK_ENABLE();
    DAC1->CR |= DAC_CR_EN2;
    efc_set(EFC_INIT);
    efc_init(&efc, EFC_INIT, EFC_SLOPE);
    /* PA0 = TIM2_ETR (AF1) */
    __HAL_RCC_GPIOA_CLK_ENABLE(); __HAL_RCC_TIM2_CLK_ENABLE(); __HAL_RCC_TIM3_CLK_ENABLE();
    GPIO_InitTypeDef g = {0};
    g.Pin = GPIO_PIN_0; g.Mode = GPIO_MODE_AF_PP; g.Pull = GPIO_NOPULL; g.Speed = GPIO_SPEED_FREQ_LOW; g.Alternate = GPIO_AF1_TIM2;
    HAL_GPIO_Init(GPIOA, &g);
    htim2.Instance = TIM2;
    htim2.Init.Prescaler = 0; htim2.Init.Period = 2500 - 1; htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
    HAL_TIM_Base_Init(&htim2);
    TIM_ClockConfigTypeDef cs = {0};
    cs.ClockSource = TIM_CLOCKSOURCE_ETRMODE2; cs.ClockPolarity = TIM_CLOCKPOLARITY_NONINVERTED;
    cs.ClockPrescaler = TIM_CLOCKPRESCALER_DIV1; cs.ClockFilter = 0;
    HAL_TIM_ConfigClockSource(&htim2, &cs);
    TIM_MasterConfigTypeDef mc = {0};
    mc.MasterOutputTrigger = TIM_TRGO_UPDATE; mc.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
    HAL_TIMEx_MasterConfigSynchronization(&htim2, &mc);
    /* TIM3: timer clock (as TIM6), IC1 on TRC = TIM2 TRGO via an internal trigger */
    htim3.Instance = TIM3;
    htim3.Init.Prescaler = 0; htim3.Init.Period = 0xFFFF; htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
    HAL_TIM_IC_Init(&htim3);
    TIM_IC_InitTypeDef ic = {0};
    ic.ICPolarity = TIM_ICPOLARITY_RISING; ic.ICSelection = TIM_ICSELECTION_TRC; ic.ICPrescaler = TIM_ICPSC_DIV1; ic.ICFilter = 0;
    HAL_TIM_IC_ConfigChannel(&htim3, &ic, TIM_CHANNEL_1);
    HAL_NVIC_SetPriority(TIM3_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(TIM3_IRQn);
    HAL_TIM_Base_Start(&htim2);
    HAL_TIM_IC_Start_IT(&htim3, TIM_CHANNEL_1);
    {   /* GPS PPS input: PC8 (CN8, D43) = TIM3_CH3, AF2, pull-down (nothing connected = quiet) */
        __HAL_RCC_GPIOC_CLK_ENABLE();
        GPIO_InitTypeDef gp = {0};
        gp.Pin = GPIO_PIN_8; gp.Mode = GPIO_MODE_AF_PP; gp.Pull = GPIO_PULLDOWN; gp.Speed = GPIO_SPEED_FREQ_LOW; gp.Alternate = GPIO_AF2_TIM3;
        HAL_GPIO_Init(GPIOC, &gp);
        TIM_IC_InitTypeDef i3 = {0};
        i3.ICPolarity = TIM_ICPOLARITY_RISING; i3.ICSelection = TIM_ICSELECTION_DIRECTTI; i3.ICPrescaler = TIM_ICPSC_DIV1; i3.ICFilter = 3;
        HAL_TIM_IC_ConfigChannel(&htim3, &i3, TIM_CHANNEL_3);
        HAL_TIM_IC_Start_IT(&htim3, TIM_CHANNEL_3);
    }
    /* which internal trigger carries TIM2's TRGO? (TIM3: ITR1 per the usual STM32 mapping) -
       try each for 250 ms and keep the one that gives 4 kHz */
    static const uint32_t itr[4] = { TIM_TS_ITR1, TIM_TS_ITR0, TIM_TS_ITR2, TIM_TS_ITR3 };
    for (int k = 0; k < 4 && ocxo_itr < 0; k++) {
        TIM_SlaveConfigTypeDef sc = {0};
        sc.SlaveMode = TIM_SLAVEMODE_DISABLE; sc.InputTrigger = itr[k];
        HAL_TIM_SlaveConfigSynchro(&htim3, &sc);
        __HAL_TIM_ENABLE_IT(&htim3, TIM_IT_CC1);
        uint32_t c0 = lse_tot_caps, t0 = HAL_GetTick();
        while (HAL_GetTick() - t0 < 250) {}
        uint32_t n = (uint32_t)(lse_tot_caps - c0);
        if (n > 900 && n < 1100) ocxo_itr = k;                 /* 4 kHz x 0.25 s = 1000 */
    }
    lse_ok = ocxo_itr >= 0;
}
#endif
#ifndef OCXO_REF
static void lse_init(void)
{
    RCC_OscInitTypeDef o = {0};
    HAL_PWR_EnableBkUpAccess();
    o.OscillatorType = RCC_OSCILLATORTYPE_LSE; o.LSEState = RCC_LSE_ON; o.PLL.PLLState = RCC_PLL_NONE;
    lse_ok = HAL_RCC_OscConfig(&o) == HAL_OK;
    if (!lse_ok) return;
    __HAL_RCC_TIM16_CLK_ENABLE();
    htim16.Instance = TIM16;
    htim16.Init.Prescaler = 0; htim16.Init.Period = 0xFFFF; htim16.Init.CounterMode = TIM_COUNTERMODE_UP;
    HAL_TIM_IC_Init(&htim16);
    TIM_IC_InitTypeDef ic = {0};
    ic.ICPolarity = TIM_ICPOLARITY_RISING; ic.ICSelection = TIM_ICSELECTION_DIRECTTI;
    ic.ICPrescaler = TIM_ICPSC_DIV8; ic.ICFilter = 0;
    HAL_TIM_IC_ConfigChannel(&htim16, &ic, TIM_CHANNEL_1);
    HAL_TIMEx_TISelection(&htim16, TIM_TIM16_TI1_RCC_LSE, TIM_CHANNEL_1);
    HAL_NVIC_SetPriority(TIM16_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(TIM16_IRQn);
    HAL_TIM_IC_Start_IT(&htim16, TIM_CHANNEL_1);
}
#endif
#ifdef OCXO_REF
void TIM3_IRQHandler(void)
#else
void TIM16_IRQHandler(void)
#endif
{
#ifdef OCXO_REF
    if (REF_TIM->SR & TIM_SR_CC3IF) {          /* GPS PPS: < 250 us after the last OCXO capture */
        uint32_t c3 = REF_TIM->CCR3;           /* reading CCR3 clears CC3IF */
        pps_tick = lse_tot_ticks + ((c3 - lse_last) & 0xFFFF);
        pps_seq++;
    }
#endif
    if (REF_TIM->SR & TIM_SR_CC1IF) {
        uint32_t c = REF_TIM->CCR1;            /* reading CCR1 clears CC1IF */
        uint32_t d = (c - lse_last) & 0xFFFF;
        lse_last = c;
        if (lse_cnt) { lse_sum += d; lse_tot_ticks += d; lse_tot_caps++; }
        cap_tick[lse_tot_caps % CAPR] = lse_tot_ticks;
        if (++lse_cnt == LSE_WIN + 1) { lse_tps = lse_sum; lse_seq++; lse_sum = 0; lse_cnt = 1;
            if (lse_log_n < 64) lse_log[lse_log_n++] = lse_tps; }
    }
    REF_TIM->SR = ~(TIM_SR_CC1IF | TIM_SR_CC3IF);   /* clear the rest; a capture flag set meanwhile stays */
}

static double cur_tps_ratio = 1.0;        /* true / nominal sample rate */
static double blk_ratio_sum; static int blk_ratio_n;   /* averages for the per-second timebase */

/* ---------------------------------------------------------------- front end */
/* mixer: running phasor, rotation per ADC sample (probe scale); f_mix in Hz of
   the probe's nominal 1 MHz scale, i.e. where the carrier appears */
static double f_mix;
static float mix_c = 1, mix_s = 0, rot_c, rot_s;
/* second channel: DCF77 at 77.5 kHz, same phase-locked true time, streamed as
   2 kHz complex baseband (AUDIO_DUMP builds) for analysis on the host */
#ifndef F_DCF
#define F_DCF 77500.0                      /* second mixer; -DF_DCF=162000.0 probes TDF (ALS162) */
#endif
static float mx2_c = 1, mx2_s = 0, rt2_c = 1, rt2_s = 0, acc2_r, acc2_i;
static double pl_cyc2;
static void set_mix(double f)
{
    f_mix = f;
    double w = -2 * M_PI * f / FS_NOM_HZ;
    rot_c = (float)cos(w); rot_s = (float)sin(w);
}
/* phase-locked mixer: every ADC sample is exactly 200 timer ticks after the
   previous one, every LSE capture is exactly 8/32768 s after the previous one,
   so the TRUE time of any sample is known by interpolation between captures.
   The mixer phase is set to -2 pi F t_true at every block boundary, so clock
   wander cannot accumulate into carrier phase noise. */
static int pl_ok;                          /* calibrated: tick of sample k = 200 k + pl_c */
static int64_t pl_c;
static double F_true = F_CARRIER;          /* mixer frequency in true Hz */
static double pl_t;                        /* true time (capture units) at the next block start */
static double pl_cyc;                      /* mixer phase (cycles, fractional) at the next block start */
static double pl_t0; static uint64_t pl_n0; /* true time (capture units) of 2 kHz sample pl_n0: the 2 kHz scale is exact true time from there */
static void pl_calibrate(uint64_t written)
{
    __disable_irq();
    uint32_t n16 = REF_TIM->CNT, c6 = TIM6->CNT, ll = lse_last;
    uint64_t lt = lse_tot_ticks;
    __enable_irq();
    int64_t tick_now = (int64_t)lt + ((n16 - ll) & 0xFFFF);
    pl_c = tick_now - 200 * (int64_t)written - (int64_t)c6;
}
static double true_time(int64_t tick)      /* capture units, from the ring */
{
    __disable_irq(); uint64_t J = lse_tot_caps; __enable_irq();
    uint64_t j = J;
    while (j > 0 && J - j < CAPR - 4 && (int64_t)cap_tick[j % CAPR] > tick) j--;
    if (j == J) j = J - 1;                 /* past the newest capture: extrapolate */
    int64_t a = (int64_t)cap_tick[j % CAPR], b = (int64_t)cap_tick[(j + 1) % CAPR];
    return (double)j + (double)(tick - a) / (double)(b - a);
}
/* ---- the two stations: same structure, separate state, no data between them ----
 * mixer (phase-locked to true time, fixed nominal frequency) -> sum over exactly 0.5 ms of
 * true time -> 2 kHz complex -> own carrier tracker (coh.c) -> own timing:
 *   e-CzasPL: 500 Hz carrier-relative phase -> ecz.c -> frame.c / timekeeper.c
 *   DCF77:    derotated 2 kHz baseband -> dcf.c (second mark, minute, phase code) */
static coh_trk_t trk_e, trk_d;
static ecz_t ez;
static dcf_t dcf;
static dcfbits_t dcfb;                     /* DCF77 time code, every minute */
static int dcf_blocks_locked, dcf_line_proven; static float dcf_line_hz = 1e9f;
/* DCF77 counts as locked only when the tracked line also carries confirmed second marks
   (a local spur can be tracked, but it has no 1-s amplitude pattern) */
static int dcf_verified(void)
{
    return trk_d.state == COH_TRACK && dcf.have_mark && dcf.mark_sigma >= 6 && fabsf((float)trk_d.hz - dcf_line_hz) < 0.15f;
}
static const char *dcf_state_txt(void)
{
    return trk_d.state == COH_SEARCH ? "searching" : trk_d.state == COH_PULL ? "pulling in" :
           dcf_verified() ? "locked (second marks)" : "tracking, not verified";
}
static void dcf_report(void);
#ifdef AUDIO_DUMP
static void dump(uint8_t type, float zr, float zi)
{   /* packet: A5 <type>, u32 index of the first 2 kHz sample, 200 x (float re, float im);
       type 5B = DCF77, 5C = e-CzasPL (both the mixer output, before the trackers) */
    typedef struct __attribute__((packed)) { uint8_t m0, m1; uint32_t n0; float x[400]; } pk_t;
    static pk_t pk[2] = { { 0xA5, 0x5B, 0, {0} }, { 0xA5, 0x5C, 0, {0} } };
    static int pn[2];
    int w = type == 0x5C;
    if (pn[w] == 0) pk[w].n0 = (uint32_t)n2k;
    pk[w].x[2 * pn[w]] = zr; pk[w].x[2 * pn[w] + 1] = zi;
    if (++pn[w] == 200) { uart_write(&pk[w], sizeof pk[w]); pn[w] = 0; }
}
#endif
static int64_t now_tick(void);
/* LEDs: LD1 e-CzasPL, LD2 DCF77 - on while the carrier is locked, a 300 ms blink (inverted)
   at every correctly decoded frame / minute; LD3 OCXO - on = locked, 1 Hz blink = calibrating,
   moving to the calibrated code or holdover, off = waiting or failed (non-OCXO build: off) */
static uint64_t led1_until, led2_until;    /* n2k at which the LD1 / LD2 blink ends */
/* spectrum diagnostic (common/spec.c): 60 s after boot and then every 10 min, 256 FFTs of 4096 samples of
   both inputs (every 4th block, ~5 s), then per input the noise floor (median PSD per band, so the carriers
   of other stations do not lift it: the tuned rod's resonance shows as a hump) and the strongest carriers.
   A0: 150-300 kHz in 3 kHz bands; A1: 40-120 kHz in 2 kHz bands; dB re 1 LSB^2/Hz (ADC floor ~ -50) */
#define SPEC_BLOCKS 256
static spec_t spec __attribute__((section(".dtcm")));
static uint64_t next_spec = 120000; static int spec_left, spec_ctr;
static float spec_med(float *v, int n)
{
    for (int i = 1; i < n; i++) { float x = v[i]; int j = i - 1; while (j >= 0 && v[j] > x) { v[j + 1] = v[j]; j--; } v[j + 1] = x; }
    return n ? (n & 1 ? v[n / 2] : 0.5f * (v[n / 2 - 1] + v[n / 2])) : 0;
}
static void spec_report(void)
{
    static const struct { int ch; const char *name; double f0, f1, step; } R[2] = {
        { 1, "A1 (DCF77 rod)", 40e3, 120e3, 2e3 }, { 0, "A0 (e-CzasPL rod)", 150e3, 300e3, 3e3 } };
    double fs = FS_NOM_HZ * cur_tps_ratio, df = fs / SPEC_N;       /* true Hz per bin */
    char m[480], b1[16], b2[16];                /* newlib-nano printf has no %f: f1() */
    for (int r = 0; r < 2; r++) {
        int o = snprintf(m, sizeof m, "%s noise dB/Hz per %d kHz from %d kHz:", R[r].name, (int)(R[r].step / 1e3), (int)(R[r].f0 / 1e3));
        for (double f = R[r].f0; f < R[r].f1 - 1 && o < (int)sizeof m - 8; f += R[r].step) {
            float v[64]; int n = 0;
            for (int k = (int)ceil(f / df); k * df < f + R[r].step && k <= SPEC_N / 2 && n < 64; k++) v[n++] = (float)spec_psd(&spec, R[r].ch, k, fs);
            o += snprintf(m + o, sizeof m - o, " %s", f1(b1, 10 * log10(spec_med(v, n) + 1e-30), 0));
        }
        put_line("SPECTRUM", m);
        /* carriers: local maxima 15 dB over the median of +-20 bins, the 8 strongest */
        int pk[8] = {0}; double pp[8] = {0}; int np = 0;
        int k0 = (int)(R[r].f0 / df) + 21, k1 = (int)(R[r].f1 / df) - 21;
        for (int k = k0; k <= k1; k++) {
            const float *a = R[r].ch ? spec.acc1 : spec.acc0;
            if (a[k] < a[k - 1] || a[k] < a[k + 1]) continue;
            float v[41]; for (int i = 0; i < 41; i++) v[i] = a[k - 20 + i];
            float md = spec_med(v, 41);
            if (a[k] < 31.6f * md) continue;
            double tp = spec_tone(&spec, R[r].ch, k);
            int w = np < 8 ? np++ : 7;
            if (w == 7 && np == 8 && tp <= pp[7]) continue;
            pk[w] = k; pp[w] = tp;
            for (int i = w; i > 0 && pp[i] > pp[i - 1]; i--) { double t = pp[i]; pp[i] = pp[i - 1]; pp[i - 1] = t; int u = pk[i]; pk[i] = pk[i - 1]; pk[i - 1] = u; }
        }
        o = snprintf(m, sizeof m, "%s carriers (kHz: dB re 1 LSB^2, %d FFTs):", R[r].name, spec.nblk);
        for (int i = 0; i < np; i++) o += snprintf(m + o, sizeof m - o, " %s: %s", f1(b2, pk[i] * df / 1e3, 0), f1(b1, 10 * log10(pp[i]), 0));
        if (!np) snprintf(m + o, sizeof m - o, " none 15 dB over the noise");
        put_line("SPECTRUM", m);
    }
}
#define LED_BLINK 600                      /* 2 kHz samples = 300 ms */
/* one line per decoded DCF77 minute; the e-CzasPL time is only compared, never used */
static void dcf_time_report(void)
{
    static const char *ST[] = { "-", "not decodable", "decoded (unconfirmed)", "confirmed", "confirmed by the expected frame" };
    char m[240], cmp[64] = "", b1[16], b2[16];
    uint32_t sec, us;
    if (dcfb.status == DCFT_CONFIRMED || dcfb.status == DCFT_PREDICTED || dcfb.status == DCFT_UNCONFIRMED) {
        led2_until = n2k + LED_BLINK;
        /* the code is the time of the next minute, which starts ~1 s after second 58 ends */
        if (tk_time(&tk, now_tick() + 1 * (int64_t)FCY_HZ, &sec, &us)) {
            int64_t ez_min = ((int64_t)sec + 30) / 60;
            int64_t d = (int64_t)dcfb.utc_min - ez_min;
            if (d == 0) snprintf(cmp, sizeof cmp, " | e-CzasPL: same minute");
            else snprintf(cmp, sizeof cmp, " | e-CzasPL differs by %ld min", (long)d);
        }
        snprintf(m, sizeof m, "TIME %04d-%02d-%02d %02d:%02d %s %s (bits repaired %d, PM seconds %d, AM=PM %d, fit %s lead %s)%s",
                 dcfb.year, dcfb.month, dcfb.day, dcfb.hour, dcfb.minute, dcfb.cest ? "CEST" : "CET", ST[dcfb.status],
                 dcfb.flips, dcfb.bits_pm, dcfb.am_pm_agree, f1(b1, dcfb.pred_score, 0), f1(b2, dcfb.pred_margin, 0), cmp);
    } else {
        snprintf(m, sizeof m, "TIME %s (PM seconds %d, AM=PM %d, fit %s lead %s) | decoded %lu, confirmed %lu, by expected frame %lu, failed %lu",
                 ST[dcfb.status], dcfb.bits_pm, dcfb.am_pm_agree, f1(b1, dcfb.pred_score, 0), f1(b2, dcfb.pred_margin, 0),
                 dcfb.n_decoded, dcfb.n_confirmed, dcfb.n_predicted, dcfb.n_failed);
    }
    put_line("DCF77", m);
}

static void station_samples(float er, float ei, float dr, float di)
{
    float a, b, ir, ii;
#ifdef AUDIO_DUMP
    dump(0x5C, er, ei); dump(0x5B, dr, di);
#endif
    if (coh_push(&trk_e, er, ei, &a, &b, &ir, &ii))
        ecz_push(&ez, (int16_t)lrintf(atan2f(ii, ir) * (32768.0f / (float)M_PI)));
    coh_push(&trk_d, dr, di, &a, &b, &ir, &ii);
    dcf_push(&dcf, a, b, trk_d.state == COH_TRACK);
    if (dcfbits_push(&dcfb, &dcf, a, b, dcf.n - 1, trk_d.state == COH_TRACK)) dcf_time_report();
    n2k++;
    /* until the first second marks: look for them every 10 s in the current block (>= 60 s tracked),
       instead of waiting for the first 10-min block (bench: marks at 120-240 s instead of 600 s) */
    /* CPU: mark_find ~16 ms, pm_eval ~8 ms, dcf_block ~24 ms, and the sample ring holds 30 ms -
       so the early checks run in their own samples (0 / 3 / 6.5 s of each 10 s) and never in the
       sample of the 10-min block (all three with the block gave 32 ms and an OVERRUN, 21:38:43) */
    int blk = dcf_block_ready(&dcf);
    if (!blk && !dcf.have_mark && trk_d.state == COH_TRACK && n2k % 20000 == 0 && dcf_quick_mark(&dcf, 10.0f)) {
        char m[100], b1[16], b2[16];
        dcf_line_hz = (float)trk_d.hz; dcf_blocks_locked = 1; dcf_line_proven = 1;
        snprintf(m, sizeof m, "second marks found early: %s ms of the second, %s sigma", f1(b1, dcf.mark / 2.0, 0), f1(b2, dcf.mark_sigma, 0));
        put_line("DCF77", m);
    }
    /* the same for the minute marker (8 sigma) and the phase code, until the first 10-min block:
       bench: first confirmed DCF77 minute after 12-15 min instead of 24-26 (15-17 dB-Hz) */
    if (!blk && trk_d.state == COH_TRACK && (n2k % 20000 == 6000 || n2k % 20000 == 13000)) {
        char m[100], b1[16], b2[16];
        if (n2k % 20000 == 6000 && dcf_quick_minute(&dcf, 8.0f)) {
            snprintf(m, sizeof m, "minute found early: %s sigma", f1(b1, dcf.minute_sigma, 0));
            put_line("DCF77", m);
        }
        static int pm_said;
        if (n2k % 20000 == 13000 && dcf_quick_pm(&dcf) && !pm_said) {
            pm_said = 1;
            snprintf(m, sizeof m, "phase code found early: %s ms, %s sigma", f1(b1, dcf.pm_lag_ms, 1), f1(b2, dcf.pm_sigma, 0));
            put_line("DCF77", m);
        }
    }
#ifdef OCXO_REF
    /* the blind pull-in at 0 Hz (see main) found nothing within 3 min: search the normal way */
    if (n2k == 360000 && !dcf.have_mark && trk_d.state != COH_SEARCH) { coh_search(&trk_d); put_line("DCF77", "no second marks 3 min after the blind pull-in - searching"); }
#endif
    static float blk_hz;                  /* carrier at the block's first step (dcf_block_step) */
    if (blk) blk_hz = trk_d.state == COH_TRACK ? (float)trk_d.hz : 0.0f;
    if (dcf_block_step(&dcf, blk_hz)) {   /* 10-min block in four ~8 ms steps (was ~24 ms in one sample) */
        /* carrier check: a DCF77 carrier has second marks; none in the first 60 min on a
         * line -> it is something else (a local spur): reject it, search again. The count
         * goes on through re-searches that find the same line again (+-0.15 Hz: a spur moves
         * with the LSE and is often lost and found again). A line that has shown marks is
         * DCF77 and is never rejected (its marks may fade for a while) */
        if (trk_d.state != COH_SEARCH) {
            if (fabsf((float)trk_d.hz - dcf_line_hz) > 0.15f) { dcf_line_hz = (float)trk_d.hz; dcf_blocks_locked = 1; dcf_line_proven = 0; }
            else dcf_blocks_locked++;
            if (dcf.mark_sigma >= 6) dcf_line_proven = 1;
        }
        if (!dcf_line_proven && dcf_blocks_locked >= 6 && dcf.mark_sigma < 6) {
            char m[80], b1[16];
            snprintf(m, sizeof m, "carrier at %s Hz has no second marks - rejected, searching", f1(b1, trk_d.hz, 1));
            put_line("DCF77", m);
            coh_reject(&trk_d, 0.05f); dcf_blocks_locked = 0; memset(dcf.yr, 0, sizeof dcf.yr);
            dcf.have_mark = 0; dcf.mark_sigma = 0;           /* the new line must prove itself */
        }
        dcf_report();
    }
}

/* one DMA block: both mixers, then sums over exactly 500 us of TRUE time
   (500 x clock ratio input samples; the fractional sample is split) */
static double dec_pos;
static float acc_r, acc_i;
static void process_block(const uint32_t *b, float mean, float mean2)
{
    double step = 500.0 * cur_tps_ratio;  /* input samples per true 500 us */
    for (int n = 0; n < BLOCK; n++) {
        float x = (float)(b[n] & 0xFFFF) - mean;
#ifdef DCF_ON_A0
        float x2 = x; (void)mean2;
#else
        float x2 = (float)(b[n] >> 16) - mean2;
#endif
        float xr = x * mix_c, xi = x * mix_s;
        float x2r = x2 * mx2_c, x2i = x2 * mx2_s;
        float t2 = mx2_c * rt2_c - mx2_s * rt2_s;
        mx2_s = mx2_c * rt2_s + mx2_s * rt2_c; mx2_c = t2;
        float t = mix_c * rot_c - mix_s * rot_s;
        mix_s = mix_c * rot_s + mix_s * rot_c; mix_c = t;
        if (dec_pos + 1.0 <= step) {       /* whole sample belongs to this output */
            acc_r += xr; acc_i += xi; acc2_r += x2r; acc2_i += x2i; dec_pos += 1.0;
        } else {                           /* split it between this output and the next */
            float f = (float)(step - dec_pos);
            station_samples(acc_r + f * xr, acc_i + f * xi, acc2_r + f * x2r, acc2_i + f * x2i);
            acc_r = (1 - f) * xr; acc_i = (1 - f) * xi;
            acc2_r = (1 - f) * x2r; acc2_i = (1 - f) * x2i;
            dec_pos = 1.0 - f;
        }
    }
    float m = 1.0f / sqrtf(mix_c * mix_c + mix_s * mix_s);
    mix_c *= m; mix_s *= m;
}

/* ---------------------------------------------------------------- frames */
/* ticks (FCY_HZ units of the eCzas core) of true time: 2 kHz sample n = n * 20000 */
static int64_t now_tick(void) { return (int64_t)n2k * (TICKS_PER_BLOCK / 4); }

/* hourly statistics (STATS line): the guaranteed e-CzasPL time frame of each minute (sent in slot 1 =
   second 03 - measured 29 Sep 2026; the frame description says slot 0), all time frames, early
   frames, DCF77 minutes, signal levels. Slots are attributed with the NUCLEO's own clock. */
static struct {
    uint32_t hour;                         /* UTC hour index (s / 3600) being counted, 0 = none */
    uint8_t  g[60], exp_[60];              /* per minute: guaranteed frame 0 none 1 heard 2 confirmed 3 correct; expected */
    uint32_t all_ok, all_conf, heard, early;
    unsigned long dcf0[4];                 /* dcfbits counters at the start of the hour */
    double   cn_e, cn_d; int ncn;
} hs;
static void hs_mark(uint32_t n3, uint8_t st)
{
    uint32_t sec = 3UL * n3;
    if (hs.hour == 0 || sec / 3600 != hs.hour) return;
    if (sec % 60 == 3) { uint8_t *g = &hs.g[(sec % 3600) / 60]; if (st > *g) *g = st; }
}
static void hs_start(uint32_t hour)
{
    memset(&hs, 0, sizeof hs); hs.hour = hour;
    hs.dcf0[0] = dcfb.n_confirmed; hs.dcf0[1] = dcfb.n_predicted; hs.dcf0[2] = dcfb.n_decoded; hs.dcf0[3] = dcfb.n_failed;
}
static void hs_report(void)
{
    char m[400], b1[16], b2[16];
    int e = 0, h = 0, c = 0, k = 0, i;
    for (i = 0; i < 60; i++) if (hs.exp_[i]) { e++; h += hs.g[i] >= 1; k += hs.g[i] == 2; c += hs.g[i] == 3; }
    unsigned long dc = dcfb.n_confirmed - hs.dcf0[0], dp = dcfb.n_predicted - hs.dcf0[1], dd = dcfb.n_decoded - hs.dcf0[2], df = dcfb.n_failed - hs.dcf0[3];
    snprintf(m, sizeof m, "%02lu UTC | e-CzasPL time frame at :03 (guaranteed): expected %d, heard %d, correct %d, confirmed %d | all time frames: correct %lu, confirmed %lu, "
             "heard %lu, early %lu | DCF77 minutes: confirmed %lu, by expected frame %lu, unconfirmed %lu, not decodable %lu | C/N0 e-CzasPL %s, DCF77 %s dB-Hz",
             (unsigned long)(hs.hour % 24), e, h, c, k, (unsigned long)hs.all_ok, (unsigned long)hs.all_conf, (unsigned long)hs.heard, (unsigned long)hs.early,
             dc, dp, dd > dc + dp ? dd - dc - dp : 0UL, df,
             hs.ncn ? f1(b1, hs.cn_e / hs.ncn, 0) : "-", hs.ncn ? f1(b2, hs.cn_d / hs.ncn, 0) : "-");
    put_line("STATS", m);
}

static void handle_candidate(void)
{
    dsp_cand_t *c = &ez.cand;
    frame_info_t fi;
    char m[240], d1[40], b1[16];
    int64_t tick = (int64_t)(c->start_block - 1) * TICKS_PER_BLOCK   /* 500 Hz block = 4 samples */
                 + (int64_t)ECZ_TEMPLATE_LAG_US * (FCY_HZ / 1000000L); /* template lag, see ecz.h */
    memset(&fi, 0, sizeof fi);
    frame_status_t st = frame_decode(c->ph + CAND_PRE, &fi);
    if (st == FR_NOT_TIME) { ez.cand_ready = 0; return; }
    n_heard++; hs.heard++;
    {
        uint32_t n3h;
        if (tk.synced && tk_expected_n3(&tk, tick, &n3h)) hs_mark(n3h, 1);
    }
    if (st == FR_UNCORRECTABLE && have_last_fi) {
        uint32_t n3p;
        if (tk_expected_n3(&tk, tick, &n3p)) {
            uint8_t bits[FRAME_BITS];
            int32_t tq = 0;
            frame_build(n3p, last_fi.tz, (uint8_t)(last_fi.ls | last_fi.lss << 1 | last_fi.tzc << 2 |
                        (last_fi.sk & 1) << 3 | (last_fi.sk >> 1) << 4), bits);
            int16_t sc = frame_confirm(c->ph + CAND_PRE, bits, &tq);
            if (sc >= CONFIRM_MIN_Q10) {
                frame_info_t fe = last_fi; fe.n3 = n3p;
                tk_result_t r = tk_frame(&tk, tick + (int64_t)tq * TICKS_PER_BLOCK / 32768, &fe);
                n_conf++;
                if (r == TK_ACCEPTED) { hs.all_conf++; hs_mark(n3p, 2); }
                date_str(d1, 3UL * n3p, fe.tz);
                snprintf(m, sizeof m, "#%lu not decodable, but %d%% agrees with the expected frame: %s%s",
                         (unsigned long)n_heard, sc * 100 / 1024, d1, r == TK_ACCEPTED ? " - confirmed" : "");
                put_line("FRAME", m);
                ez.cand_ready = 0;
                return;
            }
        }
    }
    if (st != FR_OK) {
        snprintf(m, sizeof m, "#%lu corr %d%% - not decodable (snr %d dB)", (unsigned long)n_heard, c->corr_q10 * 100 / 1024, fi.snr_db);
        put_line("FRAME", m);
        ez.cand_ready = 0;
        return;
    }
    tick += (int64_t)fi.timing_q15 * TICKS_PER_BLOCK / 32768;
    coh_level_hint(&trk_e, -fi.lvl_sep / 65536.0f);     /* measured '0' level for the carrier loop */
    int32_t off_ms = 0;
    if (tk.synced) off_ms = (int32_t)((tick - tk_second_tick(&tk, 3UL * fi.n3)) / (FCY_HZ / 1000));
    tk_result_t r = tk_frame(&tk, tick, &fi);
    n_decoded++;
    led1_until = n2k + LED_BLINK;
    date_str(d1, 3UL * fi.n3, fi.tz);
    snprintf(m, sizeof m, "#%lu corr %d%% snr %d dB, fixed %u%s: %s", (unsigned long)n_heard, c->corr_q10 * 100 / 1024,
             fi.snr_db, fi.rs_fixed, fi.chase_flips ? " + soft retry" : "", d1);
    put_line("FRAME", m);
    switch (r) {
    case TK_ACCEPTED: snprintf(m, sizeof m, "frame agrees with clock, error %s ms", f1(b1, tk.last_err_us / 1000.0, 1)); break;
    case TK_SYNCED:   snprintf(m, sizeof m, "SYNCHRONISED - two frames agree"); break;
    case TK_STEPPED:  snprintf(m, sizeof m, "STEPPED by %ld ms", (long)off_ms); break;
    case TK_CANDIDATE: snprintf(m, sizeof m, "not synchronised yet - waiting for a second frame"); break;
    default: n_rej++; snprintf(m, sizeof m, "REJECTED - differs from clock by %ld ms", (long)off_ms); break;
    }
    put_line("CLOCK", m);
    if (r == TK_ACCEPTED || r == TK_SYNCED) { hs.all_ok++; hs_mark(fi.n3, 3); }
    else if (r != TK_STEPPED && r != TK_CANDIDATE && off_ms > -2700 && off_ms < -2300) hs.early++;
    if (r == TK_ACCEPTED || r == TK_SYNCED || r == TK_STEPPED) { last_fi = fi; have_last_fi = 1; }
    ez.cand_ready = 0;
}

/* every 10 min: the DCF77 receiver's own results, plus - for the record only, nothing is
   fed back - where its second starts relative to the e-CzasPL second */
static void dcf_report(void)
{
    char m[420], b1[16], b2[16], b3[16], b4[16], b5[16], b6[16], b7[16], cmp[120] = "";
    if (dcf.have_mark && tk.synced) {
        double start = (double)((n2k - dcf.mark) / 2000 * 2000 + dcf.mark) + (dcf.pm_sigma > DCF_PM_MIN ? dcf.pm_lag_ms * 2.0 : 0);
        uint32_t sec, us;
        if (tk_time(&tk, (int64_t)(start * (TICKS_PER_BLOCK / 4)), &sec, &us)) {
            double ms = us / 1000.0; if (ms > 500) ms -= 1000;
            /* at the transmitters: minus the ground-wave delays from Wroclaw (Mainflingen 580 km 1.93 ms,
               Solec Kujawski 234 km 0.78 ms); what remains are the transmitters' and receivers' own offsets */
            snprintf(cmp, sizeof cmp, " | vs e-CzasPL second %s ms (at the transmitters %s ms)", f1(b5, ms, 1), f1(b7, ms - (1.93 - 0.78), 1));
        }
    }
    snprintf(m, sizeof m, "carrier %s, second mark %s ms of the " REF_NAME " second (%s sigma), minute %s (%s sigma), phase code %s ms (%s sigma)%s",
             dcf_state_txt(),
             dcf.have_mark ? f1(b1, dcf.mark / 2.0, 0) : "-", f1(b2, dcf.mark_sigma, 0),
             dcf.have_minute ? "found" : "not yet", f1(b3, dcf.minute_sigma, 0),
             dcf.pm_sigma > 0 ? f1(b4, dcf.pm_lag_ms, 1) : "-", f1(b6, dcf.pm_sigma, 0), cmp);
    put_line("DCF77", m);
}

/* ---------------------------------------------------------------- main */
int main(void)
{
    char m[420], b1[16], b2[16], b3[16];
    SCB_EnableICache();
    SCB_EnableDCache();
    HAL_Init();
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk; DWT->CYCCNT = 0; DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    clock_init();
    gpio_uart_init();
    uart_puts("\r\n\r\ne-CzasPL + DCF77 receiver on NUCLEO-H723ZG (M3: coherent, two independent stations)\r\n");
    {
        /* same tracker code, per-station settings (see common/coh.h) */
        static const coh_cfg_t ce = { COH_ECZAS, 4, 3.0f, 1.0f, 1500, 4, 1024, 40.0f, 25.0f, 30.0f };
        static const coh_cfg_t cd = { COH_PLAIN, 20000, 0.03f, 0.01f, 6, 500, 512, 2.0f, 40.0f, 600.0f };
        coh_init(&trk_e, &ce); coh_init(&trk_d, &cd);
#ifdef OCXO_REF
        /* the OCXO is steered to the carriers (EFC_INIT = where it was locked): DCF77 is within a
           few mHz of 0 Hz, so pull in there at once instead of a 128-s search (fallback: above) */
        coh_pull_at(&trk_d, 0.0f);
#endif
    }
    ecz_init(&ez);
    spec_init();
    dcf_init(&dcf); dcfbits_init(&dcfb);
    tk_init(&tk);
#ifdef OCXO_REF
    ocxo_init();
#else
    lse_init();
#endif
    set_mix(F_CARRIER * FS_NOM_HZ / FS_GUESS_HZ);
    adc_init();
    if (lse_ok) {                        /* first LSE measurement (~1 s) sets the mixer */
        uint32_t t0 = HAL_GetTick();
        while (lse_seq < 2 && HAL_GetTick() - t0 < 3000) {}
        if (lse_seq >= 2) { cur_tps_ratio = (double)lse_tps / LSE_TPS_NOM; set_mix(F_CARRIER / cur_tps_ratio); }
        snprintf(m, sizeof m, REF_NAME " reference OK: Nucleo clock %+ld ppm, mixer %lu Hz\r\n",
                 (long)lround((cur_tps_ratio - 1) * 1e6), (unsigned long)lround(f_mix));
    } else snprintf(m, sizeof m, REF_NAME " reference NOT running (no captures) - no drift correction\r\n");
    uart_puts(m);

    float mean = 32768.0f, mean2 = 32768.0f;
    uint64_t next_s = 2000, next_status = 20000, next_carrier = 120000;
    for (;;) {
        static uint64_t rd;               /* next sample to process */
        uint64_t wr = samples_written();
        if (wr < rd + BLOCK) continue;
        if (wr - rd > (RING_BLK - 1) * BLOCK) {   /* fell a whole ring behind: skip */
            overruns++;
            rd = (wr / BLOCK - 1) * BLOCK;
        }
        uint32_t c0 = DWT->CYCCNT;
        const uint32_t *b = adc_buf + (rd / BLOCK % RING_BLK) * BLOCK;
        {
            uint32_t a0 = (uint32_t)b & ~31u, a1 = ((uint32_t)(b + BLOCK) + 31) & ~31u;
            SCB_InvalidateDCache_by_Addr((uint32_t *)a0, a1 - a0);
        }
        rd += BLOCK;
        uint32_t lag = (uint32_t)(wr - rd);
        if (lag > max_lag) max_lag = lag;
        double s = 0, s2 = 0;
        for (int i = 0; i < BLOCK; i += 50) { s += b[i] & 0xFFFF; s2 += b[i] >> 16; }
        for (int i = 0; i < BLOCK; i += 7) {
            uint32_t v1 = b[i] & 0xFFFF, v2 = b[i] >> 16;
            if (v1 < adc_min1) adc_min1 = v1;
            if (v1 > adc_max1) adc_max1 = v1;
            if (v2 < adc_min2) adc_min2 = v2;
            if (v2 > adc_max2) adc_max2 = v2;
        }
        mean += 0.01f * ((float)(s / (BLOCK / 50)) - mean);
        mean2 += 0.01f * ((float)(s2 / (BLOCK / 50)) - mean2);
        adc_mean1 = mean; adc_mean2 = mean2;
        if (pl_ok) {                      /* phase-locked mixer for samples rd-BLOCK .. rd */
            double t1 = true_time(200 * (int64_t)rd + pl_c);
            double dt = (t1 - pl_t) * REF_CAP_S;              /* true seconds in this block */
            if (dt > 0.004 && dt < 0.006) {
                double dcyc = F_true * dt;
                double w = -2 * M_PI * dcyc / BLOCK;
                double ph0 = -2 * M_PI * pl_cyc;
                mix_c = (float)cos(ph0); mix_s = (float)sin(ph0);
                rot_c = (float)cos(w); rot_s = (float)sin(w);
                f_mix = dcyc * (FS_NOM_HZ / BLOCK);
                cur_tps_ratio = BLOCK / (dt * FS_NOM_HZ);
                pl_cyc = fmod(pl_cyc + dcyc, 1.0);
                {
                    double d2 = F_DCF * dt, p2 = -2 * M_PI * pl_cyc2, w2 = -2 * M_PI * d2 / BLOCK;
                    mx2_c = (float)cos(p2); mx2_s = (float)sin(p2);
                    rt2_c = (float)cos(w2); rt2_s = (float)sin(w2);
                    pl_cyc2 = fmod(pl_cyc2 + d2, 1.0);
                }
                blk_ratio_sum += cur_tps_ratio; blk_ratio_n++;
            } else pl_cyc = fmod(pl_cyc + F_true * dt, 1.0), pl_cyc2 = fmod(pl_cyc2 + F_DCF * dt, 1.0), pl_bad++;
            pl_t = t1;
        } else if (lse_ok && lse_seq >= 2) {
            pl_calibrate(wr);
            pl_t = true_time(200 * (int64_t)rd + pl_c); pl_cyc = 0;
            pl_t0 = pl_t; pl_n0 = n2k;
            F_true = F_CARRIER;                /* fixed; the carrier trackers follow the rest */
            pl_ok = 1;
        }
        process_block(b, mean, mean2);
        if (!spec_left && n2k >= next_spec) { spec_clear(&spec); spec_left = SPEC_BLOCKS; spec_ctr = 0; next_spec += 1200000; }
        if (spec_left && (++spec_ctr & 3) == 0 && --spec_left >= 0) {   /* every 4th block: ~1 ms per FFT */
            spec_add(&spec, b, mean, mean2);
            if (!spec_left) spec_report();
        }
#ifdef OCXO_REF
        {   /* GPS PPS: convert to true time at once - the capture ring (CAPR) holds only ~128 ms */
            static uint32_t conv;
            uint32_t q = pps_seq;
            if (q != conv && pl_ok) {
                __disable_irq(); uint64_t pt = pps_tick; __enable_irq();
                conv = q; pps_tt = true_time((int64_t)pt); pps_new = 1;
            }
        }
#endif
        {   /* LD1 / LD2: carrier locked, inverted for LED_BLINK after a decode */
            int l1 = trk_e.state == COH_TRACK && trk_e.err_avg * 360 < 25, l2 = dcf_verified();
            if (n2k < led1_until) l1 = !l1;
            if (n2k < led2_until) l2 = !l2;
            HAL_GPIO_WritePin(GPIOB, GPIO_PIN_0, l1 ? GPIO_PIN_SET : GPIO_PIN_RESET);
            HAL_GPIO_WritePin(GPIOE, GPIO_PIN_1, l2 ? GPIO_PIN_SET : GPIO_PIN_RESET);
        }
#ifdef OCXO_REF
        efc_set((uint32_t)efc_tick(&efc, BLOCK / FS_NOM_HZ));   /* ramp + dither, once per block */
#endif
        if (ez.cand_ready) handle_candidate();
        { uint32_t dc = DWT->CYCCNT - c0; busy_cyc += dc; if (dc > max_blk_cyc) max_blk_cyc = dc; }

        if (n2k >= next_s) {              /* once a second */
            next_s += 2000;
            blk_ratio_sum = 0; blk_ratio_n = 0;
            tk_maintain(&tk, now_tick());
#ifdef OCXO_REF
            {   /* GPS PPS: OCXO interval error, e-CzasPL clock and DCF77 second against the GPS second */
                static double t_prev; static uint32_t n_pps;
                if (pps_new) {
                    pps_new = 0; n_pps++;
                    double tt = pps_tt;                                    /* capture units */
                    double n2 = (double)pl_n0 + (tt - pl_t0) * REF_CAP_S / 0.0005;   /* on the 2 kHz scale */
                    char m[220], b1[16], b2[24], b3[24];
                    const char *fr = "-", *ez_s = "-", *dc_s = "-";
                    if (t_prev > 0) {
                        double dt = (tt - t_prev) * REF_CAP_S;             /* OCXO seconds between two GPS seconds */
                        if (dt > 0.9 && dt < 1.1) fr = f1(b1, (1.0 - dt) * 1e9, 1);   /* > 0: OCXO slow */
                    }
                    t_prev = tt;
                    uint32_t sec, us;
                    if (tk.synced && tk_time(&tk, (int64_t)(n2 * (TICKS_PER_BLOCK / 4)), &sec, &us)) {
                        double ms = us / 1000.0; if (ms >= 500) ms -= 1000;     /* > 0: e-CzasPL clock ahead */
                        ez_s = f3(b2, ms);
                    }
                    if (dcf.have_mark) {
                        double start = (double)(((uint64_t)n2 - dcf.mark) / 2000 * 2000 + dcf.mark) + (dcf.pm_sigma > DCF_PM_MIN ? dcf.pm_lag_ms * 2.0 : 0);
                        double x = fmod(n2 - start, 2000.0); if (x < 0) x += 2000; if (x >= 1000) x -= 2000;
                        dc_s = f3(b3, x / 2.0);                            /* > 0: the DCF77 second began before the GPS second */
                    }
                    snprintf(m, sizeof m, "PPS #%lu | OCXO %s ppb (1 s) | e-CzasPL clock %s ms | DCF77 second %s ms%s",
                             (unsigned long)n_pps, fr, ez_s, dc_s, dcf.pm_sigma > DCF_PM_MIN ? " (phase code)" : " (second mark)");
                    put_line("GPS", m);
                }
            }
#endif
            {   /* hourly statistics: expected minutes, hour change */
                uint32_t sec;
                if (tk.synced && tk_time(&tk, now_tick(), &sec, 0)) {
                    if (hs.hour != sec / 3600) { if (hs.hour) hs_report(); hs_start(sec / 3600); }
                    if (sec % 60 >= 3) hs.exp_[(sec % 3600) / 60] = 1;
                }
            }
#ifdef OCXO_REF
            /* LD3 red: on = OCXO locked, blinking = calibrating / moving / holdover, off = waiting or failed */
            if (efc.state == EFC_LOCK && !efc.skip && efc.src != EFC_SRC_NONE) HAL_GPIO_WritePin(GPIOB, GPIO_PIN_14, GPIO_PIN_SET);
            else if (efc.state == EFC_CAL_RAMP || efc.state == EFC_CAL_MEAS || efc.state == EFC_LOCK) HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_14);
            else HAL_GPIO_WritePin(GPIOB, GPIO_PIN_14, GPIO_PIN_RESET);
#endif
        }
        if (n2k >= next_carrier) {        /* every 60 s: both carriers against the LSE crystal */
            next_carrier += 120000;
            coh_report_t re, rd2;
            coh_report(&trk_e, &re); coh_report(&trk_d, &rd2);
            char b4[16], b5[16], b6[16], b7[24], b8[24];
            /* both are measured against the same crystal, so its error cancels in the difference */
            double ppb = (re.freq_hz / F_CARRIER - rd2.freq_hz / F_DCF) * 1e9;
            snprintf(m, sizeof m, "eCzas %s mHz C/N0 %s dB-Hz noise %s deg phase %s cyc %s | DCF77 %s mHz C/N0 %s dB-Hz phase %s cyc %s | eCzas-DCF77 %s ppb",
                     f1(b1, re.freq_hz * 1000, 1), f1(b2, re.cn0_dbhz, 0), f1(b3, re.err_deg, 0), f3(b7, re.phase_cyc),
                     re.state == COH_TRACK ? "locked" : re.state == COH_PULL ? "pulling in" : "searching",
                     f1(b4, rd2.freq_hz * 1000, 1), f1(b5, rd2.cn0_dbhz, 0), f3(b8, rd2.phase_cyc),
                     dcf_state_txt(),
                     (re.state == COH_TRACK && dcf_verified()) ? f1(b6, ppb, 1) : "-");
            put_line("CARRIER", m);
            if (hs.hour) { hs.cn_e += re.cn0_dbhz; hs.cn_d += rd2.cn0_dbhz; hs.ncn++; }
#ifdef OCXO_REF
            {   /* steer the OCXO from both carriers (common/efc.c): DCF77 = accuracy, e-CzasPL with
                   its learned offset removed, weighted by the measured noise */
                /* a station counts only after 2 whole minutes locked: the first minute after (re)lock still
                   holds the pull-in (e-CzasPL +30 ppb after the 20:28 reboot moved the OCXO by 1.8 us) */
                /* and DCF77 only in minutes with C/N0 >= EFC_DCF_CN0_MIN: the rod's DCF77 stayed 'locked' at
                   -14..0 dB-Hz (29/30 Sep nights) with minute errors of 6-20 ppb rms; from 0 dB-Hz up the
                   minutes are noisier but unbiased (4-5 ppb rms at 0-3 dB-Hz), which the adaptive loop averages */
                static int nd, ne;
                nd = (rd2.state == COH_TRACK && dcf_verified() && rd2.cn0_dbhz >= EFC_DCF_CN0_MIN) ? nd + 1 : 0;
                ne = (re.state == COH_TRACK && re.err_deg < 25) ? ne + 1 : 0;
                int vd = nd > 2, ve = ne > 2;
                int src = efc_minute2(&efc, vd, rd2.freq_hz / F_DCF, ve, re.freq_hz / F_CARRIER, 60.0);
                static const char *SRC[] = { "none", "DCF77", "e-CzasPL", "DCF77+e-CzasPL" };
                if (src == EFC_SRC_BOTH && efc.we <= 0) src = EFC_SRC_DCF77;   /* e-CzasPL weight 0: DCF77 steers */
                char b9[16], b10[16];
                snprintf(m, sizeof m, "EFC %s = %s V, %s, source %s (e-CzasPL weight %s), offset %s ppb, time error %s ns, slope %s ppb/code, loop %ld s | e-CzasPL-DCF77 %s ppb (%d min)",
                         f1(b1, efc.c, 0), f3(b7, efc.c * 3.3 / 4096), efc_state_txt(&efc), SRC[src], f3(b9, efc.we),
                         src ? f1(b2, efc.y * 1e9, 1) : "-", f1(b3, efc.x * 1e9, 1), f3(b8, efc.slope * 1e9), lround(efc.tau),
                         efc.bn ? f3(b10, (efc.bn < 10 ? efc.bsum / efc.bn : efc.bias) * 1e9) : "-", efc.bn);
                put_line("OCXO", m);
            }
#endif
        }
#ifdef CLOCK_TEST
        if (lse_log_n == 64) {
            char t[400]; int o2 = snprintf(t, sizeof t, "CLOCK TEST (%s, window %d captures): ppm", 
#ifdef USE_HSI
                "HSI",
#else
                "ST-LINK MCO",
#endif
                LSE_WIN);
            for (int i = 0; i < 64 && o2 < 380; i++) o2 += snprintf(t + o2, sizeof t - o2, " %ld", (long)lround(((double)lse_log[i] / LSE_TPS_NOM - 1) * 1e6));
            strcat(t, "\r\n"); uart_puts(t); lse_log_n = 65;
        }
#endif
        if (n2k >= next_status) {         /* every 10 s */
            next_status += 20000;
            {   /* map the sample count to eCzas time (offline comparisons; same format as before) */
                uint32_t sec, us;
                if (tk_time(&tk, now_tick(), &sec, &us)) {
                    char t[120];
                    snprintf(t, sizeof t, "audio sample %lu = eCzas %lu.%06lu (unix), dcf sample %lu",
                             (unsigned long)n2k, (unsigned long)(sec + 946684800UL), (unsigned long)us, (unsigned long)n2k);
                    put_line("TIMEMAP", t);
                }
            }
            static const char *PS[] = { "searching", "pulling in", "locked" };
            uint32_t sec;
            char d1[40] = "no time yet", b4[16];
            if (tk_time(&tk, now_tick(), &sec, 0)) date_str(d1, sec, 0);
            snprintf(m, sizeof m, "%s | eCzas carrier %s %s Hz noise %s deg lvl0 %s | heard %lu, decoded %lu, confirmed %lu, rejected %lu | DCF77 carrier %s %s mHz | clock %+ld ppm (" REF_NAME ") | cpu %lu%%, longest block %lu ms, max lag %lu ms | adc A0 mean %ld min %lu max %lu, A1 mean %ld min %lu max %lu%s",
                     d1, PS[trk_e.state], f1(b1, trk_e.hz, 1), f1(b2, trk_e.err_avg * 360, 0), f1(b3, trk_e.lvl0 * 360, 0),
                     (unsigned long)n_heard, (unsigned long)n_decoded, (unsigned long)n_conf, (unsigned long)n_rej,
                     dcf_state_txt(), f1(b4, trk_d.hz * 1000, 1), (long)lround((cur_tps_ratio - 1) * 1e6),
                     (unsigned long)(busy_cyc / (SystemCoreClock / 10)), (unsigned long)(max_blk_cyc / (SystemCoreClock / 1000)),
                     (unsigned long)(max_lag / 1000), lroundf(adc_mean1), (unsigned long)adc_min1, (unsigned long)adc_max1,
                     lroundf(adc_mean2), (unsigned long)adc_min2, (unsigned long)adc_max2,
                     overruns ? " OVERRUN" : "");
            if (pl_bad) { strcat(m, " PLBAD"); pl_bad = 0; }
            put_line("STATUS", m);
            overruns = 0; busy_cyc = 0; max_lag = 0; max_blk_cyc = 0;
            adc_min1 = adc_min2 = 65535; adc_max1 = adc_max2 = 0;
        }
    }
}
