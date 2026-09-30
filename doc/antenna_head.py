"""Antenna head (rods + amplifiers, Hammond 1554VAL2GY) - top view to scale and signal chain. Draws doc/antenna_head.pdf (+ png).
  docker run --rm -e HOME=/tmp -v $PWD/doc:/o python:3.12-slim sh -c "pip -q install --user matplotlib && python3 /o/antenna_head.py"
Details: frontend-architecture.md, rod-antenna-spec.md, three-station-design.md.
"""
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, Rectangle, Circle, FancyArrowPatch

BLUE, GREY, RED, GREEN, PURPLE, ORANGE = "#1f4e79", "#666", "#b22222", "#2e7d32", "#6a1b9a", "#e67e22"
ROD_L, ROD_D, KEEP = 100.0, 10.0, 12.0                       # mm


def u(bearing):                                               # compass bearing -> unit vector (north up)
    a = np.radians(bearing); return np.array([np.sin(a), np.cos(a)])


BOX_W, BOX_H = 152.0, 232.0                                   # Hammond 1554VAL2GY inside (approx.), mm


def rod(ax, c, vertical, color, name, amp_dx, amp_dy):
    c = np.array(c, float); d = np.array([0.0, 1.0]) if vertical else np.array([1.0, 0.0])
    p0, p1 = c - d * ROD_L / 2, c + d * ROD_L / 2
    w, h = (ROD_D + 2 * KEEP, ROD_L + 2 * KEEP) if vertical else (ROD_L + 2 * KEEP, ROD_D + 2 * KEEP)
    ax.add_patch(Rectangle((c[0] - w / 2, c[1] - h / 2), w, h, fc="#f4f4f4", ec=GREY, lw=0.6, ls="--"))
    ax.plot(*zip(p0, p1), color="#333", lw=7, solid_capstyle="butt")                # rod
    ax.plot(*zip(c - d * 20, c + d * 20), color=color, lw=11, solid_capstyle="butt", alpha=0.85)  # L1 + L2
    for s in (-1, 1):                                                                 # plastic standoffs / clips
        q = c + d * s * 38
        ax.add_patch(Circle(q, 3, fc="white", ec="#999", lw=0.8))
    a = c + np.array([amp_dx, amp_dy])
    ax.add_patch(FancyBboxPatch((a[0] - 14, a[1] - 9), 28, 18, boxstyle="round,pad=0.5", fc="white", ec=color, lw=1.2))
    ax.text(a[0], a[1], "C+R\nLNA", ha="center", va="center", fontsize=5.8, color=color)
    ax.plot(*zip(c, a), color=color, lw=0.9)
    return a


def page1(pdf):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.04, 0.95, "Antenna head - top view to scale (mm)", fontsize=15, weight="bold", color=BLUE)
    fig.text(0.04, 0.905, "Hammond 1554VAL2GY (polycarbonate IP68, 240 x 160 x 60 mm outside, ~232 x 152 x 53 inside); rods 10 x 100 mm,\n"
             "L1 500 uH + 7-turn L2 (rod-antenna-spec.md); head board under the rods; GPS: separate antenna.", fontsize=9, color=GREY)
    ax = fig.add_axes([0.03, 0.05, 0.40, 0.86]); ax.set_aspect("equal"); ax.axis("off")
    ax.add_patch(FancyBboxPatch((-4, -4), BOX_W + 8, BOX_H + 8, boxstyle="round,pad=0,rounding_size=8", fc="none", ec=BLUE, lw=2.2))
    ax.add_patch(Rectangle((0, 0), BOX_W, BOX_H, fc="white", ec=BLUE, lw=0.6))
    for x, y in ((6, 6), (BOX_W - 6, 6), (6, BOX_H - 6), (BOX_W - 6, BOX_H - 6)):     # lid-screw bosses
        ax.add_patch(Circle((x, y), 5, fc="#dde", ec=BLUE, lw=0.6))
    # head board under the rods (dashed): copper only in the amplifier strip and the supply corner
    ax.add_patch(Rectangle((8, 14), BOX_W - 16, BOX_H - 28, fc="none", ec=ORANGE, lw=1.2, ls=(0, (6, 3))))
    ax.add_patch(Rectangle((112, 110), 32, 104, fc="#fff3dc", ec=ORANGE, lw=0.8))
    ax.text(128, 105, "amp strip\n(ground\nplane only\nhere)", ha="center", va="top", fontsize=5.5, color=ORANGE)
    ax.add_patch(Rectangle((96, 16), 48, 22, fc="#fff3dc", ec=ORANGE, lw=0.8))
    ax.text(120, 27, "LDO, TVS\nCAT6", ha="center", va="center", fontsize=5.8, color=ORANGE)
    ax.annotate("", xy=(120, -32), xytext=(120, 16), arrowprops=dict(arrowstyle="->", color=ORANGE, lw=2))
    ax.text(124, -24, "cable gland:\nCAT6 to the\nmain board", fontsize=6.5, color=ORANGE)
    aD = rod(ax, (30, 160), True, BLUE, "DCF77", 98, 25)
    aT = rod(ax, (75, 160), True, GREEN, "TDF", 53, -25)
    aE = rod(ax, (62, 58), False, RED, "e-CzasPL", 0, 30)
    ax.text(24, 238, "DCF77 77.5 kHz", ha="center", fontsize=7, color=BLUE, weight="bold", va="bottom")
    ax.text(90, 238, "TDF 162 kHz", ha="center", fontsize=7, color=GREEN, weight="bold", va="bottom")
    ax.text(62, 34, "e-CzasPL 225 kHz", ha="center", fontsize=7, color=RED, weight="bold", va="top")
    ax.annotate("", xy=(30, 102), xytext=(75, 102), arrowprops=dict(arrowstyle="<->", color=GREY, lw=0.7))
    ax.text(52, 96, "45", ha="center", fontsize=6.5, color=GREY)
    ax.annotate("", xy=(-12, 0), xytext=(-12, BOX_H), arrowprops=dict(arrowstyle="<->", color=GREY, lw=0.7))
    ax.text(-16, BOX_H / 2, "~232", rotation=90, ha="right", va="center", fontsize=7, color=GREY)
    ax.annotate("", xy=(0, BOX_H + 26), xytext=(BOX_W, BOX_H + 26), arrowprops=dict(arrowstyle="<->", color=GREY, lw=0.7))
    ax.text(BOX_W / 2, BOX_H + 30, "~152", ha="center", fontsize=7, color=GREY)
    ax.annotate("N\n(~182 deg)", xy=(BOX_W + 32, BOX_H - 10), xytext=(BOX_W + 32, BOX_H - 70), ha="center", fontsize=7.5,
                color=GREY, weight="bold", arrowprops=dict(arrowstyle="->", color=GREY, lw=1.6))
    ax.set_xlim(-40, BOX_W + 60); ax.set_ylim(-45, BOX_H + 40)
    # side view
    sx = fig.add_axes([0.45, 0.62, 0.22, 0.25]); sx.set_aspect("equal"); sx.axis("off")
    sx.add_patch(Rectangle((0, 0), BOX_W, 53, fc="white", ec=BLUE, lw=1.2))
    sx.add_patch(Rectangle((8, 4), BOX_W - 16, 1.6, fc=ORANGE, ec="none"))
    sx.text(BOX_W - 10, 7, "board", ha="right", fontsize=6, color=ORANGE)
    for x in (30, 75):
        sx.add_patch(Rectangle((x - 4, 5.6), 8, 18, fc="#ddd", ec="#999", lw=0.6))
        sx.add_patch(Circle((x, 28.6), 5, fc="#333", ec="none"))
    sx.annotate("", xy=(-6, 5.6), xytext=(-6, 23.6), arrowprops=dict(arrowstyle="<->", color=GREY, lw=0.6))
    sx.text(-9, 14, "15-20", rotation=90, ha="right", va="center", fontsize=6, color=GREY)
    sx.text(BOX_W / 2, 58, "side view (rods DCF77 / TDF end-on), ~53 mm inside", ha="center", fontsize=6.5, color=GREY)
    sx.set_xlim(-25, BOX_W + 5); sx.set_ylim(-3, 66)
    # compass: rod axes vs station bearings
    cx = fig.add_axes([0.70, 0.50, 0.27, 0.36]); cx.set_aspect("equal"); cx.axis("off"); cx.set_xlim(-1.4, 1.4); cx.set_ylim(-1.4, 1.4)
    cx.add_patch(Circle((0, 0), 1, fill=False, ec=GREY, lw=0.8, ls=":"))
    for b, t in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
        cx.text(*(u(b) * 1.18), t, ha="center", va="center", fontsize=11, color=GREY, weight="bold")
    for name, b, col, off in (("e-CzasPL 20 deg", 19.9, RED, (0.25, 0.05)), ("DCF77 261 deg", 261.0, BLUE, (-0.05, 0.12)),
                              ("TDF 254 deg", 253.7, GREEN, (0.0, -0.25))):
        cx.annotate("", xy=u(b) * 0.95, xytext=(0, 0), arrowprops=dict(arrowstyle="->", color=col, lw=1.6))
        cx.text(*(u(b) * 0.62 + np.array(off)), name, ha="center", fontsize=6.5, color=col)
    for b, col in ((182, BLUE), (92, RED)):                                          # rod axes
        cx.plot(*zip(-u(b) * 0.9, u(b) * 0.9), color=col, lw=5, alpha=0.25)
    cx.set_title("station bearings (arrows) and rod axes (bars)", fontsize=8.5, color=GREY, pad=14)
    notes = [
        "Rods at 90 deg: DCF77 + TDF parallel, e-CzasPL crosswise.",
        "Box long side (DCF77 / TDF axis) to ~182 deg, i.e. ~north-south;",
        "  each rod is then off its ideal (broadside) direction by",
        "  DCF77 11, TDF 18, e-CzasPL 18 deg: at most -0.45 dB.",
        "Board under the rods, rods on plastic standoffs 15-20 mm above it;",
        "  no copper under the rods except narrow traces, ground plane only",
        "  in the amp strip and the supply corner, no closed copper loops.",
        "Tank (L1 + C + R, Q ~ 30) at each rod; tune in place with all",
        "  three rods mounted and the lid on (SPECTRUM hump).",
        "Rod spacing 45 mm (rods on different frequencies couple weakly):",
        "  verify with the prototype (resonance with / without neighbours).",
        "GPS: a separate active antenna (sky view) on its own coax.",
        "150 mm rods: the same layout in a 1554X2GY (300 x 200 x 90).",
    ]
    y = 0.46
    for t in notes: fig.text(0.47, y, t, fontsize=7.8); y -= 0.026
    fig.text(0.04, 0.015, "SQ6EMM / e-CzasPL receiver experiments, 30.09.2026 - a proposal, verify with the prototype (frontend-architecture.md, 6); "
             "box inside dimensions from a distributor listing - check the Hammond drawing", fontsize=7, color=GREY)
    pdf.savefig(fig); fig.savefig("/o/antenna_head.png", dpi=110); plt.close(fig)


def box(ax, x, y, w, h, t, col, fs=7.5, fc="white"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01", fc=fc, ec=col, lw=1.2))
    ax.text(x + w / 2, y + h / 2, t, ha="center", va="center", fontsize=fs, color=col)


def arrow(ax, x0, y0, x1, y1, col=GREY):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="->", mutation_scale=10, color=col, lw=1.1))


def page2(pdf):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.04, 0.95, "Antenna head - signal chain per station, cable and main board", fontsize=15, weight="bold", color=BLUE)
    ax = fig.add_axes([0.03, 0.42, 0.94, 0.48]); ax.axis("off"); ax.set_xlim(0, 10); ax.set_ylim(0, 4)
    ax.add_patch(Rectangle((0.05, 0.3), 5.45, 3.5, fc="#fbfbfb", ec=ORANGE, lw=1, ls="--"))
    ax.text(0.12, 3.6, "ANTENNA HEAD", fontsize=9, weight="bold", color=ORANGE)
    ax.add_patch(Rectangle((6.6, 0.3), 3.35, 3.5, fc="#fbfbfb", ec=BLUE, lw=1, ls="--"))
    ax.text(6.67, 3.6, "MAIN BOARD", fontsize=9, weight="bold", color=BLUE)
    for i, (nm, col, c, r) in enumerate((("DCF77 77.5 kHz", BLUE, "8.2 nF + 220 pF", "7.5 k"),
                                         ("TDF 162 kHz", GREEN, "1.8 nF + 130 pF", "15 k"),
                                         ("e-CzasPL 225 kHz", RED, "1.0 nF (trim)", "22 k"))):
        y = 2.7 - i * 0.95
        box(ax, 0.15, y, 1.25, 0.6, f"{nm}\nrod L1 500 uH\nC {c} | R {r}", col, fs=6.5)
        box(ax, 1.65, y + 0.05, 1.0, 0.5, "LNA x10-20\n(20-26 dB)\nhigh Z in", col, fs=6.5)
        box(ax, 2.9, y + 0.05, 1.0, 0.5, "low-pass\n300-400 kHz", col, fs=6.5)
        box(ax, 4.15, y + 0.05, 1.2, 0.5, "diff. line driver", col, fs=6.5)
        arrow(ax, 1.4, y + 0.3, 1.65, y + 0.3, col); arrow(ax, 2.65, y + 0.3, 2.9, y + 0.3, col)
        arrow(ax, 3.9, y + 0.3, 4.15, y + 0.3, col); arrow(ax, 5.35, y + 0.3, 6.75, y + 0.3, col)
        ax.text(6.05, y + 0.36, f"pair {i + 1}", ha="center", fontsize=6.5, color=col)
        box(ax, 6.75, y + 0.05, 1.0, 0.5, "diff. receiver", col, fs=6.5)
        box(ax, 7.95, y + 0.05, 0.9, 0.5, "anti-alias\n~400 kHz", col, fs=6.5)
        box(ax, 9.0, y + 0.05, 0.85, 0.5, "ADC\n1.65 V bias", col, fs=6.5)
        arrow(ax, 7.75, y + 0.3, 7.95, y + 0.3, col); arrow(ax, 8.85, y + 0.3, 9.0, y + 0.3, col)
    box(ax, 1.65, 0.45, 1.6, 0.4, "LDO (head supply)", ORANGE, fs=6.8, fc="#fff8e6")
    box(ax, 7.95, 0.45, 1.9, 0.4, "clean linear +5 V", ORANGE, fs=6.8, fc="#fff8e6")
    arrow(ax, 7.95, 0.65, 3.25, 0.65, ORANGE); ax.text(5.9, 0.72, "pair 4: +5 V / GND", ha="center", fontsize=6.5, color=ORANGE)
    rows = [["pair", "variant A (three lines)", "variant B (one summed line)"],
            ["1", "DCF77", "three stations summed"], ["2", "TDF", "spare"],
            ["3", "e-CzasPL", "spare"], ["4", "+5 V / GND", "+5 V / GND"]]
    tx = fig.add_axes([0.05, 0.1, 0.5, 0.26]); tx.axis("off")
    t = tx.table(cellText=rows[1:], colLabels=rows[0], loc="upper left", cellLoc="left", colWidths=[0.1, 0.35, 0.55])
    t.auto_set_font_size(False); t.set_fontsize(8.5); t.scale(1, 1.5)
    tx.set_title("CAT5e / CAT6, differential twisted pairs", fontsize=9, color=GREY, loc="left")
    notes = [
        "Values: C0G capacitors at the rod (C = 1/((2 pi f)^2 L), recompute",
        "  from each rod's measured L), R across L1 for Q ~ 30.",
        "Why the amplifier: the rod's antenna noise must stay well above the",
        "  ADC noise floor (measured ~15 dB margin at the tank; the 7-turn",
        "  link alone would cost ~18 dB).",
        "LNA: <= 10 nV/sqrt(Hz), GBW >= 50 MHz for x20 at 225 kHz (or 2 stages).",
        "Variant B: one ADC input for all three stations (STM32H730),",
        "  separated by the firmware's digital mixers.",
        "ESD/TVS at both cable ends; common-mode rejection by the pairs.",
        "GPS: separate active antenna, own coax to the main board.",
    ]
    y = 0.36
    for s in notes: fig.text(0.58, y, s, fontsize=8); y -= 0.03
    fig.text(0.04, 0.015, "SQ6EMM / e-CzasPL receiver experiments, 30.09.2026 - see frontend-architecture.md", fontsize=7, color=GREY)
    pdf.savefig(fig); plt.close(fig)


with PdfPages("/o/antenna_head.pdf") as pdf:
    page1(pdf); page2(pdf)
print("ok")
