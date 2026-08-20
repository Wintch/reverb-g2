# 22 — The G2's link anatomy, and how to diagnose it piece by piece

**Born 2026-08-07, ~00:20, after a full night (T030-T041 in `docs/pruebas.jsonl`) in which
the headset appeared to die progressively — DP first, then USB2 — across two machines and
two OSes, got a firm "the cable is dead, buy a rev2A" verdict... and then came back 100%
from reseating one connector.** Everything below was measured that night, not read
somewhere. The final resolution is at the end; the anatomy comes first because it's what
makes the diagnosis mechanical instead of guesswork.

This document has grown, session by session, into more measured detail about this specific
unit's failure modes than the authors have found gathered anywhere else for a G2 — which is
exactly why it stays this long and this specific instead of getting summarized down over
time. If you only need to match today's symptom to a known cause and fix, start with the
index below; the full sections underneath are where the evidence and the reasoning live.

## Known fault signatures — quick index

| Symptom | Root cause | Fix | Section |
|---|---|---|---|
| DP dead (no logo), USB still 5/5 | Visor-end connector marginal contact | Reseat visor-end connector | "The failure timeline, and the three wrong verdicts" |
| USB2 branch dead, kernel says `error -71` / "Maybe the USB cable is bad?" | Same visor-end marginal contact, different pin subset | Reseat visor-end connector | "The measured anatomy", point 3 |
| Companion enumerates but HID reads return `-1`, device number climbs fast | Marginal contact knocked loose specifically by panel activation's power transition | Reseat; minimize activation/panel-power cycling until the rev2A cable is in | "Recurrence, same night (T044, T043)" |
| No logo at cold boot, but USB is a healthy 5/5 and nothing was touched | **Not a fault** — the G2 never raises DP hotplug at cold power-on on any OS; needs the WMR activation HID sequence first | Run `./scripts/panel.py activate` before concluding the panel is dead | "T046's verdict revised... (T047-T049)" |
| Image glued to the face, video/audio otherwise perfect | A USB hiccup killed Monado's `wmr_run_thread` (IMU reader); Monado never restarts it | Restart the session; confirm with `grep "Exiting reading thread"` | "The tracking freeze (T045)" |
| "Logo on, panel off" appearing **mid-session** after any physical reconnect | Monado's compositor is still holding a DRM lease invalidated by the reconnect — HID activation succeeds but nothing is scanned out | Full session restart (kill `monado-service` + fresh launch), not just `panel.py activate` | "Reseating mid-session (2026-08-10)" |
| Audio cutting in/out, worse the more concurrent load (video+audio > video alone > idle) | Same marginal visor contact; PipeWire recreates the ALSA sink on every USB2 cycle | Same as the marginal-contact fixes above; no audio-specific fix needed | "Load correlates with disconnect frequency... (T052-T057)" |
| `reqCmd 23` (`hololens_handle_debug`) and/or `non-desktop: 0` on the headset's RandR connector, correlating with heavy service-restart cycling | USB-C-to-USB-A adapter fault (validated single-session, 2026-08-11) — **a different physical part than the visor-end contact above** | Swap the USB-C-to-USB-A adapter, not a visor-end reseat | "Hardware change log for the reqCmd23/non-desktop:0 cluster" |
| Windows: SteamVR "Headset not detected (**108**)", but the headset's audio device and companion do show up in Windows | Same seat lottery seen from Windows: the SuperSpeed branch never enumerated, and WMR/Oasis requires it | Same ladder as the row below — aim for all 5 devices in Device Manager, not "the headset appears" | `docs/31`, "The error index" |
| Windows: SteamVR "unexpected problem (**422**)", intermittent, unaffected by reseating | Not a cable fault at all — SteamVR started and the driver failed under it (safe-mode-disabled add-on, stale unlock after a GPU/Windows change, beta branch) | Re-enable the `oasis` add-on, re-run the unlock, leave the SteamVR beta | `docs/31`, "The error index" |
| Exactly ONE of the two USB branches enumerates per seating (SS-only or USB2-only, never both), stable at rest, changes only on reseat; "headset not detected" on Windows too | Marginal seat of the C-plug/adapter engaging one pin subgroup per insertion — all conductor groups healthy (T171, 2026-08-13) | Rear (CPU) USB3 port, firm and straight; then **rotate the C plug 180° inside the adapter without changing port**; then the other rear port; then visor-end. Success = 5/5 | "The seat lottery (T171)" |
| Tracking cameras (HoloLens Sensors) enumerate but at 480M under the USB2 hub instead of 5000M under the USB3 hub; Monado logs no error, but the debug GUI's camera panels are solid pink and `img_xfer_cb` logs "Invalid frame magic" for every frame | Same visor-end marginal contact, this time degrading the SuperSpeed branch enough to corrupt (not drop) the camera transfer's own header bytes — Monado never sees an error because the corruption happens below its own checks | Reseat visor-end connector; verify with `lsusb -t` (HoloLens Sensors back to 5000M) before trusting any tracking data | "The silent 100% camera-frame-loss signature (2026-08-15)" |
| `wmr_read_config_part` fails ("Failed to issue command 0b..."), HMD device creation fails outright, appearing AFTER camera corruption was already seen in the same session and after repeated relaunches | Same marginal contact, escalated further by repeated panel-activation power cycling while chasing the camera issue — **do not keep retrying** | STOP relaunching; reseat visor-end connector before any further attempt | "Retry escalates the fault — a stop condition, not just another symptom (2026-08-15)" |

## The measured anatomy

```
 [PC GPU] ──DP──┐                                ┌──────────── VISOR ────────────┐
 [PC USB] ─[C→A]┤  breakout box  ═══ cable ═══   │ visor-end connector (!)       │
 [brick 18.5 V] ───┘  (LED, DP        (all groups   │  ├─ USB3 hub 04b4:6504        │
                    repeater)       in one        │  │   └─ HoloLens 045e:0659   │
                                    jacket)       │  ├─ USB2 hub 04b4:6506       │
                                                  │  │   ├─ companion 03f0:0580  │
                                                  │  │   └─ audio 0bda:4c15      │
                                                  │  └─ ANX7530 bridge → panels  │
                                                  └───────────────────────────────┘
```

> **`[C→A]` is the USB-C-to-USB-A adapter, and it was missing from this diagram until
> 2026-08-12** — even after it earned its own row in the fault-signature index above. The
> headset's USB leg does not reach the PC directly, and a passive adapter carrying every USB
> conductor is a contact point like any other: it belongs in the reseat ladder. Exact parts
> and the before/after boundary are in "Hardware change log for the reqCmd23/non-desktop:0
> cluster" below (HP `L56522-002` → Nisuta `NSADU30UC`).

Facts established by direct measurement (each one earned the hard way that night):

1. **The visor-end connector is detachable** — behind the magnetic face gasket, a long
   proprietary (OCuLink-style) plug. It carries **every** conductor group between cable
   and visor: DP lanes + AUX/HPD, USB3 SuperSpeed pairs, the USB2 D+/D- pair, and the
   power rails. One marginal contact there can therefore take out *any subset* of
   functions while the rest keep working — which is exactly what makes its failures look
   like several independent faults.
2. **Both Cypress hubs live inside the visor, not in the breakout box.** With the
   visor-end connector unplugged and the cable still in the PC, the host enumerates
   *nothing* (measured: zero devices). The cable presents no USB electronics of its own.
3. **The conductor groups fail independently.** Measured sequence that night: DP + panel
   power dead while USB was a perfect 5/5 (T030-T033); hours later the USB2 pair dead
   (`error -71`, kernel printing `Cannot enable. Maybe the USB cable is bad?`) while
   SuperSpeed still enumerated (T039-T040). Four groups, four separate contact sets.
4. **Who hangs off what**: sensors (`045e:0659`) are on the USB3 hub; the companion
   (`03f0:0580`, HID control + activation) and audio (`0bda:4c15`) are on the USB2 hub.
   Corollary already in `docs/06`: sensors present + companion absent = USB2 branch down
   = no activation possible = panel will never light = DP will never hotplug. **But the
   reverse implication is NOT valid**: that night the companion was healthy and the
   activation delivered, and the panel still stayed dark — the corollary explains one
   failure direction, not all of them.
5. **The panel, backlight and the ANX7530 bridge power from the 18.5 V brick rail; the USB
   electronics can live on USB bus power alone.** That's why "everything USB works,
   display stone dead" is a *coherent single-fault picture* (18.5 V path or the contacts
   carrying it), not evidence of two failures.
6. **DP hotplug (HPD) is generated by the powered bridge.** No 18.5 V → no HPD → the
   connector reads `disconnected` with `0` EDID bytes at the kernel level, and no
   compositor can lease what never electrically exists. A dead `status` therefore does
   NOT distinguish "DP lanes cut" from "bridge unpowered".
7. **The HP logo is generated by the visor itself** when the panel is powered + activated
   but has no video signal. It needs the 18.5 V rail and a delivered HID activation — **it
   does not need DP at all.** The logo is thus a pure power+HID diagnostic, orthogonal to
   the DP lanes.
8. **The breakout-box LED tracks USB 5V presence, not the brick.** Measured: unplug USB →
   LED off; USB back → LED on, panel still dead. A lit LED says *nothing* about the 18.5 V
   rail. Don't let it reassure you.
9. **The panel auto-powers-off ~3s after activation if no video arrives** (already known
   from `wake_panel()`; reconfirmed). A logo you don't see might have come and gone —
   have eyes on the visor *while* the activation runs.
10. **The DP connector name changes per machine**: the headset is `DP-1` on the 5600
    machine, `DP-3` on the x3600. Never hardcode it — scan `/sys/class/drm/card*-DP-*`.

## The diagnostic ladder — one piece per step, cheapest first

Each step isolates exactly one link of the chain. Run them in order; the first one that
fails names the broken piece.

```bash
# 1. USB census — which branches are alive?
lsusb | grep -E "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15"
#    5/5 ................ both USB branches + contacts fine, go to 3
#    only 6504 + 0659 ... USB2 pair/contact down (companion+audio missing) -> step 2, then reseat ladder
#    nothing ............ visor connector unplugged/fully dead, or cable not in the PC

# 2. Kernel's own opinion on the USB2 branch
journalctl -k --since "-5 min" | grep -iE "usb|hub" | tail
#    'error -71' + 'Cannot enable. Maybe the USB cable is bad?' = marginal contact signature

# 3. Power + activation, WITHOUT Monado (eyes on the visor NOW — 3s window):
./scripts/panel.py activate          # + ./scripts/panel-status.py in parallel for the sink side
#    HP logo lights ..... 18.5 V rail + companion + display board ALL healthy
#    no logo ............ 18.5 V path or display board; USB being fine is irrelevant here

# 4. Did the powered bridge raise hotplug?
for d in /sys/class/drm/card*-DP-*; do echo "$d: $(cat $d/status) $(wc -c < $d/edid)"; done
#    connected + 384 bytes = DP lanes + AUX + bridge fine. Panel's full EDID is 384 bytes.

# 5. Only now bring up the stack (GNOME Wayland): ./jack-in-wayland.sh 1
```

Recovery ladder when a step fails, also cheapest first — **this order is now backed by a
controlled result**: (a) replug USB at the PC (T031: didn't fix that night's fault);
(b) different USB controller (T040: didn't either); (c) cut mains/brick power ~20s
(T030: didn't); (d) **reseat the visor-end connector** — *this* fixed everything at
once; (e) only if (d) fails repeatedly: replacement cable ("HP Reverb G2 cable rev 2A" /
"OCuLink to USB-C + DP"). Since (c) alone had already failed while (c)+(d) together
succeeded, the reseat is the proven fix, not the power cycle.

## The failure timeline, and the three wrong verdicts

| When | Event | Verdict at the time |
|---|---|---|
| 08-06 15:13 | T026-T029: 90Hz clean via hmd-vk | all good |
| 08-06 eve | `docs/20` desktop saga; heavy handling | — |
| 08-07 ~01:00 | DP dead, no logo, USB 5/5 (T030-T033) | ① "residual software state" |
| ~01:45 | Windows SSD, same box: logo yes, panel no (T034) | — |
| ~02:20 | x3600: no logo anywhere, USB2 branch dead -71 (T038-T040) | ② "the cable died, buy rev2A" |
| ~00:10* | visor reseat + mains cycle → USB 5/5 back | — |
| ~00:12* | `panel.py activate` → **logo lights** | — |
| ~00:13* | DP-3 `connected`, 384-byte EDID → lease → 4320x2160@90 | ③ **the visor-end connector** |
| ~00:15* | T041: 3-video playlist, real content, 90Hz, "nítido" | verified |

(*the x3600's clock; it sat behind the 5600's by ~2h that night.)

Why each wrong verdict looked right, for the next reader:

- ① died when the same SSD failed identically on the x3600 — no shared software left.
- ② was the community-classic story (G2 cables DID fail en masse, rev2A exists) and the
  kernel literally said "cable is bad". What it couldn't explain: the Windows logo blip
  (T034) — a truly dead cable doesn't resurrect for one host. That anomaly was the tell.
- ③ explains **everything** with one fault: a single connector carrying all groups, whose
  contacts dropped group by group as the night's heavy handling worked it looser, made
  intermittently (T034's logo), then came back wholesale on reseat. In hindsight it is
  probably also the true story behind `docs/06`'s 2026-08-04 saga ("this cable's signal
  margins are so tight that the outcome depends on the specific contact") — the port and
  USB-C orientation changes of that day likely mattered by *mechanically disturbing the
  same connector*, not because of the ports themselves.

**Meta-lesson, project rule material: when one anomaly refuses to fit an otherwise
convincing verdict (the Windows logo), that anomaly is the thread to pull — not a detail
to note and move past.** It was flagged as "complicates a clean dead-cable verdict" and
then steamrolled by accumulating evidence anyway. The reseat costs zero and was listed
first in the community's own fix list; it should have been tried before any verdict.

## What the night verified (silver linings, all physical, all logged)

- **The directory playlist works end to end** (T041, first interactive test ever): 3
  VR180 clips chained unattended, in name order, wraparound to 1/3 at the end, through
  the full mutter-lease + Monado + hello_xr stack. `scripts/playlist-session.sh` is the
  one-shot launcher.
- **Real video through the real player at 90Hz is clean** — "nítido", user-verified.
  T021's flicker does not reproduce post-bpc-fix; the last open 90Hz caveat is closed.
- **The x3600 is a validated second lab machine**: the lab SSD boots on it, the patched
  595.71.05 loads against its RTX 3060 Ti, GNOME Wayland offers the lease, headset on
  `DP-3`. Full pipeline proven end to end on it.
- NVDEC's 4096-px width ceiling reconfirmed there (4320-wide h264 → software decode,
  steady 60 fps, 0 starves — not a problem in practice).

## Recurrence, same night (T044, T043) — the reseat is a mitigation, not a repair

~40 minutes after the reseat (and right after a flawless 25-minute steady-state run,
T042), the USB2 branch dropped again on the screen-off/service-restart transition. Two
new data points for the ladder:

- **Soft vs. hard states**: this recurrence recovered with step (a) alone — a PC-end USB
  replug, instant clean re-enumeration, zero `-71` retries. The overnight death needed
  step (d). Same contact, different severity.
- **A third failure mode exists**: *enumerates but HID I/O fails* — `lsusb` shows the
  companion, yet every `wmr_hmd_activate_reverb` Send/Get returns -1, and the device
  number climbs by dozens per minute (violent re-enumeration flapping). Observed
  triggered by **panel activation attempts**: the power transition through the same
  marginal contact knocks the USB2 hub out — `docs/06`'s old "hub reset scales with
  panel load" mechanism, amplified by the degraded contact. So: check `lsusb` device
  NUMBERS across a few seconds, not just presence, before trusting the branch.

**Operational guidance until the replacement cable arrives**: steady-state sessions are
fine (25 min flawless); what kills the contact is **panel on/off cycling** — activation
spikes and screen-off re-enumerations. Minimize service restarts; batch content into one
session (the playlist exists for exactly this). The rev2A replacement cable is now a
**firm recommendation**, not a contingency. The 10-boot-cycle controller stress test
(T043) is deferred until the new cable is in.

Also nailed down by T043 while it lasted: **controller hot-add does not exist** —
controllers powered on against a running session never reach Monado (the second
controller vibration is only the headset firmware's BT-link ack; Monado only probes at
startup, exactly as `jack-in.sh`'s comment says). Power controllers on BEFORE starting
the service, always.

## The tracking freeze (T045) — a fourth symptom of the same cable, and how to spot it

During T041/T042 the user watched ~27 minutes of flawless video **with head tracking
dead** — image glued to the face — and only realized/reported it afterwards (the content
was front-facing VR180, easy to watch without turning). A reproduction attempt the same
night showed tracking fully healthy: `HELLO_XR_POSE_STATS=1` measured the documented
3DoF jitter floor at rest (mean 0.0003-0.0016°/frame, max 0.056° — byte-identical to the
historical measurement) and real movement when the head turns (mean up to 1.5°/frame,
peaks 2.9°, steady 90 fps). So the freeze was **session-specific, not a player or driver
regression**.

Best-supported hypothesis (direct proof destroyed, see below): a USB hiccup from the
degraded contact killed Monado's WMR reading thread (`wmr_run_thread`, the IMU packet
reader) mid-session, and **Monado never restarts it** — pose freezes at the last value
while compositor, video and panel continue perfectly. Same night, the HID channel showed
exactly that kind of intermittency (`screen_on` write returning -1 seconds after a
successful activation). Upstream improvement candidate, not filed: auto-restart of the
reader thread on EOF/error.

**Field guide**: image glued to the face + everything else fine → `grep "Exiting reading
thread" jack-in-wayland.log` while the session is still up. A session restart recovers
it. And the user's own observation deserves recording: mechanical cable movement during
long Windows play sessions never triggers anything — failures cluster at **power/state
transitions** (activation, screen-off), not under flexing. That fits both a
transition-sensitive marginal contact and the alternative "wedged cable/visor
electronics" reading (the visor is dual-powered — brick 18.5 V + USB 5V — so nothing short
of the visor-end disconnect removes all power from its chips; T030 cut only the brick,
T031 cut only USB, both failed; the visor reseat cuts everything at once and worked).
Discriminating test for the NEXT hard failure: unplug USB **and** brick together for
~20s *without* touching the visor connector — if that recovers it, it's wedged
electronics, not the contact, and there's a no-disassembly recovery procedure.

**Evidence-handling lesson, already fixed**: `jack-in-wayland.sh` used to truncate its
log on every start — the controller-cycle runs wiped the one log that could have proven
the T042 freeze mechanism. It now keeps one generation back (`jack-in-wayland.prev.log`).

## Minor open item spotted in the T041 log

On teardown-by-timeout mid-playlist, `hello_xr` emits Vulkan validation errors
(`vkFreeCommandBuffers ... is in use`, `vkDestroySemaphore ... in use by VkQueue`) —
in-flight command buffers freed during shutdown. Exit code was still 0 and nothing
user-visible; cosmetic for now, but it's a real ordering bug in the player's shutdown
path if anyone touches that code anyway.

## The power rail specifically, isolated from the USB2 branch (T046, 2026-08-07 ~03:30)

A session hours after the T041-T045 resolution found the panel completely dead again --
no logo, no DP hotplug on any of the system's three DP connectors -- while the USB2
branch (companion + audio) needed its usual reseat-to-recover dance (twice, both
successful). What's new: this is the first time the power path was isolated cleanly
enough to say it's a **separate fault from the USB2 data pins**, not just "the same
marginal contact, sometimes." Two reseats of the visor-end connector fixed USB 2/2 and
fixed power 0/2.

Elimination chain, each step confirmed before moving to the next:
1. **Brick**: has its own indicator LED, lit -- receiving wall power.
2. **Breakout-box barrel connector**: exercised directly by unplugging just the 18.5 V
   line and reconnecting it. Unexpected side effect worth remembering for next time:
   the *whole* USB tree (5/5 devices) dropped the instant the barrel was pulled --
   confirmed in the kernel log, five simultaneous `USB disconnect` lines at one
   timestamp -- even though nothing on the USB side was touched. Handling the
   breakout box at all disturbs this cable enough to affect branches you didn't mean
   to touch. Reconnecting the barrel brought USB straight back to a stable 5/5;
   the panel stayed dark throughout.
3. **GPU port**: moved the DP cable to a different physical port on the card. All
   three DP connectors (`DP-1`/`DP-2`/`DP-3`) read `disconnected` regardless of which
   one is occupied -- rules out a single bad GPU port.

With the brick, the breakout barrel, the USB branch and the GPU port all cleared, what's
left is inside the visor-end connector itself (a different pin subset than the USB data
pins that keep recovering) or a break further down the cable run. Not reseatable by the
procedure in the section above -- this pushes the rev2A replacement cable from "firm
recommendation" to "the next real step," and the untried, more invasive option is
opening the breakout box to inspect the internal 18.5 V wiring directly.

**Housekeeping fix from the same session**: `jack-in-wayland.sh` used to report "Socket
ready, launch an app" whenever the IPC socket existed, even if the compositor had
already failed to find a leasable connector -- the socket opens before the compositor
init, so a failed lease still left a live-but-broken `monado-service` process sitting
there (had to be killed by hand once). The script now requires the log to show a real
video mode taken, not just a live socket, before reporting success; on failure it kills
the stale service and exits 1 instead of pointing at a broken IPC endpoint.

## T046's "dead power rail" verdict revised -- it skipped step 3 of its own ladder (T047-T049, same day)

**The rev2A escalation above was premature.** Next session, on a completely cold Linux
boot with **zero reseat performed** -- USB was already 5/5 healthy on its own -- DP-1/2/3
were still `disconnected`, same dark-panel symptom as T046's end state. Step 3 of the
diagnostic ladder two sections up (`./scripts/panel.py activate`, "power + activation,
WITHOUT Monado") had never actually been re-run in T046 after its two successful USB
reseats -- the elimination chain there went brick -> barrel -> GPU port, skipping straight
to physical elimination. Running it here (T048) worked immediately: valid HID
identification data back (no `-1`s), user confirmed **the logo lit**, and `DP-1` went
straight to `connected` with the healthy 384-byte EDID. T049 then ran the full stack
(`jack-in-wayland.sh 1` + `play360.sh` on the playlist-test directory) end to end --
lease granted, `4320x2160@90.00` taken, all 3 clips chained cleanly, NVDEC used where
applicable, clean `SIGTERM` teardown -- user's words: **"si, todo perfecto."** No cable
or connector was touched at any point this session.

This matches independent evidence gathered the same morning on Windows (T047): the HP
logo **always starts dark at cold boot** there too, and only stays lit once SteamVR has
activated the headset once. Same behavior, both OSes, no reseat involved on either side
that morning -- which reframes T046's "separate dead power rail, needs the rev2A cable"
conclusion. Leading theory now: **the G2 never raises its own DP hotplug at cold
power-on, on any OS or driver; it always needs the WMR activation HID sequence first**,
and that's simply normal behavior, not a fault. T046 most likely caught Monado's own
in-flight activation attempt racing an unstable USB2 branch immediately after a reseat,
not a genuinely separate power-rail failure.

**What this does NOT undo**: the marginal-contact findings elsewhere in this document
still stand on their own evidence -- the USB2-branch dropouts (T039, T044) and the
tracking-thread freeze (T045) were never explained by "missing activation," only the
power-rail piece of T046 is in question. The rev2A cable recommendation is downgraded
from "the next real step" back to "keep it in mind if the USB2/tracking recurrence gets
worse" -- not bought yet, not urgently needed. **Practical takeaway: before ever
concluding "the panel is dead," always run `./scripts/panel.py activate` first and look
at the visor with your own eyes** -- do not skip step 3 of the ladder, even (especially)
right after a reseat that was chasing a different symptom.

## Load correlates with disconnect frequency, and audio shares the same marginal
## contact (T052-T057, same day)

Walk the downgrade right above back partway: a few hours later the USB2 branch was
caught mid-storm -- cycling on its own every ~6-12s with **nothing running at all** (no
service, no test loop). 66 reconnects of `usb 3-2` (hub `04b4:6506` + audio `0bda:4c15` +
companion `03f0:0580`) logged in one 60-minute `journalctl -k` window, denser than any
single isolated event characterized earlier in this document. The panel.py-activate fix
above is still real for the cold-boot-dead-panel case, but this storm proves the
underlying contact is not calm -- **the rev2A cable should be treated as still-open, not
retired.**

While diagnosing that storm, real audio playback was tested end-to-end for the first
time in this project (never validated before). Two threads worth keeping:

1. **A false lead, corrected fast**: an initial "it's the off-ear speaker position"
   theory was wrong and retracted -- the G2 has no proximity sensor near the speakers,
   only one near the nose bridge (`WMR_CONTROL_MSG_IPD_VALUE`) for wear detection,
   unrelated to audio. The real mechanism is the storm above: PipeWire creates/destroys
   the ALSA sink on every USB2 cycle, so a stream that starts or is running mid-cycle can
   land in a disconnected window and simply produce nothing, with no error anywhere.
   `./scripts/hmd-audio.sh {mute|unmute|status|set <pct>}` (resolves the sink by name via
   `wpctl`, survives the renumbering) is now the fast way to control it.
2. **A crude load-correlation experiment**, one 60s `journalctl`-counted window per
   condition (small sample, not rigorous, but consistent and monotonic): idle = 1
   disconnect, a standalone audio tone = 0, a Monado video session alone = 5, video +
   simultaneous audio together = 8. More concurrent activity on the shared HID/USB2
   channel tracks with more disconnects -- consistent with the `docs/06` "hub reset
   scales with panel/HID load" mechanism already on record. Note: `hello_xr`'s video path
   has no audio decode implemented yet (`docs/02`), so "video+audio" here means a
   Monado/OpenXR session running concurrently with an unrelated desktop audio stream, not
   audio muxed from the video file itself.

**Independent confirmation from Windows, from the user, same night**: on this exact
unit, display and audio failures have historically been anti-correlated there too --
when the panel wasn't working, audio was fine, and when the panel was active, audio
would cut out. That is the same "one shared marginal contact, load/contention dependent"
picture as everything measured on Linux today, on a completely different OS and driver
stack -- strong evidence this is a physical-layer property of this specific unit's cable
or connector, not a Linux/Monado-specific bug.

**A concrete, reproducible companion-channel failure, caught with `WMR_LOG=debug`**:
during this same storm, Monado's own `control_read_packets()` (`wmr_hmd.c`) was
continuously logging `Error reading from companion (HMD control) device. Call to
os_hid_read returned -1` -- every poll cycle, for a sustained ~35s window, including
through a user-performed proximity-sensor cover/uncover gesture that should have
produced a visible transition. This means the companion's **control** endpoint
specifically (separate from its being enumerated at all -- `lsusb` still showed 5/5
throughout) was unreadable start to finish. Proximity/IPD sensor status is therefore
**untested as working**, not confirmed broken by design -- it simply couldn't be
reached this session due to the live degradation. Worth a clean retry once/if the branch
is calm (check with a 60s idle `journalctl -k` count first, per the experiment above --
low single digits is the current "calm" baseline on this unit, zero is not realistic to
expect).

## Reseating mid-session (2026-08-10) -- `panel.py activate` alone isn't enough once Monado already has a lease

**Symptom**: a real VR session already running fine (Aircar, real 6DoF), then "logo on,
panel off" appeared mid-session (not at cold boot -- the case every earlier section of
this doc covers). A reconnect at the **PC-side USB connector specifically** (confirmed
after the fact -- initially assumed to be the usual visor-end reseat, corrected once the
user clarified it wasn't) caused a real DP disconnect/reconnect (confirmed in
`/sys/class/drm/card0-DP-2/status`, back to `connected` ~8s after a `panel.py activate`
run right afterward) -- but the backlight **stayed dark** and Aircar had silently fallen
back to a flat 2D window. `panel.py activate` itself kept reporting clean success
(`exit 0, full activation + screen on`) both before and after -- the HID activation
genuinely works, it just isn't the layer that's broken here.

**Open anomaly, not resolved, flagged per this doc's own meta-lesson above**: per "The
measured anatomy" section, DP and USB take *separate* physical paths from the PC into
the breakout box, only combining at the visor-end connector -- a pure PC-side USB
reconnect shouldn't, on that diagram, touch DP's state at all. It did anyway. Couldn't be
isolated cleanly that same session (a known, unrelated USB2 storm -- companion+audio
cycling every ~12s, the T052-T053 pattern -- was running concurrently and muddies the
kernel log). Worth a clean repeat sometime with the storm calm and DP status monitored
live, specifically to find out whether a plain PC-end USB reconnect is really enough on
its own, or whether the breakout box's DP and USB lines are physically closer/coupled
than the anatomy diagram currently shows.

**Root cause**: `panel.py`'s HID activation and Monado's DRM lease are two entirely
separate channels. The `monado-service` process that was already running *before* the
reseat had already taken a lease on the old DP-2 connector instance -- the physical
disconnect/reconnect invalidated that lease, but the already-running compositor has no
way to notice and never re-acquires a fresh one. Re-running `panel.py activate` fixes
the physical panel/backlight power state, but does nothing for a compositor that's still
holding a dead lease handle -- hence logo on, DP shows `connected` again, EDID
fingerprint still matches, and yet nothing is actually being scanned out to the panel.

**Fix, and the sequence that matters** (order-dependent -- skipping step 4 is exactly
what leaves the backlight dark even though every earlier step reports success):

1. Reseat/reconnect the cable physically (visor end is the historically-proven fix
   elsewhere in this doc; a PC-end USB reconnect worked once too, see the anomaly note
   above -- not yet established as reliably equivalent).
2. Wait for `/sys/class/drm/card0-DP-2/status` (or whichever connector is the headset)
   to read `connected` again -- can take a few seconds, don't assume instant.
3. `./scripts/panel.py activate` -- the HID layer, powers the panel back on.
4. **Kill the old session** -- `monado-service`, Steam, and the game process, plus
   `rm -f /run/user/1000/monado_comp_ipc` -- this is the step that's easy to skip
   because everything up to here already looks successful.
5. `./scripts/jack-in-wayland.sh` from scratch, against the now-healthy DP link, to get
   a genuinely fresh DRM lease.

**General lesson**: any physical hotplug event (reseat, unplug/replug, cable wiggle)
that happens *while Monado is already running* needs a full Monado restart, not just a
panel re-activation -- the two failure classes ("panel never got the HID command" vs.
"compositor's lease is stale") look identical from the outside (logo on, panel dark) but
need different fixes. Don't assume `panel.py activate` alone settles a backlight-dark
report without first checking whether a session was already active when the physical
event happened.

## Connector doesn't enumerate at all vs. reports disconnected -- and a `kill -9` kernel WARN found on the everyday system (2026-08-11)

**Machine**: the everyday system (`brunduk`, X11+KDE, driver 550.163.01, unpatched --
separate box from `iashur`/the lab elsewhere in this doc). Hit while trying to bring the
stack up for a 6DoF constellation-tracking re-verification session, using that machine's
own local `jack-in.sh` copy (not `jack-in-wayland.sh`).

**New diagnostic technique, extends anatomy point 10 above.** Point 10 already says the
DP connector name changes per machine and to scan `/sys/class/drm/card*-DP-*` instead of
hardcoding it. What wasn't established yet: **a connector that reports `disconnected` is
not the same signal as a connector that doesn't exist at all.** On this machine, with the
visor-end cable not actually linked, the kernel enumerates exactly 4 connectors under
`/sys/class/drm/card0-*` -- `DP-1`, `DP-2`, `HDMI-A-1`, `HDMI-A-2`, matching the 3 desktop
monitors plus one spare. No 5th connector shows up for the headset at all; it isn't
`disconnected`, it's simply absent. Meanwhile NVKMS/`xrandr`'s own internal `DP-0` slot
(the naming mismatch documented elsewhere in this repo's history) still nominally exists
in that state and reports `disconnected` regardless -- indistinguishable, from that layer
alone, from a real but transient link-training failure. Counting real DRM connectors
against a known desktop-only baseline is a free, pre-service check that tells the two
apart. Also confirmed while investigating this: **NVIDIA's driver does not expose a
`non-desktop` sysfs attribute per connector on this setup** (checked directly, the file
doesn't exist under `/sys/class/drm/card0-*/`) -- querying that property, if ever needed
here, would require going through libdrm's connector-properties ioctl, not a sysfs read.

**Real kernel bug found, worth checking for on the lab side too.** Two clean attempts
(`jack-in.sh`'s `wake_panel()`, which starts the service once, waits for `DP-0` to read
`connected`, then `kill -9`s it) both failed identically with
`vkAcquireXlibDisplayEXT: VK_ERROR_UNKNOWN` -- consistent with the connector never having
been there to acquire, per the finding above. Both times, the `kill -9` itself triggered
a real kernel WARN inside `nv_drm_revoke_modeset_permission` (`nvidia_drm`, driver
550.163.01), confirmed via `dmesg -T`: a WARN-class oops (not a panic), stack trace
through `drm_file_free` -> `drm_release` -> `__fput`, hit while tearing down a process
that still held DRM modeset permission from its own failed Vulkan acquire attempt.
Non-fatal both times -- `nvidia_drm`/`nvidia_modeset`/`nvidia` stayed loaded with sane
refcounts, `nvidia-smi` stayed responsive, GPU stayed at a normal idle `P8` pstate -- but
real, reproducible, and pointless to keep re-triggering once the connector-enumeration
check above has already told you the link isn't there. If `jack-in-wayland.sh` has any
similar "start briefly, `kill -9`, check status" sequence, it's worth one `dmesg -T`
check after a failed wake attempt there too -- this may not be everyday-system-specific,
just never looked for before.

**Fix applied locally** (everyday system's own `jack-in.sh`, not yet ported here since
that script isn't the one tracked in this repo): the connector-enumeration check now runs
before the service is ever started, and on failure prints the physical diagnosis (reseat
the visor-end cable, then check the 18.5 V brick) and exits instead of burning an attempt
that reliably reproduces the same kernel WARN for no new information. Cable reseat
requested from the user; not yet retried after that as of this note.

**CORRECTION, same session, a few hours later: the fix above was wrong and has been
reverted.** Root cause of that whole failed sequence turned out to be the 18.5 V brick
switched off, not the cable/connector -- once powered back on, a real launch succeeded
(reached "Started vblank event thread!") while `/sys/class/drm/card0-*` **still only
showed the same 4 desktop-only connectors the whole time**, proving connector count was
never a valid signal for this NVIDIA setup in the first place. Left in this doc as a
record of a dead end, not a working technique -- don't reintroduce it.

**A better signal, found later the same session: the RandR `non-desktop` property,
queried with `xrandr --prop`.** On a working setup this reads `1` for the headset's
connector; Monado's `comp_window_direct_randr_init` needs at least one output with this
property set, and fails with "No non-desktop output available" (a distinct, more specific
error than the generic `vkAcquireXlibDisplayEXT: VK_ERROR_UNKNOWN` seen elsewhere in this
doc) when none exists. Mid-session, after several service restarts to chase an unrelated
bug, this property was observed reading `non-desktop: 0` on every connector including the
one otherwise behaving like the headset (`connected`, no desktop monitor's EDID) --
correlating with a cluster of other physical-layer symptoms in the same window: the USB2
branch dropping to 2/5 devices after a PC-side-only reseat (recovered only after a
visor-end reseat, this doc's own established fix), and a firmware-side error
(`hololens_handle_debug`: `"ERROR: CommandSet st 0, cmd 0, reqCmd 23"`) recurring
intermittently, absent on some attempts. Read together, this looks like a degrading EDID
read on a marginal link -- the non-desktop bit lives in the panel's own EDID/DisplayID
data, so an incomplete or corrupted read would plausibly report `0` -- rather than three
unrelated new bugs. Not conclusively proven; worth checking `xrandr --prop`'s
`non-desktop` value as a fast diagnostic the next time this cluster of symptoms recurs,
before assuming a software regression.

## Hardware change log for the reqCmd23/non-desktop:0 cluster above -- kept verbose on purpose, do not compress

This section exists specifically so that every physical change made while chasing the
`reqCmd 23`/`non-desktop:0` cluster above stays individually visible, with its own
timestamp and its own evidence, instead of being folded into a summary paragraph that
loses the "what changed, exactly when, and what happened right after" thread. New entries
get appended here, oldest first; nothing above gets shortened to make room.

**2026-08-11, ~evening, same everyday-system session that first logged the cluster above.**
Change: the USB-C-to-USB-A adapter/connector between the PC and the breakout box was
physically swapped for a different unit -- the cheapest-parts-first step in the recovery
order this doc already established (adapter/connector, then the power brick, then the
rev2A cable, in that order; see the elimination chain elsewhere in this doc for why the
brick was already ruled out on 2026-08-07). User explicitly flagged the exact moment of
the swap in the session transcript before doing anything else, which is what makes
"tracked from there" a clean before/after boundary rather than a guess about when the new
part actually went in.

**Exact parts, for the record**: the OLD adapter (the one suspected of causing the
`reqCmd 23`/`non-desktop:0` cluster) was the **official HP unit that shipped with this G2,
part number L56522-002** -- worth noting specifically because "it's the official part" was
part of why it had been trusted this long despite the recurring symptom cluster; being
first-party doesn't rule out an individual unit degrading. The NEW adapter it was swapped
for is a **Nisuta NSADU30UC** (third-party, not HP). If this fix holds up across future
sessions, the practical implication is that the official L56522-002 adapter, at least this
specific unit, is the actual root of the cluster -- not "HP-branded parts are inherently
more trustworthy than third-party ones" the way the earlier trust in it assumed.

**A USB 3.1 Gen2 (10Gbps) adapter would not help, checked directly via `lsusb -t`**: the
PC's own xHCI root hub on this port negotiates at `10000M` (10Gbps, so the host side has
headroom), but the G2's own onboard USB3 hub chip (`04b4:6504`) negotiates at exactly
`5000M` (5Gbps, USB 3.0 / USB 3.1 Gen1 speed) regardless, and everything downstream of it
(HoloLens sensors, etc.) inherits that same 5000M ceiling. The bottleneck is inside the
headset's own hardware, not the adapter or the cable run to it -- any adapter that reaches
at least 5Gbps (which the Nisuta NSADU30UC confirmed does, currently negotiated at 5000M
in the live topology) gives the full bandwidth this headset can ever use. No reason to
shop for a higher-spec adapter on bandwidth grounds.

From that exact point forward, the same session ran a long, restart-heavy 6DoF
controller-tracking development block: at least 4 full `monado-service` restarts,
including two that followed a clean `ninja` rebuild (full relink of `drv_wmr` and the
constellation tracker), plus one run that drove real `get_tracked_pose` calls via
`hello_xr` for ~20 seconds. This specific restart-and-rebuild cadence is the same kind of
cycling the `non-desktop:0` entry above names as the trigger ("after several service
restarts to chase an unrelated bug") -- so the post-swap period was not a quiet idle
stretch, it repeated the exact conditions that produced the fault before.

**Result: zero recurrence.** Across every individual run checked (each `jack-in.log` was
truncated before the next relaunch to keep debug captures clean, so this is several
separate clean-run checks rather than one continuous multi-hour log, stated plainly as a
methodology limit) -- no `reqCmd 23`, no `non-desktop:0`, no USB2 branch drop, no hub
reset, no `LIBUSB_ERROR`, nothing matching any of this cluster's known signatures. Tracking
itself stayed live and stable the whole time (constellation samples climbing past #11000
on one controller in the last run alone, reprojection error mostly 0.10-0.18px).

**Status: validated for this specific fault signature, not yet declared permanently
closed.** One session, however restart-heavy, is not the same evidentiary bar as the
multi-day/multi-session confirmations this doc holds itself to elsewhere (see the
T046-T049 sequence above, where a one-session "dead power rail" verdict was corrected the
very next session). Practical read: **the adapter is the current best explanation for the
reqCmd23/non-desktop:0 cluster, and the next time this specific session's conditions recur
(heavy restart cycling) is the real test.** If it recurs anyway, the next suspect in the
recovery order is still the visor-end connector/cable per the rest of this document, not
back to the brick (already independently ruled out 2026-08-07) and not this adapter again
without new evidence against it.

### Conclusions, stated explicitly (not left implicit in the narrative above)

1. **Root cause, best current evidence**: the USB-C-to-USB-A adapter/connector was very
   likely at least a major contributor to the `reqCmd 23`/`non-desktop:0` cluster logged
   earlier in this section. This is a **distinct fault class** from the visor-end
   connector's marginal contact documented in the rest of this doc -- that one produces a
   different signature (DP dead + USB2 `error -71` + hub resets scaling with panel/HID
   load) and has its own separately-confirmed fix (reseat). Two independently confirmed
   physical fault classes on the same unit, not one story with two names.
2. **Fix, current status**: replacing that adapter. Validated once, under conditions
   (restart-heavy 6DoF dev session, including full rebuilds) that reliably reproduced the
   fault before. Strong single-session evidence, not yet cross-session-confirmed.
3. **Practical consequence for the recovery order**: for the `reqCmd 23`/`non-desktop:0`
   signature specifically, check/swap the USB-C-to-USB-A adapter **first**, before
   reaching for a visor-end reseat -- reseating is still the correct first move for the
   *other* signature (DP dead, USB2 `error -71`, companion/audio dropouts under load).
   Don't apply one fault class's fix to the other's symptoms; they've now been shown to
   need different physical parts replaced.
4. **What would falsify this**: `reqCmd 23` or `non-desktop:0` recurring under a similarly
   restart-heavy session on the new adapter. If that happens: do not re-suspect the brick
   (independently ruled out 2026-08-07) and do not swap this same adapter again without
   new evidence against it specifically -- move to the visor-end connector/cable per the
   order already established in the rest of this document.

### Updated diagnostic procedure for this signature

Add to the diagnostic ladder near the top of this document: if the symptom is specifically
`reqCmd 23` (`hololens_handle_debug` in the kernel/dmesg log) or `non-desktop: 0` on the
headset's own RandR connector (`xrandr --prop`) -- **not** the DP-dead/USB2-`error -71`
signature the rest of the ladder targets -- the fast first check is which
USB-C-to-USB-A adapter is currently in use, and whether it's the one validated in this
section. If it's an older/different adapter, swap it before touching the visor-end
connector at all; the visor-end reseat procedure elsewhere in this document is for the
other signature and has not been shown to fix this one.

**Lesson, project rule material, alongside the anomaly-thread lesson earlier in this
doc**: this fix was a few-dollar adapter, and it likely closed a fault that had already
cost a full diagnostic session's worth of time (finding, characterizing, and then setting
aside the `reqCmd 23`/`non-desktop:0` cluster the session before this one). The "cheapest
parts first" order this doc already uses for hardware recovery isn't just about not
overspending -- on this project, the cheap part has now paid for itself in saved
diagnostic time twice (the visor-end reseat cost nothing and replaced a whole night's
"buy a rev2A cable" verdict; this adapter cost little and replaced what could have become
another multi-session software-side goose chase). When a cheap, easy-to-swap component
sits between the machine and a hard-to-reproduce intermittent fault, swap it early and
rule it out (or in) before spending more diagnostic hours -- don't save the cheap step for
last just because it feels like the least technically interesting one to try.

## The seat lottery (T171, 2026-08-13) — one pin group per seating, every conductor healthy

**Context**: the machines were physically rearranged (a second Windows system arrived; the
lab SSD now boots on the x3600 with a single desktop monitor). The headset then failed to
be detected on BOTH Windows systems, and on Linux showed the classic `error -71` /
`Cannot enable. Maybe the USB cable is bad?` storm on the USB2 branch at boot. Ten
seatings and one control experiment later, the verdict is **nothing is broken**: this is a
marginal mechanical seat at the C-plug/adapter that engages a different subset of pin
groups on every insertion.

**The measured pattern that gives it away** (all on the x3600's CPU-fed controller
`0000:09:00.3` except where noted):

| Seat | Port | SS branch (6504+sensors) | USB2 branch (6506+companion+audio) |
|---|---|---|---|
| boot | rear A #1 (adapter) | ✅ 5000M | ❌ error -71 |
| replug | rear A #2 (adapter) | ❌ | ✅ complete |
| replug | rear A #1 (adapter) | — | ❌ (nothing) |
| native C, both orientations, ×3 | mobo USB-C direct | ✅ 5000M | ❌ |
| after visor reseat + mains cycle | mobo USB-C | ✅ | ❌ |
| replug | rear A #2 (adapter) ×2 more | ❌ | ✅ complete |
| chipset-controller port | front/other 3.0 | ❌ | ❌ |
| **A #2 + 180° flip inside adapter** | rear A #2 | **✅ 5000M** | **✅ complete** |

Key observations, in evidence order:

1. **Every conductor group in the cable is alive.** SS enumerated perfectly in 6 seats,
   USB2 in 3 others, and the winning seat got all 5/5 — nothing is electrically dead.
   This is NOT the wholesale conductor-group death of T039-T040.
2. **A software xhci rebind (full controller re-enumeration) reproduces the identical
   half-dead state** — the fault is purely physical-contact, not stuck host state.
3. **The state is rock-stable at rest**: a 5-minute journal watch on a half-dead seat
   logged ZERO spontaneous events. No self-recovery, no flapping. Whatever a seating
   engages is what you keep until the next physical manipulation.
4. **A phone enumerated instantly on the same native-C port where the G2's USB2 pair had
   failed 7 consecutive times** — port absolved, cable/plug seat condemned.
5. **The `docs/06` ladder is revalidated verbatim**: "try the port first, the orientation
   second." The winning move was the documented one — 180° rotation of the C plug INSIDE
   the C-to-A adapter (Nisuta NSADU30UC), same port, after the port itself had already
   been chosen for having the USB2 branch up.
6. **User's standing rule confirmed again**: only rear, CPU-controller ports work at all;
   the one chipset/front-port attempt enumerated nothing, and the native mobo USB-C never
   carried the G2's USB2 pair in any orientation (it never has on any machine — per the
   user, the C port has never worked for this headset).
7. **Working hypothesis for the mechanism** (unproven but consistent with all 10 seats):
   SS pins sit at the tip of the connector tongue, the USB2 pair mid-connector; worn
   contacts mean seating depth/angle selects which group mates. That's why deep clean
   seats (native C) got SS-only and one particular A-port's grip got USB2-only.

**Why Windows failed on both systems**: WMR requires the SuperSpeed link and refuses
otherwise; with the seat lottery landing on a partial branch every time, "headset not
detected" on two different Windows machines was the same single fault seen from the other
OS. The recipe for any Windows attempt is identical: rear CPU ports, aim for the full
5-device enumeration (Device Manager should show both hub faces), rotate the plug inside
the adapter if one branch is missing.

**End-to-end verification after the fix, same session**: `panel.py activate` → DP-3
hotplug with the healthy 384-byte EDID → `jack-in-wayland.sh 1 6dof` came up first try:
mutter lease granted, `4320x2160@90`, builder wmr, BOTH controllers registered, Basalt
SLAM started with the denser G2 config, camera tracking CSV growing (SS streaming under
real load), zero USB errors in the kernel log.

**Operational consequence, shipped the same day**: `scripts/power-on.py` now diagnoses
WHICH branch is missing (`branch_flags()`), prints these exact reseat instructions in
probability order (`reseat_instructions()`), and waits interactively for the fix instead
of dead-ending — with `[s]` to skip VR and continue to the plain 2D desktop. Camera
negotiated speed (step 3) got the same treatment, since "cameras enumerate at 480M through
the hub's USB2 face" is exactly what a missing-SS seat looks like.

## The silent 100% camera-frame-loss signature (2026-08-15, everyday system)

**What this section adds that the seat-lottery section above doesn't**: that section
diagnoses the missing-SS-branch *enumeration* (link speed, device count). This one is about
what happens to the camera **image data itself** once that degraded branch is carrying
traffic anyway — and specifically that Monado's own logs give **zero indication anything is
wrong** at that layer, unlike every other signature in this doc's index.

**Context**: rebuilding and testing the lab's newest 6DoF work (`lab-full`, patches through
0048, see `patches/monado/README.md`) on the everyday system for the first time. Two
unrelated things happened in sequence and must not be conflated: first, the 18.5 V brick's own
physical power switch was off (the exact false alarm from "Reseating mid-session" /
T046-family entries above — fixed by flipping the switch, not a re-plug); once power was
back, `jack-in.sh` reached a real "Jacked in - compositor is presenting" and `hello_xr`
reached `XR_SESSION_STATE_FOCUSED` with `PositionTracking=True` — so DP/panel recovered
completely. **The camera branch did not.**

**Measured signature**: `lsusb -t` showed the HoloLens Sensors (`045e:0659`) at 480M under
the USB2 hub (`04b4:6506`) instead of 5000M under the USB3 hub (`04b4:6504`) — bus 4 (USB3
root) had zero children. With `WMR_CONSTELLATION_CONTROLLERS=1` and
`CONSTELLATION_TRACKER_LOG=trace` set, and the user actively moving both controllers for
~20-30s: **236 out of 236 camera frames logged `WARN [img_xfer_cb] Invalid frame magic (got
<garbage>, expected 2b6f6c44). Dropping`** — a 100% loss rate, not intermittent, starting
from the very first frame after `wmr_camera_start` and continuing for the whole sample
window with no exceptions. The "got" values are garbage nibble-repeat patterns (`04040404`,
`a0a0a0a`, `9090909`...), consistent with the marginal SuperSpeed contact corrupting the
bulk transfer's own header bytes rather than failing the transfer outright. Zero blob
observations ever reached the constellation tracker; the debug GUI's camera panels showed
solid pink (an uninitialized texture that no valid frame ever wrote to, not a rendering
bug).

**Why this one is dangerous, more than the others in this doc**: `wmr_camera_start` logs
cleanly, the framebuffer size logged (`2560 x 480 - 1233408 transfer size`) is the normal
value, and `send_calibration` succeeds for all 4 cameras — every log line Monado itself
produces at startup says the camera pipeline is healthy. The corruption happens at a layer
below anything Monado checks (the USB transfer's own magic-number header), so **nothing
in a normal launch log flags this** — you only see it by explicitly grepping for `"Invalid
frame magic"`, which nobody does routinely. A session run this way would look, from the
outside, like "6DoF just isn't tracking" or "constellation gate is too strict" — a plausible
but wrong software diagnosis for what is actually 100% physical-layer data loss.

**Fast diagnostic, added to `jack-in.sh` on the everyday system the same day** (not yet
ported to `jack-in-wayland.sh`/`power-on.py` on the lab side — worth doing, since the
mechanism is identical): a couple seconds after "Jacked in", grep the log for
`"Invalid frame magic"` and warn loudly if the count is more than a handful, naming the
`lsusb -t` check and pointing at this section. `grep -c "Invalid frame magic" <log>` against
"is this a small number (transient) or does it never stop (this fault)" is the fast manual
check if scripted detection isn't available.

**Not yet fixed this session** — the visor-end reseat (this doc's own established fix) is
the next step, queued but not done as of this section being written. This entry exists so
whoever does the reseat next has the exact before-state to compare against
(`lsusb -t` speed + a repeat of this same trace-log test) rather than just "it's better now"
by feel.

## Retry escalates the fault — a stop condition, not just another symptom (2026-08-15)

**What happened, right after the section above.** With camera corruption already confirmed,
the everyday system relaunched `jack-in.sh` three more times in a row chasing two different
goals: a clean visual test, then the wearer's explicit request to physically *feel* what
degraded tracking is like in-headset (a legitimate goal on its own — this doc exists partly
to build that kind of hands-on fault recognition — but reached by too many activation cycles
in a row). **All three failed identically, before even reaching the display stage**:
`ERROR [wmr_read_config_part] Failed to issue command 0b: 08 19 00` → `Failed to load headset
configuration!` → `XRT_ERROR_DEVICE_CREATION_FAILED`. This is a different, *earlier* failure
than the camera corruption — the companion's own HID config-read channel, which had answered
fine in that same session's earlier successful launches, stopped responding at all by the
third retry.

**The mechanism is already documented above** (see "Recurrence, same night (T044, T043)"):
panel activation's power transition is specifically what knocks this marginal contact
looser. Every relaunch attempt sends that same activation sequence. Chasing a fix (or, here,
chasing a demonstration) by relaunching repeatedly is running the one action most likely to
make the contact worse, not better — and it did: a session that started with a healthy panel
and only-the-cameras corrupted ended with the whole HMD failing to construct.

**New standing rule, for either machine (same physical cable/connector — see
[[reference-vr-lab-topology|the two-install topology]], this is one physical machine, not
two):**

> Once a launch fails at HID config-read (`Failed to issue command`, not just camera
> corruption), **stop. Do not relaunch again.** Two consecutive failures at this stage, or
> one config-read failure in a session where camera corruption was already seen, means
> reseat the visor-end connector before any further attempt — don't treat it as an ordinary
> transient hiccup worth just trying again, the way most single-shot USB errors elsewhere in
> this doc are.

This applies to `jack-in.sh` on the everyday system (where this was found) and equally to
`jack-in-wayland.sh`/`scripts/power-on.py` on the lab side, which doesn't yet have this
specific stop condition wired in — `power-on.py`'s existing `branch_flags()`/
`reseat_instructions()` diagnose *which* branch is missing, but nothing today counts
consecutive HID config-read failures and refuses to keep cycling. Worth adding there before
the same escalation happens on dev, since it's the identical physical connector and the
identical mechanism.

**Also corrected, same incident**: this doc's own known-good enumeration is **5 devices**
(USB2 hub, audio, companion, USB3 hub, HoloLens Sensors — see "The measured anatomy"), not
4 — a mid-incident check that only found 4 (missing the USB3 hub instance itself,
`04b4:6504`) was briefly and wrongly called "healthy" before the miscount was caught. When
counting, count the hub instances too, not just the leaf devices.

## Known-good fingerprint (2026-08-16, `docs/pruebas.jsonl` T184-T187)

Everything above establishes *that* a good state exists and roughly what it looks like
(5/5). Until tonight, "it's working" was always a subjective read ("se ve perfecto") — this
session produced an objective, checkable identity for the good state instead, so a future
session can compare against something instead of a feeling. If a session ever looks wrong,
check this first: matching values mean the config is the same one validated here and the
problem is the usual physical/enumeration fault, not something new; a mismatch (different
firmware version, different serial) means something genuinely changed and this whole doc's
history doesn't automatically apply anymore.

```
Hub chip serial (both SuperSpeed and USB2 personas, same physical Cypress chip):
    EE4482CEAFE75844820A73F26905A52F
Windows ContainerID for the whole composite device (all 5 branches, one identity):
    {ee4482ce-afe7-5844-820a-73f26905a52f}
Presence device serial / InstanceId:
    03f0:0580, serial 8CC044Z2CM
    HID\VID_03F0&PID_0580\8&2513E90&0&0000  (child collection, stable across reconnects)
Sensors device serial / InstanceId:
    045e:0659, serial BDA9EF65-CA83-4C29-B649-93B019C736BB
Headset OEM firmware (three components):
    QA85QAPV1/1.2 | QA85QBLV1/7.0 | QA85QDPV1/50.49
Display EDID identity:
    220e:36c1 (HPN36C1) -- cross-checked against docs/12/26, unchanged
```

**Validated, same night, two independent ways**: (1) `docs/pruebas.jsonl` T186 — PC-end
USB-C unplug/replug (NOT a visor-end reseat), same port, same orientation, cold ~8-10s gap —
**6/6 clean 5/5**, every device number freshly incremented (genuine re-enumeration, not
cache), no settle time needed. Sharp contrast with T184's 0/3 for visor-end reseat in the
same conditions — the two ends of the cable are not interchangeable levers. (2) A real
Windows gameplay session on top of that state — user's report: "corre todo perfecto sin
problema", no audio cuts, no controller weirdness. **This is the first time this project has
had both a mechanically-repeatable trigger for the good state AND a real-load confirmation
on the same night** — previous "it's fine" verdicts were one or the other, never both
together with a checkable fingerprint underneath.

**Not yet tested, flagged for later rather than guessed at** (`docs/pruebas.jsonl` context,
2026-08-16 session): whether the PC-end reconnect trick also rescues a bad orientation or a
bad port (only tested from an already-good starting condition); whether the USB2 branch can
still flap spontaneously mid-session on Windows under sustained load, not just at cold
connect (T052/T183's storms, and now T188's full-scale live capture — peak 472175 companion
errors, monado-service pinned 400%+ CPU, confirmed independent of which/whether a client is
connected — are all Linux-only observations so far; T188 also leaves open whether
`WMR_CONSTELLATION_CONTROLLERS=1` specifically triggers or worsens it, since the storm was
already climbing before constellation was ever enabled that session -- and T052-T057, weeks
earlier, already saw the same storm at complete idle with NOTHING running, which argues
against 6dof/constellation being required at all -- **done same night, T189: settled, and it
split the problem in two.** The companion-error storm itself reproduces at complete idle (no
SLAM, no constellation, no app, headset untouched) at the same rate as under full load -- it
needs nothing running at all. But `monado-service` CPU stayed under 1.2% the whole time,
nothing like T188's 400%+ pin under Aircar+constellation. So the storm (load-independent,
always available) and the CPU spin (load-dependent, mechanism unknown) are two separate
things that only looked like one pair in T188. Next cut: constellation-only and SLAM-only in
isolation, each idle/no-app, to find which one (if either alone) turns the counter into the
CPU pin; controller and headset
auto-standby timing on Windows specifically (measured on Linux/Monado only, T181, ~15 min);
whether Oasis's native Windows stack implements HMD worn/presence detection where
Monado/xrizer does not (see `docs/03`'s War Robots VR finding).

---

## 2026-08-19 (T226) — the Windows control, and the verdict this document has been waiting for

Everything above debated the cable from **one side of the link only**: every measurement in
this file was taken on Linux, and every time the recommendation moved ("buy rev2A" → "premature"
→ "still-open, not retired" → "retracted") it moved on reasoning, not on a Windows number.

**That number now exists.** `windows-kit/usb-storm-monitor.ps1` was run for 79 minutes on the
*same physical machine* with the SSD swapped — same board, same USB host controllers, same
cable, same headset, **OS as the only variable** — and with the G2 actually driven by Oasis +
SteamVR throughout, five titles played, so it is a loaded session and not an idle one:

* USB2 branch: **274 drops, 3.47/min, outage p50 2.9 s, p90 10.5 s, incomplete 27% of the
  session**, twelve of them passing through Windows' own `PROBLEM:Error` state.
* USB3 branch (hub-ss + hololens-sensors): **zero drops**, as on Linux.
* Escalates within the session exactly like Linux: 0 events in the first 10 minutes after
  enumeration, then 38-52 per 10 minutes.

Against Linux's 0.92-4.63/min and p50 3.0 s (`~/vr/logs/hw-monitor.log`), that is the same
fault. **The storm is the link.** Per the rule written before the data was taken, the rev2A
cable goes back on the suspect list and the swap is justified — with the caveat this document
has earned the right to state: it discriminates *cable* from *connector/visor*, and if a new
cable changes nothing, the remaining suspects are the visor-side USB2 PHY and this unit's
connector, not the host.

The counterpart finding is that the *consequences* are ours: Windows rode 274 disconnects while
five titles played normally, and the only thing the user noticed was audio cutting out. On
Linux the same outages produce ~83 companion HID read failures/s and a frozen presence sensor.
Full analysis and the archived capture: `docs/60-windows-usb-storm-control.md`,
`windows-kit/captures/`.

---

## The rev2A cable is not a fix, it is a different lottery ticket (2026-08-19, user knowledge)

T226's Windows control put the rev2A cable back on the suspect list, and the temptation now is
to treat "buy the rev2A" as the answer. **It is not, and the user's own knowledge of the
community record is the reason:**

- **HP never shipped a cable that is 100% good.** There is no revision that fixes this class of
  fault outright — v1 and rev2A both have populations of users reporting the same symptoms.
- **There are no third-party alternatives.** This is not a commodity cable: it carries DP,
  USB3, USB2 and 18.5 V through a proprietary connector into an active repeater box. Nobody else
  makes one, so "buy a better cable" is not an option that exists.
- **The luck is not one-directional.** Some units are stable on rev2A, *some are stable on v1
  and get worse on rev2A*, and some are unstable on both. Swapping is a coin flip with a real
  chance of ending up worse, not an upgrade.
- **The revisions are not identical hardware.** rev2A adds a button that v1 does not have, so
  the two are not drop-in equivalents and behaviour differences between them are not automatically
  "the new one is better".

**How to hold this**: the swap remains a legitimate *experiment* — it is the cheapest way to
discriminate cable from connector from visor-side PHY, which is exactly what T226 left open. But
frame it to anyone reading as **an experiment with a real failure mode**, not as a repair. Keep
the old cable. If the new one is worse, that is a documented outcome and not a surprise.

## Port preference, and one thing this project will not test

**Rear sockets only, and on the right controller** — see `docs/00`'s port-controller section and
`scripts/usb-port-map.sh`. The **front-panel USB3 header has never been tested here and
deliberately will not be**: it reaches the board through an internal header plus a length of case
wiring, adding another marginal joint to a chain whose first joint already cost this project
weeks. **Potentially unsafe, not recommended.** The cable is enough of a mess on its own.

## This unit's cable is **Rev A** — the original (2026-08-19, T232)

Read off the cable's own label by the user, after this document had argued about cable revisions
for weeks **without anyone checking a part number**. That is worth stating as a process failure
first: the single cheapest fact in the whole saga was printed on the object the entire time.

**What it settles.** Every "buy the rev2A" and "the rev2A escalation was premature" exchange in
this file was about replacing a cable whose revision was assumed, not known. It is now known: this
headset has been running its whole life on the **original Rev A cable** — precisely the revision
with the community's mass-failure record, the one HP replaced.

**What it does NOT settle, and this is the part to hold onto.** It does not make the swap a fix.
Everything in the section above still applies: HP never shipped a cable that is 100% good, there
are no third-party alternatives, some units are stable on Rev A and get *worse* on rev2A, and the
two are not the same hardware (rev2A adds a button). What changes is only this: **the experiment
is now well-posed.** Before, "try the other cable" meant swapping an unknown for an unknown. Now
it is a clean A/B — original versus replacement — on a link whose fault rate has been measured on
both operating systems (T226: 3.47 drops/min on Windows, 0.92-4.63 on Linux, USB3 branch immune
on both).

**Read next, if the label has more on it**: the full HP part number of the cable. Rev A units
carry one, and it is the identifier a second owner would search for.

### ⚠️ CORRECTION (T232): the brick is **18.5 V, not 12 V** — this document said 12 V ~15 times

Read off the brick's own label, four identifiers together: **spare `381090-001`, P/N
`380467-001`, series `PPP009H`, model `PA-1650-02H`** — all four resolve to the same part, an
**HP 65 W / 18.5 V / 3.5 A adapter with a 4.8 × 1.7 mm barrel**. It is an ordinary HP laptop
charger (Pavilion/Presario era) that HP reused for the G2.

Nobody in this project ever measured that voltage; "12 V" was written down early, repeated
across `docs/22`, `docs/26`, `docs/31`, `CLAUDE.md` and two scripts, and never checked — the
**same failure as the cable revision**, twice in one evening, and both times the answer was
printed on the object.

**What this does NOT change**: every architectural claim built on it stands, because the
reasoning was never about the number. The panel, backlight and ANX7530 bridge do power from the
**brick's rail**, not from USB; no brick rail still means no HPD; the "USB perfect, display stone
dead" single-fault picture is still coherent. Only the label was wrong.

**What it DOES change, and it is the reason this is a warning and not a footnote**: `docs/26` is
a buying guide that tells a reader to *test or replace the brick*. Anyone who acted on it would
have gone looking for a 12 V supply — which would not work, and forcing a mismatched supply into
a barrel jack is how hardware dies. All occurrences are corrected.

### The cable, identified — and the replacement now has an orderable number (T232)

| | |
|---|---|
| **This unit's cable** | 6 m active, SPS **`M18238-001`**, regulatory model **`TPC-B001C`**, **no switch** |
| **The replacement** | SPS **`M52188-001`** — HP's own description: *"SPS-CA ACTIVE 6M BLACK **/W SWITCH**"*. Also sold as `22J68AA` / `L72080-002` |

**Three independent facts converge on the same answer**, which is why this is worth trusting: the
user read "Rev A" off the label; the cable has **no button**; and its part number sits in the
older family, while the replacement's official description literally ends in *"/W SWITCH"*. This
document had already recorded, from community knowledge alone, that *"rev2A adds a button v1
lacks"* — HP's own SPS description says the same thing in its product name.

**What actually changes for this project.** For weeks "buy the rev2A" was folklore: a thing
people said, with no part number attached, which is part of why the recommendation kept flipping
between "firm buy" and "premature". **It is now an orderable part: `M52188-001`.** That does not
make it a fix — everything in the lottery-ticket section above still stands, including that some
units get *worse* on the newer cable — but the experiment can now be specified precisely instead
of described.

`M18238-001` is exactly the number resellers list as an older G2 cable revision, so the
identification is closed from both directions: HP's own numbering and the aftermarket's.

Note also that the cable carries its **own regulatory model family** (`TPC-B001C`) distinct from
the headset and controllers (`TPC-Q077-*`). It is a separately certified product, which fits what
this document measured the hard way: it is an active device with its own silicon, not a wire.

### The cable carries a firmware version — and HP replaced every Rev 1 cable for free (T232)

Two findings from reading this unit's cable, one from the object and one from the record.

**From the object.** The inline box has **no label on its visor-facing side** — checked. What
exists is a sticker on the cable itself carrying a serial (deliberately not recorded here) and a
**firmware marking**, transcribed as approximately `fw 0x5_3 … 0x5_10`; several characters are
not confidently legible and the value is *not* being treated as known. **The finding is not the
value, it is that the marking exists at all**: the cable ships with a firmware version printed on
it, which confirms the inline box holds programmable silicon rather than passive components. This
document has suspected exactly that object for months ("a firmware/state-machine glitch in that
chip fits the evidence far better than mechanical wear"), and no public source documents cable
firmware versions at all.

**From the record, and it reframes the swap.** HP did not merely offer a newer cable — **HP ran a
free replacement programme for every Revision 1 cable**, and the community description of what
changed is specific: the rev2 box contains a **qualified hub that cleans up the signal**, plus
the on/off button, and it was aimed at *power issues*.

Read that next to what T226 measured: the **USB2 branch** storms at 3.47 drops/min on Windows and
0.92-4.63 on Linux, while the **USB3 branch never drops on either OS**. A hub-silicon change
inside the link box is exactly the shape of fix that would address a USB2-branch-only fault. That
does not promise anything — the lottery-ticket section above still stands, including units that
get *worse* on rev2 — but it moves the swap from "the community says try it" to **"the vendor
replaced this specific revision, for free, citing the subsystem we measured failing"**.

*(Sources are forum and reseller accounts, not HP technical documentation; treated as such.)*
