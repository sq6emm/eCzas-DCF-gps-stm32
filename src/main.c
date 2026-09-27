/*
 * e-CzasPL 225 kHz receiver on the NUCLEO-H723ZG (M2): direct sampling.
 *
 *   A0 (PA3) --ADC1 16 bit, 1 Msps (TIM6)--> DMA --> mixer at ~225 kHz
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
 * Input circuit: doc/nucleo_225kHz_input.pdf (bias 10k/10k, 100 nF coupling,
 * antenna tuned to ~225 kHz).
 * Output: ST-LINK virtual COM port (USART3), 115200 8N1; with -DAUDIO_DUMP
 * 921600 baud plus binary packets of the core's 10 kHz input.
 */
#include "stm32h7xx_hal.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "dsp.h"
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

#define RING_BLK 8                          /* DMA ring: 40 ms of slack for slow frame decodes */
static uint16_t adc_buf[RING_BLK * BLOCK] __attribute__((aligned(32)));
static volatile uint32_t dma_wraps;
static volatile uint32_t overruns, dma_halves;
static uint32_t max_lag, pl_bad; static uint64_t busy_cyc;

ADC_HandleTypeDef hadc1;
DMA_HandleTypeDef hdma_adc1;
TIM_HandleTypeDef htim6;
UART_HandleTypeDef huart3;
#ifdef AUDIO_DUMP                       /* stream the core's 10 kHz input as binary packets */
#define RX_UART_BAUD 921600
#else
#define RX_UART_BAUD 115200
#endif

static dsp_t g_dsp;
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
static uint64_t audio_n;                  /* 10 kHz samples since start */
static void put_line(const char *tag, const char *msg)
{
    char b[260];
    unsigned long s10 = (unsigned long)(audio_n / 1000);
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
    g.Pin = GPIO_PIN_0 | GPIO_PIN_14; g.Mode = GPIO_MODE_OUTPUT_PP;   /* LD1 green = locked, LD3 red = frame */
    HAL_GPIO_Init(GPIOB, &g);
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
    hdma_adc1.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
    hdma_adc1.Init.MemDataAlignment = DMA_MDATAALIGN_HALFWORD;
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
    htim6.Instance = TIM6;
    htim6.Init.Prescaler = 0; htim6.Init.Period = 199;
    htim6.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim6.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
    HAL_TIM_Base_Init(&htim6);
    TIM_MasterConfigTypeDef m = {0};
    m.MasterOutputTrigger = TIM_TRGO_UPDATE; m.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
    HAL_TIMEx_MasterConfigSynchronization(&htim6, &m);
    HAL_ADC_Start_DMA(&hadc1, (uint32_t *)adc_buf, RING_BLK * BLOCK);
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
#ifndef LSE_WIN
#define LSE_WIN 4096                     /* captures per measurement: 4096 = 1 s, 512 = 1/8 s */
#endif
#define LSE_TPS_NOM (200000000.0 * LSE_WIN / 4096.0)
static volatile uint32_t lse_last, lse_sum, lse_cnt, lse_tps, lse_seq;
static volatile uint32_t lse_log[64]; static volatile int lse_log_n;
static volatile uint64_t lse_tot_ticks, lse_tot_caps;   /* running totals for per-block rate */
#define CAPR 512                           /* ring of capture tick counts (125 ms) */
static volatile uint64_t cap_tick[CAPR];
static int lse_ok;
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
void TIM16_IRQHandler(void)
{
    if (TIM16->SR & TIM_SR_CC1IF) {
        uint32_t c = TIM16->CCR1;              /* reading CCR1 clears CC1IF */
        uint32_t d = (c - lse_last) & 0xFFFF;
        lse_last = c;
        if (lse_cnt) { lse_sum += d; lse_tot_ticks += d; lse_tot_caps++; }
        cap_tick[lse_tot_caps % CAPR] = lse_tot_ticks;
        if (++lse_cnt == LSE_WIN + 1) { lse_tps = lse_sum; lse_seq++; lse_sum = 0; lse_cnt = 1;
            if (lse_log_n < 64) lse_log[lse_log_n++] = lse_tps; }
    }
    TIM16->SR = 0;
}

static double cur_tps_ratio = 1.0;        /* true / nominal sample rate */
static double blk_ratio_sum; static int blk_ratio_n;   /* averages for the per-second timebase */

/* ---------------------------------------------------------------- front end */
/* mixer: running phasor, rotation per ADC sample (probe scale); f_mix in Hz of
   the probe's nominal 1 MHz scale, i.e. where the carrier appears */
static double f_mix;
static float mix_c = 1, mix_s = 0, rot_c, rot_s;
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
static uint64_t dsp_base_n;                /* audio sample index of the core's block 1 */
static int pl_ok;                          /* calibrated: tick of sample k = 200 k + pl_c */
static int64_t pl_c;
static double F_true = F_CARRIER;          /* mixer frequency in true Hz */
static double pl_t;                        /* true time (capture units) at the next block start */
static double pl_cyc;                      /* mixer phase (cycles, fractional) at the next block start */
static void pl_calibrate(uint64_t written)
{
    __disable_irq();
    uint32_t n16 = TIM16->CNT, c6 = TIM6->CNT, ll = lse_last;
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
/* 1 kHz shift of the 10 kHz stream: exact 10-step cycle */
static const float sh_c[10] = { 1, 0.809017f, 0.309017f, -0.309017f, -0.809017f, -1, -0.809017f, -0.309017f, 0.309017f, 0.809017f };
static const float sh_s[10] = { 0, 0.587785f, 0.951057f, 0.951057f, 0.587785f, 0, -0.587785f, -0.951057f, -0.951057f, -0.587785f };
static int sh_i;
static float agc = 1e-3f;                /* audio scale, slow AGC to ~25 % of full scale */
static int16_t blk[DSP_BLOCK];
static int blk_n;

/* acquisition FFT over +-500 Hz: 1 kHz complex (sum of 10 of the 10 kHz samples) */
#define AQ_LEN 8192
static float aq_re[AQ_LEN], aq_im[AQ_LEN];
static int aq_n = -1;                    /* -1 = not acquiring */
static float aq_sr, aq_si; static int aq_k;

static void fft(float *re, float *im, int n)
{
    for (int i = 1, j = 0; i < n; i++) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) { float t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
    }
    for (int len = 2; len <= n; len <<= 1) {
        float ang = -2.0f * (float)M_PI / len, wr = cosf(ang), wi = sinf(ang);
        for (int i = 0; i < n; i += len) {
            float cr = 1, ci = 0;
            for (int k = 0; k < len / 2; k++) {
                int a = i + k, b = a + len / 2;
                float tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
                re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
                float t = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = t;
            }
        }
    }
}

static void acquisition_done(void)
{
    char m[200], b1[16], b2[16];
    static float pw[AQ_LEN];
    fft(aq_re, aq_im, AQ_LEN);
    int best = -1; double sum = 0; int ns = 0;
    for (int k = 0; k < AQ_LEN; k++) {
        double f = (k < AQ_LEN / 2 ? k : k - AQ_LEN) * 1000.0 / AQ_LEN;
        pw[k] = aq_re[k] * aq_re[k] + aq_im[k] * aq_im[k];
        if (fabs(f) > 450) continue;
        sum += pw[k]; ns++;
        if (best < 0 || pw[k] > pw[best]) best = k;
    }
    double f = (best < AQ_LEN / 2 ? best : best - AQ_LEN) * 1000.0 / AQ_LEN;
    double snr = 10 * log10(pw[best] / (sum / ns));
    if (pl_ok) F_true += f; else set_mix(f_mix + f);   /* put the strongest line on the carrier position */
    snprintf(m, sizeof m, "carrier search: strongest line %s Hz, %s dB above average -> mixer %lu Hz (clock %+ld ppm)",
             f1(b1, f, 1), f1(b2, snr, 1), (unsigned long)lround(f_mix),
             (long)lround((F_CARRIER / f_mix - 1) * 1e6));
    put_line("SEARCH", m);
    dsp_init(&g_dsp);                    /* fresh acquisition on the new frequency */
    dsp_base_n = audio_n - 1 - blk_n;    /* the core counts blocks from here (current sample goes to blk[blk_n]) */
    aq_n = -1;
}

/* one DMA block: mix, decimate, shift to 1 kHz, feed the core */
static double dec_pos;                   /* input samples still owed to the current 10 kHz output */
static float acc_r, acc_i;
static void emit_sample(float zr, float zi)
{
    audio_n++;
    if (aq_n >= 0) {                      /* acquisition: 1 kHz complex samples */
        aq_sr += zr; aq_si += zi;
        if (++aq_k == 10) {
            aq_re[aq_n] = aq_sr; aq_im[aq_n] = aq_si; aq_sr = aq_si = 0; aq_k = 0;
            if (++aq_n == AQ_LEN) acquisition_done();
        }
    }
    float y = zr * sh_c[sh_i] - zi * sh_s[sh_i];     /* carrier to +1 kHz, real part */
    if (++sh_i == 10) sh_i = 0;
    float a = fabsf(y) * agc;
    agc *= (a > 12000.0f) ? 0.999f : 1.0001f;
    float v = y * agc;
    if (v > 32000) v = 32000;
    if (v < -32000) v = -32000;
    blk[blk_n++] = (int16_t)v;
#ifdef AUDIO_DUMP
    {   /* packet: A5 5A, u32 sample index of the first sample, 200 x int16 */
        static struct __attribute__((packed)) { uint8_t m0, m1; uint32_t n0; int16_t x[200]; } pk = { 0xA5, 0x5A, 0, {0} };
        static int pn;
        if (pn == 0) pk.n0 = (uint32_t)(audio_n - 1);
        pk.x[pn++] = (int16_t)v;
        if (pn == 200) { uart_write(&pk, sizeof pk); pn = 0; }
    }
#endif
    if (blk_n == DSP_BLOCK) { blk_n = 0; dsp_block(&g_dsp, blk); }
}

/* one DMA block: mix, then sum over exactly 100 us of TRUE time per output
   sample (100 x clock ratio input samples; the fractional sample is split) */
static void process_block(const uint16_t *b, float mean)
{
    double step = 100.0 * cur_tps_ratio;  /* input samples per true 100 us */
    for (int n = 0; n < BLOCK; n++) {
        float x = (float)b[n] - mean;
        float xr = x * mix_c, xi = x * mix_s;
        float t = mix_c * rot_c - mix_s * rot_s;
        mix_s = mix_c * rot_s + mix_s * rot_c; mix_c = t;
        if (dec_pos + 1.0 <= step) {       /* whole sample belongs to this output */
            acc_r += xr; acc_i += xi; dec_pos += 1.0;
        } else {                           /* split it between this output and the next */
            float f = (float)(step - dec_pos);
            emit_sample(acc_r + f * xr, acc_i + f * xi);
            acc_r = (1 - f) * xr; acc_i = (1 - f) * xi;
            dec_pos = 1.0 - f;
        }
    }
    float m = 1.0f / sqrtf(mix_c * mix_c + mix_s * mix_s);
    mix_c *= m; mix_s *= m;
}

/* ---------------------------------------------------------------- frames */
static int64_t sample_tick(uint64_t n)    /* the 10 kHz stream runs on crystal time */
{
    return (int64_t)n * TICKS_PER_SAMPLE;
}
static int64_t now_tick(void) { return sample_tick(audio_n); }

static void handle_candidate(void)
{
    dsp_cand_t *c = &g_dsp.cand;
    frame_info_t fi;
    char m[240], d1[40], b1[16];
    int64_t tick = sample_tick(dsp_base_n + (uint64_t)(c->start_block - 1) * DSP_BLOCK);
    memset(&fi, 0, sizeof fi);
    frame_status_t st = frame_decode(c->ph + CAND_PRE, &fi);
    if (st == FR_NOT_TIME) { g_dsp.cand_ready = 0; return; }
    n_heard++;
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
                date_str(d1, 3UL * n3p, fe.tz);
                snprintf(m, sizeof m, "#%lu not decodable, but %d%% agrees with the expected frame: %s%s",
                         (unsigned long)n_heard, sc * 100 / 1024, d1, r == TK_ACCEPTED ? " - confirmed" : "");
                put_line("FRAME", m);
                g_dsp.cand_ready = 0;
                return;
            }
        }
    }
    if (st != FR_OK) {
        snprintf(m, sizeof m, "#%lu corr %d%% - not decodable (snr %d dB)", (unsigned long)n_heard, c->corr_q10 * 100 / 1024, fi.snr_db);
        put_line("FRAME", m);
        g_dsp.cand_ready = 0;
        return;
    }
    tick += (int64_t)fi.timing_q15 * TICKS_PER_BLOCK / 32768;
    int32_t off_ms = 0;
    if (tk.synced) off_ms = (int32_t)((tick - tk_second_tick(&tk, 3UL * fi.n3)) / (FCY_HZ / 1000));
    tk_result_t r = tk_frame(&tk, tick, &fi);
    n_decoded++;
    HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_14);
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
    if (r == TK_ACCEPTED || r == TK_SYNCED || r == TK_STEPPED) { last_fi = fi; have_last_fi = 1; }
    g_dsp.cand_ready = 0;
}

/* ---------------------------------------------------------------- main */
int main(void)
{
    char m[260], b1[16], b2[16], b3[16];
    SCB_EnableICache();
    SCB_EnableDCache();
    HAL_Init();
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk; DWT->CYCCNT = 0; DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    clock_init();
    gpio_uart_init();
    uart_puts("\r\n\r\ne-CzasPL 225 kHz receiver on NUCLEO-H723ZG (M2: direct sampling, eCzas core, wide tracking)\r\n");
    dsp_init(&g_dsp);
    tk_init(&tk);
    lse_init();
    set_mix(F_CARRIER * FS_NOM_HZ / FS_GUESS_HZ);
    adc_init();
    if (lse_ok) {                        /* first LSE measurement (~1 s) sets the mixer */
        uint32_t t0 = HAL_GetTick();
        while (lse_seq < 2 && HAL_GetTick() - t0 < 3000) {}
        if (lse_seq >= 2) { cur_tps_ratio = (double)lse_tps / LSE_TPS_NOM; set_mix(F_CARRIER / cur_tps_ratio); }
        snprintf(m, sizeof m, "LSE crystal reference OK: Nucleo clock %+ld ppm, mixer %lu Hz\r\n",
                 (long)lround((cur_tps_ratio - 1) * 1e6), (unsigned long)lround(f_mix));
    } else snprintf(m, sizeof m, "LSE crystal NOT running - no drift correction\r\n");
    uart_puts(m);
    aq_n = 0;                            /* start with a carrier search */

    float mean = 32768.0f;
    uint64_t next_s = 10000, next_status = 100000, unlocked_since = 0;
    for (;;) {
        static uint64_t rd;               /* next sample to process */
        uint64_t wr = samples_written();
        if (wr < rd + BLOCK) continue;
        if (wr - rd > (RING_BLK - 1) * BLOCK) {   /* fell a whole ring behind: skip */
            overruns++;
            rd = (wr / BLOCK - 1) * BLOCK;
        }
        uint32_t c0 = DWT->CYCCNT;
        const uint16_t *b = adc_buf + (rd / BLOCK % RING_BLK) * BLOCK;
        {
            uint32_t a0 = (uint32_t)b & ~31u, a1 = ((uint32_t)(b + BLOCK) + 31) & ~31u;
            SCB_InvalidateDCache_by_Addr((uint32_t *)a0, a1 - a0);
        }
        rd += BLOCK;
        uint32_t lag = (uint32_t)(wr - rd);
        if (lag > max_lag) max_lag = lag;
        double s = 0;
        for (int i = 0; i < BLOCK; i += 50) s += b[i];
        mean += 0.01f * ((float)(s / (BLOCK / 50)) - mean);
        if (pl_ok) {                      /* phase-locked mixer for samples rd-BLOCK .. rd */
            double t1 = true_time(200 * (int64_t)rd + pl_c);
            double dt = (t1 - pl_t) * (8.0 / 32768.0);        /* true seconds in this block */
            if (dt > 0.004 && dt < 0.006) {
                double dcyc = F_true * dt;
                double w = -2 * M_PI * dcyc / BLOCK;
                double ph0 = -2 * M_PI * pl_cyc;
                mix_c = (float)cos(ph0); mix_s = (float)sin(ph0);
                rot_c = (float)cos(w); rot_s = (float)sin(w);
                f_mix = dcyc * (FS_NOM_HZ / BLOCK);
                cur_tps_ratio = BLOCK / (dt * FS_NOM_HZ);
                pl_cyc = fmod(pl_cyc + dcyc, 1.0);
                blk_ratio_sum += cur_tps_ratio; blk_ratio_n++;
            } else pl_cyc = fmod(pl_cyc + F_true * dt, 1.0), pl_bad++;
            pl_t = t1;
        } else if (lse_ok && lse_seq >= 2) {
            pl_calibrate(wr);
            pl_t = true_time(200 * (int64_t)rd + pl_c); pl_cyc = 0;
            F_true = f_mix * cur_tps_ratio;
            pl_ok = 1;
        }
        process_block(b, mean);
        if (g_dsp.cand_ready) handle_candidate();
        busy_cyc += DWT->CYCCNT - c0;

        if (audio_n >= next_s) {          /* once a second */
            uint64_t k = next_s / 10000;
            next_s += 10000;
            blk_ratio_sum = 0; blk_ratio_n = 0;
            (void)k;
            tk_maintain(&tk, now_tick());
            HAL_GPIO_WritePin(GPIOB, GPIO_PIN_0, g_dsp.pll_state == PLL_TRACK ? GPIO_PIN_SET : GPIO_PIN_RESET);
            /* outer loop: keep the carrier at 1 kHz in the 10 kHz stream */
            if (g_dsp.pll_state != PLL_ACQ_FLL && aq_n < 0) {
                double df = dsp_carrier_centihz(&g_dsp) / 100.0 - AUDIO_CARRIER_HZ;
                if (fabs(df) > 3.0) {
                    int32_t units = (int32_t)lround(df * 4294967296.0 / ADC_FS_HZ);
                    if (pl_ok) F_true += df; else set_mix(f_mix + df);
                    g_dsp.nco_freq -= units;
                    if (g_dsp.have_lock_freq) g_dsp.lock_freq -= units;
                }
            }
            if (g_dsp.pll_state == PLL_TRACK) unlocked_since = 0;
            else if (!unlocked_since) unlocked_since = audio_n;
            if (unlocked_since && aq_n < 0 && audio_n - unlocked_since > 300000) {   /* 30 s */
                put_line("SEARCH", "no carrier lock for 30 s - searching +-450 Hz");
                aq_n = 0; aq_k = 0; aq_sr = aq_si = 0; unlocked_since = 0;
            }
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
        if (audio_n >= next_status) {     /* every 10 s */
            next_status += 100000;
            static const char *PS[] = { "searching", "locking (fast)", "locking", "locked" };
            uint32_t sec;
            char d1[40] = "no time yet";
            if (tk_time(&tk, now_tick(), &sec, 0)) date_str(d1, sec, 0);
            snprintf(m, sizeof m, "%s | carrier %s, noise %s deg | mixer %lu Hz, clock %+ld ppm (LSE) | heard %lu, decoded %lu, confirmed %lu, rejected %lu | cpu %lu%%, max lag %lu ms%s",
                     d1, PS[g_dsp.pll_state], f1(b1, (g_dsp.lock_err_avg >> 4) * 360.0 / 65536.0, 0),
                     (unsigned long)lround(f_mix), (long)lround((cur_tps_ratio - 1) * 1e6),
                     (unsigned long)n_heard, (unsigned long)n_decoded, (unsigned long)n_conf, (unsigned long)n_rej,
                     (unsigned long)(busy_cyc / (SystemCoreClock / 10)), (unsigned long)(max_lag / 1000),
                     overruns ? " OVERRUN" : "");
            if (pl_bad) { strcat(m, " PLBAD"); pl_bad = 0; }
            (void)b2; (void)b3;
            put_line("STATUS", m);
            overruns = 0; busy_cyc = 0; max_lag = 0;
        }
    }
}
