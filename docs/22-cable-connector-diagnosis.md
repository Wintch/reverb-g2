# 22 — The G2's link anatomy, and how to diagnose it piece by piece

This document collects the measured failure modes of one G2's cable, connector and power
chain, observed across two machines and two operating systems: what each piece of the link
does, how to isolate it, and which lever fixes which signature. The central finding: a
single marginal contact at the detachable **visor-end connector** can take out any subset of
DisplayPort, USB2, USB3 and power, so its failures look like several independent faults. A
headset that appeared to die progressively (DP first, then USB2) and earned a firm "the cable
is dead, buy a rev2A" verdict came back 100% from reseating that one connector. Everything
below was measured, not read somewhere; the anatomy comes first because it makes the
diagnosis mechanical instead of guesswork.

If you only need to match today's symptom to a known cause and fix, start with the decision
tree and the signature index; the sections after the anatomy hold the evidence behind each
step.

## Troubleshooting procedure — decision tree

**Operator-runnable summary.** Match what you observe against the steps below, in
evidence-ranked order (cheapest / most-confirmed lever first, physical intervention last),
and stop at the first fix that applies. **Step 0 goes first, always** — for the single most
common "headset looks dead" report it is the highest-yield check, it needs no tools, and it
is confirmed live as of 2026-09-03. The "Known fault signatures" table right after this
section is the fuller symptom→cause→fix index; the sections further down are the evidence
each step here is built on.

### 0. DP dead? Run activation and LOOK, before touching any cable

**Not a cable fault until proven otherwise.** The G2 never raises DP hotplug on its own — it
needs one WMR activation HID sequence first. If Monado failed early (before it reached its
own activation step) or a prior session died mid-bringup, the panel is simply sitting in
**standby**, and every DisplayPort connector will correctly read `disconnected` with no G2
EDID even though nothing is broken.

1. Run `./scripts/panel.py activate` — **once**.
2. Look in the visor immediately — a few-second window; the panel auto-powers-off again if
   no video signal follows.
3. **HP firmware-splash logo visible** = the panel is alive; the DP link was just waiting on
   activation, it wasn't dead. Confirm: `for d in /sys/class/drm/card*-DP-*; do echo "$d:
   $(cat $d/status)"; done` — it's either already `connected`, or comes up within a few
   seconds of the logo appearing. **The discriminator is exactly this: logo visible + DP
   still `disconnected` at the GPU is a normal in-between state, not a fault.** Give it a
   few seconds, then re-check. **This is the fix — go straight to `jack-in-wayland.sh`; do
   not open a cable/connector diagnosis.**
4. **No logo at all** after one clean `activate` run → genuinely not standby. Proceed to
   step 4 (DP-specific fault) or step 5 (power) below, per the fuller signature there.

Don't re-run `activate` more than once chasing a flaky result before looking — see "Do NOT"
below. This step alone resolved a full DP-dead-while-USB-enumerates session on 2026-09-03
(the panel came up on `DP-2` that boot — the connector name is not stable across
machines/sessions, see anatomy point 10 below; always re-scan, never hardcode it).

### 1. Fast checks, before touching any cable

- `lsusb | grep -E "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15"` — count matches. 5/5 = both
  USB branches healthy (if the panel is still dark, see step 0 above before suspecting a DP
  fault). Fewer than 5 → step 2.
- `scripts/hmd-connector.sh` — non-empty output = panel physically present, EDID matches this
  unit's fingerprint `220ec136`. Empty = panel not detected at all.
- `grep -c "Invalid frame magic" <jack-in.log>` — near-zero = camera data clean; a large,
  non-stopping count = frame corruption even though `lsusb` shows the branch present (step 3).

### 2. USB2/companion branch missing — fewer than 5/5, `03f0:0580` absent

1. **PC-end USB-C reconnect first** (PC end or the C-to-A adapter, same port, cold ~10s gap).
   Cheapest, and proven to recover a *previously-good* seat (6/6 clean). Does **not** rescue a
   seat that has never been good — if it doesn't recover in 1-2 tries, move on.
2. Another rear, CPU-fed USB port (front-panel/chipset ports have never worked for this
   headset).
3. **Visor-end reseat** (behind the magnetic face gasket) — the connector that carries every
   conductor group; most of this doc's history traces back to a marginal contact here.
4. Confirm with `journalctl -k --since "-5 min" | grep -iE "usb|hub"` — `error -71` / "Cannot
   enable. Maybe the USB cable is bad?" is the marginal-contact signature, not a dead cable.
5. **STOP CONDITION** — see "Stop conditions" below: a `reqCmd 23` HID config-read failure
   means stop and reseat, not retry.

### 3. Camera frames corrupt — SLAM sees 0 blobs, debug camera panels pink

`grep -c "Invalid frame magic" <jack-in.log>` returns a large, non-stopping count, and/or
`lsusb -t` shows HoloLens Sensors (`045e:0659`) at `480M` under the USB2 hub instead of
`5000M` under the USB3 hub. Monado's own startup log looks clean — this corruption happens
below anything Monado checks, so a clean log does **not** mean the camera data is good;
always grep explicitly.

→ **Visor-end reseat** (same connector, same fix as step 2.3). Verify with `lsusb -t`
(Sensors back to `5000M`) before trusting any tracking data.

### 4. DP dead while USB enumerates fully — the genuine DP-specific fault (escalation only, after step 0)

**Do not enter this step without having already run step 0 once, cleanly, with eyes on the
visor.** As of 2026-09-03, most of what looks like this signature turns out to be standby
(step 0), not a fault. Only continue here if activation genuinely produced no logo.

Symptom: all DisplayPort connectors read `disconnected` (`for d in /sys/class/drm/card*-DP-*;
do echo "$d: $(cat $d/status) $(wc -c < $d/edid)"; done`), no G2 EDID (`220ec136`) on any DP,
only the desktop's own HDMI connector(s) show connected — while `lsusb` is a healthy 5/5 and
`panel.py activate` produced no logo. Monado bringup fails at compositor init
(`XRT_ERROR_VULKAN` / no leasable connector).

1. **Fix: visor-end connector reseat** — the 2026-08-07 fix that restored USB2 + panel + DP
   all together, for a genuine marginal-contact fault. Same physical connector as steps 2 and
   3, different pin subset.
2. **What did NOT fix this, confirmed live 2026-09-03 — don't send an operator down these for
   a true DP-dead symptom**: a PC-end USB reconnect (restores the USB branches, not DP),
   moving the DP plug to a different GPU output, or a plain power replug. None of these
   substitute for the reseat once step 0 has genuinely ruled out standby.
3. **The USB-C orientation flip is NOT a lever here.** This cable has one good orientation
   and it is already set; flipping it does nothing for a DP-only dropout — orientation only
   matters for the seat-lottery USB fault in step 2.
4. If "logo on, panel off" appears **mid-session** (not at cold boot) right after any physical
   reconnect while Monado was already running: that's a stale DRM lease, not a hardware fault —
   kill `monado-service` + `rm -f /run/user/1000/monado_comp_ipc` and relaunch fresh; re-running
   `panel.py activate` alone will not fix it.

### 5. Nothing lights, DP dead, brick LED off — the power branch

→ **Power-cycle the brick**: unplug and replug the barrel/wall connector. This unit's brick
runs at **18.5 V** (an HP 65 W laptop adapter — an older "12V" figure elsewhere in this doc
is superseded) and **has no power button** — power-cycling only ever means
the unplug/replug, never a switch. See "Do NOT" below for why a switch isn't the answer.

### Do NOT — dead ends and risks; skip these

- **Do NOT look for a power switch on the brick.** It doesn't have one. Two older entries in
  this doc (2026-08-11, 2026-08-15) describe flipping one — that described the rev2A
  replacement cable (`M52188-001`, HP's own description ends "/W SWITCH"), a different
  physical part this unit does not have (confirmed off the cable's own label). This unit's power-cycle is always unplug/replug the barrel connector.
- **Do NOT buy a new power supply/brick.** Investigated and explicitly ruled out (2026-08-07
  elimination chain, section *The power rail, and why "dead power rail" was wrong* below).
- **Do NOT spam `panel.py activate` or relaunch repeatedly chasing a flaky result.** Each
  activation cycle sends a real power transition through the visor-end connector, and it can
  knock a marginal contact looser — this mechanism is behind several of this doc's worst
  nights. Run it once, look, then decide; don't retry your way into a worse fault.
- **Do NOT flip the USB-C orientation as a DP fix.** This cable has a single good orientation
  and it's already set; the flip only ever helps the USB seat-lottery fault (step 2), never a
  DP-dead symptom.
- **Do NOT treat a PC-end USB reconnect, a different GPU port, or a power replug as DP-dead
  fixes.** None of them restored DP in the 2026-09-03 session; only `panel.py activate`
  (standby case, step 0) or a genuine visor-end reseat (hardware-fault case, step 4) do.

### Stop conditions — when to stop retrying

- **HID config-read failure**: a launch failing at `reqCmd 23` / `Failed to load headset
  configuration` / `Failed to issue command 0b` is a STOP CONDITION. Do **not** relaunch
  again — reseat the visor-end connector (step 2.3) before the next attempt. Retrying here is
  what turns a marginal contact into a dead one.
- **Multiple steps matching in the same session** (e.g. camera corruption *and* a config-read
  failure): treat it as one contact degrading further, not two separate faults — go straight
  to the visor-end reseat and stop retrying, don't chase each symptom with its own fix.

## Known fault signatures — quick index

| Symptom | Root cause | Fix | Section |
|---|---|---|---|
| DP dead (no logo), USB still 5/5 | Visor-end connector marginal contact | Reseat visor-end connector | "The failure timeline, and the three wrong verdicts" |
| USB2 branch dead, kernel says `error -71` / "Maybe the USB cable is bad?" | Same visor-end marginal contact, different pin subset | Reseat visor-end connector | "The measured anatomy", point 3 |
| Companion enumerates but HID reads return `-1`, device number climbs fast | Marginal contact knocked loose specifically by panel activation's power transition | Reseat; minimize activation/panel-power cycling | "Recurrence: the reseat is a mitigation, not a repair" |
| No logo at cold boot, but USB is a healthy 5/5 and nothing was touched | **Not a fault** — the G2 never raises DP hotplug at cold power-on on any OS; needs the WMR activation HID sequence first | Run `./scripts/panel.py activate` before concluding the panel is dead | "The power rail, and why \"dead power rail\" was wrong" |
| Image glued to the face, video/audio otherwise perfect | A USB hiccup killed Monado's `wmr_run_thread` (IMU reader); Monado never restarts it | Restart the session; confirm with `grep "Exiting reading thread"` | "The tracking freeze" |
| "Logo on, panel off" appearing **mid-session** after any physical reconnect | Monado's compositor is still holding a DRM lease invalidated by the reconnect — HID activation succeeds but nothing is scanned out | Full session restart (kill `monado-service` + fresh launch), not just `panel.py activate` | "Reseating mid-session (2026-08-10)" |
| Audio cutting in/out, worse the more concurrent load (video+audio > video alone > idle) | Same marginal visor contact; PipeWire recreates the ALSA sink on every USB2 cycle | Same as the marginal-contact fixes above; no audio-specific fix needed | "Load correlates with disconnect frequency" |
| `reqCmd 23` (`hololens_handle_debug`) and/or `non-desktop: 0` on the headset's RandR connector, correlating with heavy service-restart cycling | USB-C-to-USB-A adapter fault (validated single-session, 2026-08-11) — **a different physical part than the visor-end contact above** | Swap the USB-C-to-USB-A adapter, not a visor-end reseat | "The USB-C-to-USB-A adapter fault class" |
| Windows: SteamVR "Headset not detected (**108**)", but the headset's audio device and companion do show up in Windows | Same seat lottery seen from Windows: the SuperSpeed branch never enumerated, and WMR/Oasis requires it | Same ladder as the row below — aim for all 5 devices in Device Manager, not "the headset appears" | `docs/31`, "The error index" |
| Windows: SteamVR "unexpected problem (**422**)", intermittent, unaffected by reseating | Not a cable fault at all — SteamVR started and the driver failed under it (safe-mode-disabled add-on, stale unlock after a GPU/Windows change, beta branch) | Re-enable the `oasis` add-on, re-run the unlock, leave the SteamVR beta | `docs/31`, "The error index" |
| Exactly ONE of the two USB branches enumerates per seating (SS-only or USB2-only, never both), stable at rest, changes only on reseat; "headset not detected" on Windows too | Marginal seat of the C-plug/adapter engaging one pin subgroup per insertion — all conductor groups healthy (T171, 2026-08-13) | Rear (CPU) USB3 port, firm and straight; then **rotate the C plug 180° inside the adapter without changing port**; then the other rear port; then visor-end. Success = 5/5 | "The seat lottery (T171, 2026-08-13)" |
| Tracking cameras (HoloLens Sensors) enumerate but at 480M under the USB2 hub instead of 5000M under the USB3 hub; Monado logs no error, but the debug GUI's camera panels are solid pink and `img_xfer_cb` logs "Invalid frame magic" for every frame | Same visor-end marginal contact, this time degrading the SuperSpeed branch enough to corrupt (not drop) the camera transfer's own header bytes — Monado never sees an error because the corruption happens below its own checks | Reseat visor-end connector; verify with `lsusb -t` (HoloLens Sensors back to 5000M) before trusting any tracking data | "The silent 100% camera-frame-loss signature" |
| `wmr_read_config_part` fails ("Failed to issue command 0b..."), HMD device creation fails outright, appearing AFTER camera corruption was already seen in the same session and after repeated relaunches | Same marginal contact, escalated further by repeated panel-activation power cycling while chasing the camera issue — **do not keep retrying** | STOP relaunching; reseat visor-end connector before any further attempt | "Retry escalates the fault" |

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

> **`[C→A]` is the USB-C-to-USB-A adapter.** The headset's USB leg does not reach the PC
> directly, and a passive adapter carrying every USB conductor is a contact point like any
> other: it belongs in the reseat ladder. Parts and evidence are in "The USB-C-to-USB-A
> adapter fault class" below (HP `L56522-002` → Nisuta `NSADU30UC`).

Facts established by direct measurement:

1. **The visor-end connector is detachable** — behind the magnetic face gasket, a long
   proprietary (OCuLink-style) plug. It carries **every** conductor group between cable
   and visor: DP lanes + AUX/HPD, USB3 SuperSpeed pairs, the USB2 D+/D- pair, and the
   power rails. One marginal contact there can therefore take out *any subset* of
   functions while the rest keep working — which is exactly what makes its failures look
   like several independent faults.
2. **Both Cypress hubs live inside the visor, not in the breakout box.** With the
   visor-end connector unplugged and the cable still in the PC, the host enumerates
   *nothing* (measured: zero devices). The cable presents no USB electronics of its own.
3. **The conductor groups fail independently.** Measured sequence: DP + panel
   power dead while USB was a perfect 5/5; hours later the USB2 pair dead
   (`error -71`, kernel printing `Cannot enable. Maybe the USB cable is bad?`) while
   SuperSpeed still enumerated. Four groups, four separate contact sets.
4. **Who hangs off what**: sensors (`045e:0659`) are on the USB3 hub; the companion
   (`03f0:0580`, HID control + activation) and audio (`0bda:4c15`) are on the USB2 hub.
   Corollary already in `docs/06`: sensors present + companion absent = USB2 branch down
   = no activation possible = panel will never light = DP will never hotplug. **But the
   reverse implication is NOT valid**: in the original failure the companion was healthy and the
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
10. **The DP connector name changes per machine** (and per board): the headset has been
    `DP-1`, `DP-2` and `DP-3` on different machines. Never hardcode it — scan `/sys/class/drm/card*-DP-*`.

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

Recovery ladder when a step fails, also cheapest first — **this order is backed by a
controlled result**: (a) replug USB at the PC (didn't fix the original fault);
(b) different USB controller (didn't either); (c) cut mains/brick power ~20s
(didn't); (d) **reseat the visor-end connector** — *this* fixed everything at
once; (e) only if (d) fails repeatedly: replacement cable ("HP Reverb G2 cable rev 2A" /
"OCuLink to USB-C + DP"). Since (c) alone had already failed while (c)+(d) together
succeeded, the reseat is the proven fix, not the power cycle.

## The failure timeline, and the three wrong verdicts

The original failure involved two machines and two OSes:

1. **DP dead, no logo, USB 5/5** on the first machine. Verdict ① "residual software state".
2. **Same SSD on a second machine**: no logo anywhere, USB2 branch dead (`error -71`).
   Verdict ② "the cable died, buy rev2A". (A Windows boot on the first box had shown the
   logo once but no picture, which a truly dead cable would not do.)
3. **Visor-end reseat + mains cycle** → USB 5/5 back, `panel.py activate` → logo lights,
   `DP-3` `connected` with the 384-byte EDID, lease taken at 4320x2160@90, real VR180 content
   played cleanly at 90 Hz. Verdict ③ **the visor-end connector**.

Why each wrong verdict looked right, for the next reader:

- ① died when the same SSD failed identically on the second machine — no shared software left.
- ② was the community-classic story (G2 cables DO fail en masse, rev2A exists) and the
  kernel literally said "cable is bad". What it could not explain: the Windows logo blip —
  a truly dead cable does not resurrect for one host. That anomaly was the tell.
- ③ explains **everything** with one fault: a single connector carrying all groups, whose
  contacts dropped group by group as handling worked it looser, intermittently at first,
  then came back wholesale on reseat. The port and USB-C-orientation effects recorded in
  `docs/06` likely mattered by *mechanically disturbing the same connector*, not because of
  the ports themselves.

**Meta-lesson: when one anomaly refuses to fit an otherwise convincing verdict (here the
Windows logo), that anomaly is the thread to pull — not a detail to note and move past.** The
reseat costs zero and was first in the community's own fix list; it should have been tried
before any verdict.

## Recurrence: the reseat is a mitigation, not a repair

~40 minutes after the reseat (and right after a flawless 25-minute steady-state run), the USB2
branch dropped again on the screen-off/service-restart transition. Two new data points:

- **Soft vs. hard states**: this recurrence recovered with step (a) alone — a PC-end USB
  replug, instant clean re-enumeration, zero `-71` retries. The original death needed
  step (d). Same contact, different severity.
- **A third failure mode exists**: *enumerates but HID I/O fails* — `lsusb` shows the
  companion, yet every `wmr_hmd_activate_reverb` Send/Get returns -1 and the device number
  climbs by dozens per minute (violent re-enumeration flapping). Triggered by **panel
  activation attempts**: the power transition through the marginal contact knocks the USB2 hub
  out (`docs/06`'s "hub reset scales with panel load" mechanism, amplified). So check `lsusb`
  device NUMBERS across a few seconds, not just presence, before trusting the branch.

**Operational guidance**: steady-state sessions are fine; what kills the contact is **panel
on/off cycling** — activation spikes and screen-off re-enumerations. Minimize service restarts
and batch content into one session. Also: **controller hot-add does not exist** — controllers
powered on against a running session never reach Monado (it probes at startup only); power
them on BEFORE starting the service.

## The tracking freeze — a fourth symptom of the same cable

Symptom: ~27 minutes of video with **head tracking dead** (image glued to the face), noticed
only afterwards because front-facing VR180 is easy to watch without turning. A reproduction
attempt showed tracking healthy (`HELLO_XR_POSE_STATS=1`: 3DoF jitter floor at rest mean
0.0003-0.0016°/frame, max 0.056°, identical to the historical measurement; real movement mean up
to 1.5°/frame at a steady 90 fps), so the freeze was session-specific, not a player or driver
regression.

Best-supported hypothesis: a USB hiccup from the degraded contact killed Monado's WMR reading
thread (`wmr_run_thread`, the IMU packet reader) mid-session, and **Monado never restarts it** —
pose freezes at the last value while compositor, video and panel continue perfectly (the HID
channel showed the same intermittency, a `screen_on` write returning -1 seconds after a
successful activation). Upstream improvement candidate, not filed: auto-restart of the reader
thread on EOF/error.

**Field guide**: image glued to the face + everything else fine → `grep "Exiting reading
thread" jack-in-wayland.log` while the session is still up; a session restart recovers it
(`jack-in-wayland.sh` keeps one previous log generation, `jack-in-wayland.prev.log`).
Mechanical cable movement during long play sessions never triggered anything; failures cluster
at **power/state transitions** (activation, screen-off), not under flexing. That fits both a
transition-sensitive marginal contact and a "wedged visor electronics" reading (the visor is
dual-powered, brick 18.5 V + USB 5 V, so only the visor-end disconnect removes all power from
its chips; cutting only the brick or only USB failed, the reseat cutting everything worked).
Discriminating test for the next hard failure: unplug USB **and** brick together for ~20 s
*without* touching the visor connector — if that recovers it, it is wedged electronics, not the
contact, and there is a no-disassembly recovery.

## The power rail, and why "dead power rail" was wrong

A session found the panel dead again (no logo, no DP hotplug on any of three DP connectors)
while the USB2 branch needed two visor-end reseats to recover. The power path was isolated by
elimination:

1. **Brick**: own indicator LED lit, receiving wall power.
2. **Breakout-box barrel connector**: unplugging just the 18.5 V line dropped the *whole* USB
   tree (5/5) at the same instant (five simultaneous `USB disconnect` lines) even though nothing
   on the USB side was touched. Handling the breakout box at all disturbs this cable enough to
   affect branches you did not mean to touch. Reconnecting restored a stable 5/5; the panel
   stayed dark throughout.
3. **GPU port**: moving the DP cable to a different GPU port changed nothing (all three
   connectors read `disconnected`).

That pointed at a dead rail inside the visor-end connector and pushed the rev2A cable to "the
next real step". **That escalation was premature.** The next session, on a cold boot with zero
reseat and USB already 5/5, showed the same dark state; running the step that had been skipped,
`./scripts/panel.py activate`, lit the logo at once and `DP-1` went `connected` with the healthy
384-byte EDID. The full stack (`jack-in-wayland.sh 1` + `play360.sh`) then ran end to end with
no cable or connector touched. Windows behaves the same: the HP logo **always starts dark at
cold boot** and stays lit only once SteamVR has activated the headset. So **the G2 never raises
its own DP hotplug at cold power-on on any OS; it always needs the WMR activation HID sequence
first** — normal behaviour, not a fault.

**What this does not undo**: the USB2-branch dropouts and the tracking freeze were never
explained by "missing activation". **Practical takeaway: before concluding "the panel is dead",
always run `./scripts/panel.py activate` once and look at the visor** — do not skip step 3 of the
ladder, especially right after a reseat that was chasing a different symptom.

Side fix from the same session: `jack-in-wayland.sh` used to report "Socket ready" whenever the
IPC socket existed, even if the compositor had failed to find a leasable connector. It now
requires the log to show a real video mode taken; on failure it kills the stale service and
exits 1.

## Load correlates with disconnect frequency, and audio shares the same marginal contact

The USB2 branch was caught mid-storm: cycling on its own every ~6-12 s with **nothing running**
(66 reconnects of `usb 3-2`, hub `04b4:6506` + audio `0bda:4c15` + companion `03f0:0580`, in
one 60-minute `journalctl -k` window). The `panel.py activate` fix still stands for the
cold-boot dead-panel case, but the underlying contact is not calm.

- **Audio**: PipeWire creates/destroys the ALSA sink on every USB2 cycle, so a stream that
  starts or is running mid-cycle can land in a disconnected window and produce nothing, with no
  error anywhere. `./scripts/hmd-audio.sh {mute|unmute|status|set <pct>}` resolves the sink by
  name via `wpctl` and survives the renumbering. Ruled out: an "off-ear speaker position"
  theory — the G2 has no proximity sensor near the speakers, only one near the nose bridge
  (`WMR_CONTROL_MSG_IPD_VALUE`) for wear detection.
- **Crude load experiment**, one 60 s `journalctl`-counted window per condition (small sample,
  monotonic): idle = 1 disconnect, standalone audio tone = 0, a Monado video session alone = 5,
  video + simultaneous desktop audio = 8. More concurrent activity on the shared HID/USB2 channel
  tracks with more disconnects, consistent with `docs/06`'s mechanism. (`hello_xr` has no
  audio decode, so "video+audio" means a Monado session beside an unrelated desktop stream.)
- **Windows agrees**: on this unit display and audio failures were historically anti-correlated
  there too (panel not working → audio fine; panel active → audio cuts out): the same shared
  marginal contact on a different OS and driver stack, i.e. a physical-layer property of this
  unit, not a Monado bug.
- **A concrete companion-channel failure**, caught with `WMR_LOG=debug`: Monado's
  `control_read_packets()` logged `Error reading from companion (HMD control) device. Call to
  os_hid_read returned -1` on every poll for a sustained ~35 s while `lsusb` still showed 5/5 —
  the control endpoint alone was unreadable. Proximity/IPD sensor status is therefore untested
  as working, not confirmed broken. A "calm" baseline on this unit is low single digits of
  disconnects per 60 s idle; zero is not realistic.

## Reseating mid-session (2026-08-10) -- `panel.py activate` alone isn't enough once Monado already has a lease

**Symptom**: a VR session already running fine, then "logo on, panel off" mid-session (not at
cold boot). A reconnect at the **PC-side USB connector** caused a real DP disconnect/reconnect
(`/sys/class/drm/card0-DP-2/status` back to `connected` ~8 s after a `panel.py activate`), but
the backlight **stayed dark** and the game had silently fallen back to a flat 2D window.
`panel.py activate` kept reporting clean success before and after — the HID activation
genuinely works, it is just not the broken layer.

**Open anomaly**: per the anatomy, DP and USB take *separate* physical paths from the PC into
the breakout box and combine only at the visor-end connector, so a pure PC-side USB reconnect
should not touch DP state at all. It did. A concurrent USB2 storm muddied the kernel log; a
clean repeat with DP status monitored live would show whether the breakout box's DP and USB
lines are more coupled than the diagram shows.

**Root cause**: `panel.py`'s HID activation and Monado's DRM lease are two separate channels.
The `monado-service` already running before the reseat held a lease on the old connector
instance; the physical disconnect invalidated it and the compositor never re-acquires one.
Re-running `panel.py activate` restores panel/backlight power but does nothing for a compositor
holding a dead lease handle: logo on, DP `connected`, EDID fingerprint matching, nothing scanned
out.

**Fix (order-dependent — skipping step 4 is what leaves the backlight dark while every earlier
step reports success)**:

1. Reseat/reconnect the cable physically (visor end is the proven fix; a PC-end reconnect worked
   once, not established as reliably equivalent).
2. Wait for the headset's `/sys/class/drm/card0-DP-*/status` to read `connected` again (a few
   seconds).
3. `./scripts/panel.py activate` (HID layer, powers the panel back on).
4. **Kill the old session** — `monado-service`, Steam, the game — plus
   `rm -f /run/user/1000/monado_comp_ipc`.
5. `./scripts/jack-in-wayland.sh` from scratch to get a genuinely fresh DRM lease.

**General lesson**: any physical hotplug event (reseat, replug, cable wiggle) *while Monado is
running* needs a full Monado restart, not just a panel re-activation. "Panel never got the HID
command" and "compositor's lease is stale" look identical from outside (logo on, panel dark) but
need different fixes.

## Connector enumeration vs. `disconnected`, a dead-end technique, and `non-desktop: 0`

Findings from the everyday X11+KDE system (driver 550.163.01, unpatched, own `jack-in.sh`):

- **Counting DRM connectors is NOT a valid link signal on this NVIDIA setup** (dead end, don't
  reintroduce). With the visor-end cable unlinked the kernel listed only the 4 desktop connectors
  under `/sys/class/drm/card0-*`, and a first attempt to gate launches on that count was
  reverted: the whole failed sequence turned out to be the 18.5 V brick being unpowered, and a
  real launch then succeeded while the count still showed the same 4 connectors. NVIDIA also
  exposes no per-connector `non-desktop` sysfs attribute (the file does not exist); that
  property is only readable via libdrm's connector-properties ioctl or `xrandr --prop`.
- **Kernel WARN on `kill -9`**: when `wake_panel()`'s start-briefly-then-`kill -9` sequence ran
  while the headset connector was not there to acquire (`vkAcquireXlibDisplayEXT:
  VK_ERROR_UNKNOWN`), the kill triggered a WARN inside `nv_drm_revoke_modeset_permission`
  (`nvidia_drm`, 550.163.01; stack through `drm_file_free` → `drm_release` → `__fput`). Non-fatal
  (modules stayed loaded, `nvidia-smi` responsive, P8 idle) but reproducible; check `dmesg -T`
  after a failed wake attempt rather than re-triggering it.
- **`non-desktop` as a diagnostic**: on a working setup `xrandr --prop` reads `non-desktop: 1`
  for the headset connector; Monado's `comp_window_direct_randr_init` needs at least one such
  output and otherwise fails with "No non-desktop output available" (more specific than the
  generic `VK_ERROR_UNKNOWN`). After several service restarts the property was seen reading `0`
  on every connector, together with the USB2 branch dropping to 2/5 after a PC-side-only reseat
  (recovered only by a visor-end reseat) and an intermittent firmware-side error
  `hololens_handle_debug: "ERROR: CommandSet st 0, cmd 0, reqCmd 23"`. Read together this looks
  like a degrading EDID read on a marginal link (the non-desktop bit lives in the panel's
  EDID/DisplayID), not three unrelated bugs. Not proven; check `xrandr --prop`'s `non-desktop`
  value first the next time this cluster recurs. The adapter section below explains what finally
  made it stop.

## The USB-C-to-USB-A adapter fault class (reqCmd 23 / non-desktop: 0)

Swapping the USB-C-to-USB-A adapter between the PC and the breakout box (the official HP unit
`L56522-002` that shipped with the headset → a Nisuta `NSADU30UC`) ended the `reqCmd 23` /
`non-desktop: 0` cluster: a restart-heavy 6DoF development block that reproduced the fault
before (several full `monado-service` restarts, two full rebuilds, a ~20 s `get_tracked_pose`
run) showed zero recurrence of `reqCmd 23`, `non-desktop: 0`, USB2 drops, hub resets or
`LIBUSB_ERROR`, with tracking stable throughout. A faster adapter would not help: the headset's
own USB3 hub (`04b4:6504`) negotiates `5000M` even on a `10000M` host port, so any adapter that
reaches 5 Gbps gives all the bandwidth this headset can use.

1. **Root cause, best evidence**: the adapter was very likely a major contributor to the
   `reqCmd 23` / `non-desktop: 0` cluster. This is a **distinct fault class** from the visor-end
   contact (DP dead + USB2 `error -71` + hub resets scaling with panel/HID load, fixed by reseat):
   two independently confirmed physical faults on one unit. First-party does not mean immune to
   degrading.
2. **Status**: validated in one session, not cross-session-confirmed.
3. **Recovery order**: for the `reqCmd 23` / `non-desktop: 0` signature, check or swap the
   USB-C-to-USB-A adapter **first**; reseating is still the first move for the other signature.
4. **What would falsify it**: the cluster recurring under a similarly restart-heavy session on
   the new adapter. Then do not re-suspect the brick (ruled out by the elimination chain above)
   and do not swap the same adapter again without new evidence; move to the visor-end
   connector/cable.

When a cheap, easy-to-swap component sits between the machine and a hard-to-reproduce
intermittent fault, swap it early and rule it out (or in) before spending diagnostic hours.

## The seat lottery (T171, 2026-08-13) — one pin group per seating, every conductor healthy

**Context**: the headset failed to be detected
on BOTH Windows systems, and on Linux showed the classic `error -71` /
`Cannot enable. Maybe the USB cable is bad?` storm on the USB2 branch at boot. Ten
seatings and one control experiment later, the verdict is **nothing is broken**: this is a
marginal mechanical seat at the C-plug/adapter that engages a different subset of pin
groups on every insertion.

**The measured pattern that gives it away** (all on the CPU-fed controller `0000:09:00.3`
except where noted):

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
   This is NOT the wholesale conductor-group death of the original failure.
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
6. **Standing rule confirmed again**: only rear, CPU-controller ports work at all; the one
   chipset/front-port attempt enumerated nothing, and the native mobo USB-C never carried the
   G2's USB2 pair in any orientation (it has never worked for this headset on any machine).
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

**Operational consequence**: `scripts/power-on.py` now diagnoses
WHICH branch is missing (`branch_flags()`), prints these exact reseat instructions in
probability order (`reseat_instructions()`), and waits interactively for the fix instead
of dead-ending — with `[s]` to skip VR and continue to the plain 2D desktop. Camera
negotiated speed (step 3) got the same treatment, since "cameras enumerate at 480M through
the hub's USB2 face" is exactly what a missing-SS seat looks like.

## The silent 100% camera-frame-loss signature (2026-08-15, everyday system)

The seat-lottery section diagnoses the missing-SS-branch *enumeration*. This one is what
happens to the camera **image data itself** once a degraded branch carries traffic anyway — and
Monado's own logs give **zero indication anything is wrong**, unlike every other signature here.

**Measured signature** (brick power fine, DP/panel fully recovered, `hello_xr` at
`XR_SESSION_STATE_FOCUSED` with `PositionTracking=True`): `lsusb -t` showed the HoloLens Sensors
(`045e:0659`) at 480M under the USB2 hub (`04b4:6506`) instead of 5000M under the USB3 hub
(`04b4:6504`); bus 4 (USB3 root) had zero children. With
`WMR_CONSTELLATION_CONTROLLERS=1` and `CONSTELLATION_TRACKER_LOG=trace`, **236 of 236 camera
frames logged `WARN [img_xfer_cb] Invalid frame magic (got <garbage>, expected 2b6f6c44).
Dropping`** — 100% loss from the first frame after `wmr_camera_start`. The "got" values are
nibble-repeat garbage (`04040404`, `0a0a0a0a`...), consistent with a marginal SuperSpeed contact
corrupting the bulk transfer's own header bytes rather than failing the transfer. Zero blob
observations reached the constellation tracker; the debug GUI's camera panels were solid pink
(an uninitialized texture no valid frame ever wrote to, not a rendering bug).

**Why it is dangerous**: `wmr_camera_start` logs cleanly, the logged framebuffer size
(`2560 x 480 - 1233408 transfer size`) is the normal value, and `send_calibration` succeeds for
all 4 cameras. The corruption happens below anything Monado checks, so a session run this way
looks like "6DoF just isn't tracking" or "the constellation gate is too strict" — a plausible but
wrong software diagnosis for 100% physical-layer data loss. Only an explicit grep finds it:
`grep -c "Invalid frame magic" <log>` — a handful is transient, a count that never stops is this
fault. `jack-in.sh` on the everyday system greps for it a couple of seconds after "Jacked in" and
warns loudly; the lab-side `jack-in-wayland.sh`/`power-on.py` do not yet. Fix: visor-end reseat,
verified by `lsusb -t` (Sensors back to `5000M`) and a repeat of the same trace-log test.

## Retry escalates the fault (2026-08-15)

With camera corruption already confirmed, three more `jack-in.sh` relaunches in a row all failed
identically, earlier than the display stage: `ERROR [wmr_read_config_part] Failed to issue
command 0b: 08 19 00` → `Failed to load headset configuration!` → `XRT_ERROR_DEVICE_CREATION_FAILED`.
The companion's HID config-read channel, which had answered in that session's earlier launches,
stopped responding by the third retry. The mechanism is the one under "Recurrence": panel
activation's power transition knocks the marginal contact looser, and every relaunch sends that
sequence. A session that started with a healthy panel and only corrupted cameras ended with the
whole HMD failing to construct.

**Standing rule** (same physical cable on every machine): once a launch fails at HID config-read
(`Failed to issue command`), **stop; do not relaunch.** Two consecutive failures at this stage,
or one config-read failure in a session where camera corruption was already seen, means reseat
the visor-end connector before any further attempt. `power-on.py`'s
`branch_flags()`/`reseat_instructions()` diagnose *which* branch is missing, but nothing yet
counts consecutive config-read failures and refuses to keep cycling.

Counting note: the known-good enumeration is **5 devices** (USB2 hub, audio, companion, USB3
hub, HoloLens Sensors); a count of 4 that misses the USB3 hub instance (`04b4:6504`) was once
wrongly called "healthy". Count the hub instances too.

## Known-good fingerprint (2026-08-16)

"It works" used to be a subjective read; this is an objective, checkable identity for the good
state. Matching values mean the problem is the usual physical/enumeration fault; a mismatch
(different firmware version) means something genuinely changed.

```
Hub chip: one Cypress chip presenting both the SuperSpeed and USB2 personas, one shared
          identity (container ID) for the whole composite device (all 5 branches)
Companion: 03f0:0580 (HID child collection stable across reconnects)
Sensors:   045e:0659
Headset OEM firmware (three components):
    QA85QAPV1/1.2 | QA85QBLV1/7.0 | QA85QDPV1/50.49
Display EDID identity:
    220e:36c1 (HPN36C1) -- cross-checked against docs/12/26, unchanged
```

(Device serials and container GUIDs are deliberately not recorded in this repo.)

**Validated two independent ways**: (1) a PC-end USB-C unplug/replug (NOT a visor-end reseat),
same port, same orientation, cold ~8-10 s gap, gave **6/6 clean 5/5**, every device number freshly
incremented (genuine re-enumeration, no settle time needed) — in sharp contrast with 0/3 for a
visor-end reseat under the same conditions, so the two ends of the cable are not interchangeable
levers; (2) a real Windows gameplay session on that state ran with no audio cuts or controller
weirdness.

**Open items flagged then**: whether the PC-end reconnect also rescues a bad orientation or port
(only tested from an already-good seat; the first datum below says no); whether the USB2 branch
flaps spontaneously mid-session on Windows under sustained load; controller and headset
auto-standby timing on Windows (measured on Linux/Monado only, ~15 min); whether Oasis's native
stack implements HMD worn/presence detection where Monado/xrizer does not.

**Companion-error storm vs. CPU spin**: at complete idle (no SLAM, no constellation, no app,
headset untouched) the companion-error counter climbs at the same rate as under full load, while
`monado-service` CPU stays under 1.2%. A full-scale live capture under Aircar + constellation
had pinned `monado-service` at 400%+ CPU with a peak of 472175 companion errors. So the storm
(load-independent, always available) and the CPU spin (load-dependent, mechanism unknown) are
two separate things.

---

## The Windows control, and the verdict this document had been waiting for (2026-08-19)

Every measurement above was taken on Linux. `windows-kit/usb-storm-monitor.ps1` was run for 79
minutes on the *same physical machine* with the SSD swapped (same board, USB host controllers,
cable and headset; **OS the only variable**), with the G2 driven by Oasis + SteamVR throughout
and five titles played:

* USB2 branch: **274 drops, 3.47/min, outage p50 2.9 s, p90 10.5 s, incomplete 27% of the
  session**, twelve of them passing through Windows' own `PROBLEM:Error` state.
* USB3 branch (hub-ss + hololens-sensors): **zero drops**, as on Linux.
* Escalation within the session as on Linux: 0 events in the first 10 minutes after
  enumeration, then 38-52 per 10 minutes.

Against Linux's 0.92-4.63/min and p50 3.0 s, that is the same fault: **the storm is the link.**
The rev2A cable goes back on the suspect list as an experiment that discriminates *cable* from
*connector/visor*; if a new cable changes nothing, the remaining suspects are the visor-side
USB2 PHY and this unit's connector, not the host.

The *consequences* are Linux's: Windows rode 274 disconnects while five titles played normally
(only audio cut out), whereas on Linux the same outages produce ~83 companion HID read
failures/s and a frozen presence sensor. Full analysis: `docs/60-windows-usb-storm-control.md`.

---

## The rev2A cable is not a fix, it is a different lottery ticket

The Windows control makes "buy the rev2A" tempting as the answer. It is not, going by the
community record:

- **HP never shipped a cable that is 100% good.** No revision fixes this class of fault
  outright; v1 and rev2A both have populations reporting the same symptoms.
- **There are no third-party alternatives.** The cable carries DP, USB3, USB2 and 18.5 V through
  a proprietary connector into an active repeater box; nobody else makes one.
- **The luck is not one-directional.** Some units are stable on rev2A, some are stable on v1
  and get worse on rev2A, some are unstable on both.
- **The revisions are not identical hardware.** rev2A adds a button v1 lacks, so behaviour
  differences are not automatically "the new one is better".

Treat the swap as a legitimate *experiment with a real failure mode* — the cheapest way to
discriminate cable from connector from visor-side PHY — not as a repair. Keep the old cable.

## Port preference, and one thing this project will not test

**Rear sockets only, and on the right controller** — see `docs/00`'s port-controller section and
`scripts/usb-port-map.sh`. The **front-panel USB3 header has never been tested here and
deliberately will not be**: it adds an internal header plus a length of case wiring, another
marginal joint in the chain. **Potentially
unsafe, not recommended.**

## This unit's cable is **Rev A**, and the brick is 18.5 V (2026-08-19)

The cable revision was read off its own label (not assumed from a part number): this headset has run its whole life on the **original Rev A cable**,
the revision with the community's mass-failure record. That does not make the swap a fix (see
above), but it makes the experiment well-posed: original versus replacement, on a link whose
fault rate is measured on both OSes (3.47 drops/min Windows, 0.92-4.63 Linux, USB3 immune on
both).

| | |
|---|---|
| **This unit's cable** | 6 m active, SPS **`M18238-001`**, regulatory model **`TPC-B001C`**, **no switch** |
| **The replacement** | SPS **`M52188-001`**, HP description *"SPS-CA ACTIVE 6M BLACK **/W SWITCH**"*. Also sold as `22J68AA` / `L72080-002` |

Three facts converge: the label says "Rev A", the cable has **no button**, and its part number
is in the older family while the replacement's official description ends in "/W SWITCH".
`M18238-001` is also what resellers list as an older G2 cable revision. The cable has its own
regulatory model family (`TPC-B001C`, distinct from the headset's and controllers'
`TPC-Q077-*`): a separately certified active device with its own silicon, not a wire.

**The cable carries a firmware version, and HP replaced every Rev 1 cable for free.** The inline
box has no label on its visor-facing side; a sticker on the cable carries a serial (not recorded
here) and a firmware marking, approximately `fw 0x5_3 … 0x5_10` (several characters not legible,
value not treated as known). The finding is that the marking exists at all: the inline box holds
programmable silicon. Per forum and reseller accounts (not HP documentation), HP ran a free
replacement programme for every Revision 1 cable; the rev2 box adds a **qualified hub that
cleans up the signal** plus the on/off button, aimed at *power issues*. Next to the measured
pattern (USB2 branch storms, USB3 branch never drops on either OS), a hub-silicon change inside
the link box is exactly the shape of fix that would address a USB2-branch-only fault — without
promising anything, since units also get *worse* on rev2.

**The brick is 18.5 V, not 12 V.** Read off the brick's label: spare `381090-001`, P/N
`380467-001`, series `PPP009H`, model `PA-1650-02H` — one part, an **HP 65 W / 18.5 V / 3.5 A
adapter with a 4.8 × 1.7 mm barrel**, an ordinary HP laptop charger reused for the G2. "12 V" had
been written down early and never measured. The architectural claims are unaffected (panel,
backlight and ANX7530 bridge power from the brick's rail, not USB; no rail means no HPD), but
`docs/26` tells readers to test or replace the brick: anyone hunting a 12 V supply would have
risked destroying hardware by forcing a mismatched supply into the barrel jack.

### A cold PC-end replug does not rescue a seat that was never good

First test from a never-good state: socket `4-1` (CPU controller, never yet 5/5), PC-end USB-C
unplug, ~10 s cold, replug same port same side → **2/5 again**, identical signature on both
insertions (stable for 2+ minutes). The USB2 pair is not silent: the kernel detects a high-speed
device on the 480M sibling port, fails `Cannot enable` three times, power-cycles the port, and
dies on `error -71`, while SuperSpeed enumerates cleanly beside it. The PC-end lever restores a
branch to a seat that *has already proven it can carry it*; it does not convert a seat that
never has. One socket, a first datum, not a law.

### A new board: DP connector renamed, and a USB2-branch fault that was a chipset-vs-CPU port mixup

On a dedicated Gigabyte A520M K V2 board (Ryzen 5 5600X, RTX 3060 Ti) the headset is **`DP-2`**,
whereas an earlier board with the same CPU model used `DP-1`: don't trust a remembered connector
name, not even by CPU model; scan `/sys/class/drm/card*-DP-*` fresh every time.

USB came up 5/5 at boot, then regressed to 2/5 after a PC-end replug; two visor-end reseats plus
220 V mains cycles changed nothing (the kernel log was literally silent on the USB2 bus). None
of those was the cause: the USB-C plug sat in a port fed by the **A520 chipset controller** (PCI
`02:00.0`), not the CPU's own controller (PCI `07:00.3`, still USB-ID-named "Matisse" on this
Vermeer-class CPU — a shared-silicon label, not a CPU-generation tell). **Moving to a CPU-fed
rear port fixed USB2 immediately, with no reseat or power cycle** — 5/5 within seconds. With the
companion back, `panel.py activate` could finally run (it had been failing silently for want of a
companion device) and `DP-2` went `connected` with the 384-byte EDID. DP reading `disconnected`
the whole time USB2 was down was uninformative, not a second fault.

Which physical rear socket is CPU-fed is a property of each board: measure with `lsusb -t` +
`lspci -nn` (device under `07:00.3` vs `02:00.0`) before trusting any port-position claim.

## 2026-09-05: step 4 (DP-dead) re-confirmed live, plus a stale-DRM-lease follow-on

During a live troubleshooting session the exact step-4 signature appeared: all three DP
connectors `disconnected`, USB a healthy 5/5, `scripts/hmd-connector.sh` empty, and
`./scripts/panel.py activate` produced **no logo** (the step-0 discriminator had already run
clean, ruling out standby). A USB-C orientation flip and several PC-end unplug/replug cycles
changed nothing (USB stayed 5/5, DP stayed `disconnected`), as the "Do NOT" list says. **The
visor-end reseat worked immediately**: the next `panel.py activate` produced the HP logo, which
then went dark again as expected without a video signal, and re-running `jack-in-wayland.sh`
resolved it.

Two follow-ons:

- A stale `jack-in-wayland.sh` failure marker from the earlier (genuinely broken) attempts
  blocked all further launches ("Refusing to launch: the previous attempt failed") until cleared
  with `--force up`. The marker exists to stop blind relaunch loops from worsening a marginal
  connector and worked as designed; `down` never touches it.
- Later, a manual `panel.py activate` run independently of Monado after a presence-driven blank
  again produced the HP logo while `/sys/class/drm/card*-DP-*` stayed `disconnected`. That is the
  **stale DRM lease** case (step 4 point 4), not a hardware fault: Monado's compositor does not
  re-lease a connector because the panel woke via a HID command it did not issue. Fix: kill
  `monado-service` + `rm -f /run/user/1000/monado_comp_ipc` + relaunch fresh.
