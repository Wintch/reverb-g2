# 16 — The vblank experiment: is it the refresh rate, or the shape of the timing?

Prepared 2026-08-05 from the main system, with the lab SSD mounted. **The test EDID has
already been generated and verified**: `experiments/vblank/`. Still needs to be run with the
headset on — and there's also the question of **how to load it**: the "The EDID is already
built" section below leaves it as step 0, with no confirmed path yet.

---

## PREFLIGHT — run this before anything else

This experiment **is only valid in the lab**, with the patched 595-open. We already got
burned once starting to measure on the main system, which has Debian's `nvidia-current`
550.163.01 **without** the bpc patch: there, the 6 bpc clamp is active and any result comes
out confounded with the very bug we just ruled out.

```bash
# 1. correct driver
grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' /proc/driver/nvidia/version | head -1
#    must say 595.71.05   (if it says 550.x you're on the wrong system, reboot)

# 2. open modules, not the proprietary ones
modinfo nvidia 2>/dev/null | grep -i license
#    must include "Dual MIT/GPL"

# 3. the bpc patch is inside the module
./scripts/verify-bpc.sh

# 4. the headset enumerates completely (all five)
lsusb | grep -E '04b4:6506|0bda:4c15|03f0:0580|04b4:6504|045e:0659' | wc -l
#    must give 5; if 03f0:0580 is missing it's the USB port, not Monado (docs/00)

# 5. and the real bpc on the cable
dmesg | grep 'Notify Attach Begin' | tail -1
#    must say 24 bpp, not 18
```

If any of the five fails, **stop**. Measuring with the wrong driver doesn't produce a bad
result: it produces a result that looks good and points to the wrong culprit.

---

## Where we're coming from

The 6 bpc clamp is closed (see `docs/13`, `docs/14`):

- **Open PR on NVIDIA:** https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275
- **Forum thread:** post 379240, revision 6
- With the patch the headset reports `08` in byte 18 and its 33-byte HID status ends up
  byte-identical to Windows'

And yet **the two 90 Hz modes still show no image**: the panel powers on and flickers white.
The 60 Hz mode works.

---

## The hypothesis

Across the three modes the G2's EDID offers, the **horizontal** blanking is identical
(50/4/46). The only structural variable is the **vertical**:

| mode | vblank | result |
|---|---|---|
| 4320x2160@60 | **514 lines** | works |
| 4320x2160@90 | 116 lines | fails |
| 2880x1440@90 | 158 lines | fails |

In other words: **"90 Hz" and "short vblank" are perfectly confounded**. A short vblank at
60 Hz was never observed, nor a long one at 90 Hz. With these three modes there's no way to
know which of the two variables breaks the panel.

The experiment injects the two missing modes and completes the factorial.

---

## Design

|  | short vblank (158) | long vblank (514) |
|---|---|---|
| **60 Hz** | **A** — 285.72 MHz | **CTRL** — 349.38 MHz |
| **90 Hz** | native slot 0: **fails** | **B** — 524.06 MHz |

The three injected modes stay well below the 709.15 MHz of the mode that already works
(6.86 / 8.39 / 12.58 Gbps at 24 bpp), so none of them introduces bandwidth pressure.

**Why 2880x1440 and not 4320x2160:** the base block's DTD has a 12-bit horizontal active
field — **maximum 4095 px**. 4320 doesn't fit. That's why the G2 itself puts 2880x1440 in
the base block and its two 4320 modes in the DisplayID block, whose Type I descriptors use
16-bit fields. Using 2880x1440 also keeps the resolution constant against the native mode
that fails, which makes for a cleaner comparison.

**`CTRL` isn't optional and comes first.** Without it, if A fails there's no way to
distinguish "short vblank breaks the panel" from "any injected mode breaks it." It's the
baseline.

---

## The EDID is already built

`experiments/vblank/g2-vblank-test.edid` — 384 bytes, starting from
`experiments/vblank/hmd.edid`. The three modes fit into the DTD slots that were free, so
**a single EDID ends up covering the whole factorial**: the entire run happens in one
session, with no re-overriding between tests.

```
base block    slot 0  2880x1440@90  428.58 MHz  vblank 158   native, FAILS
              slot 1  2880x1440@60  349.38 MHz  vblank 514   CTRL
              slot 2  2880x1440@60  285.72 MHz  vblank 158   TEST A
              slot 3  2880x1440@90  524.06 MHz  vblank 514   TEST B
DisplayID     desc 1  4320x2160@90  905.40 MHz  vblank 116   native, FAILS  (untouched)
              desc 2  4320x2160@60  709.15 MHz  vblank 514   native, WORKS  (untouched)
```

Verified: encoding round-trip on all three, base block checksum correct, and both extension
blocks untouched byte-for-byte.

To regenerate or vary it:

```bash
./scripts/edid-tool.py inject-mode experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-test.edid CTRL:1 A:2 B:3

# with no assignments, lists the presets and what's in each slot
./scripts/edid-tool.py inject-mode experiments/vblank/hmd.edid
```

**PENDING, and this is the real step 0 of this experiment — there's no confirmed loading
path yet.** The 6 bpc bug was closed with a *driver* patch (patch 0004), not an EDID
override: there was never a need to get NVIDIA to read a fake EDID. `docs/13` lists three
candidates, none tested:

1. `/sys/kernel/debug/dri/*/DP-1/edid_override` (debugfs) — the cheapest to try first. Open
   question: it's not known whether NVKMS reads the EDID through DRM's generic helper (would
   see it) or through its own AUX channel (wouldn't see it). Writing the file **does not
   trigger a hotplug**: the connector needs to be disconnected/reconnected afterward.
2. `nvidia_modeset.config_file` — NVKMS's own mechanism, a compiled-in parameter that's
   present, but the dpy-name syntax isn't documented. Discoverable with
   `nvidia_modeset.debug=1` and reading dmesg as root during a real modeset.
3. Patching the EDID that the headset itself reports (actual bytes over the cable), if
   there's some injection point between the Analogix bridge and the host — unexplored.

Try in that order. If none of them works, the experiment isn't conclusive through this
path and the mode-injection approach needs to be rethought (the "CTRL fails" row in the
table below covers exactly that case, though there the real cause would be the loading
path, not the hypothesis).

**Option 1 — ruled out (2026-08-05), with evidence:** `g2-vblank-test.edid` was written to
`/sys/kernel/debug/dri/*/DP-1/edid_override` (the three aliases of the same connector:
`0000:05:00.0`, `0`, `128`) and `force` was cycled (`off` → `on`, one second apart) to force
a re-probe. Result: `/sys/class/drm/card0-DP-1/edid` came back **byte-identical** (`cmp`
exit 0, same md5) to `hmd.edid` **unmodified** — not to the EDID that had just been written.
Conclusion: the NVIDIA driver doesn't go through DRM's generic helper
(`drm_get_edid`/`connector->edid_override`) to populate this connector's EDID; it reads it
through its own channel (RM/AUX), which ignores the override. This answers the open question
this option had: **it doesn't see it**. Don't retry this path as-is — go straight to option
2.

---

## How to run it

Order: **CTRL → B → A**. If B works, the answer is already in and A is just confirmation.

### The verification is physical

The API lies: it reports a successful modeset and 90.0 fps with the panel off. **You have to
put the headset on and look.** For each mode, note:

- does the panel turn on? (backlight)
- does it show content in color, or white/flickering?
- `dmesg`, `Notify Attach Begin` line: pclk, raster, bpp — confirm it says `24 bpp`
- byte 18 of the HID status report (`scripts/decode-status.sh`)

---

## How to read the result

| CTRL | B | A | conclusion |
|---|---|---|---|
| fails | — | — | the injected modes don't power this panel on. **Not conclusive**: the override or the injection path fails, not the hypothesis. Rethink before continuing |
| works | **works** | — | **90 Hz isn't the problem; the short vblank is.** The best possible outcome: it gives NVIDIA a concrete variable instead of "look at the GSP" |
| works | fails | works | it's the refresh rate, 90 Hz specifically. Rules out the vblank and closes this line |
| works | fails | fails | neither the vblank nor the refresh rate on its own — points to the pixel clock or the combination |

Any of the three conclusive rows is material for a reply on thread 379240.

---

## Run (2026-08-05): CTRL fails — with evidence of why it isn't the override

**Loading path confirmed first.** `nvidia_modeset.config_file` with the corrected key
`override.[0000:05:00.0].DP-0` (NVKMS's internal naming is 0-based; see `NEXT-STEP.md` for
the full code trail) loaded on reboot: `dmesg` said `Successfully read
.../nvkms-override-candidates.conf` with no warning, `/sys/class/drm/card0-DP-1/edid` came
back byte-identical (md5 `749a63f7...`) to `g2-vblank-test.edid`, and `drmprops` confirmed
`connector 130 ... modes=6` — up from 3 to 6, exactly the 4 base-block slots plus the 2
untouched DisplayID descriptors. Path 2 is now **confirmed end to end**, not just at the
sysfs attribute level but all the way to the mode count DRM sees.

**Index order, confirmed by refresh-rate precision (Vulkan vs `edid-tool.py decode`):**
`hmd-vk native <idx>` enumerates **in the same order as the EDID slots** — base block first
(0-3), then DisplayID (4-5):

| Vulkan idx | reported refresh | corresponds to |
|---|---|---|
| 0 | 89.999 Hz | native 2880x1440@90, slot 0, already known to FAIL |
| 1 | 60.001 Hz | **CTRL** |
| 2 | 59.999 Hz | **A** |
| 3 | 90.000 Hz | **B** |
| 4 | 90.001 Hz | native 4320x2160@90, already known to FAIL |
| 5 | 60.000 Hz | native 4320x2160@60, already known to WORK |

**Physical result, headset on, full PREFLIGHT (595.71.05, Dual MIT/GPL, patch 0004 present,
all 5 USB devices, `Notify Attach Begin` at 24 bpp):**

| mode | HID (`DEVICE_STATUS`, second message) | physical |
|---|---|---|
| **CTRL** (idx1) | htotal=2980 vtotal=1954 refresh=60 bpc=8 — **exact match to design** | HP logo, nothing |
| **B** (idx3) | htotal=2980 vtotal=1954 refresh=90 bpc=8 — **exact match to design** | HP logo, nothing |
| **A** (idx2) | htotal=2980 vtotal=1598 refresh=60 bpc=8 — **exact match to design** | HP logo, nothing |

This is the **"CTRL fails"** row from the table above — but with a data point the table
didn't anticipate: the headset reports over HID a timing **byte-for-byte identical** to
what was injected in each of the three cases (`scripts/decode-status.sh` had already
established that byte 5 = refresh in decimal and bytes 19-22 = htotal/vtotal little-endian).
That **rules out** half the ambiguity of that row: it isn't that "the override never
arrived" — it did, all the way to the physical link, with the correct bpc (byte 18 = 08 in
all three). What's failing is the injection path itself (**"the injection path"**, the other
half of the ambiguity the row did anticipate), not that the headset never saw the requested
mode.

**And there's a concrete candidate for that path, one the table didn't have as a variable:
resolution.** All three injected modes are **2880x1440** — and that's the resolution of the
only other native mode that exists at that width, `2880x1440@90` (slot 0), which **already
failed before this experiment** (T002, earlier session: "HP logo on, screen off"). Meaning
2880x1440 **never showed anything, at any refresh rate, in the entire history of the
project**: not native at 90 Hz, not injected at 60 with a long vblank (CTRL, the exact shape
of the mode that does work), not injected at 60 with a short vblank (A), not injected at 90
with a long vblank (B). The only mode that ever showed video is 4320x2160@60 (T001). With
just this data, **resolution explains 100% of the results without needing the refresh rate
or the vblank**: maybe the panel firmware (or the Analogix bridge) only accepts the
bandwidths/resolutions it was calibrated for, and 2880x1440 simply isn't one of them —
regardless of how correct the electrical timing is.

This doesn't close the factorial, it **reframes it**: it needs to be repeated injecting into
the DisplayID Type I descriptors (4320x2160), as the "If it needs to be repeated at
4320x2160" section below already anticipated — there, there is a confirmed working case at
that resolution, so any result that comes from moving only the vblank/refresh at 4320 won't
carry this same confound.

**Unexplained anomaly, noted so it isn't lost:** in the second HID message of **A** (unique
among the three), byte 1 went from `00` to `01`. According to Monado's comment about the G1
(quoted in `panel-status.py`), that bit in the second message signals that the backlight
**visibly turned on**. In CTRL and B that byte stayed at `00` both times. But the user
reported "nothing, off, just the HP logo" for A same as the other two — so either the bit
isn't reliable as a signal of visible content, or something transient happened during that
particular run. Left open; not to be taken as evidence that A partially worked.

Testlogs T008/T009/T010 (`docs/pruebas.jsonl`) have the full raw HID data.

---

## Second round (2026-08-05, night): the same factorial, on 4320x2160

`scripts/edid-tool.py inject-did` is now written and tested (round-trip through the full
decoder, checksums of the DisplayID section and the extension block verified, rest of the
blocks untouched). It writes over the Type I descriptors of the DisplayID block instead of
the base block, so this time the factorial runs at 4320x2160 — the only resolution with a
confirmed working case — and doesn't carry the resolution confound from the previous round.

```bash
./scripts/edid-tool.py inject-did experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-4k-ctrl.edid CTRL4K:1
./scripts/edid-tool.py inject-did experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-4k-b.edid B4K:1
./scripts/edid-tool.py inject-did experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-4k-a.edid A4K:1
```

All three replace **descriptor #1** (the one that was already failing at 90 Hz) and leave
**descriptor #2** (@60, vblank 514, the one that works) untouched as a physical control in
each EDID.

| preset | timing | pclk | Gbps @24bpp |
|---|---|---|---|
| `CTRL4K` | 4320x2160@60 vblank 514 (same shape as the real descriptor #2) | 709.14 MHz | 17.02 |
| `A4K` | 4320x2160@60 vblank 116 (same shape as the real descriptor #1, but at 60Hz) | 603.60 MHz | 14.49 |
| `B4K` | 4320x2160@90 vblank 240 | 954.72 MHz | 22.91 |

**Why `B4K` uses vblank 240 and not 514, unlike the previous factorial:** at 4320 width,
vblank 514 at 90 Hz hits **25.53 Gbps @24bpp** — pinned against the HBR3 ceiling (25.92),
with no margin. 240 is still well above the 116 that fails (more than double) and leaves
real bandwidth margin, so it still discriminates the hypothesis without risking a second
confound (bandwidth this time, not resolution).

**Each new EDID needs its own reboot.** Confirmed from source
(`nvkms-dpy-override.c: DpyOverrideReadEdid`) that NVKMS copies the file's contents into an
in-memory buffer only once, while parsing `config_file` during module load — it doesn't read
it from disk again afterward. Overwriting the file without rebooting has no effect.
`experiments/vblank/nvkms-override-candidates.conf` already points at the first one
(`CTRL4K`); moving to the next one means editing that line and rebooting again.

**Order: CTRL4K → B4K → A4K**, same criterion as the previous round. After each reboot: full
PREFLIGHT (above) and `hmd-vk list` to confirm the actual index before presenting — with
`CTRL4K` close to 60 Hz same as descriptor #2, two nearly identical modes are going to show
up and you need to check which one shows the exact refresh (`hmd-vk list` prints it to 3
decimals, as was already done in the previous round) or just run both and compare against
the HID.

**Reading the result:** if `CTRL4K` (cloning the working mode into the other position) also
fails, the explanation can no longer be "vblank" nor "resolution" — it would be something
positional (which descriptor, or the `preferred` bit) and it needs to be rethought again. If
`CTRL4K` works, continue with `B4K`: if it works, that's the answer (90 Hz isn't the
problem, the short vblank is). If `B4K` fails and `A4K` works, it's the refresh rate
specifically. If both fail, neither one on its own — points to the pixel clock or the
combination.

### `CTRL4K` run (2026-08-05, night): works — descriptor #1 isn't the cause

Override loaded and verified with `scripts/verify-override.sh` (new: bundles everything that
needs root into a single script — `dmesg`, forcing `detect()`, comparing the active EDID's
md5 — so as not to ask for the sudo password command by command). `dmesg` clean,
`Successfully read...`, active EDID md5 (`993031c3...`) identical to the file.

`hmd-vk list` showed 3 modes (not 6: this round uses the untouched base `hmd.edid` + only
the 2 DisplayID descriptors, one of them modified): `[0] 2880x1440@89.999` (native, base
block, already known to FAIL), `[1] 4320x2160@60.000` and `[2] 4320x2160@60.000` —
**identical to 3 decimals**, expected because `CTRL4K` was designed to clone the exact shape
of descriptor #2. `[1]` was presented (the modified descriptor #1, previously occupied by
the 4320x2160@90 that always failed) by enumeration order (base block first, then DisplayID
in order — confirmed in the previous round).

**Physical result: alternating colors (blue, white, green) — the panel powered on with real
content.** A different palette than expected (orange/blue/green), but unambiguously far from
the HP logo or black that the failing modes produce. HID (`panel-status.py`) corroborated:
byte 5 = `0x3c` (60 decimal, exact), and the second `DEVICE_STATUS` message flipped byte 1
from `00` to `01` — the "backlight visibly turned on" signal from Monado's comment about the
G1 — this time coinciding with a real physical confirmation (unlike the unexplained anomaly
of `A` in the previous round, where that same bit turned on with no visible video). Full log
and testlog T012 in `docs/pruebas.jsonl`.

**Conclusion: descriptor #1's position isn't the cause.** Cloning a sane timing there works
the same as in its original position. That leaves the vblank hypothesis standing — next is
`B4K` (90 Hz, short vblank, same descriptor #1) as the test that actually decides it.

### `B4K` run (2026-08-05, night): FAILS — 90Hz + short vblank, in the position already proven sane

Same procedure: `verify-override.sh` confirmed loading (clean dmesg, active md5
`506f366f...` identical to the file), full PREFLIGHT including `Notify Attach Begin`
(`pclk 954720000 raster 4420x2400 24 bpp` — exact match to `B4K`'s design: vtotal 2400 =
2160 + vblank 240). `hmd-vk list` showed `[1]` at `90.000 Hz` as expected.

**Physical result: nothing, just the HP logo.** Same as all previous native 90Hz cases.
HID (T013) captured only 2 `DEVICE_STATUS` messages, both with byte 5 = `0x3c` (60
decimal) — **not `0x5a` (90)** — and byte 1 at `00` both times (no backlight-on signal).
Unlike the previous round's factorial (`docs/pruebas.jsonl` T008-T010), where the headset
did report the exact 90 refresh over HID despite failing visually, here the companion never
got to report 90 — it stayed at the last known state (60, from `CTRL4K`) and then
"disappeared" (re-enumerated) with no further messages. A real difference between the two
rounds, noted as-is without an explanation yet: it could be startup timing of
`panel-status.py` relative to the modeset, or it could be that here the link never trains
enough for the companion to learn about the change — what's been measured isn't enough to
decide which.

**Next is `A4K`** (60 Hz, short vblank — same descriptor, same lower pixel clock, without
the jump to 90Hz) to separate whether the cause is the refresh rate itself or the
vblank/pixel-clock.

### `A4K` run (2026-08-05, night): FAILS — and this closes the factorial

`verify-override.sh` confirmed loading (md5 `e1f99097...` identical), full PREFLIGHT,
`Notify Attach Begin`: `pclk 603600000 raster 4420x2276 24 bpp` — exact match to design
(vtotal 2160+116). **Physical result: screen off, just the HP logo.** HID (T014) confirmed
refresh=`0x3c` (60, exact) and htotal/vtotal (`4420`/`8e4`=2276, bytes 19-22) exact to
design — the timing arrived perfect again — but the backlight-on bit (byte 1 of the second
message, the same one that did turn on in `CTRL4K`/T012) stayed at `00` in both messages.
Same as `B4K`: the link never gets to turn the panel on.

**Conclusion of the complete 2x2 factorial:**

| | long vblank (514) | short vblank (116/240) |
|---|---|---|
| **60 Hz** | `CTRL4K` — **WORKS** | `A4K` — **FAILS** |
| **90 Hz** | (not tested at 4320; see below) | `B4K` — **FAILS** |

**It isn't the refresh rate. It's the short vblank.** `CTRL4K` and `A4K` are both at 60
Hz — one works and the other doesn't, and the only difference is the vblank (514 vs 116).
That also flatly closes off the bandwidth explanation: `A4K` runs at 603.6 MHz, well below
the HBR3 ceiling (25.92 Gbps), and still fails just like `B4K` at 954.72 MHz. It doesn't
matter how much bandwidth margin there is — what breaks the link is the short duration of
the vertical blanking itself, not the bits per second needed to sustain it.

**This changes the project's goal.** The limit isn't "90 Hz": it's a minimum vblank,
somewhere between 116/240 (fail) and 514 (works). If that minimum is compatible with 90 Hz
within HBR3's bandwidth, **90 Hz is achievable** with the right vblank — the most direct
candidate is exactly the combination that had been ruled out for tight bandwidth margin:
4320x2160@90 with vblank 514 (25.53 of 25.92 Gbps — 1.5% margin). If it WORKS, the lab is
done. If it fails, the minimum vblank needs to be bisected between 240 and 514 (the "second
experiment" below, but run at 4320 with `inject-did` instead of on the base block) to find
the real cutoff point and from there look for a refresh rate that fits.

Full testlog T014 in `docs/pruebas.jsonl`.

### `90long` run (2026-08-05, night): FAILS — and this narrows the problem down to microseconds

`verify-override.sh` confirmed loading (md5 `82483a9f...`), full PREFLIGHT, `Notify Attach
Begin`: `pclk 1063720000 raster 4420x2674 24 bpp` — exact match to design (vtotal 2160+514,
the same vblank that works at 60 Hz, now at 90). **Physical result: just the HP logo,
black.**

New compared to `B4K`: this time the HID (T015) **did** update — refresh `0x5a` (90, exact)
and htotal/vtotal (`4420`/`0a72`=2674) exact to design, backlight byte 1 at `00` both times.
Meaning the mode did arrive complete all the way to the link, with the same vblank (in
lines) that works perfectly at 60 Hz — and it still doesn't lock. This rules out `B4K`'s
failure being "the HID never found out"; at 90 Hz, not even a correct vblank in lines is
enough.

**The four results line up cleanly by vertical blanking time, not by lines:**

| mode | vblank (lines) | refresh | vblank (ms) = vblank/((vact+vblank)·rate) | result |
|---|---|---|---|---|
| `A4K` | 116 | 60 Hz | 0.849 ms | FAILS |
| `B4K` | 240 | 90 Hz | 1.111 ms | FAILS |
| `90long` | 514 | 90 Hz | 2.136 ms | FAILS |
| `CTRL4K` | 514 | 60 Hz | **3.204 ms** | **WORKS** |

Note that `90long` and `CTRL4K` have the **same number of lines** of vblank (514) and yet
one fails and the other works — the only difference is the refresh rate, which changes how
much real *time* that blanking lasts (at a higher refresh, each line lasts less). That rules
out "number of lines" as the relevant variable and points to a minimum duration in
microseconds that the panel/Analogix bridge needs during the vblank for whatever it does
there (maybe retraining, maybe processing the previous frame) — a hypothesis, not confirmed
yet.

**Why this is a problem for 90 Hz specifically:** the HBR3 ceiling (25.92 Gbps @24bpp) caps
the pixel clock at ~1080 MHz. At 90 Hz with `htotal=4420`, that puts a maximum vblank of
**~555 lines ≈ 2.27 ms** — below the 3.204 ms already known to work. If the real time
threshold needed is closer to 3.2 ms than to 2.27 ms, **90 Hz might not be achievable within
HBR3 with any vblank**, no matter how much it's stretched — bandwidth runs out before
reaching the minimum time.

**Before spending another reboot near the bandwidth limit at 90 Hz, it's worth narrowing
down the real threshold at 60 Hz**, where there's no bandwidth pressure and any vblank can
be tested. Next candidate: `vblank=340` lines at 60 Hz gives exactly 2.27 ms — the same time
that would be the maximum possible at 90 Hz within HBR3.

```bash
./scripts/edid-tool.py inject-did experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-4k-bisect1.edid 340@60:1
```

663.00 MHz, vtotal 2500 — 15.91 Gbps, far from any limit. **If this FAILS, 90 Hz is ruled
out within HBR3** (there's no vblank that both fits the bandwidth and reaches the minimum
time). **If it WORKS**, keep bisecting upward between 340 and 514 lines (at 60 Hz, with no
bandwidth pressure) to narrow down the real threshold, and only then evaluate whether it
fits at 90 Hz or whether an intermediate refresh rate (72/75/80 Hz) that does fit needs to
be found.

Full testlog T015 in `docs/pruebas.jsonl`.

### `bisect1` run (2026-08-05, night): FAILS — 90 Hz is ruled out within HBR3

`verify-override.sh` confirmed loading (md5 `001af82f...`), `Notify Attach Begin`: `pclk
663000000 raster 4420x2500 24 bpp` — exact (vtotal 2160+340). **Physical result: just the
HP logo.** HID (T016) confirmed exact timing (60Hz, htotal/vtotal 4420/2500) delivered
perfectly, backlight never turned on.

**vblank=340 at 60 Hz gives 2.27 ms — the same time that would be the maximum possible at
90 Hz within HBR3 — and it fails.** That confirms the real time threshold is above 2.27 ms,
and since the bandwidth ceiling at 90 Hz doesn't allow exceeding that value under any
vblank combination, **90 Hz is ruled out as achievable within this DisplayPort HBR3 link**,
regardless of what vblank is used.

**Decision with the user: go straight to an intermediate refresh rate with real margin,
instead of continuing to bisect the exact threshold at 60 Hz.** At 80 Hz the bandwidth
ceiling allows up to 3.66 ms (against the 3.204 ms already known to work at 60 Hz) — much
more margin than at 90 Hz. Candidate: `vblank=775` at 80 Hz → 1037.82 MHz, 3.301 ms, 24.91
of 25.92 Gbps (~4% margin, not pinned against the limit like the previous attempts at 90
Hz).

```bash
./scripts/edid-tool.py inject-did experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-4k-80hz.edid 775@80:1
```

**This redefines the project's goal.** `CLAUDE.md` claims that "the only cure" for the
flicker is reaching 90 Hz — but that claim was never tested at an intermediate refresh rate,
it was an assumption based on how WMR advertises its native modes (only 60/90 in the EDID),
not a measurement. If 80 Hz (or the highest refresh rate that fits within HBR3 with a
sufficient vblank) reduces or eliminates the perceptible flicker, it changes the lab's
success criterion. If it doesn't reduce it, then whether the flicker is specific to the
backlight strobe frequency at 90 Hz needs to be reviewed, rather than simply "higher is
better."

Full testlog T016 in `docs/pruebas.jsonl`.

### `80hz` run (2026-08-05, night): FAILS — refutes the time-threshold hypothesis

`verify-override.sh` confirmed loading, `Notify Attach Begin`: `pclk 1037820000 raster
4420x2935 24 bpp` — exact match to design (vtotal 2160+775). **Physical result: no image,
just the logo.** HID (T017) confirmed refresh `0x50` (80, exact) and htotal/vtotal
(`4420`/`0b77`=2935) exact.

**This breaks the "blanking time threshold" hypothesis.** `80hz` has **3.301 ms** of
vertical blanking — *more* than `CTRL4K`'s 3.204 ms, which does work. If blanking time were
the relevant variable, `80hz` should have worked. It didn't. The hypothesis built from the
first four data points (which lined up perfectly by time) is refuted by the fifth. Noted
explicitly so as not to repeat the mistake: **this hypothesis is not to be used again as if
it were confirmed.**

**Pattern that does survive all six data points, and is simpler:** the only mode that has
ever shown video, in the entire history of the project, has a **pixel clock ≈ 709.15 MHz**
(the native descriptor #2, and `CTRL4K`, its clone). All the others — native and
synthetic — have a different pixel clock, and all of them failed:

| mode | pixel clock | result |
|---|---|---|
| native 2880x1440@90 (T002) | 428.58 MHz | FAILS |
| native 4320x2160@90 (T003/T007) | 905.40 MHz | FAILS |
| `A4K` | 603.60 MHz | FAILS |
| `B4K` | 954.72 MHz | FAILS |
| `90long` | 1063.72 MHz | FAILS |
| `bisect1` | 663.00 MHz | FAILS |
| `80hz` | 1037.82 MHz | FAILS |
| **native 4320x2160@60** | **709.15 MHz** | **WORKS** |
| **`CTRL4K`** | **709.14 MHz** | **WORKS** |

This also reinterprets a result from the previous round that had been left not fully
explained: `CTRL` (T008, first round, 2880x1440@60 with a long vblank) had failed and was
attributed to the resolution confound (2880x1440 "never showed anything"). With this
pattern, there's an alternative explanation that fits equally well: 2880x1440@60 has a
pixel clock of ~397 MHz — also not 709.15 MHz — so the same mechanism explains it without
needing to invoke resolution at all.

**New hypothesis, unconfirmed: the Analogix bridge (or the panel itself) only locks at a
specific pixel clock (~709 MHz), independent of resolution, refresh rate, or vblank.** If
that's the case, no EDID combination reaches 90 Hz (or any other refresh rate) over this
link: the limit isn't a timing one but the bridge's PLL, and Windows' HID path to reach 90
Hz would have to be reprogramming that clock through another channel (DPCD/AUX, not the
EDID/mode path this experiment can touch).

**Test that separates this hypothesis from "only 60 Hz locks" (without touching the
refresh rate):** build a 60 Hz mode with a generous vblank (known good, ~514 lines) but with
a pixel clock different from 709 MHz — by changing the *horizontal* blanking instead of the
vertical (something no test so far has touched: all of them used the same horizontal
50/4/46). If that also fails, the specific pixel clock is the variable, not the refresh
rate. If it works, the pixel clock doesn't matter and the pattern in the table is
coincidence (the six failures also all share refresh ≠ 60, so it can't be separated yet
with the data on hand).

Full testlog T017 in `docs/pruebas.jsonl`.

---

## Second experiment: the refresh sweep

The factorial tells us *whether* the vblank matters. It doesn't tell us *where* the limit
is along the refresh-rate axis. For that, the shape of the timing is held fixed and only the
refresh rate is moved:

```bash
./scripts/edid-tool.py inject-mode experiments/vblank/hmd.edid \
    -o experiments/vblank/sweep-70-75-80.edid  SHORT@70:1 SHORT@75:2 SHORT@80:3
```

`SHORT` is the blanking of the modes that fail (vblank 158), `LONG` that of the one that
works (vblank 514). The parametric form is `BLANKING@RATE` and accepts any refresh rate
between 24 and 240.

**The base block has 4 slots and slot 0 carries the native mode, so 3 fit per EDID.** That's
why the sweep is done by **bisecting**, not in a single pass:

| round | modes | what it answers |
|---|---|---|
| 1 | `SHORT@70` `SHORT@75` `SHORT@80` | is there a threshold, and which third does it fall in? |
| 2 | three values around the change | narrows it to ±1-2 Hz |

Pixel clock reference with `SHORT` (all well below the 709 MHz of the working mode, so none
of them introduces bandwidth pressure):

```
SHORT@65  309.53 MHz     SHORT@75  357.15 MHz
SHORT@70  333.34 MHz     SHORT@80  380.96 MHz
SHORT@72  342.87 MHz     SHORT@85  404.77 MHz
```

How to read it: if the panel works up to a certain refresh rate and fails past it **with
the timing shape held constant**, there's a hard threshold and it's a far more actionable
data point than "90 Hz fails." If instead it fails at any refresh rate other than 60 with
`SHORT`, it isn't a threshold but the shape of the timing — and it reinforces whatever the
factorial says.

Run this **after** the factorial: if `B` (90 Hz with a long vblank) works, the refresh-rate
axis is already ruled out and the sweep loses its point.

---

## If it needs to be repeated at 4320x2160

`edid-tool.py` already **decodes** the DisplayID Type I descriptors (`decode_did_type1`),
but doesn't write them yet. The encoder was written and validated against this real EDID:
the decoder reproduces exactly `905.400 MHz` with vblank 116 and `709.150 MHz` with vblank
514, so the layout is empirically confirmed and adding an `inject-did` is straightforward.

Type I layout (20 bytes, every field except the polarities stores `value - 1`):

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

**Two** checksums need correcting: the one for the DisplayID section (last byte of the
section, which starts at `blk+1` and spans `5 + section_size`) and the one for the EDID
extension block (`blk+127`).

Suggested presets, all within HBR3 (25.92 Gbps):

| preset | timing | pclk | Gbps @24bpp |
|---|---|---|---|
| `CTRL4K` | 4320x2160@60 vblank 514 | 709.15 MHz | 17.02 |
| `A4K` | 4320x2160@60 vblank 116 | 603.60 MHz | 14.49 |
| `B4K` | 4320x2160@90 vblank 240 | 954.72 MHz | 22.91 |

With only two descriptors in the block, it's best to replace **desc 1** (the @90 that
already fails) and leave desc 2 (@60) untouched as a control.

---

## Corrections already applied — do not reintroduce

The published report had errors that were fixed along the way. If something new is drafted
for the forum or the PR:

- The G2's extension is **DisplayID 1.2** (version byte `0x12`), with two **Type I**
  descriptors. It is NOT DisplayID 2.0 nor Type VII. *(verified against the real bytes)*
- `input.u.digital.bpc` is assigned in **three** places in the tree, not two: `nvt_edid.c:932`,
  `nvt_edidext_displayid20.c:314`, and `nvkms-dpy.c:2257` — this last one inside
  `CreateParsedEdidFromNVT_TIMING()`, which never runs for a sink with a real EDID.
- Line numbers on the 595.71.05 tag: DP clamp in `nvkms-dpy.c:3456`, DisplayID dispatch in
  `nvt_edid.c:1101`. On `main` (610.57.04) they're 3468 and 1101.
- DSC is ruled out **by arithmetic**, not by the absence of strings in `dmesg`: the working
  mode is 17.0 Gbps uncompressed and the failing one 10.3, so DSC can't be required for the
  one that fails.
- The `.patch.txt` attached on the forum is **outdated**: it says "DisplayID 2.0" and has a
  miscounted hunk header. A regenerated one is in `patches/nvidia/`.

## Verified against the real EDID bytes

All of this was checked against `experiments/vblank/hmd.edid`, and it matches what the
forum post states:

```
byte 0x14 = 0x80          digital, color bit depth = 000 (undefined)
checksum base block 0xE8  block sum = 0
ManufID 0x220E            = HPN
CTA byte 3 = 0x00         no YCbCr 4:4:4 nor 4:2:2
DisplayID: 70 12 79 00 00 03   version 1.2, tag 0x03, 40 bytes = 2 Type I descriptors
g2-edid-8bpc-repro.bin    differs in exactly 2 bytes: 0x14 and 0x7F, valid checksum
```
