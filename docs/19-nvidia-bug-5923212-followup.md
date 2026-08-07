# 19 — Follow-up for the 5923212 bug thread (60Hz-only on NVIDIA)

## Update (2026-08-06): the patch DOES work — exact cause found, no mystery

**Exact cause, verified line by line against `docs/16-lab-vblank.md`, not a list of
suspects:** nobody had retested the **EDID-native modes, with no override
loaded**, with the bpc patch active — until today.

The full chain:

1. **`T002` (2026-08-04, 23:30)** — first time `2880x1440@90` is tested with `hmd-vk`
   (DRM-lease, the usual mechanism). Fails ("hp on, screen off"). **The
   bpc bug isn't found until the next day**, 2026-08-05 — meaning `T002` ran
   before the patch even existed.
2. That failure becomes a working assumption: *"2880x1440 never showed anything, at any
   refresh rate, in the entire history of the project"* — quoted verbatim like that in
   several places in `docs/16`.
3. **The extensive factorial that did run with the patch active** (confirmed by PREFLIGHT:
   `595.71.05`, `patch 0004 present`, `Notify Attach Begin` at **24 bpp**) — `A4K`, `B4K`,
   `90long`, `bisect1`, `80hz`, `CTRL4K` — **never used the native modes exactly as the EDID
   declares them**. All of them used synthetic timings injected via `nvidia_modeset.config_file`
   (`vblank=240` instead of the real `116` from native descriptor #1, `vtotal=1954` instead
   of the real `1598`, etc.), to isolate vblank as an independent variable — that was the
   question being investigated at the time, before knowing that bpc was the real cause.
4. In one of those sessions (`docs/16`, line 320, **after** the patch, with `hmd-vk list`
   showing mode `[0] 2880x1440@89.999` as available), it's explicitly noted as
   **"(native, base block, already known to FAIL)"** — citing `T002` — and they move on to
   testing another mode without retrying it.
5. **Today, for the first time since the patch has existed, the real native mode was run
   with no override at all** (`hmd-vk native 0`, EDID untouched, confirmed with no
   `nvidia_modeset.config_file` loaded via `journalctl`/`/sys/module/nvidia_modeset/parameters/config_file`)
   — and it lit up. Same result with the native supersampled mode (`hmd-vk native 1`,
   descriptor #1 unmodified, real vblank=116, also never before tested in its plain form).

**There's no need to invoke Wayland-vs-X11, DRM-lease-vs-Direct-Mode, or the driver
reinstall as the cause.** Those things were incidental to how today's test was run, not the
explanation. The complete and sufficient explanation is: the patch fixes the bug, and the
old conclusion "native 90Hz fails" was never reevaluated after the patch existed — it kept
getting cited from memory, never remeasured.

**What's still unexplained, and why this isn't fully "closed":** the panel still appears to
flicker as if it were running at ~60Hz, even though the headset's HID, the compositor's
timing (11.111ms, exact), and the API all three confirm it genuinely runs at 90Hz. It
persists the same with a synthetic pattern, with real video, **and in the native mode too**
(so it isn't a "wrong mode" issue either — the exact same timing Windows uses was explicitly
tested, confirmed via CRU, and it still flickers). Without a high-speed camera (120fps+)
there's no way to measure the physical backlight strobe from here — see the "flicker lead"
section in `linuxlab-kit/NEXT-STEP.md` for the current hypothesis (backlight duty cycle,
auto-adjusted by firmware based on the detected timing, with no host command).

**Posted on 379240** (2026-08-06, confirmed via direct fetch — post #3 of the thread):
<https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240/3>.
Loose copies of the two drafts (to paste without having to look them up in this file) are in
`forum-attachments/nvidia-post-1-bpc-thread-379240.txt` and
`forum-attachments/nvidia-post-2-original-thread-337744.txt`.

**Still need to post on 337744** (the original 5923212 thread, the short reply that points
here) — still pending, draft below.

**Public repo (2026-08-06):** confirmed via the GitHub API (`private: false`) that
`github.com/Wintch/reverb-g2` is genuinely public — from now on reference it in the posts,
inviting the community in (someone might have a piece of missing backlight data). Edit draft
to add the link to the already-published post is in
`forum-attachments/nvidia-post-3-edit-add-repo-link.txt` (it's an EDIT to the existing post
#3, not a new post). The 337744 draft (still not posted) already includes the entry link.

**Big new data point (2026-08-06): on Windows, the flicker happens exactly the opposite way
from Linux.** The user confirms: on Windows, **60Hz flickers and 90Hz does NOT** — the exact
opposite of what we measured today on Linux (where 90Hz does flicker). This is much stronger
evidence than what's already posted: it flatly rules out a physical panel/headset defect (if
it were, it would flicker the same way on both OSes) and confirms it's a real, mode-linked
behavior specific to how Linux negotiates the link — not something explainable by damaged
hardware. Worth adding to the thread, it's more conclusive than the current "I don't know why
it flickers."

## RESOLVED: the 90Hz flicker no longer reproduces (2026-08-06, afternoon — T026-T029)

**Result, with a static solid white pattern (`HMD_VK_SOLID=1`, added to `hmd-vk` today) and
the user's physical verdict looking at the panel:**

| Mode | Verdict |
|---|---|
| 2880x1440@90 native | **clean** ("perfect") |
| 4320x2160@90 | **clean** ("perfect") — also immediately after a 60Hz session (order-independent) |
| 4320x2160@60 | **flickers** ("flickers") |

In other words: **Linux now behaves EXACTLY like Windows** (60 flickers, 90 clean — the
"big new data point" above). The reportable anomaly is gone; the 60Hz flicker is factory
backlight behavior at a non-native panel frequency, not a Linux or driver problem.

**Methodological correction that invalidates our own evidence:** of the three previous
confirmations of "90Hz flicker," two (T020 and T023) used `hmd-vk`'s color test, which
**alternates color EVERY FRAME** — at 90fps that's a ~30Hz strobe by construction. Those two
observations were the test flickering, not the panel. Only T021 (real video via Monado) was
a valid observation — and that one doesn't reproduce today (video at 90 clean, confirmed by
the user with real content before this batch).

**What changed between T021 (flickering) and today (clean):** on the driver side, NOTHING —
same 595.71.05-open, same bpc patch, verified in both states. What did happen in between: a
full reboot and several unplug/reconnect cycles of the headset's USB (the marginal cable
documented in `docs/06`). Most plausible hypothesis (labeled as a hypothesis, not proven —
with no AUX access there's no way to prove it): backlight state stuck on an old timing
config, cleared by the power cycle; the headset firmware manages backlight duty cycle based
on the detected timing (strings from the Windows driver:
`left duty %d, right duty %d, frame timing %d`, see `docs/09`).

**Forum action: DONE (2026-08-06, afternoon).** Both published posts were EDITED by the
user with "EDIT (same day...)" blocks (no auto-reply). The exact texts are in
`forum-attachments/nvidia-post-1-bpc-thread-379240.txt` and
`forum-attachments/nvidia-post-2-original-thread-337744.txt`. With this the public record is
correct: 90Hz working and clean with the bpc patch; the only driver issue still standing in
the threads = the bpc default when the EDID leaves color depth undeclared.

**Software tooling exhausted, confirmed (2026-08-06):** tried
`/sys/kernel/debug/dri/*/DP-1/dpcd` (DRM's generic debugfs for dumping DPCD registers) —
**that file doesn't exist for this connector**, only `edid_override`, `force` (already ruled
out in `docs/16`), `output_bpc`, and `vrr_range`. Confirms what was already suspected: NVIDIA
doesn't expose DPCD/AUX through DRM's generic helpers for this connector. USB capture was
also ruled out as a path — DisplayPort's AUX/DPCD isn't a USB protocol, it runs over the DP
cable itself, so a USB capture (like the one already done) **could never see it**, no matter
how much you looked. **Without a real DisplayPort protocol analyzer (dedicated hardware, not
available here), there's no software tool left to inspect this.**

**Watch out for untracked personal photos** (`photo_51613...jpg`,
`docs/Screenshot_20260806_064623.png`) still sitting loose in the working directory — with
the repo now genuinely public, a careless `git add` would expose them. Check before any
`git add -A`/`git add .` in this repo.

### Draft for 379240 (the bpc thread — the most relevant one, reply to the original post) — ALREADY POSTED

```
Update: the patch works — 90 Hz now lights up the panel with a real image.

Following up on my original report above (6bpc clamp root-caused, two-line patch, but 90 Hz
still failing to light at the time).

Root cause of that gap, now found: nobody had retested the panel's native EDID modes with no
EDID override loaded at all, after the patch was in place. The "90 Hz native fails" data
point in my own investigation predates the patch by about 24 hours (it's from before I'd
found the 6bpc bug), and every subsequent test that ran with the patch active used synthetic,
injected timings to isolate vertical blanking as a variable - never the plain, unmodified
native mode. One of my own working notes even lists the native 2880x1440@90 mode as available
and explicitly skips retesting it, citing the pre-patch result. That's on me, not a mystery -
just an assumption that outlived the fix that invalidated it.

Retested today with a plain EDID and no override at all: 90 Hz produces a real image,
verified physically with the headset on (flat alternating test colors, and separately with
real decoded video content) - the first time in this whole investigation that anything got
past the boot logo at 90 Hz. Tested at both the supersampled 4320x2160@90 mode and, more
importantly, the native 2880x1440@90 mode (the EDID's own base-block DTD, unmodified - the
exact mode I separately confirmed via CRU that Windows itself drives this panel with).

One thing still open, and it's the reason I'm not closing this out yet: the panel still
visually appears to flicker/strobe at what looks like ~60 Hz to the eye, despite genuinely
running at 90 Hz confirmed at every layer I can check - the headset's own HID status report,
the compositor's frame pacing (11.111 ms period, matches 90 Hz exactly), and the presentation
API. This persists identically with a synthetic test pattern, with real video content, and at
the native Windows-matching mode too - so it isn't a rendering/compositor artifact and it
isn't a "wrong mode" issue either. I don't have a way to measure the physical backlight
strobe rate directly from here (would need a 120fps+ camera) so I can't rule in or out yet
whether this is a separate firmware-level backlight-timing behavior, unrelated to the
DisplayPort link itself.

Happy to share the exact steps/config if useful to anyone else hitting this.
```

### Draft for 337744 (the original 5923212 bug thread — short reply, points to the other thread)

```
Update on my factorial results above: they're superseded — 90 Hz does light up now, and I
found exactly why the factorial never showed it.

Short version: every test in that factorial (and the native-mode result I'd cited before it)
either predates a separate bug I later found and fixed (NVKMS clamps color depth to 6 bpc
when this EDID leaves it undeclared), or used a synthetic/injected timing rather than the
panel's plain, unmodified native mode. Nobody had retested the literal native EDID timing
with that patch actually in place until today - and it lights up fine. Full root-cause,
patch, and today's confirmation are in a separate thread I'd opened for that specific issue:

https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240

The bridge-chip-ceiling conclusion from the factorial doesn't hold up - once the bpc bug is
patched, native 90 Hz (the exact same EDID timing, unmodified, byte-identical to what Windows
itself uses per a CRU capture) lights up fine. There's still an open question about a visible
flicker at 90 Hz even with a real image now, detailed in the other thread, so I'm not calling
this fully closed - but the "90 Hz is architecturally impossible on this link" conclusion I
posted earlier was wrong, and I wanted to correct the public record here rather than leave it
standing.
```

---


Thread: https://forums.developer.nvidia.com/t/reverb-g2-unable-to-drive-more-than-60hz-mode-on-nvidia/337744

Status as of 2026-08-05: NVIDIA (`abchauhan`) confirmed the reproduction and opened internal
bug **5923212** on 2026-03-20, asking whether any older driver version worked. No response
from NVIDIA since. Last community post: `MiaPerec`, 2026-07-19, same symptom on 610.43.02.

**What this follow-up adds that the thread doesn't have yet:**

1. The bridge chip identified by name (`ANX7530`, read from the headset's own firmware
   version string) and its datasheet, which explicitly states the ceiling as **"4K x 2K x
   60Hz"** — not just a bandwidth calculation.
2. A complete factorial that separates refresh rate, vblank, and pixel clock as independent
   variables, with physical verification at every cell (not just "the API reports success").
3. The fact that the headset's own HID confirms, byte for byte, that the requested timing
   reaches the link perfectly even in the cases that fail — ruling out "the mode never
   arrived" as an explanation.

It's in English because it's meant for the forum. Copy it as-is or edit it before posting —
**I'm not posting it**, I don't have your forum credentials and posting there is a public
action that's your call to decide when and how.

---

## Update (2026-08-06): the content below got posted, but in the wrong thread

The draft further below ended up getting posted as a reply in the **bpc thread (379240)**,
not here (337744) — confirmed with a direct fetch of both threads: 379240 has today's
00:53am post with this same content; 337744 still has nothing new since `MiaPerec` on
2026-07-19. It might have been intentional (it's your thread, you have more context there)
or a tab mix-up — I don't know, I'm not assuming either way.

Decision: post **here too**, adapted as a short cross-post that points `abchauhan` to the
full result, instead of duplicating the entire table. Draft below, same treatment as above:
**I'm not posting it**, it's text ready to copy/paste or edit.

**Posted 2026-08-06, 10:00am**, as post #14 of thread 337744:
<https://forums.developer.nvidia.com/t/reverb-g2-unable-to-drive-more-than-60hz-mode-on-nvidia/337744/14>.
It went in as a normal post at the end of the thread, **not** as a threaded reply to
`abchauhan`'s post #10 (no "in reply to" indicator). If there's no response within a
reasonable time, consider editing the post to add `@abchauhan` at the start — on Discourse
that does trigger a direct notification. No response from NVIDIA yet on either thread
(checked the same day, a few minutes after posting — it's expected that there'd be nothing
yet).

### Draft for 337744 (cross-post, short)

**Reply to `abchauhan`'s bug 5923212:**

Following up here — I ran a full factorial that isolates refresh rate, vertical blanking, and
pixel clock as independent variables on real hardware (physical verification every time,
headset worn, not just API success), plus identified the bridge chip's own datasheet ceiling.
Posted the full results (table, methodology, bridge chip data, an open question about the
ANX7530's PLL) as a follow-up in a related thread I'd started for a different EDID issue on
the same headset, to avoid fragmenting the data across two threads further:

<https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240/2>

Short version: none of resolution, refresh rate, vblank duration, or total DisplayPort
bandwidth alone explain the failure — the only pixel clock that has ever produced an image,
across every combination tried, is exactly ~709.15 MHz (the bridge chip's own native
4320x2160@60 timing). That, plus the bridge chip's datasheet ("DisplayPort Receiver Input
Bandwidth supports up to 4K x 2K x 60Hz" as an explicit spec line), points at a
hardware/firmware ceiling rather than a pure EDID/mode-timing problem.

Any update on bug 5923212 from your side? It's been quiet since March.

---

## Post draft

**Summary:** Ran a full 2×2×N factorial isolating refresh rate, vertical blanking, and
pixel clock as independent variables on real hardware (physical verification each time,
headset worn, not just API success). Result: none of resolution, refresh rate, vblank
duration, or total DisplayPort bandwidth alone explain the failure. The only pixel clock
that has ever produced an image, across every combination tried, is **exactly ~709.15 MHz**
— which is also the bridge chip's own native 4320x2160@60 timing. That, plus the bridge
chip's datasheet, points at a hardware/firmware ceiling rather than a pure EDID/mode-timing
problem.

**Setup:** RTX 3060 Ti, 595.71.05-open, patched with the 3-patch Project-VR stack plus a
4th patch fixing a separate 6bpc-clamp bug in this same EDID (undeclared color depth —
[NVIDIA/open-gpu-kernel-modules#1275](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275),
unrelated to this bug but worth ruling out first if anyone else hits it). Modes injected via
`nvidia_modeset.config_file` EDID override, so htotal/vtotal/refresh are controlled
precisely per attempt. Verified two ways every time: (a) physically, headset worn, backlight
on/off and color vs. logo; (b) the headset's own HID status report
(`DEVICE_STATUS`, 33 bytes), which echoes back the negotiated htotal/vtotal/refresh/bpc —
confirms the requested timing actually reached the panel, independent of whether it lit up.

**Bridge chip:** `ANX7530` (Analogix DisplayPort-to-dual-MIPI, VR-targeted), identified from
a firmware version string on the device (`ANX7530:x.x`). Its product brief
(AA-004263-PB-7) states: "DisplayPort Receiver Input Bandwidth supports up to 4K x 2K x
60Hz" as an explicit spec line, and lists HBR2.5 (6.75 Gbps/lane) as its DisplayPort link
ceiling — not HBR3. Both numbers are far above anything any of our attempted 90Hz modes
needed, so neither the chip's raw link rate nor total pixel throughput explains the
failures below.

**Results** (all at 4320x2160 unless noted; vblank time = vblank_lines / ((v_active +
vblank_lines) × refresh)):

| label | resolution | refresh | vblank (lines) | pixel clock | vblank time | result |
|---|---|---|---|---|---|---|
| native, working | 4320x2160 | 60.00 Hz | 514 | 709.15 MHz | 3.204 ms | **works** |
| CTRL4K (cloned copy of the working mode, different descriptor slot) | 4320x2160 | 60.00 Hz | 514 | 709.14 MHz | 3.204 ms | **works** |
| A4K | 4320x2160 | 60.00 Hz | 116 | 603.60 MHz | 0.849 ms | fails |
| B4K | 4320x2160 | 90.00 Hz | 240 | 954.72 MHz | 1.111 ms | fails |
| 90long (same vblank *line count* as the working mode, at 90Hz) | 4320x2160 | 90.00 Hz | 514 | 1063.72 MHz | 2.136 ms | fails |
| bisect1 (60Hz, short vblank, no bandwidth pressure) | 4320x2160 | 60.00 Hz | 340 | 663.00 MHz | 2.267 ms | fails |
| 80hz (more vblank *time* than the working mode, comfortable bandwidth margin) | 4320x2160 | 80.00 Hz | 775 | 1037.82 MHz | 3.301 ms | fails |
| native, previously reported | 2880x1440 | 90.00 Hz | — | 428.58 MHz | — | fails (lower total bandwidth than the working mode) |

Every row that isn't ≈709 MHz fails, regardless of whether it has more bandwidth headroom,
more vblank lines, or more vblank *time* than the one working mode. `80hz` is the clearest
single data point: strictly more vertical blanking time than the working 60Hz mode, well
inside the bridge's own bandwidth spec, and it still doesn't light up.

**What this rules out, with this methodology:**
- Total DisplayPort bandwidth (`80hz` needs less than the chip's declared HBR2.5 ceiling
  and still fails; `2880x1440@90`, reported earlier in this thread, needs *less* bandwidth
  than the working mode and also fails).
- Vertical blanking duration, whether measured in lines or in time (`80hz` has more than
  the working mode; `A4K`/`bisect1` have less; both buckets fail identically).
- The EDID/mode-injection mechanism itself not reaching the panel — the headset's own HID
  status confirms exact timing delivery in every failing case tested.

**Open question for anyone with lower-level visibility (DPCD/MSA capture, or the Windows
driver's internal handling of this panel):** is there a known reason the ANX7530's PLL (or
its `MCU` block, per the datasheet's block diagram) would only lock to specific discrete
pixel clocks rather than an arbitrary continuous range? If so, is ~709 MHz special-cased
somewhere in NVIDIA's Windows driver for this device (a quirk/allowlist), which the Linux
595-open path doesn't carry over?

Happy to run more targeted captures if anyone with visibility into the internal bug can
point at what to look for specifically.

**Update (2026-08-05, evening): live Windows capture — no special pixel clock, no extra USB
command**

With direct access to a Windows machine driving the same headset, I read the *active* timing
with CRU (Custom Resolution Utility) while 90 Hz was working: `2880x1440 @ 89.999 Hz
(428.58 MHz)`, `htotal=2980 vtotal=1598`. This is exactly the base-block DTD from the EDID,
unmodified — same pixel clock, same totals. Windows isn't using any special or out-of-band
timing for this mode: it's exactly what the EDID itself publishes.

This reframes the open question above (is there a "special" pixel clock cached somewhere in
the Windows driver for this device?): there isn't, at least not in the sense of a magic value
that differs from the EDID. Windows drives the 60 Hz mode (709.15 MHz, DisplayID descriptor
#2) and the 90 Hz mode (428.58 MHz, base-block DTD) both "as-is," straight from the EDID.
What separates the two isn't the pixel clock itself — it's specifically crossing the
refresh-rate threshold, consistent with the factorial results above.

I also captured, over USB (Wireshark + USBPcap), the exact moment of a live refresh-rate
change on Windows (60→90 Hz and 90→60 Hz, without disconnecting the headset). No additional
HID command appears during the transition — only the usual status report (`DEVICE_STATUS`,
33 bytes) updating refresh/htotal/vtotal, identical in shape to what's already seen in steady
state. This rules out a hidden, Windows-specific USB activation sequence as well.

At this point, from the Windows user-tooling side (Wireshark/USBPcap, CRU, HWiNFO64, GPU-Z,
NVIDIA's own control panel) there's nothing left to check: no special EDID, no hidden USB
command, no visible DSC (the Reverb G2 doesn't even show up as a selectable display in the
NVIDIA panel or in Windows Settings while in direct/HMD mode). What's still invisible from
here is exactly the open question above: what happens during DisplayPort link training
(DPCD/AUX), or inside the closed GSP firmware — no user-space tool reaches either of those on
any OS.

---

## Local check (2026-08-05, no reboot): stereo/3D bits in the EDID — nothing

The ANX7530 datasheet lists "Horizontal left/right line splitting" and "3D stereo modes" as
DisplayPort receiver features — hypothesis: maybe Windows enables a split-stream mode (a
lightweight stream per eye, instead of one combined 4320-wide stream) via some stereo bit in
the EDID that our clones aren't preserving.

`byte 17` of the base block's only DTD and `byte 3` of the two native DisplayID Type I
descriptors were decoded by hand:

- Base block (2880x1440@90, native, fails): byte17=`0x1e`, stereo bits (0 and 6-5) all
  0 — no stereo declared.
- DisplayID descriptor #1 (4320x2160@90, native, fails): byte3=`0x88` — `preferred=1`,
  stereo bits (6-5) at `00`, otherwise identical to #2 except for that bit.
- DisplayID descriptor #2 (4320x2160@60, native, WORKS): byte3=`0x08` — `preferred=0`,
  same stereo bits at `00`.

**No native descriptor declares stereo, and the only bit that distinguishes the working one
from the failing one is `preferred`.** If the dual-stream split exists, it isn't triggered by
a visible flag in the EDID — which we've already been preserving untouched across all clones.
This doesn't rule out the dual-stream hypothesis, but if it's real, the mechanism that
triggers it lives outside the EDID (DPCD, AUX, or a proprietary command), consistent with
everything else this document already points to as "below the EDID."

## Search for the original Windows Mixed Reality driver (2026-08-05): not what's needed

Looked for Microsoft's original driver/runtime (from before WMR's removal) to see if it had
the panel logic that Oasis lacks. Result: the candidates found (`microsoft.com/.../id=56265`,
the archive.org zip) are the **sensor/IMU** driver (`HololensSensors`, tracking), not the
video pipeline — they don't mention the ANX7530, DisplayPort, or 90 Hz. The holographic
shell's *Feature-on-Demand* (`Microsoft-Windows-Holographic-Desktop-FOD-Package`, ~1.5 GB) is
listed on the same archive.org, not inspected yet.

**But getting it probably wouldn't close any of this anyway.** `driver_oasis.dll` itself —
the driver that actually achieves 90 Hz on Windows, already disassembled in chapter 09 —
**doesn't touch video timing at all**: it only speaks HID/USB for tracking and sends
`Display Enable`. If the only verified component that achieves 90 Hz doesn't negotiate the
video mode, that negotiation happens entirely through the **standard Windows NVIDIA driver**,
not through any Microsoft or HP component. Neither the holographic FOD nor the original
portal is going to explain the real mechanism — the mystery lives inside the Windows NVIDIA
driver, which we have no way to inspect without reverse-engineering that binary or a real
DPCD/AUX capture during the 60→90 transition on a Windows machine with the physical hardware
(expensive, and already noted as such in the project's history).

Additional data point found: there are "black screen at 90Hz" reports with Microsoft's own
original Mixed Reality Portal, on both AMD and NVIDIA — the G2's 90 Hz seems fragile even on
the reference platform, not an issue exclusive to this lab or to Linux.

## Update (2026-08-05, night): real captures on Windows — no special pixel clock, no extra USB command

With real access to a Windows machine driving the same headset, the ACTIVE timing was read
with CRU (Custom Resolution Utility) while 90Hz was working: `2880x1440 @ 89.999 Hz
(428.58 MHz)`, `htotal=2980 vtotal=1598`. **It's exactly the EDID base block's DTD, without a
single bit modified** — same pixel clock, same totals. Windows isn't using any special or
out-of-band timing for this mode: it's exactly what the EDID itself publishes.

This reframes the open question above (is there a "special" pixel clock cached somewhere in
the Windows driver?): there isn't, at least not in the sense of a magic value that differs
from the EDID. Windows drives both the 60Hz mode (709.15 MHz, DisplayID descriptor #2) and
the 90Hz mode (428.58 MHz, base block DTD) equally "as-is" — both, straight from the EDID.
What separates one from the other isn't the pixel clock itself, it's specifically crossing
the refresh-rate threshold, consistent with what the factorial in this same thread already
showed.

The exact moment of a LIVE refresh-rate change on Windows was also captured over USB
(Wireshark + USBPcap) (60→90Hz and 90→60Hz, without disconnecting the headset). **No
additional HID command appears during the transition** — only the usual status report
(`DEVICE_STATUS`, 33 bytes) updating refresh/htotal/vtotal, identical in shape to what's
already seen in steady state. This also rules out a hidden, Windows-specific USB activation
sequence.

With this, on the Windows user-tooling side (Wireshark/USBPcap, CRU, HWiNFO64, GPU-Z,
NVIDIA's own control panel) there's nothing left to check: no special EDID, no hidden USB
command, no visible DSC (the Reverb G2 doesn't even show up as a selectable display in the
NVIDIA panel or in Windows Settings while in direct/HMD mode). What's still invisible from
here is exactly what was asked above: what happens during DisplayPort link training
(DPCD/AUX) or inside the closed GSP firmware — no user-space tool reaches either of those on
any OS.
