"""GPS PPS for the one-off calibration: u-blox LEA-M8T TIMEPULSE -> NUCLEO-H723ZG PC8 (TIM3_CH3).
Draws doc/nucleo_gps_pps.pdf (+ png).
  docker run --rm -e HOME=/tmp -v $PWD/doc:/o python:3.12-slim sh -c \
    "pip -q install --user schemdraw matplotlib && python3 /o/nucleo_gps_pps.py"
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import schemdraw, schemdraw.elements as elm

BLUE, GREY, RED, GREEN, PURPLE = "#1f4e79", "#666", "#b22222", "#2e7d32", "#6a1b9a"

schemdraw.config(fontsize=12)
d = schemdraw.Drawing(show=False, unit=2.5)
for a, b in [((0, -0.5), (3.4, -0.5)), ((3.4, -0.5), (3.4, 11.5)), ((3.4, 11.5), (0, 11.5)), ((0, 11.5), (0, -0.5))]:
    d.add(elm.Line().at(a).to(b))
d.add(elm.Label().at((1.7, 12.3)).label("LEA-M8T board", fontsize=13))
rows = {10: "TIMEPULSE (PPS)", 7.5: "GND", 5: "VCC (see note 3)", 2.5: "TX (optional)", 0.5: "RF / antenna"}
for y, t in rows.items():
    d.add(elm.Label().at((3.2, y)).label(t, halign="right"))
d.add(elm.Line().at((3.4, 10)).to((4.4, 10)))
d.add(elm.Resistor().at((4.4, 10)).to((7.4, 10)).label("1 kΩ", loc="top", color=GREEN))
d.add(elm.Line().at((7.4, 10)).to((10.5, 10)))
d.add(elm.Dot(open=True).at((10.5, 10)).label("PC8  (CN8 pin 2, D43)  = TIM3_CH3", loc="right", ofst=0.25, color=GREEN))
d.add(elm.Line().at((3.4, 7.5)).to((10.5, 7.5)))
d.add(elm.Dot(open=True).at((10.5, 7.5)).label("GND  (CN8 pin 11 or 13)", loc="right", ofst=0.25))
d.add(elm.Line().at((3.4, 5)).to((10.5, 5)))
d.add(elm.Dot(open=True).at((10.5, 5)).label("its own supply, or 3V3 (CN8 pin 7) if the board takes 3.3 V", loc="right", ofst=0.25, color=RED))
d.add(elm.Line().at((3.4, 2.5)).to((5.0, 2.5)).linestyle("--"))
d.add(elm.Label().at((5.2, 2.5)).label("-> USB-serial adapter RX (only for u-center; not needed)", halign="left", color=GREY))
d.add(elm.Line().at((3.4, 0.5)).to((5.0, 0.5)))
d.add(elm.Label().at((5.2, 0.5)).label("active GPS antenna ('mouse') with sky view", halign="left", color=PURPLE))
d.save("/o/gps_wiring.png", dpi=200)

with PdfPages("/o/nucleo_gps_pps.pdf") as pdf:
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.04, 0.95, "GPS PPS for the one-off calibration: LEA-M8T -> NUCLEO-H723ZG (3 wires + one 1 kΩ)", fontsize=15, weight="bold", color=BLUE)
    fig.text(0.04, 0.925, "Firmware /data/claude/nucleo-h723/gps/rx_build_ocxo_gps.bin: the pulse is captured on PC8 = TIM3_CH3, the counter that "
             "timestamps the OCXO and the ADC samples (5 ns steps).", fontsize=9.5, color=GREY)
    a = fig.add_axes([0.03, 0.30, 0.94, 0.60]); a.axis("off"); a.imshow(plt.imread("/o/gps_wiring.png"))
    notes = [
        "1. Power order as with the OCXO: NUCLEO on USB first, then the GPS board; off in the reverse order. Common GND is required.",
        "2. TIMEPULSE -> 1 kΩ -> PC8. The 1 kΩ protects the pin whatever the board's output level is (3.3 V module pin, or 5 V after a level shifter).",
        "   PC8 is on connector CN8, pin 2 (marked D43 / PC8) - please check the marking on your board before connecting. The firmware sets a pull-down there.",
        "3. Supply: LEA-M8T modules take 2.7-3.6 V; many breakout boards have their own regulator and take 5 V - use what the board says.",
        "   From the NUCLEO: 3V3 = CN8 pin 7 (only if the board is a 3.3 V board), 5V = CN8 pin 9. The GPS draws ~30-70 mA plus the active antenna.",
        "4. No configuration needed: the default TIMEPULSE is 1 pulse per second (rising edge = the second). GPS time and UTC differ by exactly 18 s,",
        "   so the fraction of the second is the same. Antenna with a clear view of the sky; wait for a fix (the board's LED blinks with the PPS).",
        "5. Then the new firmware is flashed; from the first pulse the log shows one 'GPS PPS' line per second (OCXO vs GPS, e-CzasPL clock and DCF77 second",
        "   vs the GPS second). Leave it connected ~24 h (day and night); tools/gps_calib.py turns the lines into the calibration.",
    ]
    y = 0.25
    for t in notes: fig.text(0.04, y, t, fontsize=9.2); y -= 0.026
    fig.text(0.04, 0.02, "SQ6EMM / e-CzasPL receiver experiments, 29.09.2026", fontsize=7.5, color=GREY)
    pdf.savefig(fig); fig.savefig("/o/nucleo_gps_pps.png", dpi=110)
print("ok")
