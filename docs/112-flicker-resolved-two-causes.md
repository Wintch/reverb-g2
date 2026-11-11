# 112 — Flicker resolved: two unrelated causes, neither of them the panel (2026-09-07)

Read this before investigating any G2 flicker. Earlier write-ups that blamed the panel or
headset state are superseded by it.

## Bottom line

There was never a Linux-side panel bug. Two separate causes produced one symptom, and each
one was mistaken for the other:

| Reported symptom | Actual cause |
|---|---|
| "flickers at 90 Hz, even under pure Vulkan" | `hmd-vk`'s **default test pattern**, which alternates colour every frame — a ~30 Hz strobe by construction. The instrument, not the panel. |
| "the bright areas flicker" in Aircar and the video player | The **xrizer brightness gain at 1.25×**, which pushes composited values between representable 8-bit levels; the result is dithered temporally downstream (see §3). |
| "flickers at 60 Hz" | Factory backlight behaviour at a non-native panel frequency. **Identical on Windows.** Not a defect. |

The headset is healthy, the NVIDIA patch stack works, the DP link is correct, and USB is fine.

## 1. The A/B that closed the panel question

Run with `HMD_VK_SOLID=1` — solid white, zero source variation, so any flicker seen is the
panel's. Observer verdicts, same headset, same night:

| Mode | Linux | Windows |
|---|---|---|
| 4320x2160@**90** | **clean** | perfect |
| 4320x2160@**60** | flickers | pronounced flicker |

Linux and Windows behave identically. This reproduces the verdict already reached on
2026-08-06 (`docs/19`) after the same mistake.

## 2. What the headset itself reports

`DEVICE_STATUS` (0x05), captured on Linux at 4320x2160@90, against a USBPcap of Windows taken
the same night:

```
Windows:  05 01 01 01 01 5a 0e 00 00 09 38 1e 04 00 77 77 00 00 08 44 11 e4 08 01 00 80 ...
Linux:    05 01 01 01 01 5a 00 00 00 09 38 1e 04 00 77 77 00 00 08 44 11 e4 08 01 00 80 ...
                            ^^
                          byte 6 -- companion-board session counter, resolved dead end (docs/13)
```

Byte-for-byte identical apart from that counter.

| Mode | OS | refresh (b5) | htotal (b19-20) | vtotal (b21-22) | bpc (b18) | pixel clock |
|---|---|---|---|---|---|---|
| 4320x2160@90 | Linux | 90 | 4420 | 2276 | **8** | 905.4 MHz |
| 4320x2160@90 | Windows | 90 | 4420 | 2276 | **8** | 905.4 MHz |
| 4320x2160@60 | Windows | 60 | 4420 | 2674 | **8** | 709.1 MHz |

Both computed pixel clocks match the DRM modes (905400 / 709150 kHz) exactly, in two
independent modes — which is what validates the byte offsets rather than assuming them.

**Patch 0004 is confirmed effective at runtime:** byte 18 reads 8, where the broken-era
reference messages in `docs/12` read `06`. This was previously argued from static evidence
(the patch present in `dkms.conf`, its string in the built module); it is now measured from
the headset's own state.

### How to capture this — four constraints, all learned by failing at them

Earlier attempts the same night returned **zero messages across 7 trials**
and then only zero-filled payloads. Both failures are explained, and none was bad luck:

1. **The DRM connector does not exist until `panel.py activate` has run.** Start `hmd-vk`
   before it and you get `el compositor no ofrece conectores arrendables`.
2. **The companion emits `DEVICE_STATUS` only on a backlight transition**, and fills in the
   mode fields only if **video is actually flowing at that instant**. `verify-bpc.sh` starts
   its listener *after* activation, so the transition is already gone; starting the listener
   first but with nothing presenting yields the all-zero payloads.
3. **`panel.py cycle` kills `hmd-vk`** (`vkQueuePresentKHR: -13`, surface lost). Don't cycle
   mid-test — instead let `hmd-vk` perform its own activation and catch that transition.
4. **`panel-status.py` must run under `python3 -u`.** Redirected to a file, Python block-buffers;
   the buffer is discarded when the process is killed, so the output never arrives at all.

Working sequence: `panel.py off` → listener up (`python3 -u`) → `panel.py activate` → poll for
the connector → start `hmd-vk` the instant it appears → the useful message lands ~9 s later
(the same delay Monado's own comment describes as *"once the HMD screen backlight visibly
powers on"*, and the same delay seen in the Windows capture).


## 3. The real-content flicker: the xrizer brightness gain

The panel A/B did not explain the flicker reported in Aircar and the video player — Monado's
own log proves those sessions negotiated `4320x2160@90.00`. The cause was found in the
compositing path, and settled by a live A/B **hot-swapped mid-flight without doffing** (the
gain is re-read from disk every 30 frames, so no restart is needed):


| gain | verdict |
|---|---|
| 1.000 | **clean, no flicker** — on par with Windows |
| 1.250 | flickers |
| 4.000 | blown out to white, flickers much more |
| 1.000 | clean again |

**Mechanism.** `~/vr/xrizer/src/compositor.rs` (`current_brightness_gain()`) reads and clamps
the gain scalar (`[0.0, 4.0]`) and attaches it as `XR_KHR_composition_layer_color_scale_bias`
to the projection layer, so Monado multiplies the game's RGB *after* it renders and before
scanout. The multiplied values land between representable 8-bit levels and the result is
dithered temporally: adjacent values alternate frame to frame ("colours that alternate"), and
it hits hardest in bright areas, which the multiplier drives against the ceiling. At
`gain == 1.0` the colour layer is not attached at all, so there is nothing to dither.

**Correction (2026-09-08): xrizer itself does not dither.** There is no pixel-level dithering
code in xrizer; the dithering happens downstream, most likely in Monado's compositor or in
NVIDIA's driver at KMS scanout to the 8bpc DisplayPort link. This was not pinned down:
`nvidia-settings` cannot reach the Xorg dithering toggle from a Wayland session (Xwayland has
no NV-CONTROL), and the leased DRM connector (for a `dither` property via `modetest -c`)
exists only while the panel is active. The next step, if it is ever worth chasing, is probing
the connector properties with the panel active, not changing xrizer. The fix and conclusion
(`gain == 1.0` is the only clean value) are unaffected.

**Cross-check against Oasis.** Oasis ships the same kind of control (`driver_oasis` in
`default.vrsettings`: `rgb_gain`, `red_gain`, `green_gain`, `blue_gain`, all default 1). On
Windows, SteamVR brightness left at 220% showed no flicker comparable to Linux's 1.25x, only
clipped highlights. So the difference is not a design choice by either side; it is most
likely a Linux/NVIDIA driver-stack behaviour difference in the presentation path.

**Fixed.** Live file and both non-default profiles set to 1.0:

```
~/vr/logs/xrizer-brightness      1.250 -> 1.000
~/vr/logs/user-profiles.json     both non-default profiles: 1.25 -> 1.0
                                 (backup: user-profiles.json.bak-20260907)
```

Fixing the profile is **mandatory**, not belt-and-braces: `status-dashboard.py` (~line 2748)
re-applies the active profile's `brightness` to the live file on every user switch, so
changing only the live file lets 1.25 silently return.

**Standing rule: never ship a gain other than 1.0 on the G2.** There is no host backlight
command on this headset — none exists on Windows either — so this gain is the only "brightness"
control there is, and what it buys in apparent brightness it pays for in visible dithering.
The dashboard's own settings table already says `"panel backlight": "FIXED -- no host
brightness command exists (Windows included)"`.

## 4. What this cost, and why the existing fix didn't prevent it

This is the **second time** `hmd-vk`'s default pattern produced a false flicker confirmation.
The first was 2026-08-06 — `docs/19`, commit `cc98bb0`, whose own title is *"90Hz flicker
RESOLVED — and two of our three prior confirmations were the test itself"*. The remedy adopted
then was the `HMD_VK_SOLID` environment variable, added to `hmd-vk.c` with an explicit comment
saying the default is *"NEVER for judging backlight flicker"*.

That remedy did not hold: before the hardening in §6, `grep -rn HMD_VK_SOLID scripts/`
returned hits **only inside `hmd-vk.c` itself**. Not one wrapper that ran `hmd-vk` and then
asked a human to look ever set the flag, including the official post-patch check. A warning
comment inside a tool does not protect the operator who runs a wrapper around that tool; **a
safe default would have**.

Concrete cost: an earlier elimination table concluded the flicker was "mode-independent,
bandwidth-independent, refresh-independent, host-software-independent" (two of those four were
wrong, both resting on the same invalid run), a Windows-boot brief was built around a theory of
"persistent state written into the headset by Oasis" that the Windows boot then disproved, and
a long detour into frame pacing followed from misreading a description of what a flicker
looked like ("similar to 60 Hz refresh") as a frame-rate claim.

Ruled out — fake-pacer phase jump: not the cause and not fixed; that investigation chased a
non-problem. `WARN Fake pacer fell behind: jumped N period(s) forward` is a benign,
long-standing Monado + NVIDIA direct-mode artifact, present in healthy logs since 2026-08-15
at thousands per session while the compositor measures a correct 90 fps. The commit that
rate-limited the WARN (monado `63b71c926`) only reduced log volume; a live retest still showed
~90 phase-jump periods per second.

## 5. What held up


- **NVIDIA patch 0004 works at runtime** — measured, not inferred (§2).
- **HID activation is correct.** `scripts/panel.py activate` (report `0x50` SET then GET, then
  `{0x04,0x01}`) is identical to what Oasis sends, verified against a same-night USBPcap of a
  cold panel bring-up (companion `03f0:0580`). Beyond that sequence Windows sends the companion only `{0x04,0x00}` (screen off)
  and the standard `SET_IDLE`. No persistence, duty-cycle or brightness command exists to be
  missing. This closes the cold bring-up case the same way `docs/13` closed the live 60↔90
  transition: there is no panel command, at either moment, that Monado does not already send.
- **USB is clean from both sides.** 5/5 at correct speeds on the CPU-fed Matisse controller
  (PCI `07:00.3`), zero kernel errors. Windows *also* refuses to provision the headset on the
  A520 chipset controller (PCI `02:00.0`) — which confirms the `docs/22` CPU-vs-chipset rule
  from the other side rather than indicating a new fault.

## 6. Instrument hardening applied

The generalisable lesson is that a diagnostic must not be able to produce the symptom it is
used to diagnose, and if it can, the *safe* mode must be the default. Applied:

- `verify-bpc.sh`, `hmd-test.sh` (the official post-patch check) and `collect-nv.sh` run
  `hmd-vk` with `HMD_VK_SOLID=1`; `hmd-modeset.c`, a second tool with the identical
  always-alternating design, got the equivalent `HMD_MODESET_SOLID`.
- `jack-in.sh` warns out loud when `XRT_COMPOSITOR_DESIRED_MODE` is unset and it silently
  defaults to mode 2 (4320x2160@**60**), which flickers by design.
- `panel-cam-capture.sh` pins the webcam's exposure/white balance (a camera hunting its own
  AE/AWB produces brightness jumps that `panel-cam-analyze.py` flags as panel events), and
  `panel-cam-analyze.py` emits the alternative explanation next to every flagged frame.

## 7. Still open

Nothing blocking. Loose threads:

- The Linux 4320x2160@**60** `DEVICE_STATUS` was not captured (only Windows@60 was); it would
  complete the table.
- The `0x03` DEBUG firmware-log channel (`docs/12` §6) was not examined in either 2026-09-07
  capture. `docs/09` records the Windows driver string
  `left duty %d, right duty %d, frame timing %d`, but the firmware-log listener was not run
  during either A/B. (Decoded in `docs/114` §1: camera/IMU boot log, no duty or backlight
  data; hypothesis retracted.)
- Neither real-content session has a headset-side capture tied to it (logs were overwritten);
  the brightness-gain A/B explains the symptom without it.

## References

- `scripts/hmd-vk.c` — the solid-pattern flag and its warning comment
- `docs/19-nvidia-bug-5923212-followup.md` — the first occurrence of this exact trap, commit `cc98bb0`
- `docs/12-g2-protocol.md` §5 — `DEVICE_STATUS` field map; pre-patch reference with byte 18 = `06`
- `docs/13-bug-6bpc.md` — byte 6 resolved as a session counter
- `docs/22-cable-connector-diagnosis.md` — CPU-fed vs chipset USB controller rule
- `~/vr/xrizer/src/compositor.rs` — `current_brightness_gain()`, the colour-scale layer
