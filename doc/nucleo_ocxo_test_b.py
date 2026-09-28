"""OCXO test, minimal variant B: CTI OSC5A2B02 to the NUCLEO-H723ZG with one resistor.
Draws doc/nucleo_ocxo_test_b.pdf (+ png).
  docker run --rm -v $PWD/doc:/o python:3.12-slim sh -c "pip -q install schemdraw matplotlib && python3 /o/nucleo_ocxo_test_b.py"
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch
from matplotlib.backends.backend_pdf import PdfPages
import schemdraw, schemdraw.elements as elm

BLUE, GREY, RED, GREEN, PURPLE = "#1f4e79", "#666", "#b22222", "#2e7d32", "#6a1b9a"

# bottom view
fig1, ax = plt.subplots(figsize=(5.2, 5.2))
ax.set_xlim(-1.6, 1.6); ax.set_ylim(-1.75, 1.6); ax.set_aspect("equal"); ax.axis("off")
ax.add_patch(FancyBboxPatch((-1.0, -1.0), 2.0, 2.0, boxstyle="round,pad=0.03", fc="#e8e8e8", ec="k", lw=1.5))
ax.text(0, 0.05, "CTI\nOSC5A2B02\n10 MHz", ha="center", va="center", fontsize=11, weight="bold")
ax.text(0, -1.35, "BOTTOM VIEW (pins towards you)", ha="center", va="center", fontsize=9, color=GREY)
pins = {1: (-0.7, -0.7, "1  OUT", "left", GREEN), 2: (-0.7, 0.0, "2  GND", "left", "k"),
        3: (-0.7, 0.7, "3  EFC", "left", PURPLE), 4: (0.7, 0.7, "4  NC", "right", GREY),
        5: (0.7, -0.7, "5  +5 V", "right", RED)}
for n, (x, y, lab, side, c) in pins.items():
    ax.add_patch(Circle((x, y), 0.09, fc=c, ec="k"))
    ax.text(x + (-0.17 if side == "left" else 0.17), y, lab, ha="right" if side == "left" else "left",
            va="center", fontsize=10, color=c, weight="bold")
ax.add_patch(Circle((-0.88, -0.88), 0.035, fc="k"))
ax.text(-0.88, -1.02, "dot = pin 1", fontsize=7, color=GREY, ha="left", va="top")
fig1.savefig("/o/b_pins.png", dpi=220, bbox_inches="tight"); plt.close(fig1)

# wiring
schemdraw.config(fontsize=12)
d = schemdraw.Drawing(show=False, unit=2.5)
Y = {1: 12, 2: 9, 3: 6, 4: 3.5, 5: 1}
NAME = {1: "1  OUT", 2: "2  GND", 3: "3  EFC", 4: "4  NC", 5: "5  +5 V"}
for a, b in [((0, -0.5), (3, -0.5)), ((3, -0.5), (3, 13.5)), ((3, 13.5), (0, 13.5)), ((0, 13.5), (0, -0.5))]:
    d.add(elm.Line().at(a).to(b))
d.add(elm.Label().at((1.5, 14.3)).label("CTI OSC5A2B02", fontsize=13))
for n, y in Y.items():
    d.add(elm.Label().at((2.8, y)).label(NAME[n], halign="right"))
d.add(elm.Line().at((3, 12)).to((4, 12)))
d.add(elm.Resistor().at((4, 12)).to((7, 12)).label("1 kΩ  (the only part)", loc="top", color=GREEN))
d.add(elm.Line().at((7, 12)).to((10, 12)))
d.add(elm.Dot(open=True).at((10, 12)).label("PA0 = D32   (CN10 pin 29)", loc="right", ofst=0.25, color=GREEN))
d.add(elm.Line().at((3, 9)).to((10, 9)))
d.add(elm.Dot(open=True).at((10, 9)).label("GND  (NUCLEO CN8)  +  5 V supply GND", loc="right", ofst=0.25))
d.add(elm.Line().at((3, 6)).to((10, 6)))
d.add(elm.Dot(open=True).at((10, 6)).label("PA5 = D13   (CN7 pin 10)   plain wire", loc="right", ofst=0.25, color=PURPLE))
d.add(elm.Line().at((3, 3.5)).to((3.8, 3.5)))
d.add(elm.Label().at((4.1, 3.5)).label("not connected", halign="left", color=GREY))
d.add(elm.Line().at((3, 1)).to((10, 1)))
d.add(elm.Dot(open=True).at((10, 1)).label("+5 V, >= 1 A, SEPARATE supply", loc="right", ofst=0.25, color=RED))
d.save("/o/b_wiring.png", dpi=200)

with PdfPages("/o/nucleo_ocxo_test_b.pdf") as pdf:
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.04, 0.95, "OCXO test, variant B (minimal): 4 wires + one 1 kΩ resistor", fontsize=15, weight="bold", color=BLUE)
    fig.text(0.04, 0.925, "CTI OSC5A2B02 -> NUCLEO-H723ZG. Firmware build -DOCXO_REF (commit 9eab67b): TIM2 counts the OCXO on PA0, the DAC on PA5 drives its EFC.",
             fontsize=9.5, color=GREY)
    a1 = fig.add_axes([0.02, 0.33, 0.30, 0.55]); a1.axis("off"); a1.imshow(plt.imread("/o/b_pins.png"))
    a2 = fig.add_axes([0.34, 0.30, 0.64, 0.60]); a2.axis("off"); a2.imshow(plt.imread("/o/b_wiring.png"))
    notes = [
        "1. Power ORDER: NUCLEO powered first (USB), then the OCXO's 5 V supply; switch off in the reverse order.",
        "2. Pin 5 -> +5 V from a separate supply (>= 1 A: 600 mA for the first minutes, 250 mA warm). Pin 2 -> that supply's GND AND NUCLEO GND.",
        "3. Pin 1 -> 1 kΩ -> PA0 / D32. The pin's own protection clamps the 5 V square at 3.3 V; 1 kΩ limits that current to about 1.5 mA",
        "   (allowed: 5 mA). Keep this wire short (< 10 cm) and twist it with the ground wire. An 0805 on a jumper wire + heat-shrink is fine.",
        "4. Pin 3 (EFC, marked 'Vref' on the datasheet) -> PA5 / D13 with a plain wire. The DAC starts at mid-scale = 1.65 V",
        "   (about -0.3 ppm, harmless); 0 ... 3.3 V covers about -1.5 ... +0.9 ppm. Pin 4: nothing.",
        "5. Let the OCXO warm up >= 10 minutes, then the OCXO firmware is flashed. 'OCXO reference OK' in the log = 4 kHz captures found.",
    ]
    y = 0.24
    for t in notes:
        fig.text(0.04, y, t, fontsize=9.3); y -= 0.028
    fig.text(0.04, 0.02, "SQ6EMM / e-CzasPL receiver experiments, 28.09.2026 - pin data: CTI OSC5A2B02 datasheet", fontsize=7.5, color=GREY)
    pdf.savefig(fig)
    fig.savefig("/o/nucleo_ocxo_test_b.png", dpi=110)
print("ok")
