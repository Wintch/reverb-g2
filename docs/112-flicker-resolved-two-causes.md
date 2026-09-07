# 112 — Flicker resolved: two unrelated causes, neither of them the panel (2026-09-07)

Supersedes the conclusions of `docs/109`, `docs/110` and `docs/111`, which are corrected in
place with pointers here.

## Bottom line

There was never a Linux-side panel bug. Two separate causes produced one symptom, and each
one was mistaken for the other:

| Reported symptom | Actual cause |
|---|---|
| "flickers at 90 Hz, even under pure Vulkan" | `hmd-vk`'s **default test pattern**, which alternates colour every frame — a ~30 Hz strobe by construction. The instrument, not the panel. |
| "the bright areas flicker" in Aircar and the video player | The **xrizer brightness gain at 1.25×**, which pushes composited values between representable 8-bit levels and gets dithered temporally. |
| "flickers at 60 Hz" | Factory backlight behaviour at a non-native panel frequency. **Identical on Windows.** Not a defect. |

The headset is healthy, the NVIDIA patch stack works, the DP link is correct, and USB is fine.

## 1. The A/B that closed the panel question

Run with `HMD_VK_SOLID=1` — solid white, zero source variation, so any flicker seen is the
panel's. Wearer verdicts, same headset, same night:

| Mode | Linux | Windows |
|---|---|---|
| 4320x2160@**90** | **clean** — *"es la matrix, rocksteady"* | perfect |
| 4320x2160@**60** | flickers — *"parpadeo que se nota"* | pronounced flicker |

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

Earlier attempts the same night returned **zero messages across 7 trials** (`decode-status.sh`)
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

| gain | wearer verdict |
|---|---|
| 1.000 | **clean, no flicker** — *"a la par con Windows"* |
| 1.250 | flickers |
| 4.000 | blown out to white, flickers much more |
| 1.000 | clean again |

**Mechanism.** `~/vr/xrizer/src/compositor.rs` (`current_brightness_gain()`) attaches
`XR_KHR_composition_layer_color_scale_bias` to the projection layer, so Monado multiplies the
game's RGB *after* it renders and before scanout. The multiplied values land between
representable 8-bit levels and are dithered temporally — the driver alternates adjacent values
frame to frame. That reads exactly as the wearer's original description, *"veo colores que se
alternan"*, and it hits hardest in bright areas, which are the ones the multiplier drives
against the ceiling. At `gain == 1.0` the colour layer is not attached at all, so there is
nothing to dither.

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
brightness command exists (Windows included)"`; the gain is a workaround for that, not a
brightness control, and it has a real cost.

## 4. What this cost, and why the existing fix didn't prevent it

This is the **second time** `hmd-vk`'s default pattern produced a false flicker confirmation.
The first was 2026-08-06 — `docs/19`, commit `cc98bb0`, whose own title is *"90Hz flicker
RESOLVED — and two of our three prior confirmations were the test itself"*. The remedy adopted
then was the `HMD_VK_SOLID` environment variable, added to `hmd-vk.c` with an explicit comment
saying the default is *"NEVER for judging backlight flicker"*.

That remedy did not hold, and the reason is worth stating plainly:

> Before the hardening in §6 below, `grep -rn HMD_VK_SOLID scripts/` returned hits **only
> inside `hmd-vk.c` itself**. Not one wrapper that ran `hmd-vk` and then asked a human to
> look ever set the flag — not `verify-bpc.sh`, not `hmd-test.sh` (the *official*
> post-patch check, which `apply-bpc-patch.sh` tells operators to run), not
> `test-powermizer-90hz.sh`. (Running that grep today returns six files — §6 is why.)

The fix was real and was never adopted where it mattered. A warning comment inside a tool does
not protect the operator who runs a wrapper around that tool. **A safe default would have;** an
opt-in flag documented only at the point of definition would not, and did not.

Concrete cost: `docs/110` built a five-row elimination table and concluded the flicker was
*"mode-independent, bandwidth-independent, refresh-independent, host-software-independent"* —
two of those four words were wrong, both resting on the same invalid run. `docs/111` inherited
that premise and built a Windows-boot brief around *"persistent state written into the headset
by Oasis"*, a theory the Windows boot then disproved. And roughly four hours went into frame
pacing (`docs/109`, monado `63b71c926`) from misreading *"parecido a 60hz de refresh"* as a
frame-rate claim rather than a description of what a flicker looked like.

A separate overclaim from the same night, called out so the two are not conflated: `docs/109`
declared the fake-pacer phase-jump storm *"root cause found and fixed"*. A live retest with
that fix applied still showed ~90 phase-jump periods per second. It reduced WARN log volume, by
design of its own rate limiter; it did not change the behaviour. The WARN itself is benign and
long-standing — present in healthy logs since 2026-08-15, thousands per session at a measured,
correct 90 fps (`docs/96`, with the date and per-session counts in `docs/109`).

## 5. What held up

- **NVIDIA patch 0004 works at runtime** — measured, not inferred (§2).
- **HID activation is correct.** `scripts/panel.py activate` (report `0x50` SET then GET, then
  `{0x04,0x01}`) is identical to what Oasis sends, verified against a same-night USBPcap of a
  cold panel bring-up (`flicker.pcapng`, 699 MB, 267 s; companion `03f0:0580` at bus 2,
  address 5). Beyond that sequence Windows sends the companion only `{0x04,0x00}` (screen off)
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

| File | Change |
|---|---|
| `scripts/verify-bpc.sh` | run `hmd-vk` with `HMD_VK_SOLID=1` — it asks for a physical verdict |
| `scripts/hmd-test.sh` | same; this is the official post-patch check |
| `scripts/test-powermizer-90hz.sh` | same, plus say which pattern is in use where the operator is asked to trust their eyes |
| `scripts/collect-nv.sh` | same (automated consumer, but the same missing default) |
| `scripts/hmd-modeset.c` | a second, independently written tool with the **identical** always-alternating design and no escape hatch at all — `HMD_MODESET_SOLID` ported over |
| `scripts/jack-in.sh` | warn out loud when `XRT_COMPOSITOR_DESIRED_MODE` is unset and it silently defaults to mode 2 (4320x2160@**60**), which flickers by design |
| `scripts/panel-cam-capture.sh` | pin the webcam's exposure/white balance — a camera hunting its own AE/AWB produces brightness jumps that `panel-cam-analyze.py` flags as panel events |
| `scripts/panel-cam-analyze.py` | emit the alternative explanation next to every flagged frame, not only in the docstring |

## 7. Still open

Nothing blocking. Two loose threads:

- The Linux 4320x2160@**60** `DEVICE_STATUS` was not captured (only Windows@60 was). Not needed
  for the conclusion, but it would complete the table.
- **The `0x03` DEBUG firmware-log channel (`docs/12` §6) was not examined in either
  2026-09-07 capture.** `docs/09` records the Windows driver string
  `left duty %d, right duty %d, frame timing %d` — exactly the kind of data this
  investigation cared about — but nobody ran the firmware-log listener during either A/B.
  Nothing points at it being relevant; nothing rules it out either. The captures live on an
  external SSD that is currently disconnected.
- Neither real-content session from 2026-09-06/07 has a headset-side capture tied to it —
  `jack-in-wayland.sh` rotates its log only one level deep, and both wearer sessions' logs were
  overwritten by the headless pacer runs that followed. The brightness-gain A/B explains the
  symptom without it, so this is completeness, not doubt.

## References

- `scripts/hmd-vk.c` — the solid-pattern flag and its warning comment
- `docs/19-nvidia-bug-5923212-followup.md` — the first occurrence of this exact trap, commit `cc98bb0`
- `docs/12-g2-protocol.md` §5 — `DEVICE_STATUS` field map; pre-patch reference with byte 18 = `06`
- `docs/13-bug-6bpc.md` — byte 6 resolved as a session counter
- `docs/22` — CPU-fed vs chipset USB controller rule
- `docs/96` — the "Fake pacer fell behind" WARN as a normal direct-mode artifact
- `~/vr/xrizer/src/compositor.rs` — `current_brightness_gain()`, the colour-scale layer
