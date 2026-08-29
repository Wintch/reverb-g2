# 63 — Hardware map: every part we can name, and every one we cannot

**Born 2026-08-19 (T231) at the user's request: "asegurate de mapear todo el hardware. Tener
referencias. Me avisas y las busco."** The knowledge existed — it was just scattered across
`docs/10` (firmware strings and FCC filings), `docs/12` (protocol and video chain) and `docs/00`
(USB topology), so nobody could see what was *missing*. This is one table, and the last column is
the point: **what is actually confirmed, what is inferred, and what nobody here has ever
identified.** The gaps at the end are a shopping list for someone with a screwdriver or a better
search engine.

Confidence is stated per row and means exactly this:
- **confirmed** — read from the device, its firmware, or its own datasheet.
- **inferred** — a strong chain of reasoning from something confirmed, but never seen directly.
- **unknown** — nobody here has identified it. Not "probably X". Unknown.

## Identifiers on the physical labels

Read off this unit by the user, 2026-08-19 (T232). **Model and regulatory numbers only —
serial numbers never go in this repo**, and none are needed here: what makes these useful is
that they identify a *model*, which is exactly what a spare-parts search or a second owner needs.

| Identifier | What it is |
|---|---|
| **`TPC-Q077-VH`** | HP **regulatory model** for the headset. `TPC-Q077` covers the whole G2 family; the suffix names the component |
| **`TPC-Q077-C1`** / **`M09967-001`** | **RIGHT** controller — regulatory model / HP part number |
| **`TPC-Q077-C2`** / **`M09967-002`** | **LEFT** controller |
| **`VR3000-0XX`** | HP **product/model number of the base Reverb G2**. `0XX` is a wildcard for regional variants |
| `HFS-A85Q` | FCC ID of the G2 (grantee Quanta, 2020-06-05) |
| `HFS-A85R` | FCC ID of the **Omnicept**, a separate SKU (e.g. `3A7X9AA#ABA`) |

### Every regulatory marking on this unit's label (T232)

Read off one label, in one pass. Together they say this is a **global-SKU label** — HP printed
every market's approval on the same sticker, which is also what makes the `0XX` in `VR3000-0XX`
a wildcard rather than a mystery.

| Marking | Authority | Confidence |
|---|---|---|
| **`HFS-A85Q`** | **FCC** (USA). Confirms on the object itself the filing this repo attributes to the base G2 | **confirmed** |
| **`R-R-HPI-TPC-Q077-VH`** | **KC / RRA** (South Korea). The `R-R-<applicant>-<model>` form is unambiguous: `HPI` = HP Inc., model as printed | **confirmed** |
| **`CCAM20LP1040T9`** | **NCC** (Taiwan). `CCA` + year/month `M20` + type `LP` + sequence — the standard NCC form | **confirmed** |
| **`09742-20-02585`** | **ANATEL** (Brazil) homologation, 2020. Their numbers are exactly `NNNNN-YY-NNNNN` | **confirmed by format** |
| **`TA-2020/6310`** | **ICASA** (South Africa) type approval. ICASA's documented form is `TA` + year + sequence | **confirmed by format** |
| **`IC: 1787B-A85Q`** | **ISED Canada** certification. `1787B` is HP's IC company identifier and `A85Q` the model — **the same model code as the FCC ID**, which independently corroborates that `A85Q` is the base G2 | **confirmed** |
| **`CAN ICES-3(B)/NMB-3(B)`** | **Canada ICES-003 Class B** — a *compliance statement*, not an identifier: it declares the unit a Class B digital apparatus, printed bilingually (`ICES` English / `NMB` French) | **confirmed** |
| **`RCPHPTP20-1711`** | **IFT** (Mexico) homologation, 2020. `RCP` + brand code + two-digit year + sequence is IFT's documented form | **confirmed by format** |
| **`E142692`** (with `CQ10`) | **UL file number** — a safety listing, not radio. `E` + six digits is UL's file format; the `CQ10` suffix is presumably a category code and is **not identified** | **file number confirmed, suffix unknown** |

Markets covered: **US, Canada, Mexico, Brazil, South Korea, Taiwan, South Africa**, plus a UL
safety listing — the Americas end to end, plus east Asia and southern Africa. Note that the
Canadian IC number embeds **`A85Q`**, the same model code as the FCC ID: two regulators
independently corroborating the identification this repo had to correct tonight. For
a rescued second-hand unit this is provenance nobody normally records, because the original owner
never needed it.

> **Correction this produced (T232).** Three files in this repo — `docs/10`, `docs/12`,
> `docs/04` — stated that `VR3000-0XX` was the **Omnicept's** SKU and matched filing `HFS-A85R`.
> It is the **base G2's own number**, now read directly off a plain G2's label. The repo already
> contained the disproof and nobody had reconciled it: `docs/31` records the live readout
> `Found headset: HP Inc. VR3000-0XX (HP Reverb Virtual Reality Headset G2)`. Fixed in all three.
> The FCC split itself — `A85Q` = G2, `A85R` = Omnicept — stands.

**Why model numbers earn their place in a repo about recycling hardware**: `TPC-Q077-C1` +
`M09967-001` is how you find a replacement controller for a discontinued headset. The equivalent
numbers for the cable and the PSU are exactly the ones still missing below.

## Headset — video chain

| Subsystem | Part | How we know | Confidence |
|---|---|---|---|
| DP → MIPI DSI bridge | **Analogix ANX7530** | Firmware version string `STM:..;DFU:..;ANX7688:..;ANX7530:..`; [product brief](https://www.analogix.com/en/system/files/AA-004263-PB-7-ANX7530_Product_Brief.pdf) obtained, rated for VR to 120 Hz | **confirmed** |
| Second Analogix part | **ANX7688** | Same firmware string. Its role here is *not* pinned down — the part is a USB-C/DP alt-mode + HDMI bridge, which does not obviously fit a headset that receives plain DP | **confirmed present, role unknown** |
| Bridge MCU | **STM32** (exact model unknown) | `STM:` in the version string; `MCU Download` silkscreen on the A85Q board; DFU paths in firmware (`bridge_fw_check_update`, `bridge_fw_switch_bank`, `QCI_FEATURE_ERASE_FLASH`) — the bridge firmware is field-updatable in banks | **confirmed family, model unknown** |
| Bridge debug access | **`DES JTAG` header** on the main board | Readable silkscreen in the FCC teardown photos. `DES` ≈ deserializer, i.e. the video chip. **There is a JTAG header on the bridge** | **confirmed** |
| Panels | 2 × LCD, 2160×2160, 90 Hz, PWM backlight | `panel_backlight_duty`, `[%s] left duty %d, right duty %d, frame timing %d, panel ID %d` in firmware; modes read from EDID | **confirmed behaviour, part unknown** |
| EDID modes | `4320x2160@90` (905150 kHz), `2880x1440@90` (428580), `4320x2160@60` (709150) | Read from the kernel, verified with `hmd-modeset list` | **confirmed** |

## Headset — tracking and sensors

| Subsystem | Part | How we know | Confidence |
|---|---|---|---|
| Cameras | 4 × **OmniVision OV7251**, 640×480 mono 8-bit, 2560×480 combined framebuffer | Firmware logs `OV7251SetFrameRate: 90hz requested but not USB3.0SS` | **confirmed** |
| Camera aggregator | **Lattice CrossLink `LIF-MD6000-6CSFBGA81`** | Datasheet + the Acer WMR teardown, where the same chip fills this role. **Was once wrongly called the video bridge — it is not**, its datasheet does not mention DisplayPort | **confirmed** |
| IMU | — | Nobody here has identified it | **unknown** |
| Proximity sensor (nose bridge) | — | Its *data* is fully characterised (binary 1/0, `WMR_CONTROL_MSG_IPD_VALUE`, debounce measured in T225) but the part is not | **unknown** |
| IPD adjustment | motorised/encoded, value reported over HID | Same message carries it | **confirmed behaviour, part unknown** |

## Headset — USB and audio

| Device | ID | What it is | Confidence |
|---|---|---|---|
| SuperSpeed hub | `04b4:6504` | Cypress, in the cable's active box | **confirmed** |
| USB2 hub | `04b4:6506` | Cypress `CY4603` per its own USB strings | **confirmed** |
| Sensors | `045e:0659` "HoloLens Sensors" (Microsoft) | Cameras, IMU and the controller radio tunnel. Enumerates at SuperSpeed *or* high speed (measured T231) | **confirmed** |
| Companion | `03f0:0580` "QHMD A85V" (Quanta) | Panel on/off, activation, IPD, proximity. Almost certainly the STM32 above | **confirmed device, inferred silicon** |
| Audio | `0bda:4c15` (Realtek) | Speakers + mic | **confirmed** |
| Speakers / mic | — | Off-ear speakers, mic array size unknown | **unknown** |

## Cable and power — the part that has caused the most trouble

| Subsystem | Part | How we know | Confidence |
|---|---|---|---|
| Cable type | **Active**, with an inline box | Measured: the box contains USB hub silicon and a DP repeater (`docs/22`) | **confirmed** |
| Inline USB hub | Cypress (`04b4:650x`) | Enumerates as such | **confirmed** |
| **DP repeater in the box** | — | Its *existence* is established by the cable anatomy; **the chip has never been identified**. **The box carries NO external label on the visor-facing side (checked T232)**, so the only remaining route is opening it | **unknown — highest-value gap** |
| **Cable/box manufacturer** | **BizLink (Kunshan) Co., Ltd.** | Printed on the box label, T232. BizLink is a large cable-assembly and connector OEM (also dongles and active modules) — HP did not build this, they specified it | **confirmed** |
| Box label, other markings | `CAN ICES-3(B)/NMB-3(B)` (Canada Class B statement) and `HQ-TRE, 71025 Germany` — HP's EU authorised representative address (HP Deutschland GmbH, Böblingen) | Read T232 | **confirmed** |
| Box position on the cable | breakout at **~5 m**, splitting into a ~1 m **DisplayPort** tail and a ~1 m **USB-C** tail; cable ends are natively DP 1.3 and USB-C 3.0 | Public product descriptions, consistent with this repo's measured anatomy (`docs/22`) | **confirmed** |
| Cable sticker | serial (deliberately not recorded) **+ a firmware marking**, transcribed with uncertain characters as `fw 0x5_3 … 0x5_10` | Read T232. **That the cable carries a firmware version at all is the finding**: it confirms the inline box holds programmable silicon, which is the object docs/22 has suspected for months | **present, value not yet legible** |
| **THIS unit's cable** | **6 m active, SPS `M18238-001`, HP P/N `L72080-001`, regulatory model `TPC-B001C`** — the ORIGINAL revision, no switch | Read off the cable label, 2026-08-19 (T232); **P/N `L72080-001` confirmed T239** against a second, physically different unit's box (below) | **confirmed** |
| Replacement part, if the swap is ever run | **`M52188-001`**, HP P/N **`L72080-002`** — *"SPS-CA ACTIVE 6M BLACK **/W SWITCH**"*, also sold as `22J68AA` | HP's own listing (SPS + `22J68AA`); the one HP support recommends under warranty. **P/N `L72080-002` confirmed T239** — see below | **confirmed** |
| Revisions in existence | Rev A (original) and **rev2A** (adds a button Rev A lacks) | User knowledge, community record (`docs/22`) | **confirmed** |
| **PSU** | **HP 65 W, 18.5 V, 3.5 A, 4.8 × 1.7 mm barrel.** Spare `381090-001`, P/N `380467-001`, series `PPP009H`, model `PA-1650-02H` (LiteOn) | All four read off the brick's own label, T232, and all four resolve to the same 65 W / 18.5 V family — an ordinary HP laptop adapter that HP reused here | **confirmed** |

### Two units side by side (T239) — a rare direct rev1/rev2 comparison, and what it does and doesn't show

Credit where due: the comparison images that drove this section came from a YouTube video,
**"HP Reverb G2 (ВТОРАЯ РЕВИЗИЯ) ► Сравниваем с первой и аналогами"** ("HP Reverb G2 [SECOND
REVISION] ► Comparing with the first and analogues"), channel **VR Studio**
(`youtube.com/@VRStudio`), <https://youtu.be/POGlHlz4qLk>. Two physical G2 revisions filmed
side by side, labels legible — that's uncommon; most teardowns only ever show one unit.

**Headset labels: identical, no revision marking found.** Both units' regulatory labels read
`TPC-Q077-VH`, `VR3000-0XX`, FCC ID `HFS-A85Q`, IC `1787B-A85Q`, ANATEL `09742-20-02585`,
`CCAM20LP1040T9` — every field this repo already treats as the base G2's identity (see the
table above) matches across both units, character for character. **This is negative evidence
against a headset-label-visible hardware revision**: whatever changed between the two units in
this video, it isn't declared on the regulatory sticker. (The user's opening question this
session was whether vertical FOV differs between the two — the labels can't settle that; FOV
isn't a regulatory field, and no optics/lens photo from this video has been reviewed yet.)

**The cable's inline box: the two P/Ns this repo already had, now seen on camera together.**
Same video, box labels legible on both: **`L72080-001` / SPS `M18238-001`** (original Rev A,
matches this unit's own cable, row above) and **`L72080-002` / SPS `M52188-001`** ("w/ switch"
replacement, also matches the row above). Model Name `TPC-B001C` identical on both boxes —
consistent with the headset finding: HP kept the regulatory model constant across a hardware
revision. No switch was visible in the frame reviewed (label side only, not the box's edge).

**Open thread: a second PSU.** The user reports the rev2 cable in the video ships with a
different power supply than this unit's `PPP009H`/`PA-1650-02H` (row above), and that the two
*looked* interchangeable — **not yet confirmed by a label read or a physical swap test**.
Needed to close this: the second PSU's own label (P/N, output V/A) from the video, and whether
"interchangeable" means same electrical spec or an actual tested swap. Until then, treat the
single-PSU row above as covering only this unit.

## Controllers

| Subsystem | Part | How we know | Confidence |
|---|---|---|---|
| Tracking LEDs | ring of **32** IR LEDs | Constellation model in the WMR calibration data; ~11° spacing derived in T224 | **confirmed count** |
| LED drive | **host-commanded LED pulse train / intensity** (12-byte output report: 9-bit 1-399 pulse-length field + 55-bit exposure timestamp) | Windows re-sends it ~15x/s for the whole tracking session (10,503 commands in one 730 s capture) -- `docs/re-windows/04-led-model.md` s3, decompiled 2026-08-17 and confirmed on the wire 2026-08-25. Upstream Monado never sends it; thaytan's `dev-constellation-controller-tracking` branch does (`WMR_MOTION_CONTROLLER_LED_CONTROL` `0x03`, `fill_timesync_packet()`, plus a blob-brightness feedback loop) -- see s4 of the same doc. T229's "no host command exists" (2026-08-19) was wrong; row corrected 2026-08-28 | **confirmed present** |
| IMU | — | Data fully characterised (gain 0.9905 L/R, wobble <1°, T212 quorum test); part unknown | **unknown** |
| Radio | Bluetooth, tunnelled through the headset's HoloLens device | `docs/03` | **confirmed path, part unknown** |
| Battery | 2 × AA | Measured extensively (`docs/46`) | **confirmed** |
| MCU | — | | **unknown** |
| **Left vs right are DIFFERENT PARTS** | right `TPC-Q077-C1` / `M09967-001`, left `TPC-Q077-C2` / `M09967-002` | Read off both controllers, T232 | **confirmed** |

## Host board (the lab machine, not the headset — but the port map lives here)

| item | value | source |
|---|---|---|
| Board | **ASUS TUF GAMING B450M-PLUS II** | DMI + label |
| Socket / chipset | AM4 / **B450** | ASUS techspec |
| CPU | AMD Ryzen 5 3600 (Matisse) | `/proc/cpuinfo` |
| USB controllers | **`09:00.3` Matisse (CPU)** — headset works; **`02:00.0` B450 chipset** — headset fails | live `lspci` |
| Rear USB | 6 (2× USB2, USB-C, teal Gen2 Type-A, 2× Gen1 Type-A blue) | ASUS rear-panel diagram §1.2.2 |
| The gap ASUS leaves | **which rear port is CPU vs chipset is NOT in the public spec** | — |

This is a property of the BOARD, not the headset, and it is why `docs/00` + `usb-port-map.sh`
carry a per-board ledger. The identity here is the reference; the live census is the map.

## Regulatory / teardown references

## Regulatory / teardown references

| Reference | What it is | Where |
|---|---|---|
| **FCC ID `HFS-A85Q`** | The G2 itself. Grantee Quanta Computer, grant 2020-06-05 | [fccid.io/HFS-A85Q](https://fccid.io/HFS-A85Q) |
| **FCC ID `HFS-A85R`** | The **Omnicept** — a different SKU; its teardown photos are of the **Tobii** eye-tracking board | [fccid.io/HFS-A85R](https://fccid.io/HFS-A85R) |
| Internal photos | 78 images extracted; scanned at ~130 DPI ≈ **7 px/mm**, which is *below* silkscreen legibility — the main IC is a black square with no readable text even at 10× | local, not in repo |
| Schematics / block diagram | **Filed with the FCC and permanently withheld** at Quanta's request | not obtainable |

## What is worth going to find

Ordered by what it would actually unlock, not by how easy it is:

1. **The DP repeater chip in the cable's inline box.** Years of link faults point at that box
   (`docs/22`), the rev2A "fix" is a lottery, and we cannot even name the part. A photo of the
   board inside the box — the box opens — would answer it in one step. **Highest value.**
2. **The headset's IMU part.** Roll drift under motion is an open problem attributed to
   gyro-bias-under-dynamics (`docs/pruebas` T203 item 2). Knowing the part means knowing its
   spec'd bias stability, which turns "the drift seems high" into "the drift is 3× spec" or "we
   are asking too much of a cheap part".
3. **The controller IMU and MCU.** Same reasoning. (The LED-drive half of this question is
   answered: the host commands the pulse length, see the Controllers table above.)
4. **The panel part number.** Would settle whether the 90 Hz limit is the panel or the bridge,
   which is the question this whole repo started from.
5. **The exact STM32 model.** With `MCU Download` and `DES JTAG` headers on the board, a named
   part is the difference between "there is a JTAG header" and actually talking to it.
6. **ANX7688's role — and a hypothesis that would resolve it (T232).** A USB-C/DP-alt-mode
   bridge makes no obvious sense *inside a headset fed by plain DP*. But the **link box has a
   USB-C tail**, and an ANX7688 is precisely the part for a USB-C end that must carry DP alt-mode
   alongside USB. **Hypothesis: the ANX7688 is in the BOX, not in the visor** — the version string
   that names it (`STM:..;DFU:..;ANX7688:..;ANX7530:..`) is a firmware manifest, and nothing in it
   says the two chips live in the same enclosure. Two further facts point the same way: the cable
   label carries **two** firmware values, which fits an enclosure with two programmable parts; and
   `docs/22` has suspected programmable silicon in that box for months on independent evidence.
   **This is a hypothesis, not a finding.** The test is one photograph of the board inside the box
   — and it would simultaneously close gap #1.

### The hands are not the same part, and that matters right now

`TPC-Q077-**C1**` / `M09967-**001**` (right) versus `TPC-Q077-**C2**` / `M09967-**002**` (left):
**different regulatory suffix and different HP part number.** Two open investigations were
resting on an assumption this quietly removes.

- **The LED brightness asymmetry** (T229/T230): Windows shows the left ring at 1.61× the blob
  count and 2.45× the area of the right, while Linux shows the two as identical. The reasoning so
  far treated the controllers as interchangeable units, which made a physical difference between
  them look implausible and pushed the explanation toward batteries or environment. They are not
  interchangeable units.
- **"The left hand is worse"** (carried since T215, then destabilised by T225's measurement of
  the hands *inverting* between windows): same assumption, same removal.

**Do not over-read it.** Any mirrored pair gets two part numbers — the shells alone are
handed — so distinct numbers are **necessary but nowhere near sufficient** for an electrical or
optical difference. What is dead is only the argument *"they are the same unit, so the difference
must be external"*. The measurements still have to do the work: the **battery swap** and the
**position-swap photograph** already queued (T230) are unaffected and are still what decides it.

## Labels still to read, and where they are

The identifiers above came off one label. These are the rest, in the order they would be useful —
all of them are **model/part numbers, not serials**:

1. ~~**The cable's own label**~~ **done and confirmed (T232)**: SPS **`M18238-001`**, which is
   exactly the number resellers list as an older cable revision. (A first reading had a stray
   digit; re-read and corrected on the spot, which is the only reason it is mentioned — a part
   number someone will search on has to be right.)
2. **Any marking on the inline box** on that cable — the box holding the DP repeater nobody has
   identified. Even a bare number would close gap #1 of the list above.
3. ~~**Both controllers**~~ **done (T232)**: right `TPC-Q077-C1` / `M09967-001`, left
   `TPC-Q077-C2` / `M09967-002` — see the note below, it bears directly on the LED question.
4. **The headset label's remaining fields**: the HP **SPS / spare part number** (`M#####-001`
   form) if present, the **IC** number next to the FCC ID, and the **date code** — a manufacture
   date bounds which cable revision shipped with it.
5. ~~**The PSU**~~ **done (T232)** — and it corrected a voltage this repo had wrong in 33 places.

**All five are done, and the label sweep is closed.** The one thing the labels could NOT give is
the highest-value gap in this document: the inline box carries **no external marking on its
visor-facing side**, so the DP repeater's identity still requires opening it.

**How to help:** clear photographs of board silkscreen at legible resolution — the FCC scans are
too coarse by roughly a factor of three. The G2 opens; the cable box opens. Anything readable
goes straight into the table above.
