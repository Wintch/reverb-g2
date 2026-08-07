# 15 — Triage of Feedback on the NVIDIA Report (2026-08-05)

Thread published:
<https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240>
(at the time of this triage: no replies yet).

Feedback received: six items ranked "by expected return," plus one channel suggestion.
Below, each one is checked against what's already been measured in this repo.

---

## Triage summary

| # | feedback item | verdict |
|---|---|---|
| 1 | Apply Project-VR patches on top of the bpc one and bisect | **Already done.** All three have been applied all along. And the premise ("works on Ada") was never verified |
| 2 | Capture Windows HID during the 60→90 transition | **Partially closed via disassembly, but it's the only one that's genuinely still open.** The critique of byte 18 is correct; it doesn't touch the disassembly |
| 3 | Read DPCD in all three modes | **Half closed, and the missing part is expensive.** The EDID itself already settles the color space |
| 4 | Sweep refresh rate with custom modelines (61/72/75/80) | **The best experiment on the list, and it hasn't been run.** But it's not five minutes: it needs an EDID override |
| 5 | Parse the DisplayID by hand and compare the modeline | **Done today. Negative — and along the way found an error in the published report** |
| 6 | Attach `nvidia-bug-report.log.gz` and raw EDID | **Correct, do it now** |
| — | Open an issue on `NVIDIA/open-gpu-kernel-modules` | **Correct, do it now** |

---

## 1 — The Project-VR patches are already applied. There's nothing to bisect

`dkms.conf` from the installed tree:

```
PATCH[0]="0001-nvkms-VESA-DisplayID-DSC-VSDB-spec-correctness-fixes.patch"
PATCH[1]="0002-nvkms-nvidia-drm-enable-Wayland-DRM-lease-of-VR-HMDs.patch"
PATCH[2]="0003-dp-force-maximum-link-config-for-the-HP-Reverb-G2-ED.patch"
```

and `0004` (bpc) is applied directly on top of `/usr/src/nvidia-595.71.05` (see the
reproducibility note in `docs/13`). In other words: **the current result — white flicker at 90 Hz — is
already the full Project-VR stack plus the bpc patch, running on GA104.** It's not a matter of
still needing to combine them.

The second half of the premise also fails: "that it also works on Ampere is publishable
data" assumes it works on Ada. **There is no verified positive case.** See
`docs/06`, section "CAUTION: Project-VR is NOT a verified positive case": its evidence of
90 Hz is a successful Vulkan/OpenXR session with its logs — exactly the kind of evidence
that this project has shown nine times over to be compatible with a dead panel.

**What's publishable here is the negative result**, and it is worth publishing: the three patches to the open
kernel module, plus the bpc one, on GA104 → 90 Hz still fails.

## 2 — The Windows HID: the critique is valid, but it points at the wrong evidence

The reviewer says: "your identical byte 18 is from a status report (IN) — it says nothing about
the OUT/feature reports Windows sends". **That's correct** about byte 18. But the
hypothesis wasn't closed with byte 18: it was closed by disassembling the Oasis driver
(`docs/09`), and that disassembly is *exactly* an inventory of OUT/feature reports:

- `driver_oasis.dll` has **a single** call site for `HidD_SetFeature` in the entire binary:
  Usage Page `0x03` / Usage `0x21` = Display Enable. Nothing else.
- `HololensSensors.dll` does the same thing written differently.
- The other four `HidP_SetUsageValue` calls are Usage Page `0x0E` (Haptics) = controller
  rumble.
- `MROEMFwHost.dll` is just the firmware updater; `client_utility.exe` belongs to Steam.

**Where the reviewer is still right:** a disassembly bounds what that binary *can*
send, not what actually goes over the bus. Two real gaps remain:

1. `driver_oasis.dll` uses **Microsoft Detours** (sections `.detourc`/`.detourd`) and what
   it hooks was never examined.
2. The OS's WMR runtime is a separate component, and `unlock_wmr.exe` touches display state through
   `Windows.Devices.Display.Core` — not via HID, but it's uncovered surface area.

A bus capture resolves both gaps at once and doesn't depend on NVIDIA. The kit is already set up
(`windows-kit/capture.bat` + `scripts/parse-usbpcap.py` + `scripts/analyze-hid.py`), the
Windows disk is in the machine. It costs one boot. **It's the only item on the list that can
resolve the problem without NVIDIA, so it goes first among the open ones** — not because the
hypothesis is still alive, but because it turns "we read the driver and there was nothing" into "we watched
the wire and nothing happened".

## 3 — DPCD: half is already answered, and the other half is expensive

Already closed, with two independent pieces of evidence:

- **Color space**: the headset's CTA-861 block (extension 1) has **byte 3 = `0x00`** — no
  YCbCr 4:4:4, no YCbCr 4:2:2. The sink doesn't advertise YCbCr at all, so the link is
  necessarily RGB in all three modes. There's no color space variable that could differ.
  This replaces the "loose claim" with a hard fact pulled from the EDID in 30 seconds.
- **DSC**: zero mentions of DSC/compression in `dmesg` with `nvidia_modeset.debug=1` across the
  three modes (`docs/13`), plus the bandwidth math that already ruled it out twice over.

What's **not** there: the trained link rate and lane count read from the DPCD, and `DSC_ENABLE` (0x160)
read from the sink instead of inferred from the log. And the cost is high: `nvidia-drm` doesn't expose DPCD via
debugfs (there's no equivalent of `i915_dpcd` or amdgpu's `dp_dpcd_address`), so it would take
writing an RM client against `/dev/nvidiactl` using `NV0073_CTRL_CMD_DP_AUXCH_CTRL`.
That's a long half-day to confirm something the log and the EDID already suggest. **Low priority.**

## 4 — The refresh sweep: the best experiment on the list, and there's a way to do it

The reviewer's logic is correct: if it fails at 61 Hz, this isn't a high-frequency timing
story but one of mode parsing/selection, and that changes the whole diagnosis.

**But it's not five minutes**, for a reason already measured (`docs/09`): NVIDIA on Linux **rejects
any timing that isn't in the EDID** — `vkCreateDisplayModeKHR` and `drmModeSetCrtc` fail.
So the sweep requires an **EDID override**, and that's where things got stuck (`docs/13`,
"other ways to force bpc"): `nvidia-drm` doesn't honor `drm.edid_firmware`, it's unknown
whether NVKMS reads the debugfs `edid_override`, and the syntax for
`nvidia_modeset.config_file` isn't documented.

**The path that was ruled out for the wrong reason: xorg.conf's `Option "CustomEDID"`.**
It was ruled out with "X11 only, and we're going with Wayland" — that is, for convenience, not for
technical reasons. And the X11 Direct-Mode path **works** on this rig (it was the original; the
60 Hz control gives a perfect image through it). For *this* experiment, going back to X11 on purpose is fine.

Concrete recipe:

1. Start from `hmd.edid` (384 bytes) and add DTDs for 61/72/75/80 Hz, keeping H total and
   porches unchanged, varying only V blanking (the same axis the real EDID already uses between its
   60 and 90 Hz modes).
2. Fix block checksums.
3. `Option "CustomEDID" "DP-0:/path/g2-sweep.bin"` and run `hmd-vk` in each mode, with
   physical verification.

Bonus: the same approach works for an EDID with byte `0x14` set to `0xA0` (8 bpc declared), which
**reproduces the bpc fix without patching the driver**. That drastically lowers the cost for
NVIDIA to reproduce the bug, and it's worth offering it in the thread.

## 5 — Done today. Negative, and it found an error in the published report

The raw EDID was decoded by hand, byte by byte, and compared against what nvkms programs.

### The error: it's not DisplayID 2.0, it's DisplayID 1.2

EDID block 2: `70 12 79 00 00 03 00 28 ...`

- `0x70` = DisplayID extension tag.
- **`0x12` = version 1, revision 2.** DisplayID **1.2**, not 2.0.
- The data block is tag `0x03`, length `0x28` = 40 bytes = **two 20-byte Type I
  Detailed Timing descriptors** (tag `0x03` only becomes Type VII in DisplayID 2.0; that's
  where the confusion came from).

And this **matters**, because `nvt_edid.c:1101` branches on version:

```c
case NVT_EDID_EXTENSION_DISPLAYID:
    if ((pExt[1] & 0xF0) == 0x20) // displayID2.x as EDID extension
        getDisplayId20EDIDExtInfo(...);
    else                          // displayID13 as EDID extension
        getDisplayIdEDIDExtInfo(...);
```

`0x12 & 0xF0 = 0x10` → the G2 goes through the **DisplayID 1.3** parser. And across the entire tree,
`input.u.digital.bpc` is written in **exactly two places**:

```
nvt_edid.c:914-932                 <- the base block switch (default: bpc = 0)
nvt_edidext_displayid20.c:314      <- Display Parameters for DisplayID 2.x
```

The 1.3 parser **never touches it**.

**The published report says "its DisplayID 2.0 extension carries only a Type VII timing
block, no Display Parameters block, so nothing overrides this".** The conclusion is correct
but the reasoning isn't, and the correct version is *stronger*: it's not that this DisplayID is
missing the 0x21 block — it's that **for any sink with a DisplayID 1.x extension, the only
override site is unreachable by construction**. In other words, the clamp to 6 bpc is
*inevitable* for every DisplayPort sink that leaves depth undeclared in the base block
and doesn't carry DisplayID 2.x with Display Parameters. This needs to be corrected in the thread: an
NVIDIA engineer will see it, and once fixed the argument generalizes better.

### The modelines: they match exactly. No second root cause

| source | pclk | H act/front/sync/back | V act/front/sync/back | refresh |
|---|---|---|---|---|
| DisplayID desc #1 (preferred) | 905.40 MHz | 4320 / 50 / 4 / 46 | 2160 / 16 / 2 / 98 | 90.00 Hz |
| DisplayID desc #2 | 709.15 MHz | 4320 / 50 / 4 / 46 | 2160 / 14 / 2 / 498 | 60.00 Hz |
| Base block DTD | 428.58 MHz | 2880 / 50 / 4 / 46 | 1440 / 18 / 2 / 138 | 90.00 Hz |

All three, with `+H +V` polarity (DTD byte 17 = `0x1e`; bit 15 of the front
porch fields in the DisplayID descriptors). **They match byte for byte what
`drmModeGetConnector` reports** (`docs/13`) and the log's raster (`raster 2980 x 1598`,
`pclk 428580000`).

So the driver programs exactly the timing the headset declares. What **remains**
open on this item is only the Windows-side half: comparing against the modeline that
Windows programs. It comes for free alongside the item 2 capture.

## 6 and channel — attachments assembled, ready to upload

Everything is in `forum-attachments/`:

| file | size | what it is |
|---|---|---|
| `g2-edid.zip` | 2.4 KB | raw EDID + copy with 8 bpc + annotated decode + README |
| `nvidia-bug-report.log.gz` | 545 KB | captured with the patch applied (renamed to the filename NVIDIA expects) |
| `0004-nvkms-no-6bpc-clamp.patch.txt` | 2.8 KB | the patch, with `.txt` because the forum doesn't accept `.patch` |

The `.bin` files go inside the `.zip` because Discourse rejects that extension on its own.

**Heads up on the bug report:** it carries the hostname, kernel logs, and user paths. That's normal for
that forum, but it's worth knowing before uploading it.

The repro EDID (`g2-edid-8bpc-repro.bin`) comes from `scripts/edid-tool.py set-bpc`: byte 0x14
`0x80`→`0xA0` and checksum `0xE8`→`0xC8`, two bytes and nothing else. It lets NVIDIA reproduce
the bpc half **without building the driver**, and it's the same approach the item 4 sweep
needs.

And open the issue on `NVIDIA/open-gpu-kernel-modules`: `nvkms-dpy.c` and `nvt_edid.c` live there,
and the issue gets seen by engineering directly. Text ready in `docs/14`.

---

## Proposed order

> **OVERTAKEN (2026-08-07):** item 1 happened (post edited, then edited again with the
> 90Hz resolution — `docs/19`); items 2-4 became moot when the bpc patch turned out to be
> the complete fix on the plain native modes. Kept as the record of the plan at the time.

1. **Edit the original post** (not reply) with the DisplayID correction —which strengthens it—,
   the three new negative results, and the attachments. Full text ready to paste, in
   `docs/14`. Then open the issue on GitHub and link it from the post.
2. **Refresh sweep via `CustomEDID` on X11** (61/72/75/80 Hz). It's the most discriminating
   one and doesn't depend on anyone else. The unpatched repro EDID for NVIDIA comes out of the same work.
3. **USBPcap capture on Windows** of the 60→90 transition, and along the way the modeline that
   Windows programs. One boot, kit already set up.
4. DPCD via RM control call. Only if 2 and 3 turn up nothing.
