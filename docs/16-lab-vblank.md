# 16 — The vblank experiment: injected timings, method and data

> **SUPERSEDED: this factorial's central conclusion — "90 Hz is ruled out as achievable
> within this HBR3 link" — is WRONG.** Every cell used synthetic injected timings; the plain
> native EDID modes were never retested after the bpc patch existed (the "native fails"
> citation predates the patch by a day). Tested clean, native 90Hz works perfectly. The
> correct conclusion and the line-by-line trace of how the stale assumption propagated are in
> [`docs/19-nvidia-bug-5923212-followup.md`](19-nvidia-bug-5923212-followup.md) ("the patch
> DOES work") and the project summary in
> [`docs/21-project-retrospective.md`](21-project-retrospective.md). What is kept here is the
> *method* (how to inject EDID timings into NVKMS), the EDID presets, and the vblank /
> pixel-clock measurements, which remain valid as measurements of how this panel reacts to
> non-native timings. The "~709 MHz only locks" and "minimum vblank time" hypotheses below
> are refuted; do not reuse them.

**Validity precondition for any display experiment**: run it on the lab install with the
patched `nvidia-open` (595.71.05) and the bpc patch in the module (`./scripts/verify-bpc.sh`);
`dmesg | grep 'Notify Attach Begin'` must say `24 bpp`, not 18, and all five headset USB
devices (`04b4:6506 0bda:4c15 03f0:0580 04b4:6504 045e:0659`) must enumerate. Measuring with
the unpatched driver produces results that look plausible and blame the wrong culprit.

## The hypothesis and design

The G2's EDID offers three modes with identical horizontal blanking (50/4/46); only the
vertical blanking differs:

| mode | vblank | result at the time |
|---|---|---|
| 4320x2160@60 | 514 lines | works |
| 4320x2160@90 | 116 lines | fails (pre-patch) |
| 2880x1440@90 | 158 lines | fails (pre-patch) |

"90 Hz" and "short vblank" were perfectly confounded, so the experiment injected the missing
cells of a factorial (refresh rate x vblank shape). `CTRL` (60 Hz, long vblank, clone of the
working mode) is mandatory and runs first: without it a failure cannot be told apart from
"any injected mode breaks it".

**Why 2880x1440 for the first round:** the base block's DTD has a 12-bit horizontal active
field (max 4095 px), so 4320 does not fit; the G2 itself puts 2880x1440 in the base block and
its two 4320 modes in the DisplayID block (Type I descriptors, 16-bit fields).

Verification must be physical: the API reports a successful modeset and 90.0 fps with the
panel off. Put the headset on and note whether the backlight comes on, whether content is
shown in color or white/flickering, the `Notify Attach Begin` pclk/raster/bpp, and byte 18 of
the HID `DEVICE_STATUS` report (`scripts/panel-status.py`: byte 5 = refresh in decimal, bytes
19-22 = htotal/vtotal little-endian).

## Tooling: injecting EDID timings

`scripts/edid-tool.py` rewrites DTD slots (`inject-mode`, base block, 4 slots, slot 0 keeps
the native mode) and DisplayID Type I descriptors (`inject-did`). With no assignments it lists
the presets and slot contents. The input is the headset's own EDID
(`/sys/class/drm/card0-DP-1/edid`, saved to a file, `hmd.edid` below).

```bash
./scripts/edid-tool.py inject-mode hmd.edid -o g2-vblank-test.edid CTRL:1 A:2 B:3
./scripts/edid-tool.py inject-did  hmd.edid -o g2-vblank-4k-b.edid B4K:1
./scripts/edid-tool.py inject-did  hmd.edid -o g2-vblank-4k-80hz.edid 775@80:1   # BLANKING@RATE
```

Presets, all inside HBR3 (25.92 Gbps) except where noted:

| preset | timing | pclk | Gbps @24bpp |
|---|---|---|---|
| `CTRL` | 2880x1440@60 vblank 514 | 349.38 MHz | 8.39 |
| `A` | 2880x1440@60 vblank 158 | 285.72 MHz | 6.86 |
| `B` | 2880x1440@90 vblank 514 | 524.06 MHz | 12.58 |
| `CTRL4K` | 4320x2160@60 vblank 514 (clone of desc #2) | 709.14 MHz | 17.02 |
| `A4K` | 4320x2160@60 vblank 116 (desc #1 shape at 60 Hz) | 603.60 MHz | 14.49 |
| `B4K` | 4320x2160@90 vblank 240 (514 would need 25.53 Gbps, 1.5% margin) | 954.72 MHz | 22.91 |

Layout of the 384-byte first-round EDID: base block slot 0 native 2880x1440@90 (428.58 MHz,
vblank 158), slots 1-3 = `CTRL`, `A`, `B`; DisplayID descriptors untouched (4320x2160@90
905.40 MHz vblank 116, and @60 709.15 MHz vblank 514). For the second round only DisplayID
descriptor #1 (the failing @90) is replaced and descriptor #2 stays as a physical control.

DisplayID Type I descriptor layout (20 bytes, every field except polarities stores
`value - 1`):

```
0-2   pixel clock / 10 kHz, 24 bits LSB first
3     flags: bit7 preferred, bit4 interlaced
4-5   horizontal active        6-7    horizontal blanking
8-9   horizontal front porch, bit15 = hsync polarity
10-11 horizontal sync width
12-13 vertical active          14-15  vertical blanking
16-17 vertical front porch, bit15 = vsync polarity
18-19 vertical sync width
```

Two checksums must be corrected after editing: the DisplayID section's (last byte of the
section, which starts at `blk+1` and spans `5 + section_size`) and the extension block's
(`blk+127`). The decoder reproduces exactly 905.400 MHz / vblank 116 and 709.150 MHz / vblank
514 from the real bytes, which confirms the layout.

## Loading an EDID override into NVKMS

1. **`/sys/kernel/debug/dri/*/DP-1/edid_override` does not work.** Writing the file (on all
   three connector aliases) and cycling `force` left `/sys/class/drm/card0-DP-1/edid`
   byte-identical to the original: NVIDIA reads the EDID through its own RM/AUX channel, not
   DRM's generic helper. Do not retry.
2. **`nvidia_modeset.config_file` works end to end.** Grammar (from `nvkms-conf.c`):
   `override.[<domain>:<bus>.<slot>.<function>].<dpy-name> = /path/to/edid` with the brackets
   literal. The dpy name is NVKMS's **0-based** internal one: `DP-0` for what DRM calls
   `DP-1`. Verified by `dmesg` ("Successfully read ..."), by `/sys/class/drm/card0-DP-1/edid`
   matching the file's md5, and by the DRM mode count going from 3 to 6. A working template is
   `experiments/vblank/nvkms-override-candidates.conf`.
3. **Each new EDID needs its own reboot.** NVKMS copies the file into memory once while
   parsing `config_file` at module load (`nvkms-dpy-override.c: DpyOverrideReadEdid`).
4. Mode indices in `hmd-vk native <idx>` follow EDID slot order: base block first, then
   DisplayID. Identify clones by refresh precision (`hmd-vk list` prints 3 decimals) or by the
   HID report.

## Results (all with the bpc patch active, 24 bpp confirmed)

In every cell below the headset's HID `DEVICE_STATUS` reported htotal/vtotal/refresh/bpc
**byte-identical to what was injected**, so a failure is never "the timing did not arrive".

| label | resolution | refresh | vblank (lines) | pixel clock | vblank time | result |
|---|---|---|---|---|---|---|
| native @60 (desc #2) | 4320x2160 | 60 | 514 | 709.15 MHz | 3.204 ms | works |
| `CTRL4K` (clone in desc #1 slot) | 4320x2160 | 60 | 514 | 709.14 MHz | 3.204 ms | works (colors, backlight bit set) |
| `A4K` | 4320x2160 | 60 | 116 | 603.60 MHz | 0.849 ms | fails |
| `B4K` | 4320x2160 | 90 | 240 | 954.72 MHz | 1.111 ms | fails |
| `90long` | 4320x2160 | 90 | 514 | 1063.72 MHz | 2.136 ms | fails |
| `bisect1` | 4320x2160 | 60 | 340 | 663.00 MHz | 2.267 ms | fails |
| `80hz` | 4320x2160 | 80 | 775 | 1037.82 MHz | 3.301 ms | fails |
| `CTRL`, `A`, `B` | 2880x1440 | 60/60/90 | 514/158/514 | 349/286/524 MHz | - | all fail (HP logo) |
| native 2880x1440@90 | 2880x1440 | 90 | 158 | 428.58 MHz | - | failed pre-patch; **works** retested plain (docs/19) |

(vblank time = vblank / ((vactive + vblank) x refresh).) What the data does and does not say:

- Descriptor position is not a factor: `CTRL4K` works in descriptor #1's slot.
- The first four 4K cells sorted perfectly by vblank *time*, which suggested a minimum
  blanking duration; `80hz` (more blanking time than the working mode, comfortable bandwidth)
  refuted that. Every non-709 MHz cell failing then suggested "the bridge only locks at
  709 MHz". Both patterns are refuted by the later plain-native results (native 2880x1440@90
  at 428.58 MHz works). Why the injected timings fail while the native ones work was never
  explained; do not treat either pattern as a finding.
- Unexplained, left open: in `A` (first round) byte 1 of the second HID status message went
  `00` to `01` (Monado's G1 comment: "backlight visibly turned on") with no visible video; in
  `CTRL4K` the same bit coincided with real video, and in `B4K` HID never reported 90 at all
  (stayed at the previous 60 state). Treat that bit as unreliable as a content signal.
- Bandwidth was never the constraint: `A4K` fails at 14.49 Gbps; all injected modes were well
  inside 25.92 Gbps except the near-ceiling 90 Hz ones.

An untested follow-up that remained on the list: vary the *horizontal* blanking (every test
used 50/4/46) and a refresh sweep with fixed blanking shape (`SHORT@70/75/80`, 3 slots per
EDID, so bisect in rounds). With native 90 Hz working these lost their purpose.

## Corrections already applied to the published reports (do not reintroduce)

- The G2's extension is **DisplayID 1.2** (version byte `0x12`) with two **Type I**
  descriptors. It is NOT DisplayID 2.0 nor Type VII (verified against the real bytes).
- `input.u.digital.bpc` is assigned in **three** places in the tree, not two: `nvt_edid.c:932`,
  `nvt_edidext_displayid20.c:314`, and `nvkms-dpy.c:2257` (inside
  `CreateParsedEdidFromNVT_TIMING()`, which never runs for a sink with a real EDID).
- Line numbers on the 595.71.05 tag: DP clamp in `nvkms-dpy.c:3456`, DisplayID dispatch in
  `nvt_edid.c:1101`. On `main` (610.57.04) they are 3468 and 1101.
- DSC is ruled out **by arithmetic**, not by the absence of strings in `dmesg`: the working
  mode is 17.0 Gbps uncompressed and the failing one 10.3, so DSC cannot be required for the
  one that fails.
- The `.patch.txt` once attached on the forum was outdated ("DisplayID 2.0", miscounted hunk
  header); the regenerated patch is in `patches/nvidia/`.

## Verified against the real EDID bytes

```
byte 0x14 = 0x80          digital, color bit depth = 000 (undefined)
checksum base block 0xE8  block sum = 0
ManufID 0x220E            = HPN   (EDID spelling; DPLib getManufId() reads 0x0E22)
CTA byte 3 = 0x00         no YCbCr 4:4:4 nor 4:2:2
DisplayID: 70 12 79 00 00 03   version 1.2, tag 0x03, 40 bytes = 2 Type I descriptors
8bpc repro EDID           differs in exactly 2 bytes: 0x14 and 0x7F, valid checksum
```
