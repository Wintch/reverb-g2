**Summary**

Two findings on the HP Reverb G2 (EDID ManufID 0x220E) with the 595.71.05 open kernel
modules. They are independent, and the first one is not specific to this headset:

1. **A confirmed bug with a two-line fix.** `nvkms-dpy.c` treats "the EDID did not declare a
   color depth" as "the sink wants 6 bpc" and drives the DisplayPort link at 18 bpp. The DSI
   branch of the *same function* already treats that same input as 8 bpc. This applies to
   **any** DisplayPort sink that leaves EDID Color Bit Depth undefined — on an ordinary
   monitor it would show up as banding, easy to misattribute. Confirmed in `dmesg`, and
   independently by the sink itself reporting the bpc back to the host.
2. **A failure that the patch does *not* fix.** Both of this headset's 90 Hz modes still fail
   to display correctly while its 60 Hz mode works. I have ruled out link bandwidth, DSC,
   color space, mode derivation, the display path, and the HID activation sequence — what is
   left appears to sit below the open kernel modules.

Everything about the 90 Hz behaviour below was verified by physically looking inside the
headset, because the API layer reports a successful modeset and a happy 90.0 fps with the
panel completely dark. It has failed on every attempt, nine runs, across two display paths
that share almost no driver code.

I believe this is the same underlying problem as the "60 Hz only on Reverb G2" reports
tracked as bug 5923212 — please correct me if I'm conflating two different bugs.

**Environment**
- GPU: RTX 3060 Ti (GA104, Ampere)
- Driver: 595.71.05, open kernel modules (nvidia-kernel-open-dkms)
- OS: Debian 13 (trixie), kernel 6.12.100+deb13-amd64
- Tested on both X11 NVIDIA Direct-Mode and Wayland (GNOME 48.7 / mutter) via DRM lease —
  identical failure on both, so this isn't specific to one display path.
- I have only tested 595.71.05 myself; reports of 590.x–610.x being affected come from other
  posters in the earlier thread, not from my own testing.

**Symptom**
The G2's EDID advertises three modes: 4320x2160@60 (works), 4320x2160@90 and
2880x1440@90 (both fail). At either 90 Hz mode the panel shows only the static HP boot logo
— no video ever reaches the panel — while Vulkan/DRM report a fully successful modeset and
90.0 fps presented. `nvidia-modeset`'s own attach log looks identical (success, no errors)
for both the working 60 Hz mode and the failing 90 Hz modes.

**Finding 1 — the 6 bpc clamp: root cause**

The G2's EDID is 1.4 and leaves the "Color Bit Depth" field of the Video Input Definition
byte (offset 0x14, bits 6-4) at `000` = "undefined" (byte value `0x80`).

`src/common/modeset/timing/nvt_edid.c` parses the undefined case into
`input.u.digital.bpc = 0`:

    default :
        pInfo->input.u.digital.bpc = 0;
        break;

`src/nvidia-modeset/src/nvkms-dpy.c`, in `nvDpyGetOutputColorFormatInfo()`, DP branch, then
does:

    } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
        colorFormatsInfo.rgb444.maxBpc = NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_6;
        colorFormatsInfo.yuv444.maxBpc = NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_UNKNOWN;

`0 < 8` is true, so an EDID that simply didn't declare a depth gets clamped to 6 bpc
(18bpp) for every mode, confirmed in `dmesg`:

    nvidia-modeset: DPCONN> Notify Attach Begin (Head 0, pclk 428580000 raster 2980 x 1598  18 bpp)

Note the DSI branch of this *same* function already treats an unrecognized/unknown bpc as
8, not 6:

    default:
        nvAssert(!"Unsupported bpc for DSI");
        // fall through
    case 8:
        colorFormatsInfo.rgb444.maxBpc = NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_8;

so DP and DSI disagree on how to handle the exact same "undefined" input, in the same
source file.

**Nothing else in this EDID can override the 0, and that generalizes**

`input.u.digital.bpc` is assigned in exactly two places in the whole tree: the base-block
switch quoted above, and `nvt_edidext_displayid20.c:314`, which reads the Display Parameters
block of a DisplayID **2.x** extension. Which of the two DisplayID parsers runs is decided in
`nvt_edid.c` purely by the version byte:

    case NVT_EDID_EXTENSION_DISPLAYID:
        if ((pExt[1] & 0xF0) == 0x20) // displayID2.x as EDID extension
            getDisplayId20EDIDExtInfo(...);
        else                          // displayID13 as EDID extension
            getDisplayIdEDIDExtInfo(...);

This headset's DisplayID extension block starts `70 12 79 00 00 03 ...`, i.e. version byte
`0x12` = DisplayID 1.2, so `0x12 & 0xF0 == 0x10` and it takes the DisplayID 1.3 path — which
never writes `digital.bpc` at all. (Its single data block, tag `0x03` / 40 bytes, is two
20-byte Type I Detailed Timing descriptors.)

So this isn't really a quirk of one headset's EDID. **For any DisplayPort sink whose
DisplayID extension is 1.x — or that has no DisplayID extension — the only override site is
unreachable by construction, so leaving Color Bit Depth undefined in the base block means an
unconditional 6 bpc clamp.** On an ordinary monitor that would show up as banding, which is
easy to misattribute. Here it happens to break a headset.

**Independent confirmation via the headset itself**

The G2's companion device reports its own panel state over HID (report 0x05, 33 bytes) —
byte 18 of that report reflects the bpc actually in use. Capturing this on Linux (6 on the
DP-side per above) and on Windows (610.74, same GPU) at the identical mode
(4320x2160@90):

    Windows (works):  05 01 01 01 01 5a 00 00 00 09 38 1e 04 00 77 77 00 00 08 44 11 e4 08 ...
    Linux (fails):    05 00 01 01 00 5a 00 00 00 09 38 14 04 00 77 77 00 00 06 44 11 e4 08 ...
                                                              ^^                  ^^
Byte 18: `06` on Linux vs `08` on Windows, with the same GPU. Windows is driving this sink
at 8 bpc; our open-kernel Linux driver is driving it at 6.

**The patch**

    --- a/src/nvidia-modeset/src/nvkms-dpy.c
    +++ b/src/nvidia-modeset/src/nvkms-dpy.c
    @@ -3453,7 +3453,8 @@
                         colorFormatsInfo.rgb444.maxBpc =
                             NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_10;
                         colorFormatsInfo.yuv444.maxBpc =
                             NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_10;
    -                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
    +                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc != 0 &&
    +                           pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
                         colorFormatsInfo.rgb444.maxBpc =
                             NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_6;
                         colorFormatsInfo.yuv444.maxBpc =

Treats 0 ("not declared") the same way the DSI branch already does, and falls through to
the 8bpc default instead of clamping to 6.

**Verified effect of the patch**

- `dmesg` now shows `24 bpp` instead of `18 bpp` for every mode.
- The headset's own status byte 18 goes from `06` to `08`, matching Windows exactly.
- In fact, with the patch applied, the headset's full 33-byte status report for
  4320x2160@90 becomes **byte-for-byte identical** to the working Windows capture at the
  same mode.

**If you want to reproduce the clamp without building a driver**

Attached (`g2-edid.zip`) is the raw EDID plus a copy with exactly two bytes changed: base
byte `0x14` from `0x80` to `0xA0` (Color Bit Depth undefined → 8 bpc) and the base block
checksum from `0xE8` to `0xC8`. Feeding that as an EDID override produces the same 24bpp
result as the source patch, which makes the bpc half of this testable on any sink you can
override.

**Finding 2 — the 90 Hz failure, which this patch does *not* fix**

With the patch applied and 8bpc confirmed on the wire, physical verification (someone
wearing the headset, not API state) at the two 90 Hz modes shows:

- 4320x2160@90 (905.4 MHz pixel clock): panel lights up and flickers, but shows plain white,
  no color content.
- 2880x1440@90 (428.6 MHz pixel clock — well under half the bandwidth of the mode above,
  and even under the 60Hz mode's 709.15 MHz): **identical white flicker**, no color.

Both 90 Hz modes fail identically despite a >2x difference in pixel clock, which rules out
DP or MIPI-side bandwidth as the differentiator. 4320x2160@60 continues to display correctly
with the same patch applied (so the patch does not regress the working mode).

This is real forward progress — pre-patch, both 90 Hz modes showed nothing but a static
boot logo, no backlight/panel activity at all. Post-patch, the panel activates but doesn't
render correct pixel content, specifically and only at 90 Hz.

**What we ruled out for the remaining 90 Hz failure**

- **Color space**: ruled out from the EDID itself, not just from logs. The CTA-861 extension
  has byte 3 = `0x00` — this sink advertises no YCbCr 4:4:4 and no YCbCr 4:2:2 at all, so the
  link is necessarily RGB in all three modes and there is no color-space variable that could
  differ between the working mode and the failing ones.
- **DSC**: zero hits for DSC/compression terms in `dmesg` with `nvidia_modeset.debug=1`
  across all three modes.
- **Mode derivation / timings**: I decoded all three timings by hand out of the raw EDID and
  compared them against what `drmModeGetConnector` reports the driver programming:

      source                       pclk       H act/fp/sync/bp    V act/fp/sync/bp     rate
      DisplayID desc #1 (pref)  905.40 MHz  4320 / 50 / 4 / 46  2160 / 16 / 2 /  98  90.00
      DisplayID desc #2         709.15 MHz  4320 / 50 / 4 / 46  2160 / 14 / 2 / 498  60.00
      base block DTD            428.58 MHz  2880 / 50 / 4 / 46  1440 / 18 / 2 / 138  90.00

  All three with positive H and V sync polarity, all three matching what the driver programs
  bit for bit (and matching the `raster 2980 x 1598 / pclk 428580000` in the attach log). The
  driver is programming precisely the timings the sink asks for; there is no second root
  cause hiding in mode derivation. Full annotated decode is in the attached zip.
- **Community open-kernel patches for this headset**: in addition to my bpc patch, this
  system has three others applied against 595.71.05 — VESA DisplayID/DSC VSDB
  spec-correctness fixes, DRM-lease enablement for VR HMDs, and a `forceMaxLinkConfig` WAR
  keyed on EDID ManufID 0x220E in `dp_wardatabase.cpp`. With all four applied on GA104, both
  90 Hz modes still fail physically. Mentioning it so nobody re-tests that combination:
  nothing found so far at the open kernel module level lights this panel at 90 Hz.
- `NVreg_ResmanDebugLevel`: default is already `~0` (all bits); we suspect these debug
  prints are compiled out of release builds, same as `nvidia_modeset.debug` which is capped
  at 7 fixed lines regardless of value.
- GSP-RM firmware logs: this GPU (GA104) uses GSP firmware
  (`/lib/firmware/nvidia/595.71.05/gsp_ga10x.bin`), so a lot of the interesting logic likely
  runs there, not in the open kernel modules. We set `NVreg_EnableGpuFirmwareLogs=1`
  expecting more detail, but the driver reports it needs `gsp_log_ga10x.bin`, which is not
  present. We downloaded your official 595.71.05 `.run` installer in full and confirmed by
  MD5 that its `gsp_ga10x.bin` is byte-identical to the one already installed — the
  logging-capable firmware variant does not appear to be publicly distributed for this
  consumer GPU. We have no way to see what the GSP does during the 90 Hz negotiation.

**Ask**

Would appreciate if someone with access to the closed GSP-RM source could look at what
differs at 90 Hz specifically (independent of bandwidth, since both native 90 Hz modes fail
identically) now that the bpc is correctly negotiated. Happy to test additional patches or
provide more diagnostics — I have physical access to the hardware and a working automated
test harness (custom minimal Vulkan display client, bypassing Monado/SteamVR entirely) that
reproduces this on demand.

**Attached**

- `0004-nvkms-no-6bpc-clamp.patch.txt` — the two-line patch above
- `g2-edid.zip` — raw 384-byte EDID, the 8bpc override copy, and a full annotated decode
- `nvidia-bug-report.log.gz` — captured with the patch applied

The bpc part of this is also filed as an issue against the open kernel modules:
PEGAR_URL_DEL_ISSUE_ACA
