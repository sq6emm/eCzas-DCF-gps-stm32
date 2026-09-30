"""Antenna head (rods + amplifiers + GPS antenna) - top view to scale and signal chain. Draws doc/antenna_head.pdf (+ png).
  docker run --rm -e HOME=/tmp -v $PWD/doc:/o python:3.12-slim sh -c "pip -q install --user matplotlib && python3 /o/antenna_head.py"
Details: frontend-architecture.md, rod-antenna-spec.md, three-station-design.md.
"""
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, Rectangle, Circle, FancyArrowPatch

BLUE, GREY, RED, GREEN, PURPLE, ORANGE = "#1f4e79", "#666", "#b22222", "#2e7d32", "#6a1b9a", "#e67e22"
ROD_L, ROD_D, KEEP = 150.0, 10.0, 15.0                       # mm


def u(bearing):                                               # compass bearing -> unit vector (north up)
    a = np.radians(bearing); return np.array([np.sin(a), np.cos(a)])


def rod(ax, c, axis_bearing, color, name, amp_side):
    c = np.array(c, float); d = u(axis_bearing); n = np.array([-d[1], d[0]])
    p0, p1 = c - d * ROD_L / 2, c + d * ROD_L / 2
    # copper-free zone
    ang = np.degrees(np.arctan2(d[1], d[0]))
    ax.add_patch(FancyBboxPatch((c[0] - (ROD_L / 2 + KEEP), c[1] - (ROD_D / 2 + KEEP)), ROD_L + 2 * KEEP, ROD_D + 2 * KEEP,
                                boxstyle="round,pad=0,rounding_size=12", fc="#f4f4f4", ec=GREY, lw=0.6, ls="--",
                                transform=matplotlib.transforms.Affine2D().rotate_deg_around(c[0], c[1], ang) + ax.transData))
    ax.plot(*zip(p0, p1), color="#333", lw=7, solid_capstyle="butt")              # rod
    w0, w1 = c - d * 25, c + d * 25
    ax.plot(*zip(w0, w1), color=color, lw=11, solid_capstyle="butt", alpha=0.85)  # L1 (+ L2 on top)
    ax.text(*(c - n * amp_side * 40), name, ha="center", va="center", fontsize=8.5, color=color, weight="bold",
            rotation=ang - 90 if abs(ang - 90) < 45 else 0)
    # amplifier module at the rod
    a = c + n * amp_side * 45
    ax.add_patch(FancyBboxPatch((a[0] - 22, a[1] - 11), 44, 22, boxstyle="round,pad=1", fc="white", ec=color, lw=1.2))
    ax.text(a[0], a[1], "C+R\namp", ha="center", va="center", fontsize=6.5, color=color)
    ax.plot(*zip(c + n * amp_side * 8, a - n * amp_side * 11), color=color, lw=1.0)
    return a


def page1(pdf):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.04, 0.95, "Antenna head - top view to scale (mm), north up", fontsize=15, weight="bold", color=BLUE)
    fig.text(0.04, 0.925, "Plastic box with sky view (attic / roof / window). Rods 10 x 150 mm, L1 500 uH + 7-turn L2 (rod-antenna-spec.md); "
             "one amplifier module per rod; CAT6 to the main board.", fontsize=9, color=GREY)
    ax = fig.add_axes([0.03, 0.05, 0.62, 0.86]); ax.set_aspect("equal"); ax.axis("off")
    W, H = 500, 430
    ax.add_patch(Rectangle((0, 0), W, H, fc="white", ec=BLUE, lw=2))
    ax.text(6, H - 12, "head enclosure (plastic, no metal) ~ 500 x 430 mm", fontsize=8, color=BLUE)
    # rods: axis perpendicular to the station bearing
    aD = rod(ax, (110, 290), 261 - 90, BLUE, "DCF77 77.5 kHz", +1)
    aT = rod(ax, (270, 290), 254 - 90, GREEN, "TDF 162 kHz", +1)
    aE = rod(ax, (385, 120), 20 - 90, RED, "e-CzasPL 225 kHz", -1)
    # main head board: power, TVS, CAT6 - in line with the DCF77 / TDF rod axes (their null)
    bx, by = 150, 30
    ax.add_patch(FancyBboxPatch((bx, by), 110, 55, boxstyle="round,pad=2", fc="#fff8e6", ec=ORANGE, lw=1.4))
    ax.text(bx + 55, by + 38, "head board", ha="center", fontsize=8, weight="bold", color=ORANGE)
    ax.text(bx + 55, by + 14, "LDO (no switcher)\nTVS, CAT6 jack\n(opt.: GPS module, shielded)", ha="center", fontsize=6.5, color=ORANGE)
    for a, col in ((aD, BLUE), (aT, GREEN), (aE, RED)):
        ax.annotate("", xy=(bx + 55, by + 57), xytext=a, arrowprops=dict(arrowstyle="-", color=col, lw=0.9, ls=(0, (4, 2))))
    ax.annotate("", xy=(bx + 55, -40), xytext=(bx + 55, by - 2), arrowprops=dict(arrowstyle="->", color=ORANGE, lw=2))
    ax.text(bx + 62, -30, "CAT6 to the main board (tens of m)", fontsize=8, color=ORANGE)
    # GPS antenna
    g = np.array([440.0, 392.0])
    ax.add_patch(FancyBboxPatch((g[0] - 25, g[1] - 18), 50, 36, boxstyle="round,pad=2", fc="#efe6f5", ec=PURPLE, lw=1.3))
    ax.text(g[0], g[1], "GPS\nantenna", ha="center", va="center", fontsize=7, color=PURPLE)
    ax.add_patch(Circle(g, 150, fill=False, ec=PURPLE, lw=0.8, ls=":"))
    ax.text(g[0] - 20, g[1] - 110, ">= 150 mm from\nevery rod (magnet\n+ ground plate)", fontsize=6.5, color=PURPLE)
    ax.annotate("", xy=(W + 40, g[1]), xytext=(g[0] + 27, g[1]), arrowprops=dict(arrowstyle="->", color=PURPLE, lw=1.2))
    ax.text(W + 5, g[1] + 8, "GPS coax\n(variant a)", fontsize=6.5, color=PURPLE)
    # spacing dimension between DCF77 and TDF rods
    ax.annotate("", xy=(110, 380), xytext=(270, 380), arrowprops=dict(arrowstyle="<->", color=GREY, lw=0.8))
    ax.text(190, 385, ">= 150 mm", ha="center", fontsize=7, color=GREY)
    ax.text(8, 190, "dashed: copper-free zone\n>= 15 mm around each rod", fontsize=6.5, color=GREY)
    ax.set_xlim(-10, W + 70); ax.set_ylim(-50, H + 10)
    # compass + bearings
    cx = fig.add_axes([0.68, 0.45, 0.28, 0.42]); cx.set_aspect("equal"); cx.axis("off"); cx.set_xlim(-1.4, 1.4); cx.set_ylim(-1.4, 1.4)
    cx.add_patch(Circle((0, 0), 1, fill=False, ec=GREY, lw=0.8, ls=":"))
    for b, t in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
        cx.text(*(u(b) * 1.18), t, ha="center", va="center", fontsize=11, color=GREY, weight="bold")
    for name, b, col in (("e-CzasPL 20 deg\nSolec Kujawski 234 km", 19.9, RED), ("DCF77 261 deg\nMainflingen 580 km", 261.0, BLUE),
                         ("TDF 254 deg\nAllouis 1162 km", 253.7, GREEN)):
        cx.annotate("", xy=u(b) * 0.95, xytext=(0, 0), arrowprops=dict(arrowstyle="->", color=col, lw=1.6))
        off = {19.9: (0.05, 0.12), 261.0: (-0.1, 0.12), 253.7: (0.0, -0.42)}[b]
        cx.text(*(u(b) * 0.62 + np.array(off)), name, ha="center", fontsize=6.5, color=col)
    cx.set_title("station bearings from Wroclaw", fontsize=9, color=GREY)
    notes = [
        "Each rod lies broadside to its station",
        "  (axis perpendicular to the bearing):",
        "  DCF77 axis ~171 deg, TDF ~164 deg (nearly",
        "  parallel, side by side); e-CzasPL ~110 deg.",
        "The head board sits in line with the DCF77 /",
        "  TDF rod axes: a rod is deaf along its own",
        "  axis (the null of its figure-8).",
        "Tank (L1 + C + R, Q ~ 30) at each rod; amplifier",
        "  (20-26 dB) + line driver in the module next",
        "  to it; tune with the module connected",
        "  (SPECTRUM hump on the station's frequency).",
        "Install: turn the head so 'north' points north.",
    ]
    y = 0.42
    for t in notes: fig.text(0.68, y, t, fontsize=7.8); y -= 0.026
    fig.text(0.04, 0.015, "SQ6EMM / e-CzasPL receiver experiments, 30.09.2026 - dimensions are a proposal, verify with the prototype (frontend-architecture.md, 6)",
             fontsize=7, color=GREY)
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
    rows = [["pair", "variant A (three lines)", "variant B (one line + GPS in the head)"],
            ["1", "DCF77", "three stations summed"], ["2", "TDF", "GPS PPS (RS-422)"],
            ["3", "e-CzasPL", "GPS UART TX (RS-422)"], ["4", "+5 V / GND", "+5 V / GND"]]
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
    ]
    y = 0.36
    for s in notes: fig.text(0.58, y, s, fontsize=8); y -= 0.03
    fig.text(0.04, 0.015, "SQ6EMM / e-CzasPL receiver experiments, 30.09.2026 - see frontend-architecture.md", fontsize=7, color=GREY)
    pdf.savefig(fig); plt.close(fig)


with PdfPages("/o/antenna_head.pdf") as pdf:
    page1(pdf); page2(pdf)
print("ok")
