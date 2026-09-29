"""NUCLEO-H723ZG e-CzasPL + DCF77 receiver: architecture document -> doc/nucleo_architecture.pdf
  docker run --rm -e HOME=/tmp -v $PWD/doc:/o python:3.12-slim sh -c \
    "pip -q install --user reportlab matplotlib && python3 /o/nucleo_architecture.py"
State: firmware commit e436259 (29 Sep 2026). Numbers marked 'measured' come from the logs of 28-29 Sep 2026.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak)

BLUE = "#1f4e79"; RED = "#b22222"; GREEN = "#2e7d32"; PURPLE = "#6a1b9a"; GREY = "#666666"; ORANGE = "#c05800"


# ------------------------------------------------------------------ diagrams
def box(ax, x, y, w, h, text, col, fs=8.5, fc=None):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02", fc=fc or "white", ec=col, lw=1.4))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color="black")


def arrow(ax, x1, y1, x2, y2, col="black", text=None, fs=7, off=(0, 0.12)):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color=col, lw=1.2))
    if text: ax.text((x1 + x2) / 2 + off[0], (y1 + y2) / 2 + off[1], text, ha="center", fontsize=fs, color=col)


def fig_hardware(fn):
    fig, ax = plt.subplots(figsize=(10, 5.6)); ax.set_xlim(0, 10); ax.set_ylim(0, 5.6); ax.axis("off")
    box(ax, 0.1, 4.2, 1.9, 0.9, "ROD 1  360 µH\n+ 1.5 nF\n225 kHz", RED)
    box(ax, 0.1, 2.9, 1.9, 0.9, "ROD 2  375 µH\n+ 11.2 nF\n77.5 kHz", BLUE)
    box(ax, 2.4, 3.4, 1.7, 1.4, "input network\n330 Ω series\n1.65 V bias node\n(shared, 1 µF)", GREY, fs=8)
    arrow(ax, 2.0, 4.65, 2.4, 4.4, RED); arrow(ax, 2.0, 3.35, 2.4, 3.7, BLUE)
    ax.add_patch(FancyBboxPatch((4.5, 0.4), 4.0, 4.8, boxstyle="round,pad=0.02", fc="#f4f7fb", ec=BLUE, lw=1.6))
    ax.text(6.5, 5.0, "NUCLEO-H723ZG  (Cortex-M7, 400 MHz from HSI)", ha="center", fontsize=9, weight="bold", color=BLUE)
    box(ax, 4.7, 4.0, 1.7, 0.6, "ADC1 16 bit\nA0 = PA3", RED, fs=8)
    box(ax, 4.7, 3.2, 1.7, 0.6, "ADC2 16 bit\nA1 = PC0 (INP10)", BLUE, fs=8)
    arrow(ax, 4.1, 4.3, 4.7, 4.3, RED); arrow(ax, 4.1, 3.6, 4.7, 3.5, BLUE)
    box(ax, 6.7, 3.4, 1.6, 1.1, "TIM6 1 MHz trigger\ndual simultaneous\nDMA 32-bit words\nring 6 x 5 ms", GREY, fs=7.5)
    arrow(ax, 6.4, 4.3, 6.7, 4.1); arrow(ax, 6.4, 3.5, 6.7, 3.7)
    box(ax, 4.7, 1.9, 1.7, 0.9, "TIM3 captures\nat 200 MHz\n= true time", PURPLE, fs=7.5)
    box(ax, 6.7, 1.9, 1.6, 0.9, "TIM2 counts OCXO\n(ETR on PA0)\nTRGO every 2500", PURPLE, fs=7.5)
    arrow(ax, 6.7, 2.35, 6.4, 2.35, PURPLE)
    ax.text(6.55, 2.85, "4 kHz", ha="center", fontsize=7, color=PURPLE)
    box(ax, 4.7, 0.6, 1.7, 0.9, "USART3 -> ST-LINK\nUSB virtual COM\n921600 baud", GREY, fs=7.5)
    box(ax, 6.7, 0.6, 1.6, 0.9, "DAC1 ch2\nPA5 (12 bit,\ndithered)", ORANGE, fs=7.5)
    box(ax, 8.9, 1.2, 1.0, 1.4, "CTI\nOSC5A2B02\n10 MHz\nOCXO\n(own 5 V)", PURPLE, fs=7.5)
    arrow(ax, 8.9, 2.35, 8.3, 2.35, PURPLE)
    ax.text(9.4, 2.75, "OUT via 1 kΩ", ha="center", fontsize=6.5, color=PURPLE)
    arrow(ax, 8.3, 1.05, 8.9, 1.05, ORANGE)
    ax.text(9.4, 0.85, "EFC", ha="center", fontsize=6.5, color=ORANGE)
    box(ax, 8.9, 3.8, 1.0, 1.1, "LEDs\nLD1 e-CzasPL\nLD2 DCF77\nLD3 OCXO", GREY, fs=7)
    ax.text(0.1, 0.35, "USB to the 'power' server:\nnucleo-logger (log + 2 kHz\nbaseband dumps), flashing", fontsize=7.5, color=GREY)
    arrow(ax, 4.7, 1.05, 2.3, 0.8, GREY)
    fig.savefig(fn, dpi=170, bbox_inches="tight"); plt.close(fig)



def path(ax, pts, col):
    xs, ys = zip(*pts)
    ax.plot(xs[:-1] + (xs[-1],), ys[:-1] + (ys[-1],), color=col, lw=1.2)
    ax.annotate("", xy=pts[-1], xytext=pts[-2], arrowprops=dict(arrowstyle="->", color=col, lw=1.2))

def fig_signal(fn):
    fig, ax = plt.subplots(figsize=(10, 6.4)); ax.set_xlim(0, 10); ax.set_ylim(0, 6.4); ax.axis("off")
    box(ax, 0.1, 5.2, 2.0, 0.9, "ADC samples\n1 Msps x 2\n(5 ms blocks)", GREY)
    box(ax, 2.5, 5.2, 2.3, 0.9, "true time per block\n(OCXO captures,\ninterpolated)", PURPLE)
    arrow(ax, 2.1, 5.65, 2.5, 5.65)
    box(ax, 5.2, 5.6, 2.2, 0.6, "mixer 225 kHz  (A0)", RED)
    box(ax, 5.2, 4.8, 2.2, 0.6, "mixer 77.5 kHz  (A1)", BLUE)
    arrow(ax, 4.8, 5.65, 5.2, 5.9); arrow(ax, 4.8, 5.65, 5.2, 5.1)
    box(ax, 7.8, 5.2, 2.1, 1.0, "sum over exactly\n500 µs of true time\n-> 2 kHz complex", GREY)
    arrow(ax, 7.4, 5.9, 7.8, 5.8); arrow(ax, 7.4, 5.1, 7.8, 5.5)
    ax.text(5.1, 6.3, "phase-locked: mixer phase = -2 pi F t_true at every block", fontsize=7.5, color=PURPLE)
    # e-CzasPL branch
    box(ax, 0.1, 3.2, 2.3, 1.0, "carrier tracker\n(coh.c, e-CzasPL mode)\ndecision-directed PLL\n~1 Hz, 2 ms updates", RED, fs=7.5)
    box(ax, 2.8, 3.2, 2.1, 1.0, "phase stream 500 Hz\n-> preamble detector\n(ecz.c)", RED, fs=7.5)
    box(ax, 5.3, 3.2, 2.3, 1.0, "eCzas 2.0.5 core\nframe.c: RS decode\ntimekeeper.c: clock", RED, fs=7.5)
    box(ax, 8.0, 3.2, 1.9, 1.0, "FRAME / CLOCK\nconfirm by expected\nframe, reject early", RED, fs=7.5)
    path(ax, [(8.6, 5.2), (8.6, 4.5), (1.25, 4.5), (1.25, 4.2)], RED); arrow(ax, 2.4, 3.7, 2.8, 3.7, RED); arrow(ax, 4.9, 3.7, 5.3, 3.7, RED); arrow(ax, 7.6, 3.7, 8.0, 3.7, RED)
    # DCF77 branch
    box(ax, 0.1, 1.5, 2.3, 1.1, "carrier tracker\n(coh.c, plain PLL)\n0.01 Hz, 10 s updates\nblind pull-in at 0 Hz", BLUE, fs=7.5)
    box(ax, 2.8, 1.5, 2.1, 1.1, "dcf.c: folds\nsecond mark, minute,\nphase code (PTB PN)\n10-min block, 4 steps", BLUE, fs=7.5)
    box(ax, 5.3, 1.5, 2.3, 1.1, "dcfbits.c: minute\nAM + phase-code bits\nparity / BCD checks\nconfirmation", BLUE, fs=7.5)
    box(ax, 8.0, 1.5, 1.9, 1.1, "DCF77 TIME\n(compared with\ne-CzasPL, never used\nfor the clock)", BLUE, fs=7.5)
    path(ax, [(9.3, 5.2), (9.3, 4.65), (9.95, 4.65), (9.95, 2.9), (1.25, 2.9), (1.25, 2.6)], BLUE); arrow(ax, 2.4, 2.05, 2.8, 2.05, BLUE); arrow(ax, 4.9, 2.05, 5.3, 2.05, BLUE); arrow(ax, 7.6, 2.05, 8.0, 2.05, BLUE)
    # OCXO loop
    box(ax, 2.8, 0.05, 7.1, 1.0, "efc.c - OCXO steering once a minute: DCF77 carrier = reference, adaptive loop 600-3600 s,\nrate limit 1e-10/s, sigma-delta dither -> DAC -> EFC;  e-CzasPL (learned offset) only if DCF77 is lost", ORANGE, fs=7.5)
    path(ax, [(1.25, 1.5), (1.25, 0.6), (2.8, 0.6)], ORANGE)
    ax.text(1.35, 1.05, "carrier\nfrequency", fontsize=7, color=ORANGE)
    path(ax, [(0.1, 3.7), (0.03, 3.7), (0.03, 0.3), (2.8, 0.3)], ORANGE)
    ax.text(0.1, 0.05, "(e-CzasPL: fallback)", fontsize=6.5, color=ORANGE)
    fig.savefig(fn, dpi=170, bbox_inches="tight"); plt.close(fig)


def fig_timing(fn):
    fig, ax = plt.subplots(figsize=(8, 2.4)); ax.set_xlim(0, 33); ax.set_ylim(0.3, 3); ax.axis("off")
    for i in range(6):
        ax.add_patch(plt.Rectangle((i * 5, 1.9), 5, 0.7, fc="#e8eef6" if i % 2 else "#dfe7f2", ec=BLUE))
        ax.text(i * 5 + 2.5, 2.25, f"block {i}\n5 ms", ha="center", va="center", fontsize=9)
    ax.text(30.3, 2.25, "ring\n30 ms", fontsize=9, va="center", color=BLUE)
    for x0, w, t, c in ((0, 1, "normal ~1 ms", GREEN), (7, 8, "10-min DCF77 step ~8 ms", ORANGE),
                        (17, 16, "early mark check ~16 ms (once after boot)", ORANGE)):
        ax.add_patch(plt.Rectangle((x0, 1.1), w, 0.5, fc=c, alpha=0.6)); ax.text(x0, 0.75, t, fontsize=8.5)
    fig.savefig(fn, dpi=170, bbox_inches="tight"); plt.close(fig)


fig_hardware("/tmp/a_hw.png"); fig_signal("/tmp/a_sig.png"); fig_timing("/tmp/a_tim.png")

# ------------------------------------------------------------------ document
ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], textColor=colors.HexColor(BLUE), fontSize=15, spaceAfter=6)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], textColor=colors.HexColor(BLUE), fontSize=12, spaceBefore=8, spaceAfter=4)
P = ParagraphStyle("P", parent=ss["BodyText"], fontSize=9, leading=12)
S = ParagraphStyle("S", parent=P, fontSize=7.5, leading=9.5, textColor=colors.HexColor(GREY))
TC = ParagraphStyle("TC", parent=P, fontSize=8, leading=10)


def tbl(rows, widths, head=True):
    data = [[Paragraph(str(c), TC) for c in r] for r in rows]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if head else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b8c4")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    if head: st += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfe7f2"))]
    t.setStyle(TableStyle(st)); return t


def img(fn, w_mm):
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(fn).getSize(); return Image(fn, width=w_mm * mm, height=w_mm * mm * ih / iw)


story = []
story += [Paragraph("NUCLEO-H723ZG time receiver: e-CzasPL 225 kHz + DCF77 77.5 kHz + OCXO", H1),
          Paragraph("Architecture of the current hardware and firmware - state of 29 September 2026, firmware commit e436259, "
                    "repository sq6emm/eCzas-DCF-gps-stm32 (firmware/nucleo-h723, firmware/common). SQ6EMM / e-CzasPL receiver experiments.", S),
          Spacer(1, 4)]

story += [Paragraph("1. Purpose and overview", H2), Paragraph(
    "A software-defined receiver for two long-wave time signals on one inexpensive development board. Two tuned ferrite rods feed two "
    "16-bit ADCs that sample the band directly at 1 Msps; everything else is software: phase-locked mixers, coherent carrier trackers, "
    "the unchanged e-CzasPL firmware core for the time frames, an own DCF77 receiver with a per-minute time-code decoder, and a loop that "
    "steers a 10 MHz OCXO to the received carriers. The board runs continuously; a logger on the 'power' server records its text log and "
    "the two 2 kHz baseband streams for offline analysis.", P)]
story += [tbl([["", "e-CzasPL", "DCF77"],
               ["transmitter", "Solec Kujawski, 234 km, bearing 20°", "Mainflingen, 580 km, bearing 261°"],
               ["carrier / modulation", "225 kHz, phase modulation, 50 b/s, 3-s slots", "77.5 kHz, AM second marks + pseudo-random phase code"],
               ["what the NUCLEO takes from it", "time of day (clock), carrier frequency", "carrier frequency (OCXO reference), second, minute time code"],
               ["role", "the receiver's clock (e-CzasPL core)", "frequency reference for the OCXO; independent time check"]],
              [42, 64, 64])]

story += [Paragraph("2. Hardware", H2), img("/tmp/a_hw.png", 170), Spacer(1, 3)]
story += [tbl([["part", "connection", "notes"],
               ["ROD 1 (225 kHz)", "A0 = PA3 -> ADC1", "360 µH ferrite rod, 1.5 nF tuning capacitor at the board, 330 Ω series"],
               ["ROD 2 (77.5 kHz)", "A1 = PC0 -> ADC2 (INP10)", "375 µH rod, 10 nF + 1.2 nF at the board, 330 Ω series"],
               ["bias", "shared 1.65 V node, 1 µF", "both inputs biased to mid-scale (ADC mean ~32280 of 65535)"],
               ["OCXO CTI OSC5A2B02", "OUT -> 1 kΩ -> PA0 (TIM2_ETR); EFC <- PA5 (DAC1 ch2); own 5 V", "10 MHz HCMOS; EFC slope measured +0.816 ppb per DAC code (1.07 ppm/V); locked near code 2252 = 1.815 V"],
               ["MCU clock", "HSI (16 MHz into the PLL) -> 400 MHz core, 200 MHz timers", "the board has no crystal; HSI is ~+0.6 % off and wanders - the firmware measures it against the OCXO continuously"],
               ["USB (ST-LINK)", "USART3 virtual COM, 921600 baud", "text log + binary baseband packets; also flashing (st-flash)"],
               ["LEDs", "LD1 green, LD2 yellow, LD3 red", "LD1 e-CzasPL / LD2 DCF77: on = carrier locked, short blink = decode; LD3: on = OCXO locked, 1 Hz = calibrating/holdover"]],
              [34, 55, 81]),
          Paragraph("Input wiring: doc/nucleo_225_77kHz_input.pdf. OCXO wiring: doc/nucleo_ocxo_test_b.pdf.", S)]

story += [Paragraph("3. Time base: sampling on true (OCXO) time", H2), Paragraph(
    "TIM6 triggers both ADCs together every 200 timer ticks (1 Msps, dual regular simultaneous mode); DMA writes 32-bit words "
    "(ADC2 << 16 | ADC1) into a ring of 6 blocks of 5000 samples (30 ms). Because the CPU/timer clock (HSI) is ~6000 ppm off and wanders, "
    "sample count is not time. Therefore TIM2 counts the OCXO's 10 MHz on its external-clock input and produces a trigger every 2500 cycles "
    "(4 kHz); TIM3 timestamps each trigger in timer ticks. Interpolating between these captures gives the true time of every ADC sample. "
    "The previous build used the LSE watch crystal the same way (TIM16); -DOCXO_REF selects the OCXO.", P),
    Paragraph("Consequences: the mixers are phase-locked to true time (their phase is set to -2 pi F t_true at every 5 ms block), and the "
              "decimator sums exactly 500 µs of true time per output sample (fractional samples are split). So the HSI wander never appears as "
              "carrier phase noise, and every carrier measurement is a measurement against the OCXO.", P)]

story += [Paragraph("4. Signal chain", H2), img("/tmp/a_sig.png", 170)]
story += [tbl([["stage", "e-CzasPL", "DCF77"],
               ["mixer + decimation", "225 kHz, 2 kHz complex baseband", "77.5 kHz, 2 kHz complex baseband"],
               ["carrier tracker (coh.c)", "search: 2-s FFT; decision-directed 2nd-order PLL on the two data phase levels, ~1 Hz, updates every 2 ms",
                "blind pull-in at 0 Hz (OCXO build; FFT search 128 s as fallback after 3 min); plain PLL 0.01 Hz, updates every 10 s; "
                "counts as locked only when its second marks are verified (spur rule: a line without marks is rejected after 60 min)"],
               ["data", "carrier-relative phase at 500 Hz -> ecz.c preamble detector -> eCzas 2.0.5 core (frame.c Reed-Solomon, CRC; "
                        "timekeeper.c clock, sync, rejection of frames that disagree with the clock; confirmation of undecodable frames by the expected frame)",
                "dcf.c: second mark (fold of the 100/200 ms reductions), minute marker (second 59), phase code (fold of the fixed-sign seconds "
                "correlated with the PTB sequence, anchored at pm_ref); dcfbits.c: per-minute AM + phase-code bits, parities, BCD ranges, "
                "confirmation by a second decode or by the expected frame"],
               ["evaluation", "per frame (every 3-s slot)", "every 10 min (block, in four ~8 ms steps 0.1 s apart); early checks every 10 s until "
                                                           "the first block: marks ~2 min, minute ~6 min, phase code ~7 min after boot"]],
              [30, 68, 72])]

story += [PageBreak(), Paragraph("5. OCXO steering (efc.c)", H2), Paragraph(
    "Once a minute each carrier tracker reports its mean frequency against the OCXO time base (y = f / F; y > 0 means the OCXO runs slow). "
    "The steering loop turns that into a DAC code:", P)]
story += [tbl([["element", "current setting"],
               ["reference", "DCF77 carrier (PTB-steered) only (EFC_WE_MAX 0); e-CzasPL steers only when DCF77 is lost, with its offset to DCF77 "
                             "learned while DCF77 is clean (minute noise < 2 ppb)"],
               ["start", "straight into lock at code 2253 with the known slope 0.816 ppb/code; a station counts after 2 whole locked minutes"],
               ["loop", "2nd-order PLL on the carrier phase (time error = integral of y), damping 0.7; time constant 600 s by day, lengthened "
                        "automatically up to 3600 s when DCF77's minute noise grows (night)"],
               ["actuator", "DAC1 ch2 12 bit on PA5 -> EFC directly; changes rate-limited to 1e-10 / s (the 0.01 Hz DCF77 loop must not slip); "
                            "first-order sigma-delta dither between neighbouring codes every 5 ms for sub-LSB resolution"],
               ["calibration (fallback)", "without a known slope: 3 min wait, half-way ramp, measured slope, sign checked; no response = FAILED"],
               ["log line", "OCXO once a minute: code and volts, state, source, e-CzasPL weight, offset (ppb), time error (ns), slope, loop time constant, learned e-CzasPL-DCF77 offset"]],
              [32, 138]),
          Paragraph("Simulation (host/efcsim.c) before each change: by day ~18 ns time wander; a simulated night (3x DCF77 noise + ±300 ns sky-wave) "
                    "98 ns with the adaptive loop against 332 ns with a fixed 600 s loop; mixing both stations' frequencies was worse (585 ns) and is not used.", S)]

story += [Paragraph("6. Processing budget", H2), img("/tmp/a_tim.png", 170), Paragraph(
    "Processing per 5 ms block must on average stay far below 5 ms; a single slow block may take up to ~25 ms before the DMA overwrites unread samples (OVERRUN) - two heavy tasks in one sample took 32 ms on 28 Sep 21:38 and broke the DCF77 timing. Everything runs in the main loop, one 5 ms block at a time (no RTOS). Measured: CPU ~20 %, longest block 1-2 ms normally, 8-9 ms in the "
    "10-min DCF77 steps. The early checks and the four block steps are placed in different samples so that two heavy tasks never meet. "
    "The host benches cannot see CPU time: the 'longest block' in the STATUS line is checked after every flash.", P)]

story += [Paragraph("7. Outputs (text log on the USB serial port)", H2)]
story += [tbl([["line", "when", "content"],
               ["STATUS", "10 s", "time (e-CzasPL clock), e-CzasPL carrier state and loop noise, frame counters, DCF77 carrier state, MCU clock offset, "
                                  "CPU %, longest block, ADC means/min/max, OVERRUN / PLBAD flags"],
               ["FRAME / CLOCK", "every e-CzasPL frame", "correlation, SNR, RS corrections, decoded time; accepted / confirmed / REJECTED (early frames ~-2.4 s)"],
               ["CARRIER", "1 min", "both carriers: frequency vs OCXO (mHz), C/N0, loop noise, unwrapped phase, state"],
               ["OCXO", "1 min", "steering state (see section 5)"],
               ["DCF77 TIME", "1 min", "decoded DCF77 time, status (confirmed / by expected frame / unconfirmed / not decodable), comparison with e-CzasPL"],
               ["DCF77", "10 min", "second mark, minute, phase-code timing with significance; DCF77 second vs e-CzasPL second, also at the transmitters"],
               ["STATS", "1 h", "guaranteed e-CzasPL frame at :03 (expected / heard / correct / confirmed), all time frames, early frames, DCF77 minutes, mean C/N0"],
               ["TIMEMAP", "10 s", "sample count -> e-CzasPL time (for offline alignment of the dumps)"],
               ["binary packets", "continuous", "2 kHz complex baseband of both mixers (A5 5C e-CzasPL, A5 5B DCF77), written to .c64 files by the logger"]],
              [24, 24, 122])]

story += [PageBreak(), Paragraph("8. Host side (server 'power', all in Docker containers)", H2)]
story += [tbl([["component", "what it does"],
               ["nucleo-logger", "reads the USB serial port; text log /data/claude/nucleo-h723/log/rx.log, 10-min .c64 baseband files"],
               ["nucleo-carrier-cmp", "e-CzasPL vs DCF77 carrier comparison from the CARRIER lines (the board clock cancels): offset, Allan deviation, hourly report"],
               ["nucleo-dcf-track", "DCF77 timing from the dumps with e-CzasPL assistance (10-min phase-code lag, significance)"],
               ["build / flash", "arm-none-eabi-gcc in image eczas-arm:1, make CFLAGS_EXTRA='-DAUDIO_DUMP -DOCXO_REF'; st-flash over the ST-LINK"],
               ["host tests", "firmware/host: dcfsim, dcfminsim (the NUCLEO's DCF77 code on recordings; DCF_QUICK, DCF_BLIND, DCF_STAGED as the firmware), "
                              "efcsim (steering loop vs a simulated OCXO); tools/dcfbench.py and dcfminbench.py: noise benches on KiwiSDR recordings with GPS "
                              "truth - every DCF77 change must keep 0 wrong confirmed minutes"],
               ["references", "IC-7610 over LAN (e-CzasPL + DCF77, best reference receiver), KiwiSDR (Czech Republic, GPS-timed), Legnica bench (eCzas module)"]],
              [34, 136])]

story += [Paragraph("9. Measured performance (28-29 Sep 2026)", H2)]
story += [tbl([["", "e-CzasPL", "DCF77"],
               ["C/N0 on the rods", "45 dB-Hz, day and night", "12-21 dB-Hz by day, 6-14 at night"],
               ["carrier noise per minute (day)", "0.29 ppb", "0.71 ppb"],
               ["decoding", "99.6 % of all time frames; 98.7 % of the guaranteed frame at :03 (00:30-09:30 UTC)", "~95 % of minutes confirmed by day; ~30 % in the worst night hours"],
               ["second / timing", "frames vs clock ±0.25 ms", "phase code ±0.07 ms (30-min values)"],
               ["e-CzasPL vs DCF77 carrier", "-0.92e-9 over 9 h (Allan deviation 1.8e-10 at 3 h)", "reference"],
               ["OCXO locked to DCF77", "", "0.5-1 ppb rms per minute by day, time error ±0.25 µs by day, ±1 µs at night (fixed loop)"],
               ["early e-CzasPL frames (-2.4 s)", "detected and rejected, never used for the clock (events 31-50 all caught by the NUCLEO or the IC-7610)", ""]],
              [40, 70, 60])]

story += [Paragraph("10. Known limitations and next steps", H2)]
for t in [
        "DCF77 on the small rod is weak at night (6-14 dB-Hz): minute decoding then relies on the expected frame; a better DCF77 antenna helps most.",
        "Absolute time: the e-CzasPL and DCF77 seconds differ by ~9 ms at the board; propagation (1.93 / 0.78 ms) is known, the rest (decoder and transmitter offsets) needs a GPS PPS reference (LEA-M8T) for a one-off calibration.",
        "The MCU runs on HSI and every sample is corrected in software; clocking the MCU from the OCXO (HSE bypass) would remove that layer.",
        "Third station TDF 162 kHz (Allouis): decoder proven offline on IC-7610 recordings; needs a 162 kHz rod (doc/three-station-design.md, doc/three_rods_layout.pdf) and a third mixer/tracker.",
        "Time output to other equipment (NMEA over USB to chrony, or NTP/PTP over the board's Ethernet) is not implemented yet."]:
    story.append(Paragraph("• " + t, P))

doc = SimpleDocTemplate("/o/nucleo_architecture.pdf", pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                        title="NUCLEO time receiver architecture", author="SQ6EMM")
doc.build(story, onFirstPage=lambda c, d: None,
          onLaterPages=lambda c, d: (c.setFont("Helvetica", 7), c.setFillColor(colors.grey),
                                     c.drawString(18 * mm, 8 * mm, f"NUCLEO e-CzasPL + DCF77 receiver - architecture, 29.09.2026 - page {d.page}")))
print("ok")
