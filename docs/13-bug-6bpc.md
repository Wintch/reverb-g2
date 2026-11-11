# 13 — The bug: NVIDIA pins the G2 at 6 bits per color

> **RESOLVED: the patch below is the complete fix for 90Hz.** With it both native 90Hz modes
> come up clean on the plain EDID, and real video through the full player is verified.
> Resolution chain in `docs/19`; retrospective in `docs/21`. The bug was reported to NVIDIA
> (threads 379240 + 337744, PR #1275, still unmerged). This file documents the bug's anatomy.

It is one line of driver code.

---

## Summary

The Reverb G2's EDID **does not declare its color depth**. The Linux NVIDIA driver
interprets that "undeclared" as **6 bits per component** and drives the link at 18 bpp in
all modes. Windows, with the same GPU, uses 8. At 60 Hz the panel tolerates 6 bits; at 90 Hz
it doesn't light up.

---

## The causal chain, verified link by link

| # | link | evidence |
|---|---|---|
| 1 | The headset's EDID leaves the depth undeclared | byte `0x14` = `0x80`: digital, bits 6-4 = `000` = *undefined*, EDID 1.4 |
| 2 | The parser converts it to `bpc = 0` | `nvt_edid.c:932`, `default:` branch |
| 3 | Nothing overwrites it | the headset's extension is **DisplayID 1.2** (version byte `0x12`), and `nvt_edid.c:1101` only calls the 2.x parser if `(pExt[1] & 0xF0) == 0x20`. Across the whole tree `digital.bpc` is written in three places: `nvt_edid.c:914-932`, `nvt_edidext_displayid20.c:314` (DisplayID **2.x** Display Parameters) and `nvkms-dpy.c:2257` inside `CreateParsedEdidFromNVT_TIMING()` (not reached for a sink with a real EDID; see the corrections list in docs/16) — **the 1.3 parser never touches it** |
| 4 | **`bpc < 8` pins the max at 6** | `nvkms-dpy.c:3456` |
| 5 | Since nothing is requested, the max is used | `ChooseColorBpc()` returns `max` if `requested == UNKNOWN` |
| 6 | The link runs at 18 bpp | `nvidia-modeset: DPCONN> Notify Attach Begin (Head 0, pclk 428580000 raster 2980 x 1598  18 bpp)` |
| 7 | **The headset confirms it** | byte 18 of its `DEVICE_STATUS` = `06` on Linux, `08` on Windows |
| 8 | At 90 Hz the panel doesn't light up | physical verification, nine runs |

## The code

`src/nvidia-modeset/src/nvkms-dpy.c`, in `nvDpyGetOutputColorFormatInfo()`, DisplayPort
branch:

```c
if (pDpyEvo->parsedEdid.info.input.u.digital.bpc >= 10) {
    colorFormatsInfo.rgb444.maxBpc = ..._BPC_10;
    colorFormatsInfo.yuv444.maxBpc = ..._BPC_10;
} else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {   // <-- 0 falls here
    colorFormatsInfo.rgb444.maxBpc = ..._BPC_6;
    colorFormatsInfo.yuv444.maxBpc = ..._BPC_UNKNOWN;
} else {
    colorFormatsInfo.rgb444.maxBpc = ..._BPC_8;
    colorFormatsInfo.yuv444.maxBpc = ..._BPC_8;
}
```

**"Undefined" means the sink didn't declare it, not that it wants 6.**

And there's an inconsistency within the same function: a few lines above, the **DSI**
branch treats the unknown case as **8**:

```c
default:
    nvAssert(!"Unsupported bpc for DSI");
    // fall through
case 8:
    colorFormatsInfo.rgb444.maxBpc = ..._BPC_8;
```

DisplayPort and DSI do different things with the same input.

## The patch

`patches/nvidia/0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch`:

```c
-                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
+                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc != 0 &&
+                           pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
```

Register it as `PATCH[3]` in the DKMS tree (ch. 04); it requires a reboot. **This patch is
the complete fix.**

## Terminology: "HP logo" is not a signal, it's just "has power"

Early notes describe failures as "HP logo, black". The "HP logo" is a lit LED badge on the
front of the headset, physically separate from the internal LCD panels. It lights up from
USB power alone, with no host software involved, and **says nothing** about the video path.
The only state that matters is the **internal panel** (the one seen through the lens):

| Internal panel (looking through the lens) | What it means |
|---|---|
| Black | Backlight off. This is what "HP logo, black" always meant: external badge lit (trivial, ignore) + panel off. |
| Solid white / flicker, no color | Backlight on, no real image. |
| Real image (colors, video) | Success. |

## How to verify the patch took effect

1. **Byte 18 of `DEVICE_STATUS` goes from `06` to `08`** (and byte 11 from `0x14` to `0x1e`
   at 90 Hz, since it depends on bpc, not on refresh). This is a measurement on the headset
   side, so it does not depend on trusting NVIDIA: run `./scripts/panel-status.py 40` in
   parallel with `hmd-vk`. After the patch the 33-byte message is byte-identical to the
   one Windows produces at 90 Hz.
2. **The nvidia-modeset log shows `24 bpp`** instead of `18 bpp` in all three modes.
3. **Physical verification at 90 Hz.** As always: only what's seen inside the headset counts.

### It is DisplayID 1.2, not 2.0

The first forum report said *"its DisplayID 2.0 extension carries only a Type VII
timing block"*. **This is incorrect**, and the error stems from here. EDID block 2 starts with
`70 12 79 00 00 03 00 28`: the `0x12` is version 1 revision 2, i.e. **DisplayID 1.2**, and the
40-byte tag `0x03` data block is **two Type I Detailed Timing descriptors** of 20 bytes each
(tag `0x03` only becomes Type VII in DisplayID 2.0 — hence the confusion).

The conclusion doesn't change and the argument becomes **stronger**: it's not that this
DisplayID is missing the Display Parameters block, it's that for **any** sink with a
DisplayID 1.x extension, the only place that could reassign `digital.bpc` is unreachable by
construction. The clamp to 6 bpc is unavoidable for every DP sink that leaves the depth
undeclared in the base block and doesn't carry DisplayID 2.x with Display Parameters.

The corrected report is in `docs/14`.

### The modelines derived from the EDID match exactly what nvkms programs

Manually decoded to rule out a second root cause in mode derivation:

| source | pclk | H act/fp/sync/bp | V act/fp/sync/bp | refresh |
|---|---|---|---|---|
| DisplayID desc #1 (preferred) | 905.40 MHz | 4320 / 50 / 4 / 46 | 2160 / 16 / 2 / 98 | 90.00 Hz |
| DisplayID desc #2 | 709.15 MHz | 4320 / 50 / 4 / 46 | 2160 / 14 / 2 / 498 | 60.00 Hz |
| Base block DTD | 428.58 MHz | 2880 / 50 / 4 / 46 | 1440 / 18 / 2 / 138 | 90.00 Hz |

All three with `+H +V` polarity, and all three identical to what `drmModeGetConnector`
reports and to the raster in the log (`raster 2980 x 1598`, `pclk 428580000`). **There's no
second root cause here.**

### The color space is settled by the EDID itself

The CTA-861 extension (block 1) has **byte 3 = `0x00`**: the headset doesn't advertise YCbCr
4:4:4 or 4:2:2. The link is mandatorily RGB in all three modes — there's no color space
variable that could differ between the mode that works and the ones that fail. This is
independent of the search through `nvidia_modeset` logs, which had already come up empty.

## Why it matters beyond the G2

This **is not specific to the Reverb G2**. It affects any DisplayPort sink with an EDID 1.4
that leaves color depth undeclared: the driver handles it at 6 bpc on Linux and 8 on
Windows. On a regular monitor the symptom would be *banding* and poor colors, easy to
attribute to something else. On this headset the symptom is that the panel doesn't light up
at 90 Hz.

It's worth checking whether this explains either of the other two HMD bugs NVIDIA has open
(Bigscreen Beyond with DSC corruption, bug 4834531; Index/Vive with judder, bug 5372097).

## Ruled out (no second root cause)

With the patch active the headset reports the same state as under Windows, and the
`nvidia-modeset` logs (debug=1, all three modes) contain no mention of DSC, color space or
YCbCr and show the identical `Attach Begin` -> `Attach End` pattern per mode. The full
modelines read back from `drmModeGetConnector` (porches, sync, `flags=0x5` = +H +V) are
consistent across modes. GSP firmware logs (`NVreg_EnableGpuFirmwareLogs=1`) are not
obtainable: the driver wants `gsp_log_ga10x.bin`, which NVIDIA does not ship, not even in
the official `.run` installer (its `gsp_ga10x.bin` is byte-identical to the packaged one).
The HID/USB channel carries no mode command in any phase (live refresh change, cold
bring-up): see `docs/12` §4 and `docs/112` §5.

Install the patch through DKMS `PATCH[3]` (see ch. 04): editing `/usr/src` directly is lost
silently when `apt` replaces the package.
