"""NUCLEO-H723ZG input: two tuned ferrite rods (e-CzasPL 225 kHz on A0, DCF77 77.5 kHz on A1) with one
shared, decoupled 1.65 V bias node. Draws doc/nucleo_225_77kHz_input.pdf.
  docker run --rm -v $PWD/doc:/o python:3.12-slim sh -c "pip -q install schemdraw matplotlib && python3 /o/nucleo_input_2rods.py"
"""
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import schemdraw, schemdraw.elements as elm

BLUE, GREY = "#1f4e79", "#666"
L1, L2 = 360e-6, 375e-6        # measured: rod on A0 (with 1.5 nF: 217 kHz), second rod bare 375 uH
f0 = lambda C, L: 1 / (2 * math.pi * math.sqrt(L * C))
schemdraw.config(fontsize=11)
d = schemdraw.Drawing(show=False, unit=3)


def box(x0, y0, x1, y1, title):
    for a, b in [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]:
        d.add(elm.Line().at(a).to(b).color(GREY).linestyle("--").linewidth(1))
    d.add(elm.Label().at(((x0 + x1) / 2, y1 + 0.35)).label(title, halign="center", color=BLUE))


def channel(y_hot, y_cold, rod_label, c_label, pin_label, cable_y):
    """rod at the antenna end, twisted pair, tuning capacitor at the board end"""
    d.add(elm.Inductor2(loops=5).at((0, y_hot)).to((0, y_cold)).label(rod_label, loc="top", ofst=0.25))
    d.add(elm.Line().at((0, y_hot)).to((7, y_hot)))
    d.add(elm.Line().at((0, y_cold)).to((7, y_cold)))
    d.add(elm.Label().at((3.5, cable_y)).label("twisted pair (up to ~1 m)", halign="center", color=GREY))
    d.add(elm.Dot().at((7, y_hot))); d.add(elm.Dot().at((7, y_cold)))
    d.add(elm.Capacitor().at((7, y_hot)).to((7, y_cold)).label(c_label, loc="bottom", ofst=0.25))
    d.add(elm.Line().at((7, y_hot)).to((10.2, y_hot)))
    d.add(elm.Dot(open=True).at((10.2, y_hot)).label(pin_label, loc="right", ofst=0.25))


# channel 1: hot on top (y=11), cold y=7;  channel 2: cold on top (y=4), hot at the bottom (y=0)
channel(11, 7, "ROD 1\n360 µH", "C1\n1.2 nF\n+ 180 pF\nC0G", "A0  (CN9 pin 1)\ne-CzasPL 225 kHz", 11.45)
channel(0, 4, "ROD 2\n375 µH", "C2\n10 nF\n+ 1.2 nF\nC0G / film", "A1  (CN9 pin 3)\nDCF77 77.5 kHz", -0.55)
# cold ends of both channels -> bias node (vertical bus at x = 8.4)
d.add(elm.Line().at((7, 7)).to((8.4, 7))); d.add(elm.Line().at((7, 4)).to((8.4, 4)))
d.add(elm.Line().at((8.4, 7)).to((8.4, 4)))
d.add(elm.Dot().at((8.4, 5.5)))
d.add(elm.Line().at((8.4, 5.5)).to((11.8, 5.5)))
d.add(elm.Label().at((10.1, 5.05)).label("bias node 1.65 V", halign="center", color=BLUE))
d.add(elm.Dot().at((11.8, 5.5)))
d.add(elm.Resistor().at((11.8, 5.5)).to((11.8, 8.9)).label("R1\n10 k", loc="bottom", ofst=0.3))
d.add(elm.Dot(open=True).at((11.8, 8.9)).label("3V3 (CN8)", loc="top", ofst=0.2))
d.add(elm.Line().at((11.8, 5.5)).to((13.6, 5.5)))
d.add(elm.Resistor().at((11.8, 5.5)).to((11.8, 2.3)).label("R2\n10 k", loc="bottom", ofst=0.3))
d.add(elm.Capacitor().at((13.6, 5.5)).to((13.6, 2.3)).label("C3\n1 µF\n(+100 nF)", loc="bottom", ofst=0.3))
d.add(elm.Line().at((11.8, 2.3)).to((13.6, 2.3)))
d.add(elm.Dot().at((12.7, 2.3)))
d.add(elm.Ground().at((12.7, 2.3)).label("GND (CN8)", loc="right", ofst=0.4))
box(-2.2, -1.2, 1.3, 12.2, "at the rods")
box(5.9, -1.2, 16.6, 12.2, "at the NUCLEO board (all parts here)")
d.save("/o/sch2.png", dpi=220)

with PdfPages("/o/nucleo_225_77kHz_input.pdf") as pdf:
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.07, 0.955, "Two ferrite rods to NUCLEO-H723ZG: e-CzasPL on A0, DCF77 on A1", fontsize=12.5, weight="bold", color=BLUE)
    fig.text(0.07, 0.935, "Rods alone at the antenna end; tuning capacitors and one shared 1.65 V bias node at the board", fontsize=9.5, color=GREY)
    ax = fig.add_axes([0.05, 0.615, 0.90, 0.31]); ax.axis("off"); ax.imshow(plt.imread("/o/sch2.png"))
    c1, c2 = 1.2e-9 + 180e-12, 10e-9 + 1.2e-9
    notes = [
        ("Parts", True),
        ("  ROD 1: the rod on A0 today (12 cm, 360 µH);  ROD 2: the second rod, measured 375 µH (bare coil)", False),
        (f"  C1 = 1.2 nF + 180 pF in parallel (1.38 nF) -> {f0(c1, L1)/1e3:.1f} kHz         (today: 1.5 nF = {f0(1.5e-9, L1)/1e3:.1f} kHz)", False),
        (f"  C2 = 10 nF + 1.2 nF in parallel (11.2 nF) -> {f0(c2, L2)/1e3:.1f} kHz          (ideal 11.25 nF; 10 nF + 1.5 nF would be {f0(11.5e-9, L2)/1e3:.1f} kHz)", False),
        ("  C1, C2: C0G/NP0 ceramic, polystyrene or polypropylene film (stable, low loss; not X7R)", False),
        ("  R1, R2 = 10 k;  C3 = 1 µF ceramic, optionally + 100 nF, at the board next to R1 / R2", False),
        ("", False),
        ("Connections", True),
        ("  At the rods: nothing but the rod. Each rod -> its own twisted pair -> the board end.", False),
        ("  At the board end: C1 across pair 1, C2 across pair 2 (parallel tuned circuits), R1, R2, C3.", False),
        ("  Hot end of ROD 1 + C1 -> A0 (CN9 pin 1);   hot end of ROD 2 + C2 -> A1 (CN9 pin 3).", False),
        ("  Cold ends of both rods -> the bias node;  3V3 -> R1 -> bias node -> R2 -> GND;  C3 bias node -> GND.", False),
        ("  Put C1 / C2 right at the pins. The cable capacitance (about 50 pF per metre) adds to C1 / C2.", False),
        ("", False),
        ("Why this is simpler and better", True),
        ("  One divider and one decoupling capacitor serve both channels; the two 100 nF coupling capacitors", False),
        ("  are gone. The bias node is an AC ground (C3), so each tuned circuit sits between its pin and AC ground,", False),
        ("  and DC reaches the pin through the rod winding (a few ohms): both pins sit at 1.65 V.", False),
        ("  Old input: the 10k/10k divider (5 k) loaded the tuned rod through 100 nF: Q about 8 instead of about 50,", False),
        ("  about 15 dB less signal at 225 kHz. Now nothing loads it (ADC sampling at 1 Msps is about 200 k).", False),
        ("  The tuning capacitor at the pin is also the charge reservoir for the ADC's sampling capacitor.", False),
        ("", False),
        ("Tuning (higher Q = narrower: 225 kHz about +-2 kHz, 77.5 kHz about +-0.8 kHz)", True),
        ("  Rods vary by several %. Tune for the highest C/N0 in the NUCLEO's CARRIER line (every 60 s):", False),
        ("  add or remove small capacitors at the board (47-220 pF at 225 kHz, 0.47-1 nF at 77.5 kHz).", False),
        ("  With 1 m of twisted pair (about 50 pF) C1 = 1.2 nF + 150 pF is closer; 77.5 kHz hardly changes.", False),
        ("", False),
        ("Placement", True),
        ("  A ferrite rod receives best broadside (its axis at right angles to the station's direction).", False),
        ("  From Wroclaw: Solec Kujawski (225 kHz) is about north -> ROD 1 axis east-west;", False),
        ("  Mainflingen (DCF77) is about west -> ROD 2 axis north-south. The rods end up crossed, which also", False),
        ("  keeps them from coupling; keep them 20-30 cm apart and away from the board and power supplies.", False),
        ("", False),
        ("Firmware", True),
        ("  Today both stations come from A0. A1 needs a firmware change (second ADC, DCF77 from A1); I make it", False),
        ("  after the rod is connected. Until then A1 is simply unused.", False),
    ]
    y = 0.595
    for text, bold in notes:
        fig.text(0.07, y, text, fontsize=9.6 if bold else 8.2, weight="bold" if bold else "normal",
                 color=BLUE if bold else "black")
        y -= 0.0152
    fig.text(0.07, 0.012, "SQ6EMM / e-CzasPL receiver experiments, 28.09.2026", fontsize=7.5, color=GREY)
    pdf.savefig(fig)
print("ok")
