# Ferrite rod antennas for e-CzasPL (225 kHz), TDF (162 kHz) and DCF77 (77.5 kHz)

One rod + coil type for all three stations; each is tuned by its own capacitor (added by us, at the rod).
Background: `three-station-design.md`; measurements behind the choices below: 30 Sep 2026 (SPECTRUM
diagnostic: the DCF77 rod on the NUCLEO resonates ~12 kHz too low, most likely the cable capacitance
inside the tuned circuit; the e-CzasPL rod's antenna noise is already ~15 dB above the ADC floor, so
reception is limited by what the antenna picks up, not by rod size).

## 1. Specification for the manufacturer (copy and paste)

```
Ferrite rod antenna coil - request for quotation

Quantity: 4 pcs (3 + 1 spare)
Application: LF receiving antenna, 70-250 kHz (time signal reception)

1. Ferrite rod
   - Dimensions: diameter 10 mm, length 100 mm (tolerance +-0.3 mm / +-1 mm)
   - Material: EITHER NiZn ferrite, initial permeability 400-1000 (medium-wave antenna grade)
               OR MnZn ferrite, initial permeability 2000-2500 (e.g. PC40 / 2K grade)
     NOT acceptable: MnZn with initial permeability above 3000 (5K/10K grades);
                     NiZn with initial permeability below 200 (shortwave grades)
   - Please state the material grade and its initial permeability.

2. Main winding (L1)
   - Inductance: 500 uH +-10 %, measured at 100 kHz, 0.1-1 V, on the finished rod
   - Wire: litz wire (e.g. 20 x 0.05 mm or 40 x 0.07 mm)
   - Single layer, centred on the rod, winding length approx. 30-45 mm
   - Number of turns: as needed for 500 uH (please state it)
   - Unloaded Q: at least 60 at 100 kHz and at 200 kHz (please state the measured value)
   - Leads: 2 wires, at least 100 mm long, ends tinned, marked "L1 start" / "L1 end"

3. Secondary (link) winding (L2)
   - 7 turns, wound on top of the middle of L1, insulated from L1
     (insulating tape between the windings)
   - Wire: enamelled copper 0.3-0.5 mm or insulated stranded wire
   - Leads: 2 wires, at least 150 mm long, ends tinned, marked "L2"

4. Mechanical
   - Windings fixed with tape or varnish (no loose turns); the rod must not slide in the coil
   - Coil former / sleeve allowed; please state its length and position on the rod
   - No metal parts (clips, brackets) within 20 mm of the rod ends

5. Documentation with the delivery
   - Per piece: measured inductance of L1 (uH) and Q at 100 kHz
   - Material grade, number of turns of L1
```

### The same in Chinese (for Chinese suppliers)

```
磁棒天线线圈 - 询价

数量: 4 个 (3 个 + 1 个备用)
用途: 长波接收天线, 70-250 kHz (授时信号接收)

1. 铁氧体磁棒
   - 尺寸: 直径 10 mm, 长度 100 mm (公差 +-0.3 mm / +-1 mm)
   - 材料: 镍锌铁氧体, 初始磁导率 400-1000 (中波天线用材料)
           或 锰锌铁氧体, 初始磁导率 2000-2500 (例如 PC40 / 2K 材料)
     不可接受: 初始磁导率高于 3000 的锰锌材料 (5K/10K); 初始磁导率低于 200 的镍锌材料 (短波用)
   - 请注明材料牌号和初始磁导率。

2. 主线圈 (L1)
   - 电感量: 500 uH +-10 %, 在成品磁棒上于 100 kHz, 0.1-1 V 测量
   - 线材: 多股利兹线 (例如 20 x 0.05 mm 或 40 x 0.07 mm)
   - 单层绕制, 位于磁棒中部, 绕线长度约 30-45 mm
   - 匝数: 按 500 uH 需要 (请注明)
   - 空载 Q 值: 在 100 kHz 和 200 kHz 时至少 60 (请注明实测值)
   - 引线: 2 根, 长度至少 100 mm, 线头镀锡, 标记 "L1 起" / "L1 末"

3. 次级 (耦合) 线圈 (L2)
   - 7 匝, 绕在 L1 中部的上面, 与 L1 之间绝缘 (两线圈之间加绝缘胶带)
   - 线材: 0.3-0.5 mm 漆包铜线或绝缘多股线
   - 引线: 2 根, 长度至少 150 mm, 线头镀锡, 标记 "L2"

4. 机械要求
   - 线圈用胶带或绝缘漆固定 (不得松动); 磁棒在线圈中不得滑动
   - 可以使用线圈骨架/套管; 请注明其长度和在磁棒上的位置
   - 磁棒两端 20 mm 以内不得有金属零件 (夹子, 支架)

5. 随货文件
   - 每个: L1 实测电感量 (uH) 和 100 kHz 时的 Q 值
   - 材料牌号, L1 匝数
```
(The Chinese text is our translation of the English above; if in doubt, the English is binding.)

Length: 100 mm (changed from 150 mm on 30 Sep so that three rods fit a Hammond 1554VAL2GY, see
`frontend-architecture.md`): ~-4.5 dB of signal against 150 mm, but the antenna noise stays ~10 dB above
the ADC floor, so practically no SNR loss; not below ~80 mm. 150 mm rods need the 1554X2GY (300 x 200 x 90).
The inductance and the capacitors do not depend on the length.

## 2. Our part: tuning, Q, cable

Capacitors: C0G/NP0, 1-2 %, soldered **at the rod** across L1. CORRECTION (30 Sep): the capacitor's position
alone does not keep a cable out of the tuning - a cable on L1 is in parallel with the tank wherever C sits.
The cable must hang on the amplifier output (antenna head, `frontend-architecture.md`) or on the 7-turn
link L2 (capacitance transformed down ~50-100x); L1 only ever sees a few cm of wiring. Calculated for
L1 = 500 uH:

| station | f | C (500 uH) | practical | R across L1 for Q ~ 30 |
|---|---|---|---|---|
| DCF77 | 77.5 kHz | 8.43 nF | 8.2 nF + ~220 pF | ~7.5 kOhm |
| TDF | 162 kHz | 1.93 nF | 1.8 nF + ~130 pF | ~15 kOhm |
| e-CzasPL | 225 kHz | 1.00 nF | 1.0 nF (trim -20...-50 pF for strays) | ~22 kOhm |

C = 1 / ((2 pi f)^2 L) - recompute with each rod's measured L (+-10 % tolerance). Q ~ 30 (R = Q 2 pi f L)
keeps enough bandwidth for DCF77's phase code (+-650 Hz; needs Q <= ~50 at 77.5 kHz) and makes the
resonance insensitive to temperature (timing). The 7-turn L2 (with ~50-70 turns on L1: impedance
~50-100x lower, ~100-350 Ohm) can feed a cable - but it also lowers the voltage ~8x (-18 dB), below the ADC
noise floor without an amplifier; the planned front end has an amplifier at each rod in an antenna head
(`frontend-architecture.md`).

Why the material hardly matters: for a 10 x 150 mm rod (length/diameter 15) the effective permeability
is set by the geometry - about 75 for NiZn mu_i 400, about 90 for MnZn mu_i 2300 (demagnetisation
estimate), i.e. ~1.5 dB (10 x 100 mm: ~45 / ~49, even less); the same factor dilutes the material's temperature coefficient. What must be
avoided: lossy very-high-mu MnZn (5K/10K) above ~100 kHz and low-mu shortwave NiZn.

## 3. Acceptance checks on arrival

1. L1 with an LCR meter at 100 kHz: 500 uH +-10 %; note the value per rod, compute C.
2. Solder C (+ R), connect L2 to A0 / A1 of the NUCLEO: the `SPECTRUM` line (every 10 min, noise
   floor per band) must show the hump at the station's frequency; move it with 47-220 pF steps.
   (162 kHz needs its own input - see `three-station-design.md`.)
3. A very broad, flat hump = a lossy rod.
4. Warm the rod with a hair dryer for a minute: the hump must move by less than ~1 % of f.

## 4. Mounting

- DCF77 (bearing ~261 deg) and TDF (~254 deg) rods side by side, parallel; the e-CzasPL rod (bearing
  ~20 deg) at 90 deg to them. With the DCF77 / TDF axis at ~182 deg each rod is off its broadside
  direction by at most 18 deg (-0.45 dB) - see `frontend-architecture.md` (head layout, box) and
  `antenna_head.pdf`.
- Rods ~45 mm apart in the head (different frequencies: weak coupling; verify with the prototype);
  the head away from switch-mode supplies, the NUCLEO, computers.
- Optional: a slit copper-foil shield over the windings, grounded at one end only.
