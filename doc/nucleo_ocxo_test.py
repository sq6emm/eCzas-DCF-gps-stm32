"""OCXO test wiring: CTI OSC5A2B02 (pin layout, bottom view) to the NUCLEO-H723ZG.
Draws doc/nucleo_ocxo_test.pdf (+ png).
  docker run --rm -v $PWD/doc:/o python:3.12-slim sh -c "pip -q install schemdraw matplotlib && python3 /o/nucleo_ocxo_test.py"
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, FancyBboxPatch
from matplotlib.backends.backend_pdf import PdfPages
import schemdraw, schemdraw.elements as elm

BLUE, GREY, RED = "#1f4e79", "#666", "#b22222"

# ---------------- 1. pin layout, bottom view (as in the datasheet)
fig1, ax = plt.subplots(figsize=(5.2, 5.2))
ax.set_xlim(-1.6, 1.6); ax.set_ylim(-1.75, 1.6); ax.set_aspect("equal"); ax.axis("off")
ax.add_patch(FancyBboxPatch((-1.0, -1.0), 2.0, 2.0, boxstyle="round,pad=0.03", fc="#e8e8e8", ec="k", lw=1.5))
ax.text(0, 0.05, "CTI\nOSC5A2B02\n10 MHz", ha="center", va="center", fontsize=11, weight="bold")
ax.text(0, -1.35, "BOTTOM VIEW (pins towards you)\n25.4 x 25.4 mm", ha="center", va="center", fontsize=9, color=GREY)
pins = {1: (-0.7, -0.7, "1  OUT\n10 MHz, 5 V square", "left"), 2: (-0.7, 0.0, "2  GND", "left"),
        3: (-0.7, 0.7, "3  Vref = EFC\n(tuning 0-4 V)", "left"), 4: (0.7, 0.7, "4  NC\n(not connected)", "right"),
        5: (0.7, -0.7, "5  Vcc +5 V\n(600 mA warm-up)", "right")}
col = {1: "#2e7d32", 2: "k", 3: "#6a1b9a", 4: GREY, 5: RED}
for n, (x, y, lab, side) in pins.items():
    ax.add_patch(Circle((x, y), 0.09, fc=col[n], ec="k"))
    ax.text(x + (-0.17 if side == "left" else 0.17), y, lab, ha="right" if side == "left" else "left",
            va="center", fontsize=8.5, color=col[n], weight="bold")
ax.add_patch(Circle((-0.88, -0.88), 0.035, fc="k"))          # the dot marking pin 1
ax.text(-0.88, -1.02, "dot = pin 1", fontsize=7, color=GREY, ha="left", va="top")
fig1.savefig("/o/ocxo_pins.png", dpi=220, bbox_inches="tight"); plt.close(fig1)

# ---------------- 2. wiring (explicit coordinates, no overlaps)
schemdraw.config(fontsize=11)
d = schemdraw.Drawing(show=False, unit=2.5)
Y = {1: 14, 2: 11, 3: 8, 4: 4.5, 5: 1}
NAME = {1: "1  OUT", 2: "2  GND", 3: "3  EFC (Vref)", 4: "4  NC", 5: "5  Vcc"}
# the OCXO box
for a, b in [((0, -0.5), (3, -0.5)), ((3, -0.5), (3, 15.5)), ((3, 15.5), (0, 15.5)), ((0, 15.5), (0, -0.5))]:
    d.add(elm.Line().at(a).to(b))
d.add(elm.Label().at((1.5, 16.3)).label("CTI OSC5A2B02", fontsize=13))
for n, y in Y.items():
    d.add(elm.Label().at((2.8, y)).label(NAME[n], halign="right"))
    d.add(elm.Line().at((3, y)).to((4, y)))
# pin 1: OUT -> 1k -> PA0, 2k to GND
d.add(elm.Resistor().at((4, 14)).to((7, 14)).label("1 kΩ", loc="top"))
d.add(elm.Dot().at((8, 14))); d.add(elm.Line().at((7, 14)).to((12, 14)))
d.add(elm.Dot(open=True).at((12, 14)).label("PA0 = D32  (CN10 pin 29)   3.3 V square", loc="right", ofst=0.25, color="#2e7d32"))
d.add(elm.Resistor().at((8, 14)).to((8, 11.8)).label("2 kΩ", loc="bottom"))
d.add(elm.Ground().at((8, 11.8)))
# pin 2: GND
d.add(elm.Ground().at((4, 11)))
d.add(elm.Label().at((4.6, 10.2)).label("supply GND + NUCLEO GND", halign="left"))
# pin 3: EFC network
d.add(elm.Dot().at((5, 8))); d.add(elm.Line().at((4, 8)).to((11, 8)))
d.add(elm.Capacitor().at((5, 8)).to((5, 6.2)).label("10 µF", loc="bottom"))
d.add(elm.Ground().at((5, 6.2)))
d.add(elm.Dot().at((8, 8)))
d.add(elm.Resistor().at((8, 8)).to((8, 5.8)).label("68 kΩ", loc="bottom"))
d.add(elm.Ground().at((8, 5.8)))
d.add(elm.Dot().at((11, 8)))
d.add(elm.Resistor().at((11, 8)).to((11, 10.2)).label("39 kΩ", loc="bottom"))
d.add(elm.Dot(open=True).at((11, 10.2)).label("3V3 (CN8)", loc="right", ofst=0.25))
d.add(elm.Resistor().at((11, 8)).to((14.5, 8)).label("100 kΩ", loc="top"))
d.add(elm.Dot(open=True).at((14.5, 8)).label("PA5 = D13  (CN7 pin 10)  DAC", loc="right", ofst=0.25, color="#6a1b9a"))
# pin 4: NC
d.add(elm.Label().at((4.3, 4.5)).label("not connected", halign="left", color=GREY))
# pin 5: +5 V
d.add(elm.Line().at((4, 1)).to((12, 1)))
d.add(elm.Dot(open=True).at((12, 1)).label("+5 V, >= 1 A, SEPARATE supply (not the NUCLEO 5V pin)", loc="right", ofst=0.25, color=RED))
d.save("/o/ocxo_wiring.png", dpi=200)

with PdfPages("/o/nucleo_ocxo_test.pdf") as pdf:
    fig = plt.figure(figsize=(11.69, 8.27))                       # A4 landscape
    fig.text(0.04, 0.95, "OCXO test on the NUCLEO-H723ZG: CTI OSC5A2B02 wiring", fontsize=15, weight="bold", color=BLUE)
    fig.text(0.04, 0.925, "Firmware build -DOCXO_REF (commit 9eab67b): TIM2 counts the OCXO on PA0, TIM3 captures every 2500 counts; DAC on PA5 tunes it.",
             fontsize=9.5, color=GREY)
    a1 = fig.add_axes([0.02, 0.30, 0.33, 0.58]); a1.axis("off"); a1.imshow(plt.imread("/o/ocxo_pins.png"))
    a2 = fig.add_axes([0.35, 0.27, 0.64, 0.62]); a2.axis("off"); a2.imshow(plt.imread("/o/ocxo_wiring.png"))
    notes = [
        "1. Power: pin 5 to a separate 5 V supply (>= 1 A: 600 mA during the first minutes, 250 mA warm). Pin 2 to that supply's GND AND to NUCLEO GND.",
        "2. Clock: pin 1 (5 V square) -> 1 kΩ -> PA0 / D32, and 2 kΩ from PA0 to GND (5 V -> 3.3 V). Keep it short (< 10 cm), twist it with a ground wire.",
        "3. Tuning: pin 3 ('Vref' on the datasheet = the frequency control input). Network: 39 kΩ from 3V3, 68 kΩ to GND, 100 kΩ from PA5 / D13, 10 µF to GND.",
        "   PA5 open or DAC mid-scale: about 2.0 V = the OCXO's nominal centre. DAC 0 ... 3.3 V -> about 1.67 ... 2.33 V (about +-0.25 ppm).",
        "4. Pin 4: not connected. Pin 1 is marked by the dot (bottom view: pins towards you, pin 1 bottom left, pin 5 bottom right).",
        "5. Warm up >= 10 min on its own supply, then the OCXO build is flashed. 'OCXO reference OK' in the log = captures at 4 kHz found.",
    ]
    y = 0.22
    for t in notes:
        fig.text(0.04, y, t, fontsize=9.3); y -= 0.028
    fig.text(0.04, 0.02, "SQ6EMM / e-CzasPL receiver experiments, 28.09.2026 - pin data: CTI OSC5A2B02 datasheet", fontsize=7.5, color=GREY)
    pdf.savefig(fig)
    fig.savefig("/o/nucleo_ocxo_test.png", dpi=110)
print("ok")
