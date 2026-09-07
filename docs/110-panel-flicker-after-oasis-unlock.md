# 110 — Panel flicker after the Oasis re-Unlock: what it is NOT

**Status: unresolved.** This document records an elimination pass, not a fix. Its value is the
list of hypotheses that are now closed with hard evidence, so the next session does not re-run
them.

## The symptom

Reported by the wearer on 2026-09-07, after a day in which the headset had been working normally
on Linux:

- Rapid flicker, **most visible in bright areas**. Later described more precisely as white
  flicker with **alternating colours** — the signature of temporal dithering.
- Frame delivery is **not** affected: 90 fps confirmed both by the presenter's own counter and by
  the wearer.
- Appears in **every** application tried: the `hello_xr` video player, Aircar under Proton, and —
  decisively — `hmd-vk`, which presents straight to the leased DRM connector through Vulkan with
  no Monado, no Steam, no Proton and no compositor of ours in the path.

An earlier report the same night of "it feels like 60 Hz" turned out to be the wearer describing
the *character* of this same flicker ("parecido a 60hz de refresh"), not a frame-rate claim. A
substantial amount of work that night chased frame pacing on the strength of that misreading; see
docs/109 and the "what this cost" note at the end.

## What changed between "working" and "broken"

Per the operator, in order: the cable was reconnected → Windows was booted on that machine → the
headset did not come up → **Oasis had auto-updated** → Oasis was reopened and the headset was
**re-Unlocked in the same slot** → back to Linux → flicker. Separately, an HDMI monitor was off
during part of the failing period and switched on partway through the investigation.

## Ruled out, with the evidence

| Hypothesis | How it was killed |
|---|---|
| Any of our software (Monado, the presence stack, the compositor pacer) | The flicker reproduces under `hmd-vk` — pure Vulkan on the leased connector. Nothing of ours is in that path. |
| GPU memory bandwidth / power state | The GPU was found in P8 at **405 MHz** memory (of 7001) while presenting 4320x2160@90 — a genuinely alarming find, and a plausible-looking cause. Locking memory to 6801 MHz (`nvidia-smi -lmc 7001`, confirmed P2 / 6801 MHz / 48 W) changed **nothing**. |
| Refresh rate | Flickers identically at 4320x2160@**60** (mode 2) as at @90. |
| Pixel clock / link bandwidth | Flickers identically across all three modes: 2880x1440@90 (**428 MHz**), 4320x2160@60 (**709 MHz**), 4320x2160@90 (**905 MHz**). Halving the pixel clock does not touch it. |
| Volatile headset state | A **full power cycle** of the headset (19 V removed at the breakout for ~30 s, confirmed by USB re-enumeration to 5/5) did not change it. |
| The headset's EDID | Byte-identical (`md5 1b4510cd…`) to four saved references including `nv-report-20260805-014230/hmd.edid` and the copy published to the NVIDIA forum. Oasis did **not** rewrite the display descriptor. |
| The NVIDIA patch stack | All four patches applied cleanly in the DKMS rebuild of 2026-09-03 05:38, confirmed in `/var/lib/dkms/nvidia/595.71.05/6.12.107+deb13-amd64/x86_64/log/make.log` — including `0004-nvkms-do-not-clamp-to-6bpc…` ("Hunk #1 succeeded at 3453"). Patch 0003's string is present in the built `nvidia-modeset.ko`. `dpkg -V` over ~70 NVIDIA packages shows no missing files; the only drift is the deliberately edited `dkms.conf`. |
| Driver / kernel regression | Unchanged since 2026-09-03, and the same build demonstrably worked earlier the same day. |
| USB link | 5/5 devices, correct negotiated speeds (2× 5000 Mbps, 2× 480, companion at 12), zero USB errors in the kernel log over three hours. |
| DP link failure | `modetest` reports `link-status: Good`, `non-desktop: 1`, all three modes advertised. |

## What the remaining profile looks like

The flicker is **mode-independent, bandwidth-independent, refresh-independent, host-software-
independent, and survives a full headset power cycle.** Very little fits all five at once.

The EDID's byte 20 is `0x80` — digital input, **colour depth "undefined"**. That is precisely the
case patch 0004 exists to handle (without it NVIDIA clamps to 6 bpc, and 6 bpc is dithered
temporally, which is exactly what "white flicker with alternating colours" looks like). The patch
is present and applied, so either it is not effective at runtime, or something else re-clamps —
a possibility `verify-bpc.sh` itself warns about in as many words.

**The measurement that would settle it was not obtainable.** `panel-status.py` captured only the
two zero-filled activation messages; `decode-status.sh` (7 trials alternating modes) returned
**0 DEVICE_STATUS messages across every trial**, so byte 18 (bits per component, as reported by
the headset itself) is still unknown. Getting that byte is the single highest-value next step on
the Linux side. `nvidia-settings` cannot substitute: it resolves no display targets here, because
the HMD is a non-desktop connector held by a DRM lease and outside X's control.

## Leading hypothesis by elimination

**Persistent, non-volatile state written into the headset by the new Oasis version's Unlock.**
It is the only candidate left that is simultaneously host-independent, mode-independent and
immune to a power cycle. It is not proven — it is what survives.

## Next step

Boot Windows and look. This is now the decisive experiment, and it cuts both ways:

- **Flicker present in Windows too** → the headset itself changed. Oasis is then both the cause
  and the only tool that can inspect or revert it.
- **Windows clean** → something host-side on Linux that this pass did not find, and Windows
  becomes a working reference to diff against.

The operator offered this early in the session and it was deferred in favour of exhausting the
cheaper Linux-side tests first. Those are now exhausted.

## What this cost, recorded deliberately

Roughly four hours went into frame-pacing work (docs/109, monado `63b71c926`) that started from
misreading "parecido a 60hz de refresh" as a frame-rate report. Two things would have caught it
much earlier: asking what the flicker actually *looked like* before theorising, and running
`hmd-vk` — the no-Monado control that immediately localises a fault above or below our own
stack — as the *first* test rather than the seventh. Note also that the "Fake pacer fell behind"
storm that anchored that work is a **pre-existing artefact**, present in logs since 2026-08-15 and
described in docs/96 as appearing identically in healthy sessions.
