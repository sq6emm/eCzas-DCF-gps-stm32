"""Three ferrite rods (225 / 162 / 77.5 kHz): top-view layout by station bearing + stacked-tank input.
  docker run --rm -v $PWD/doc:/o python:3.12-slim sh -c "pip -q install schemdraw matplotlib && python3 /o/three_rods_layout.py"
"""
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import schemdraw, schemdraw.elements as elm

BLUE, GREY, RED, GREEN, PURPLE = "#1f4e79", "#666", "#b22222", "#2e7d32", "#6a1b9a"
ST = [("e-CzasPL 225 kHz\nSolec Kujawski 234 km", 19.9, RED), ("DCF77 77.5 kHz\nMainflingen 580 km", 261.0, BLUE),
      ("TDF 162 kHz\nAllouis 1162 km", 253.7, GREEN)]

def xy(bearing, r):                     # compass bearing -> plot coordinates (north up)
    a = np.radians(bearing); return r * np.sin(a), r * np.cos(a)

fig1, ax = plt.subplots(figsize=(7, 7)); ax.set_aspect("equal"); ax.axis("off"); ax.set_xlim(-1.35, 1.35); ax.set_ylim(-1.35, 1.35)
ax.add_patch(plt.Circle((0, 0), 1.0, fill=False, ec=GREY, lw=0.8, ls=":"))
for b, t in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
    x, y = xy(b, 1.12); ax.text(x, y, t, ha="center", va="center", fontsize=12, color=GREY, weight="bold")
for name, b, col in ST:
    x, y = xy(b, 1.0); ax.annotate("", xy=xy(b, 0.62), xytext=(x, y), arrowprops=dict(arrowstyle="->", color=col, lw=1.8))
    off = {19.9: (0, 0), 261.0: (0.02, 0.36), 253.7: (0, -0.16)}[b]
    tx, ty = xy(b, 1.23); ax.text(tx + off[0], ty + off[1], f"{name}\n{b:.0f}°", ha="center", va="center", fontsize=8.5, color=col)
# rods: axis perpendicular to the bearing; positions: e-CzasPL rod north-east, the two western rods side by side
rods = [("ROD 1  225 kHz", 19.9 + 90, (0.30, 0.30), RED, (0.30, 0.52)), ("ROD 2  77.5 kHz", 261.0 + 90, (-0.42, -0.10), BLUE, (-0.42, -0.34)),
        ("ROD 3  162 kHz", 253.7 + 90, (0.10, -0.12), GREEN, (0.14, -0.34))]
for name, axis, (cx, cy), col, (lx, ly) in rods:
    dx, dy = xy(axis, 0.16)
    ax.plot([cx - dx, cx + dx], [cy - dy, cy + dy], color=col, lw=9, solid_capstyle="round", alpha=0.85)
    ax.text(lx, ly, f"{name}\naxis {axis % 180:.0f}°", ha="center", va="center", fontsize=8, color=col)
ax.annotate("", xy=(0.10, -0.50), xytext=(-0.42, -0.50), arrowprops=dict(arrowstyle="<->", color=GREY))
ax.text(-0.16, -0.58, ">= 25-30 cm (2 rod lengths)", ha="center", fontsize=7.5, color=GREY)
ax.text(0, -1.33, "TOP VIEW, north up. A rod receives broadside (null along its axis): axis = bearing + 90°.\n"
        "DCF77 and TDF are 7° apart -> their rods are almost parallel; e-CzasPL's is ~60° off them.", ha="center", fontsize=8, color=GREY)
fig1.savefig("/o/tr_layout.png", dpi=200, bbox_inches="tight"); plt.close(fig1)

schemdraw.config(fontsize=11)
d = schemdraw.Drawing(show=False, unit=2.5)
# 225 kHz tank (top) in series with 162 kHz tank (bottom), between A0 feed and the bias node
d.add(elm.Dot(open=True).at((0, 10)).label("to A0 via 330 Ω\n(as nucleo_225_77kHz_input.pdf)", loc="left", ofst=0.3))
d.add(elm.Line().at((0, 10)).to((0, 9)))
d.add(elm.Line().at((-1.2, 9)).to((1.2, 9)))
d.add(elm.Inductor2(loops=4).at((-1.2, 9)).to((-1.2, 6)).label("ROD 1\n360 µH", loc="bottom", color=RED))
d.add(elm.Capacitor().at((1.2, 9)).to((1.2, 6)).label("1.5 nF", loc="bottom", color=RED))
d.add(elm.Line().at((-1.2, 6)).to((1.2, 6)))
d.add(elm.Line().at((0, 6)).to((0, 5)))
d.add(elm.Line().at((-1.2, 5)).to((1.2, 5)))
d.add(elm.Inductor2(loops=4).at((-1.2, 5)).to((-1.2, 2)).label("ROD 3\n~360 µH", loc="bottom", color=GREEN))
d.add(elm.Capacitor().at((1.2, 5)).to((1.2, 2)).label("~2.7 nF", loc="bottom", color=GREEN))
d.add(elm.Line().at((-1.2, 2)).to((1.2, 2)))
d.add(elm.Line().at((0, 2)).to((0, 1)))
d.add(elm.Dot(open=True).at((0, 1)).label("to the 1.65 V bias node\n(1 µF to GND there)", loc="left", ofst=0.3))
d.add(elm.Label().at((4.4, 7.5)).label("225 kHz tank: ~25 kΩ at 225 kHz\n162 kHz tank: ~0.55 kΩ at 225 kHz", halign="left", color=RED))
d.add(elm.Label().at((4.4, 3.5)).label("162 kHz tank: ~18 kΩ at 162 kHz\n225 kHz tank: ~0.76 kΩ at 162 kHz", halign="left", color=GREEN))
d.save("/o/tr_tanks.png", dpi=200)

with PdfPages("/o/three_rods_layout.pdf") as pdf:
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.04, 0.95, "Three ferrite rods for e-CzasPL (225 kHz), TDF (162 kHz) and DCF77 (77.5 kHz)", fontsize=15, weight="bold", color=BLUE)
    fig.text(0.04, 0.925, "Layout by station bearing from Wrocław (left) and the 225 + 162 kHz 'stacked tanks' on A0 (right); DCF77 stays on A1.", fontsize=9.5, color=GREY)
    a1 = fig.add_axes([0.01, 0.22, 0.50, 0.68]); a1.axis("off"); a1.imshow(plt.imread("/o/tr_layout.png"))
    a2 = fig.add_axes([0.53, 0.26, 0.46, 0.62]); a2.axis("off"); a2.imshow(plt.imread("/o/tr_tanks.png"))
    notes = [
        "1. Not a triangle: an equilateral triangle would turn one of the two western rods 60° away from its station (-6 dB). Use the 'V': ROD 2 and ROD 3 ~N-S, ROD 1 ~ESE-WNW.",
        "2. Parallel rods (ROD 2, ROD 3) couple most: >= 2 rod lengths apart side by side, or on one line end to end with a gap >= 1 rod length. ROD 1 at ~60°: 20-30 cm is enough.",
        "3. Tuning capacitors near the board (as before). Retune each rod with the others in place - the TDF probe build (-DF_DCF=162000) shows C/N0 within minutes.",
        "4. ROD 3: measure its inductance first; C = 1 / (4 pi² f² L): 360 µH -> 2.68 nF at 162 kHz (e.g. 2.2 nF + 470 pF, then trim). Values with ~ are estimates.",
        "5. Stacked tanks: each station's voltage reaches A0 with ~3-4 % loss; the ADC samples 0-500 kHz, the firmware separates the stations (mixers).",
    ]
    y = 0.19
    for t in notes: fig.text(0.04, y, t, fontsize=8.8); y -= 0.028
    fig.text(0.04, 0.02, "SQ6EMM / e-CzasPL receiver experiments, 29.09.2026 - draft, see doc/three-station-design.md", fontsize=7.5, color=GREY)
    pdf.savefig(fig); fig.savefig("/o/three_rods_layout.png", dpi=110)
print("ok")
