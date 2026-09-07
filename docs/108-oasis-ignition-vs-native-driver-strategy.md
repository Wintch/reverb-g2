# 108 — Oasis/Ignition vs. the native Monado WMR driver: a strategy comparison

**Date:** 2026-09-07. **Status:** not a decision document — the user explicitly deferred this
question on 2026-09-06 in favor of finishing the presence-detection debounce work, and asked for
this comparison to be prepared in parallel so it's ready to revisit "in a few days." Nothing here
changes today's operational setup (`jack-in-wayland.sh`, Monado `lab-full`, the presence stack
landed 2026-09-06/07) — this is groundwork for a decision, not the decision itself.

## The two paths

**Path A — Oasis + Ignition.** Run Microsoft's real Windows WMR driver (mbucchia's "Oasis") inside
a Wine-hosted bridge process (Bnuuy Solutions' "Ignition" framework, MIT licensed), with
Supremium's Wine USB bring-up making the WMR hardware visible to it. Announced for Linux
2026-09-06 (see `reference_wine_wrapped_windows_vr_drivers.md` for full sourcing). We have not
installed or run this — everything below is from the primary sources (official Steam post,
Ignition/PSVR2Toolkit repos and wiki), not hands-on testing.

**Path B — the native Monado WMR driver.** Everything this lab has built directly in Monado's own
`wmr` driver (`~/vr/monado`, branch `lab-full`) plus the surrounding operational layer in this repo
(`~/Documents/reverb-g2`): DRM-lease Wayland launch (`jack-in-wayland.sh`), the presence-detection
stack landed and live-validated 2026-09-06/07, thermal/perf telemetry, the web dashboard, GPU
power-cap tuning, passthrough v0, and a sensor-capability audit. This is code we read, patch, and
fully control.

## 1. What each gives TODAY

**Path A, today:**
- A real, working Windows WMR driver stack, running under Wine — inherits whatever maturity Oasis
  has on Windows itself (Room View passthrough, cross-eye distortion correction, multi-headset
  support incl. Odyssey+/G1/G2).
- Requires: Steam's Oasis app on the **preview** branch, SteamVR on **beta**, manual udev rule
  install, and (per the PSVR2Toolkit wiki it inherits setup from) **native Steam, not Flatpak**,
  Proton Experimental as the mandatory host for Ignition's own bridge process.
- Explicitly documented as **not working on Wayland** ("I had no success with Wayland, therefore I
  do not recommend using Oasis with Wayland" — the developer's own words). All of the developer's
  confirmed-working configs are X11 (including one that is our exact headset: Ubuntu 24.04 + X11 +
  AMD + HP Reverb G2).
- G2/Odyssey+/G1 controllers' **built-in Bluetooth radio does not work on Linux today** — a PC/USB
  external Bluetooth receiver is mandatory. This is a known, explicitly "being looked into" gap,
  not a fundamental limitation, but it's real today.
- No G2 Omnicept eye tracking (not on the roadmap — would need the full Omnicept Runtime under
  Proton too). No Windows-key-as-click.
- **Zero presence detection, telemetry, thermal safety, dashboard, or booth/kiosk tooling** — none
  of that is Oasis's or Ignition's problem domain. It is purely a driver bridge; everything this
  lab built around Monado for unattended booth operation would need to be rebuilt from scratch on
  top of it, or run in parallel some other way.

**Path B, today:**
- Native 90Hz DRM-lease Wayland operation, no X11, no Wine, no Proton dependency for the driver
  itself — this *is* what iashur's whole production pipeline is built on.
- A presence-detection stack that, as of tonight's live wearer test, correctly commits WORN via
  IMU motion alone within ~250ms even when the proximity sensor is silent/stale for 30+ seconds —
  the exact failure mode that made "always on" or "never on" bugs possible in the first place. Live
  DRM-lease-death regression (`754beed30`) found and fixed same night (`af290d0e3`).
- Thermal telemetry (confirmed HMD stays under 40°C in current room conditions), GPU power-cap
  tuning per title (Aircar 130W/90fps vs. Dalí needing 160-210W), a live web dashboard, USB
  companion auto-reconnect (patch `0090`), frame-pacing fix (`0092`), a v0 monocular passthrough.
- **Known, unfixed gaps**: controller 6DoF constellation tracking is fragile under bright/mixed
  lighting (~1.4% pose-solve success measured in one real test — blob-swamping from ambient
  light drowns real LED blobs); controller LED intensity is measurably dimmer than Windows (root
  cause identified — Monado never sends the `0x03` LED-intensity HID packet Windows does — not yet
  fixed); no native Linux Bluetooth *pairing* script for the controllers yet — initial pairing
  still leans on a Windows/Oasis USB capture to reverse-engineer the handshake; the panel-blank/
  DRM-lease interaction just cost a full night to find and is currently only worked around
  (`WMR_USER_PRESENCE_BLANK_PANEL` defaults OFF) rather than truly fixed at the compositor level.

**Honest read**: Path A is more feature-complete *as a driver* (it's literally the real Windows
driver). Path B is more complete *as a production system* (booth/kiosk operation, safety,
observability) and is the only one that runs on the lab's actual Wayland setup today without a
parallel X11 session.

## 2. Each path's realistic finished/mature ceiling

**Path A's ceiling** is bounded by two things outside this lab's control: (a) how fast Ignition and
Oasis's Linux port close their own gaps (Wayland support, built-in Bluetooth for G2), which is
entirely on Bnuuy Solutions/Supremium/mbucchia's schedule, and (b) how well a Wine-hosted Windows
driver can ever integrate with a Linux-native booth/kiosk operational layer — presence detection,
telemetry, thermal monitoring, and the dashboard would all need either (i) a full parallel
reimplementation reading whatever telemetry Oasis/SteamVR exposes, or (ii) staying dependent on
Monado/Path-B tooling running *alongside* it somehow, which is architecturally awkward (two
different runtimes fighting for the same DRM lease and USB devices). Even at full Wayland +
built-in-BT maturity, Path A does not obviously get easier to operate unattended in a booth than
Path B is today — it gets *feature-complete as a driver*, not *operationally complete as a kiosk*.

**Path B's ceiling** is bounded by this lab's own engineering time and Monado upstream review
cycles. The concrete remaining work is scoped and understood, not mysterious: fix the LED-intensity
gap (send `0x03` periodically, mirroring the already-decompiled Windows packet format — a
well-understood, medium-effort patch), improve constellation tracking's robustness to ambient light
(needs a real fix, not just tuning — the blob-swamping problem is structural), build a native
Bluetooth pairing script (currently blocked on finishing the capture-based reverse-engineering), and
properly fix the DRM-lease recovery gap at the compositor level (currently a kill-switch workaround,
not a fix — this is the one item here that is a genuine unknown-effort research problem, not just
unscoped engineering time). None of these require anyone else's roadmap to move.

## 3. Where each project is actually headed

Path A is someone else's fast-moving third-party project. Its Linux support is one day old as of
this writing, explicitly gated behind preview/beta branches, and its own author is the one flagging
the Wayland incompatibility and the Bluetooth gap — those aren't our findings, they're the
developer's own stated limitations on launch day. It will keep moving, likely quickly (Oasis on
Windows has shipped real updates roughly every 4-8 weeks since 2025-09), but its priorities are set
by its own maintainers, not by this lab's booth/demo needs.

Path B is this lab's own code, moving at this lab's own pace, with a real (if slow) upstreaming
trajectory into Monado itself (`project_monado_upstreaming` — the retry-log MR already posted,
awaiting review). Every fix here compounds: the presence stack, the telemetry, and the dashboard are
already integrated with each other and with the actual demo-day pipeline. There's no external
dependency that could deprecate or obsolete this work except Monado's own upstream WMR driver
eventually absorbing it wholesale — which is the *goal*, not a risk.

## 4. Does our solution stay valuable if Oasis/Ignition matures?

**Yes, and the reason is that the two projects aren't actually solving the same problem.** Oasis/
Ignition is a *driver-completeness* play: get the real Windows driver logic running on Linux at
all. This lab's work is an *operational-completeness* play: run a specific headset unattended, in a
booth, all day, on a Wayland kiosk machine, with presence detection, thermal safety, and
observability — which is a lab-specific concern that no third-party driver project sets out to
solve, because it isn't the kind of thing a driver "solves." Concretely:

- **Genuinely redundant if Ignition matures**: the controller Bluetooth *pairing* reverse-engineering
  effort. If Ignition/Oasis ships a working built-in-BT path for G2 on Linux, that specific piece of
  unfinished Path-B work becomes moot — no reason to keep chasing it once someone else's driver does
  it natively. Constellation-tracking quality might also become less urgent to fix ourselves if
  Oasis's own (Windows-proven) tracking code ends up usable on Linux via Ignition — worth
  re-evaluating at that point, not assumed now.
- **Genuinely orthogonal/complementary, regardless of what Oasis does**: presence detection
  (XR_EXT_user_presence + the motion/proximity debounce stack), thermal telemetry, the GPU
  power-cap-per-title tuning, the dashboard, and the whole booth/kiosk unattended-operation layer.
  None of these are driver concerns — they're operational concerns *on top of* whichever driver is
  running, and they don't currently exist on Path A at all. Even in the best case where Ignition
  fully matures, this lab would still need to build an equivalent of this layer against it from
  scratch — the Wayland incompatibility just makes that harder, since the layer as built assumes a
  DRM-lease Wayland session.
- **The Wayland gap is the load-bearing fact right now**: as long as Oasis/Ignition doesn't run on
  Wayland, it isn't a drop-in alternative to today's pipeline at all — it would require a parallel
  X11 session, which is a real architecture change, not a swap. That alone means Path B stays the
  operative solution for the demo-day pipeline regardless of Path A's driver-level maturity, until
  and unless that specific gap closes.

## 5. What to actually watch for over the next few days

Concrete, checkable signals — not "wait and see":

1. **Does Ignition/Oasis ship Wayland support**, or does the developer's "no success with Wayland"
   note get updated/retracted. Check the Steam event post and `github.com/BnuuySolutions/Ignition`
   issues/commits periodically, not by re-testing ourselves — no evidence yet it's even attempted.
2. **Does the DRM-leasing wiki note turn out to be the real explanation.** The PSVR2Toolkit wiki
   says DRM leasing is required and iashur's compositor already does DRM leasing successfully for
   Monado — so "no Wayland" might be narrower than a blanket incompatibility (e.g. a GNOME/Mutter
   Wayland-specific issue rather than DRM leasing itself). This is a real, cheap thing to verify
   later (a throwaway X11-vs-Wayland test), not to assume either way.
3. **Does the G2 built-in-Bluetooth gap close on Linux** — the post already flags it as "being
   looked into," so this could land within days or weeks, not months.
4. **Does anyone else in the LVRA community report a live G2 + Ignition test result** (Matrix
   `#general-linux-vr-adventures`) — free signal, no cost to watch for.

None of these should trigger a context-switch away from finishing Path B's own scoped work (LED
intensity, constellation robustness, native BT pairing, the DRM-lease compositor-level fix) — they
should just be checked periodically and re-evaluated against this doc's section 4 reasoning if any
of them change.
