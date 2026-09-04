# 95 — Booth demo runbook

**Audience: the human running the booth, not a developer.** Everything here is measured,
not guessed — sources are `docs/96` (today's power sweep), `docs/84`/`docs/80` (per-title
tuning), `docs/76` (demo-day prep), plus a live verification done today (2026-09-03, see the
Dalí-3dof note below). If a step here ever disagrees with those docs, the docs win; come
back and fix this file.

**Rig**: RTX 3060 Ti (210 W max), Monado + xrizer on Linux, HP Reverb G2.
**Approved titles**: Aircar (appid `1073390`) and Dreams of Dalí (appid `591360`), each with
**two head-tracking modes** — see §2. Dashboard: `http://127.0.0.1:8765/`.

**Comfort policy, read this before doors open**: Dalí's **6dof** (positional) tracking
carries a real, known prediction-latency artifact (a brief "settle" when turning the head
fast — `docs/96` §8.1, §9). It is not dangerous and it is not a fault, but it is a genuine
nausea trigger for a guest who has never been in VR before. **Dalí's 3dof mode does not have
this problem at all** — verified live today: Dalí's navigation is 100 % gaze/orientation
based (its own start screen: *"place the pointer on a sphere for 3 seconds to begin, and on
any sphere to navigate"*) — it needs no positional tracking, so 3dof is fully sufficient for
the whole experience, and with no SLAM running there is no microajuste (same platinum path as
Aircar 3dof; 90 fps, CPU dropped to ~16 % vs. 55–92 % in 6dof).

**So the booth has two first-timer-safe, platinum demos, not one: Aircar 3dof (gamepad) and
Dalí 3dof (gaze). Dalí's 6dof mode is a separate, gated upgrade for experienced/consenting
guests only — never a first contact.** Full rule in §4.

---

## 1. Pre-flight checklist (run in this order, every time the booth opens or restarts)

- [ ] **1a. Clean state.** Nothing should be running from the last session/test:
  ```
  python3 ~/vr/vr-launcher.py stop all
  python3 ~/vr/vr-launcher.py status        # must read clean
  pgrep -af "monado[-]service"              # must print nothing
  ```

- [ ] **1b. Display up.** Run the consolidated check:
  ```
  ./scripts/preflight.sh
  ```
  It checks, in order: USB (5/5 headset devices), controllers, and the HMD's real DP
  connector (EDID fingerprint + `non-desktop=1`, not just "a DP port is connected").
  - **If the DP-connector step is NOT READY**: run `python3 scripts/panel.py activate`,
    then **look inside the visor**. This is the project's one non-negotiable rule
    (`docs/22`, `CLAUDE.md`): the OpenXR/Vulkan stack can report a happy 90 fps with the
    panel completely black. A dashboard/log green light is never proof by itself — only a
    human looking inside the headset is.
  - **If the panel stays dark after `activate`**: reseat the cable at the **visor end**
    first (`docs/22`); if that doesn't help, check the 18.5 V brick. Don't re-diagnose
    this in software again — `preflight.sh` already rules out compositor/Monado causes.
  - **Known caveat, ignore it for the booth**: `preflight.sh`'s controller step checks the
    WMR **motion controllers**. None of the four approved (title × tracking-mode)
    combinations use them (Aircar = gamepad, Dalí = gaze-only in either mode), so a
    "controller NOT READY" from this one line is expected and harmless — don't chase it.
    What actually matters is step 1c below.

- [ ] **1c. Controllers/gamepad ON before Monado starts.** There is no hot-add — a device
  powered on after the compositor is already up will register as `<none>` for the whole
  session, and only a full `down` → `up` cycle fixes it.
  - **Aircar**: Xbox pad powered on and connected. Confirm: `lsusb | grep 045e:028e`.
  - **Dalí (either mode)**: nothing to power on — headset-only, no controller at all.
  - **Ask before launching, not after** you've already started Monado.

- [ ] **1d. Power watchdog active.**
  ```
  systemctl status vr-power-watchdog.service
  ```
  should be `active (running)`. The dashboard's power row should show a real **SAVER**
  (idle, minimum watts) or **PERFORMANCE** (session/game live, full watts) state — not
  *"unknown — vr-power-watchdog.service not installed."* It flips automatically the moment
  a session or game is live; you don't need to arm it by hand. See §2 for setting the
  *per-title* efficient cap on top of that (optional, not safety-critical).

- [ ] **1e. Lit room, only if Dalí 6dof will be offered tonight.** Dalí's 6dof mode needs
  real light to track (dark room → tracking runs away 80–160 m, `docs/80`). Eyeball the
  room; if it looks dim to you, it's dim for the tracker — fix the light before offering the
  6dof upgrade to anyone. **Not required for Aircar or for Dalí 3dof** — neither runs SLAM
  or cameras.

---

## 2. Per-demo operator cards

**Operator talking point — the efficiency dividend.** Every card below sets its own measured
knee cap, not turbo, and it costs nothing: `frame-pacing.sh` reads 0 dropped frames at these
caps (`docs/96` §8, §10). If a guest asks why the rig isn't running "full power," this is a
real, safe answer, not marketing: **"In a 4-hour session, without losing a frame, the rig drew
148 W instead of 210 W — 248 Wh saved, −29.5 %."** (Full math and the assumed guest mix:
`docs/96` §10.)

### Card A — Aircar · 3dof — **platinum, first-contact (active)**

| | |
|---|---|
| **Status** | Approved, first-timer safe |
| **Launch** | Dashboard button **"Aircar · 3dof [approved]"**, or CLI: `VR_LAUNCH_APPID=1073390 python3 ~/vr/vr-launcher.py 1 3dof` |
| **Power mode** | **smart-eco, ~130 W (~62 % of the 3060 Ti's 210 W max).** Measured 2026-09-03: 90 fps, 58 % GPU, ~10 % CPU, 0 late frames (`docs/96` §8.2). To set it explicitly: `sudo ./scripts/vr-power-setup.sh --gpu-limit 62`. Full-eco (100 W / 48 %) also holds a clean 90, just tighter — smart-eco is the comfortable target. Turbo buys nothing here; don't use it. |
| **Tracking** | 3dof — IMU only, rotation only. No SLAM, no cameras (`WMR_CAMERAS=0` in this mode) → zero microajuste, by construction. |
| **Input** | Xbox gamepad. No motion controllers, no hands. |
| **Recenter** | Guest presses the **A button** on the pad if they ever feel "outside" the cockpit. Operator fallback: dashboard **🎯 Recentrar**. (The automatic donning-recentre is deliberately *not* wired on this button — in the 3dof cockpit a runtime recentre only nudges the view a few degrees, it's the game's own re-basing that matters; the A-button/🎯 combo is the real lever, `docs/80` 2026-08-30.) |
| **Comfort / quirks** | Wearer verdict: *"identical to Windows, super fluid, no problem."* No SLAM microajuste at all — this is the Windows-parity path. A brief "flying away" / relocation blip can happen occasionally; it's a known, harmless cosmetic glitch — mention it up front, the A button clears it instantly. |
| **Good scene to start a guest in** | The dense neon city — the demo's heaviest, most visually rich scene, and the one that was actually measured (`docs/84`). |

### Card B — Dreams of Dalí · 3dof — **platinum, first-contact (calm), recommended default**

| | |
|---|---|
| **Status** | Approved, first-timer safe — **the recommended default demo for a guest with no preference** |
| **Launch** | CLI: `VR_LAUNCH_APPID=591360 python3 ~/vr/vr-launcher.py 1 3dof`. **No dashboard button exists for this yet** — it was verified live today (2026-09-03) and the booth button (`demo-591360-3dof`) still needs to be added to `status-dashboard.py`'s `DEMO_LAUNCHES`, mirroring the existing 6dof entry. Use the CLI until that's wired. |
| **Power mode** | **max-reasonable, ~160 W (~76 % of 210 W)**, same as 6dof — GPU load is similar (only CPU dropped, to ~16 %, since no SLAM runs); not yet separately re-measured at a lower cap, so don't try to save further tonight. `sudo ./scripts/vr-power-setup.sh --gpu-limit 76`. |
| **Tracking** | 3dof — IMU only, rotation only. No SLAM, no cameras. The title's whole interaction model is gaze/orientation-based (look at a sphere to select), so 3dof loses **nothing** — verified live today. |
| **Input** | None. Headset-only gaze/head-look, no controllers — hands stay free. |
| **Recenter** | Dashboard **🎯 Recentrar** if the gaze pointer ever feels off-center relative to the scene. The automatic donning-recentre (xrizer 0009) is currently wired to 6dof titles only in the dashboard's booth-button logic — not yet validated for this mode, so use the manual button. |
| **Comfort / quirks** | No SLAM running → no microajuste, same guarantee as Aircar 3dof. Calm, hands-free, no input to learn — a good pick for a guest who looks nervous about a gamepad. |
| **Good scene to start a guest in** | The title's own opening gaze-dwell scene — it gaze-guides the guest forward on its own; no operator action needed once loaded. |

### Card C — Dreams of Dalí · 6dof — **gated upgrade, experienced/consenting guests only**

| | |
|---|---|
| **Status** | Approved, but **not for first-timers** — see §4 |
| **Launch** | Dashboard button **"Dreams of Dali · 6dof [approved]"**, or CLI: `VR_LAUNCH_APPID=591360 python3 ~/vr/vr-launcher.py 1 6dof` |
| **Power mode** | **max-reasonable, ~160 W (~76 % of 210 W).** Measured 2026-09-03: solid 90 fps at only 72–83 % GPU, 0 dropped frames (`docs/96` §8.1). Turbo (210 W) buys zero extra fps — wasted watts. To set it explicitly: `sudo ./scripts/vr-power-setup.sh --gpu-limit 76`. |
| **Tracking** | 6dof — real SLAM via Basalt (position + rotation), same gaze interaction as 3dof but now with real positional movement. **Requires a lit room** (§1e) — dark rooms produce large tracking runaways. |
| **Input** | None. Headset-only gaze/head-look, no controllers at all — hands stay free. |
| **Recenter** | Automatic: the booth button arms xrizer's donning auto-recentre (`WMR_USER_PRESENCE=1` + flag) — the scene recentres itself **~2 s after the guest puts the headset on and looks forward**, no operator action needed. Dashboard **🎯 Recentrar** stays as a manual fallback. **Operator rule**: leave the headset resting on the desk, screen up, until the title has finished loading (~60 s) — *then* the guest puts it on. This keeps the SLAM anchor's starting offset small; skipping it is what produces the "guest starts 1–2 m off" symptom. |
| **Comfort / quirks** | Guests may feel a subtle **"microajuste"** — a brief, smooth camera settle when turning the head quickly. This is a known SLAM **prediction-latency** artifact (`docs/96` §8.1/§9): it is **not** power-related, **not** a fault, and it's being actively worked on — reassure, don't alarm: *"a small settle when you turn quickly — that's expected, not a glitch."* If a guest reports anything beyond a mild curiosity (real queasiness, disorientation), **stop immediately** and either end the session or move them to Card A/B (§4). |
| **Good scene to start a guest in** | The title's own opening gaze-dwell scene — it gaze-guides the guest forward on its own; no operator action needed once loaded. |

---

## 3. Guest flow

1. **Greet, seat** the guest.
2. **First-timer gate — mandatory, ask before anything else**: *"Have you used VR before?
   Any motion sickness history?"*
   - First time, hesitant, or any motion-sickness history → **platinum roster only: Aircar
     3dof or Dalí 3dof.** If they have no preference, default to **Dalí 3dof** (calm,
     hands-free, nothing to learn); offer Aircar 3dof as the active/gamepad alternative.
     **Do not mention or offer Dalí 6dof on this pass.**
   - Guest has already had a comfortable VR session (earlier tonight or elsewhere) **and**
     explicitly asks for "the other one" / positional Dalí → Dalí 6dof is available, **with
     the comfort note from Card C stated up front, before they put the headset on.**
3. **Don the headset**: fit (forehead first, then down, tighten the rear wheel firm-not-tight),
   focus/IPD (turn the bottom wheel until the image is sharp and single, ask directly —
   don't assume yes), let the wear sensor start the picture on its own. Full spoken-line
   script (Spanish, with English gloss) is in `docs/76` §3 — use it, don't re-derive it.
4. **Recenter** per the card for the title/mode running (§2).
5. **Hand the input**: gamepad for Aircar; nothing to hand for either Dalí mode — tell the
   guest their hands are free.
6. **Comfort check-in, every session, no exceptions**: ask at least once mid-session,
   *"todo bien? / all good?"* — offer to stop immediately at any sign of discomfort, no
   explanation needed from them.
7. **Session length**: 3–5 minutes.
8. **End**: headset off the guest first, before touching anything else. Then reset for the
   next guest (§5).

---

## 4. Fallback rule — 3dof (either title) is the default, not the backup

- **Aircar 3dof and Dalí 3dof are the guest's default first contact, every time** — not
  merely a fallback for when 6dof goes wrong. Both are guaranteed-smooth, zero-microajuste
  experiences (no SLAM runs in either).
- **Dalí 6dof is an opt-in upgrade**, offered only to a guest who has already had a good VR
  experience and actively wants it, with the comfort note said out loud first.
- **If a 6dof guest's microajuste ever reads as more than a curiosity** — real queasiness,
  disorientation, "I don't feel right" — **drop to Aircar 3dof or Dalí 3dof immediately.**
  Don't try to talk them through it or debug the rig live.
- **Never let a first-time guest's first VR experience be anything other than a 3dof title**
  (Aircar or Dalí). Never ship a stuttery or uncomfortable first experience — that first
  impression is the whole booth.

---

## 5. Reset for next guest

```
python3 ~/vr/vr-launcher.py stop all
python3 ~/vr/vr-launcher.py status        # must read clean
pgrep -af "monado[-]service"              # must print nothing
```
Wipe the lens/facial interface as normal between wearers, then go back to §1 pre-flight
before the next guest sits down — don't skip straight to launching.

---

## See also

- `docs/96-gpu-fps-per-watt-and-power-modes.md` — the power-mode measurements this runbook's
  numbers come from.
- `docs/84-aircar-tuning-and-per-game-method.md`, `docs/80-aircar-6dof-yaw-drift-plan.md` —
  the tuning history behind each card's config.
- `docs/76-demo-day-final-prep.md` §3–§5 — full spoken onboarding script, the Windows
  fallback go/no-go table, and the room-relocation checklist (not duplicated here to avoid
  drift — read those sections if the rig itself misbehaves, as opposed to a comfort issue).
- **TODO, not done in this pass**: add a `demo-591360-3dof` booth button to
  `scripts/status-dashboard.py`'s `DEMO_LAUNCHES` (mirror the existing 6dof entry, tracking
  `"3dof"`) so Card B has the same one-click launch as the other three combinations.
