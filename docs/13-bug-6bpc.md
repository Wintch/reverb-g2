# 13 — The bug: NVIDIA pins the G2 at 6 bits per color

> **RESOLVED (2026-08-06): the bpc patch turned out to be the COMPLETE fix for 90Hz.**
> This document's later sections say the patch "half-works" (white flicker, 90Hz still
> broken) — those observations came from EDID-override/forced-mode testing; nobody had
> retested the plain native EDID modes with the patch active. Tested clean, both native
> 90Hz modes come up perfect, later re-verified with real video through the full player
> (T041). Full resolution chain in `docs/19`; retrospective in `docs/21`. The "report to
> NVIDIA" next step at the end was done (threads 379240 + 337744, PR #1275 — still open,
> unmerged). Keep reading this file for the bug's anatomy, not for the 90Hz status.

**Found on 2026-08-05, while reading the driver source code.** It's one line.

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
| 3 | Nothing overwrites it | the headset's extension is **DisplayID 1.2** (version byte `0x12`), and `nvt_edid.c:1101` only calls the 2.x parser if `(pExt[1] & 0xF0) == 0x20`. Across the whole tree `digital.bpc` is written in two places: `nvt_edid.c:914-932` and `nvt_edidext_displayid20.c:314` (DisplayID **2.x** Display Parameters) — **the 1.3 parser never touches it** |
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

Applied and rebuilt with `sudo ./scripts/apply-bpc-patch.sh` (and `--revert` removes it).
**Requires a reboot.**

## Terminology: "HP logo" is not a signal, it's just "has power" (clarified 2026-08-06)

Throughout this document and `docs/16-lab-vblank.md`, the phrase "HP logo, black" appears
constantly as a failure result. **Important clarification, so no one misreads it in the
future:** the "HP logo" is a lit LED badge on the front of the headset, physically separate
from the internal LCD panels — it lights up simply by receiving USB power, with no host
software doing anything. **It is not a diagnostic signal of anything** other than
"the headset has power." There was never a boot image drawn on the internal panel itself.

The only thing that matters, and the only thing that varies between attempts, is the state
of the **internal panel** (the one seen looking through the lens):

| Internal panel (looking through the lens) | What it means |
|---|---|
| Black | Backlight off. This is what "HP logo, black" always meant: external badge lit (trivial, ignore) + panel off. |
| Solid white / flicker, no color | Backlight on, no real image — the original finding of this document (finding #2). |
| Real image (colors, video) | Success. |

**New practical detail:** this unit has physical damage (impact) that leaves a visible light
leak point when looking through the lens — it's the only indicator visible to the naked eye,
without a camera or HID, of whether the backlight is on or not, even when the rest of the
panel looks black at first glance. Reference coordinates (for camera use, not applicable to
the naked eye) in `linuxlab-kit/NEXT-STEP.md`, webcam experiment section.

## How it's verified to have worked

Two signals, and it's worth checking both:

1. **Byte 18 of `DEVICE_STATUS` has to go from `06` to `08`.** This is a measurement on the
   headset side, not the driver, so it doesn't depend on trusting NVIDIA.
   `./scripts/panel-status.py 40` in parallel with `hmd-vk`.
2. **Physical verification at 90 Hz.** As always: only what's seen inside the headset counts.

If byte 18 goes to `08` and the panel **still** doesn't light up at 90 Hz, then the bpc was a
real bug but not *the* bug — and the next step would be byte 11, which is the other
difference against Windows (`0x14`=20 on Linux vs `0x1e`=30 on Windows at 90 Hz).

### Correction from 2026-08-05 (post-publication): it's DisplayID 1.2, not 2.0

The report published on the forum says *"its DisplayID 2.0 extension carries only a Type VII
timing block"*. **This is incorrect**, and the error stems from here. EDID block 2 starts with
`70 12 79 00 00 03 00 28`: the `0x12` is version 1 revision 2, i.e. **DisplayID 1.2**, and the
40-byte tag `0x03` data block is **two Type I Detailed Timing descriptors** of 20 bytes each
(tag `0x03` only becomes Type VII in DisplayID 2.0 — hence the confusion).

The conclusion doesn't change and the argument becomes **stronger**: it's not that this
DisplayID is missing the Display Parameters block, it's that for **any** sink with a
DisplayID 1.x extension, the only place that could reassign `digital.bpc` is unreachable by
construction. The clamp to 6 bpc is unavoidable for every DP sink that leaves the depth
undeclared in the base block and doesn't carry DisplayID 2.x with Display Parameters.

Correction drafted for posting to the thread: `docs/14`, "Reply #1".

### The modelines derived from the EDID match exactly what nvkms programs

Manually decoded on 2026-08-05, to rule out a second root cause in mode derivation:

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

## The patch works halfway: it unlocks the panel, but doesn't restore color (2026-08-05)

Rebooted with the patch compiled in. Four tests, physical verification on each.

### The expected confirmation: byte 18 went from 06 to 08

```
before: 05 00 01 01 00 5a 00 00 00 09 38 14 04 00 77 77 00 00 06 44 11 e4 08 ...
now:    05 01 01 01 01 5a 00 00 00 09 38 1e 04 00 77 77 00 00 08 44 11 e4 08 ...
                                                              ^^
```

The patch does exactly what the code reading predicted.

### What was NOT expected

| test | mode | physical result |
|---|---|---|
| T004 | `4320x2160@90` | **white flicker**, no color, more pronounced than the known 60Hz strobe |
| T005 | `4320x2160@60` (control) | colors visible, flicker equally pronounced as T004 |
| T006 | `2880x1440@90` (LOWER bandwidth 90Hz: 428 MHz) | **also all white, flickering** |

**T006 is the important elimination.** Both 90Hz modes fail the same way — one with a 428
MHz pixel clock and the other with 905 MHz, a difference of more than 2x — so **it's not a
MIPI bandwidth limit**. It's something about the 90Hz refresh itself, independent of
resolution.

### The finding that matters most: the headset's state is now BYTE-IDENTICAL to Windows

Captured during T004 (panel manually turned on with `panel.py on` while `hmd-vk` was
presenting at 90Hz in `4320x2160`):

```
Windows (WORKS):            05 01 01 01 01 5a 00 00 00 09 38 1e 04 00 77 77 00 00 08 44 11 e4 08 01 00 80 00 80 00 80 00 80 02
Linux post-patch (WHITE):   05 01 01 01 01 5a 00 00 00 09 38 1e 04 00 77 77 00 00 08 44 11 e4 08 01 00 80 00 80 00 80 00 80 02
```

**They are exactly identical, all 33 bytes.** Even byte 11 — which we had noted as the other
pending difference against Windows (`0x14` vs `0x1e`) — fixed itself: it went from 20 to 30 in
both 90Hz modes as soon as the bpc was fixed. It wasn't an independent variable; it depended
on bpc, not on refresh as originally thought.

**Conclusion: we've exhausted what the `DEVICE_STATUS` channel can tell us.** The headset
reports the same thing to the host as it does to Windows — same refresh, same timing, same
bpc, same backlight flag — and the visual result is different. The remaining difference **is
not visible from this angle**. It has to be in something in the video stream itself that this
channel doesn't capture:

- **DSC silently kicking in.** Now that bpc went up to 8, the bandwidth math is tighter
  (10.08 Gbps per panel vs. 12 Gbps for the ANX7530), and NVIDIA could be invoking DSC for the
  heavier mode — but that doesn't explain why the lighter mode (10.29 Gbps total link
  bandwidth, with plenty of margin) also fails the same way.
- **A timing detail that `htotal`/`vtotal` don't capture**: front porch, back porch, or sync
  polarity. The totals can match while the internal breakdown differs.
- **The color format on the link** (RGB444 vs YCbCr444/422): `nvDpyGetOutputColorFormatInfo()`
  also decides the color space, not just the bpc, and that code hasn't been read yet.

### Honest assessment

It's not the complete solution, but it's real, measurable progress: the patch crossed the
obstacle that left the panel **completely dead** (static logo, zero activity) and brought it
to a new state (flicker with content, albeit without color). The bpc was a real bug —
confirmed by the code, by the NVIDIA log, and by the headset itself — but it's not the
*whole* bug.

## Next step: read the NVIDIA logs with all three modes, now with the patch applied

`scripts/collect-nv.sh` already exists and does exactly this: enables `nvidia_modeset
debug=1`, runs all three modes (60 control first, then the two 90 modes) capturing `dmesg`
each time, and gathers the full context. It was already run once before the patch; it needs
to be repeated now that bpc changed, to see if anything new shows up — especially any mention
of DSC, color space, or format that wasn't there before.

```bash
sudo /home/iam/Documents/reverb-g2/scripts/collect-nv.sh
```

Takes a few minutes (most of it is `nvidia-bug-report.sh`). Nobody needs to look at the
headset for this — it's log capture on the driver side.

## Exhausted the diagnostics accessible without deeper root access (2026-08-05, 01:30)

`collect-nv.sh` run again, now with the patch applied, capturing all three modes. Confirmed
again: **24 bpp** in all three (previously 18), matching the headset's byte 18.

Three searches, all three came up empty:

1. **DSC / color space / YCbCr / compression**: zero mentions in the three
   `nvidia-modeset` logs. That avenue is closed — there's no evidence that NVIDIA is
   silently invoking DSC or changing color space between modes.
2. **The log gives no more information at this verbosity level.** The exact same pattern
   (`Attach Begin` → `VIDEO` → `Attach End` → `Delayed HDCP` → `detach`) repeats for each
   mode, without a single extra line.
3. **The complete modeline the driver assembles** (not just htotal/vtotal, but front/back
   porch and sync polarity, read directly from `drmModeGetConnector`):

   ```
   4320x2160@90:  H front=50 sync=4 back=46   V front=16 sync=2 back=98    flags=0x5
   2880x1440@90:  H front=50 sync=4 back=46   V front=18 sync=2 back=138   flags=0x5
   4320x2160@60:  H front=50 sync=4 back=46   V front=14 sync=2 back=498   flags=0x5
   ```

   Same H blanking in both 4320 modes (60 and 90). Same sync polarity (`flags=0x5`
   = positive H and V) in all three. V blanking scales reasonably with vtotal. **Nothing
   anomalous at this level.**

### Where this stands

Exhausted what can be inspected without more disruptive actions. What's left:

- **`NVreg_ResmanDebugLevel`** in the core module — much more verbose than `nvidia_modeset
  debug`, but **requires unloading and reloading the module**, which kills the graphical
  session. Not something to do in passing; it needs to be planned (log out, or do it from a
  text console).
- **Report to NVIDIA with everything we already have.** Although the bpc bug didn't resolve
  90Hz on its own, it's a real bug, verified in the source code, with a two-line patch, and
  with evidence that the headset ends up in a new state (flicker with content instead of a
  static logo) — information their engineers, with access to the closed parts of the driver
  (GSP firmware, RM), can use to continue where we can't.

This is a reasonable stopping point for the session: four hours of physical testing, one
real bug found and confirmed, and two more avenues closed off with evidence. What follows
requires either much more time of invasive GPU debugging, or the collaboration of someone
with access to the closed-source code.

## Enabling GSP firmware logs (2026-08-05, 01:45)

The GPU (RTX 3060 Ti = GA104) uses **GSP** firmware
(`/lib/firmware/nvidia/595.71.05/gsp_ga10x.bin`): a good portion of the resource manager
logic — likely including DisplayPort link training and mode negotiation — runs on a
microcontroller **inside the GPU**, not in the open-source kernel module we read. That
explains why `nvidia_modeset.debug` was capped at 7 lines: there's nothing more to log on the
Linux side, the decision happens elsewhere.

Found in `nv-reg.h`: **`NVreg_EnableGpuFirmwareLogs`** — makes the GSP firmware itself send
its logs to the host. By default, in a release build, it's disabled
(`gpu_mgr.c:1024`: the `ENABLE_ON_DEBUG` branch only activates if the driver is a
`DEBUG`/`DEVELOP` build, which isn't our case). It has to be forced with
`NVreg_EnableGpuFirmwareLogs=1`.

`NVreg_ResmanDebugLevel` was ruled out along the way: its default is already `~0` (all bits
set), which looks the same as `nvidia_modeset`'s `debug` when it turned out to be capped —
smells like the same thing, host prints compiled out in a release build.

`scripts/enable-gsp-logs.sh` writes `/etc/modprobe.d/99-nvidia-gsp-logs.conf` with that
option. **Requires a reboot**: the parameter belongs to the `nvidia` (core) module, which
loads before `nvidia-modeset` — it can't be hot-enabled the way we did with modeset's
`debug`.

## The GSP logging firmware doesn't exist anywhere accessible (2026-08-05, 01:50)

Rebooted with `NVreg_EnableGpuFirmwareLogs=1` set and ran `collect-nv.sh` again.
**The parameter activated correctly**, but the driver reports:

```
nvidia 0000:05:00.0: firmware: failed to load nvidia/595.71.05/gsp_log_ga10x.bin (-2)
NVRM: RmFetchGspRmImages: Failed to load gsp_log_*.bin, no GSP-RM logs will be printed (non-fatal)
```

**A specific firmware file for logging is missing**, different from the one the driver
already uses in production (`gsp_ga10x.bin`). Searched in every reasonable place:

- The Debian package `firmware-nvidia-gsp` (every version available in the repo, from
  550.163.01 to 610.57.04): only ships `gsp_ga10x.bin` and `gsp_tu10x.bin`, never the
  `_log_` variant.
- **NVIDIA's official installer** (`NVIDIA-Linux-x86_64-595.71.05.run`, 403 MB, downloaded
  in full and extracted with `--extract-only`): its `firmware/gsp_ga10x.bin` is **byte for
  byte identical** (same MD5) to the one already installed. **NVIDIA does not publicly
  distribute the logging firmware for this consumer GPU.**

With this, the last available software resource is exhausted. The logic that decides how to
latch the panel at 90Hz runs on a microcontroller inside the GPU, with closed firmware for
which no public logging-enabled version exists. **There's no way to see, from Linux, what
the GSP is thinking while it negotiates the 90Hz mode.**

## Status

- [x] bpc causal chain verified in the code and against three independent measurements
- [x] Patch written, compiled, and installed
- [x] Verified: byte 18 goes from 06 to 08 — the patch works as the code predicted
- [x] Verified: the failure is NOT bandwidth-related (both 90Hz modes fail the same way, with
      2x of difference in pixel clock)
- [x] Verified: the headset's state is now byte-identical to Windows's — exhausted what this
      channel can tell us
- [x] Ruled out: DSC, color space, YCbCr — zero mentions in the logs with `nvidia_modeset
      debug=1`
- [x] Ruled out: the complete modeline (porches, sync, polarity) — consistent across the
      three modes, nothing anomalous
- [x] Attempted and exhausted: GSP firmware logs (`NVreg_EnableGpuFirmwareLogs=1`) — the
      `gsp_log_ga10x.bin` binary is missing, which **NVIDIA does not distribute publicly**,
      not even in its full official installer (verified by MD5 against the 403 MB `.run`)
- [ ] **Exhausted what's accessible from Linux. The next step is to report to NVIDIA** — with
      the bpc bug (real, confirmed, with a two-line patch) and everything else as diagnostic
      context already done, so someone with access to the closed GSP firmware can continue
      from there. Thread: 337744 (bug 5923212).
- [ ] **Not attempted: sniffing the DisplayPort AUX channel** with a logic analyzer (Saleae-
      type) on the AUX+/AUX- pins, to see the actual DPCD during link training — it's the
      only layer that no method used so far can show. The main link (several Gbps) isn't
      sniffable without a dedicated DP protocol analyzer (thousands of dollars); AUX runs at
      ~1MHz and is reachable with generic hardware. Depends on having the instrument on hand
      — not worth building anything for this until that's sorted out first.

### 2026-08-05 (night): the USB channel is also closed off for the TRANSITION, not just the steady state

Using `windows-kit/` (see `windows-kit/README.txt`), the exact moment of a LIVE refresh
change on Windows was captured for the first time (60→90 and 90→60, without reconnecting the
headset), something the earlier comparison in this document didn't cover (that one compared
two already-settled states). Result: **at the moment of transition, no special HID command or
report appears** — just the usual `DEVICE_STATUS` (0x05), with byte 5 (refresh) and
htotal/vtotal updated, and the periodic 4-byte heartbeats (Report ID 0x01) that were already
there before and remain unchanged afterward, unrelated to the mode. With this, the HID/USB
channel is exhausted for the transition too, not just the steady state — this closes that
investigative avenue entirely.

Along the way, byte 6 of `DEVICE_STATUS` was resolved, which had remained as the only
difference between a patched-Linux capture and a Windows one (see
`windows-kit/analyze-windows.py`): it stayed at `0x0e` throughout an ENTIRE 90-second Windows
session with two refresh changes in the middle, and at `0x00` in that same day's Linux
captures. Since it doesn't change with refresh, it's a session/connection value (probably a
reset counter for the companion board itself since it booted), not something OS- or
mode-specific — no need to keep chasing it.

It was also confirmed via screenshot that the Reverb G2 **does not appear as a selectable
display** either in Windows' "Settings > Advanced display" or in the NVIDIA panel's "Change
resolution" — both only list the desktop monitors. The avenue of reading DSC from there is
closed due to lack of access to that screen, not because of a negative result from it.

---

## Reproducibility note (important)

Tonight's installation was done by **editing the source tree directly**
(`/usr/src/nvidia-595.71.05/src/nvidia-modeset/src/nvkms-dpy.c`), not through DKMS's
`PATCH[]` mechanism. This was done on purpose: the other three patches are already applied
in that tree, and a new `PATCH[]` would apply against the clean copy and conflict.

Verified that the change made it into the module:

| check | result |
|---|---|
| patch in the source tree | yes, `nvkms-dpy.c:3456-3457` |
| `0001`/`0002`/`0003` touch `nvkms-dpy.c` | **zero** matches each |
| source edited | `00:57:47` |
| module built | `00:58:54` |

**But direct editing is fragile**: if `apt` updates the NVIDIA package, `/usr/src` gets
replaced and the patch is lost **silently**. That's why `bootstrap-lab.sh` already registers
`PATCH[3]` for fresh installs.

**If the two paths ever need to be reconciled** (edited tree + registered `PATCH[3]`),
`PATCH[3]` will fail with "already applied". The correct order is:
`sudo ./scripts/apply-bpc-patch.sh --revert` first, and only afterward let DKMS apply it via
`PATCH[3]`.

## If the patch isn't enough: other ways to force bpc

In order of what has the best chance, and all of them below X11/Wayland:

1. **`nvidia_modeset.config_file`** — this is NVKMS's own mechanism for replacing the EDID
   the parser sees, i.e. the same subsystem where the bpc decision lives. The parameter
   **exists and is compiled in** the module
   (`/sys/module/nvidia_modeset/parameters/config_file`). The gap: the dpy name syntax isn't
   publicly documented nor does it appear in the open-source code (it's generated in the
   closed part of the RM). It would have to be discovered with `nvidia_modeset.debug=1` and
   watching dmesg as root.

2. **Patched EDID**, if an override path that NVIDIA respects can be found. The recipe is
   short: byte `0x14` from `0x80` to `0xA0` (bits 6-4 from `000` to `010` = 8 bpc) and fix
   the base block checksum by subtracting `0x20` from byte `127`.

3. **`/sys/kernel/debug/dri/*/DP-1/edid_override`** — cheap to try but with an underlying
   doubt: it's not confirmed whether NVKMS's closed logic reads the EDID through the generic
   DRM helper (which would see the override) or pulls it from the AUX channel on its own. A
   negative result here doesn't rule anything out. Also, writing the file **doesn't trigger a
   hotplug**: it has to be disconnected and reconnected.

**Ruled out for our setup:** xorg.conf's `CustomEDID` (X11 only, and we're going through
Wayland/DRM lease), `drm.edid_firmware=` (nvidia-drm doesn't honor it), `nvidia-settings`
(the attribute doesn't exist), and the DRM `max bpc` property (not implemented in
`nvidia-drm.ko`).
