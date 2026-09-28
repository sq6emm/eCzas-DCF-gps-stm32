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
L = 360e-6
f0 = lambda C: 1 / (2 * math.pi * math.sqrt(L * C))
schemdraw.config(fontsize=11)
d = schemdraw.Drawing(show=False, unit=3)


def tank(x, c_label, rod_label, pin_label):
    """rod || C between the bias bus (y=0) and the pin (top)"""
    d.add(elm.Inductor2(loops=5).at((x, 5)).to((x, 0)).label(rod_label, loc="top", ofst=0.25))
    d.add(elm.Capacitor().at((x + 2.2, 5)).to((x + 2.2, 0)).label(c_label, loc="bottom", ofst=0.25))
    d.add(elm.Line().at((x, 5)).to((x + 2.2, 5)))
    d.add(elm.Dot().at((x + 2.2, 5)))
    d.add(elm.Line().at((x + 2.2, 5)).to((x + 2.2, 6.6)))
    d.add(elm.Dot(open=True).at((x + 2.2, 6.6)).label(pin_label, loc="top", ofst=0.2))
    d.add(elm.Dot().at((x, 0))); d.add(elm.Dot().at((x + 2.2, 0)))


tank(0.0, "C1\n1.2 nF\n+ 180 pF\nC0G", "ROD 1\n360 µH", "A0  (CN9 pin 1)\ne-CzasPL 225 kHz")
tank(6.5, "C2\n10 nF\n+ 1.8 nF\nC0G / film", "ROD 2\n360 µH", "A1  (CN9 pin 3)\nDCF77 77.5 kHz")
d.add(elm.Line().at((0, 0)).to((14.5, 0)))
d.add(elm.Label().at((10.9, -0.45)).label("bias node 1.65 V", halign="center", color=BLUE))
# shared bias: divider and decoupling
d.add(elm.Dot().at((12.5, 0)))
d.add(elm.Resistor().at((12.5, 0)).to((12.5, 3.6)).label("R1\n10 k", loc="bottom", ofst=0.3))
d.add(elm.Dot(open=True).at((12.5, 3.6)).label("3V3 (CN8)", loc="top", ofst=0.2))
d.add(elm.Resistor().at((12.5, 0)).to((12.5, -3.2)).label("R2\n10 k", loc="bottom", ofst=0.3))
d.add(elm.Dot().at((14.5, 0)))
d.add(elm.Capacitor().at((14.5, 0)).to((14.5, -3.2)).label("C3\n1 µF\n(+100 nF)", loc="bottom", ofst=0.3))
d.add(elm.Line().at((12.5, -3.2)).to((14.5, -3.2)))
d.add(elm.Ground().at((13.5, -3.2)).label("GND (CN8)", loc="right", ofst=0.4))
d.add(elm.Dot().at((13.5, -3.2)))
d.save("/o/sch2.png", dpi=220)

with PdfPages("/o/nucleo_225_77kHz_input.pdf") as pdf:
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.07, 0.955, "Two ferrite rods to NUCLEO-H723ZG: e-CzasPL on A0, DCF77 on A1", fontsize=12.5, weight="bold", color=BLUE)
    fig.text(0.07, 0.935, "One shared 1.65 V bias node, no coupling capacitors (replaces nucleo_225kHz_input.pdf)", fontsize=9.5, color=GREY)
    ax = fig.add_axes([0.05, 0.615, 0.90, 0.31]); ax.axis("off"); ax.imshow(plt.imread("/o/sch2.png"))
    c1, c2 = 1.2e-9 + 180e-12, 10e-9 + 1.8e-9
    notes = [
        ("Parts", True),
        ("  ROD 1, ROD 2: the same ferrite rod type (12 cm, about 360 µH; the rod on A0 today)", False),
        (f"  C1 = 1.2 nF + 180 pF in parallel (1.38 nF) -> {f0(c1)/1e3:.1f} kHz         (today: 1.5 nF = {f0(1.5e-9)/1e3:.1f} kHz)", False),
        (f"  C2 = 10 nF + 1.8 nF in parallel (11.8 nF) -> {f0(c2)/1e3:.1f} kHz          (10 nF + 1.5 nF would be {f0(11.5e-9)/1e3:.1f} kHz)", False),
        ("  C1, C2: C0G/NP0 ceramic, polystyrene or polypropylene film (stable, low loss; not X7R)", False),
        ("  R1, R2 = 10 k;  C3 = 1 µF ceramic, optionally + 100 nF, close to the rods' bias ends", False),
        ("", False),
        ("Connections", True),
        ("  Each rod with its capacitor directly across it (a parallel tuned circuit).", False),
        ("  Hot end of ROD 1 + C1 -> A0 (CN9 pin 1);   hot end of ROD 2 + C2 -> A1 (CN9 pin 3).", False),
        ("  Cold ends of both rods -> the bias node;  3V3 -> R1 -> bias node -> R2 -> GND;  C3 bias node -> GND.", False),
        ("  Put C1 / C2 at the board end (next to the pins); twisted pair from the rods, keep both short.", False),
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
        ("  add or remove small capacitors (47-220 pF at 225 kHz, 0.47-1 nF at 77.5 kHz). The cable adds 10-20 pF.", False),
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
