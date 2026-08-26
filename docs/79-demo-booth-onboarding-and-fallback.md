# 79 — Demo booth: first-timer onboarding script, Linux→Windows fallback, room-relocation checklist

**Written 2026-08-26 for tonight's live public demo.** Operator's stated philosophy, verbatim:
*"our responsibility is to show the best, fallback to Windows if Linux has a problem, short
demos, use the best we've put together."* This doc is written for that reality: many short
back-to-back sessions (3-5 min each) with people who have mostly never worn a VR headset, run by
one operator under time pressure — not a lab soak test. Nothing here is new investigation; it
assembles `CLAUDE.md`, `docs/75`, `docs/56`, `docs/47`, `docs/31`, `docs/67`/T245, and
`jack-in-wayland.sh` into three usable pieces. **Per this project's own rule: verification is
physical — trust what the guest and the operator actually see, not a log line that "looks fine."**

Titles tonight (per `docs/75`): **Aircar** (1073390, Xbox pad, recentres with A),
**Dreams of Dalí** (591360, headset-only gaze-dwell, no controllers), **Hellblade: Senua's
Sacrifice VR Edition** (747350, motion controllers, treated as hands-title, one good pre-fix
look only — see `docs/75`'s own caveats before promising it's flawless).

---

## 1. Handing the headset to a first-timer

**30-second operator pre-check before every single handover** (not just the first):
look at the room — if it reads dim to your own eyes, it's dim for the tracker too
(`docs/56`/T245: 3 tracking runaways in the first 75 s of Aircar's own worn test, room
described as "tenue" by the wearer; no software warns about this, `docs/75` §1.7). Fix the
light before you fix anything downstream. Also glance at `hmd-audio.sh status` — the sink
gets torn down and rebuilt on every USB2 re-enumeration and can land muted.

**Spoken script** (guests here are Spanish-speaking; said aloud, English gloss in brackets for
anyone maintaining this doc who doesn't read Spanish):

1. **Fit.** *"Te lo voy a ajustar — apoyalo en la frente primero, después bajalo, y yo te
   ajusto la rueda de atrás para que quede firme pero no apretado."* [Rest it on the forehead
   first, then lower it down; the operator tightens the rear wheel — snug, not tight.]
2. **Focus / IPD.** *"Girá esta rueda de abajo hasta que la imagen se vea nítida y sea una
   sola imagen, no dos superpuestas."* [Turn the IPD wheel on the underside until the image is
   sharp and single, not doubled.] Ask them directly: *"¿La ves nítida?"* — don't assume yes.
3. **The wear sensor, one line.** *"El casco se prende solo apenas lo tenés puesto bien —
   no hay que tocar nada más."* [The headset wakes the experience the moment it's actually worn
   — nothing else to press.] This is true mechanically: the real session only opens once the
   nose-bridge wear sensor fires (`docs/75` — Cyberpolot's real session never opens without a
   human actually wearing it), so if the picture doesn't start, the fix is "seat it properly,"
   not "something broke."
4. **Recenter, per title** (say the one that matches what's about to launch):
   - Aircar: *"Si en algún momento te ves 'afuera' del lugar donde deberías estar, apretá el
     botón A del control y volvés a tu lugar. Es un detalle conocido, no un error."* [If you
     ever find yourself "outside" where you should be, press A on the pad and you're back — a
     known quirk, not a bug.]
   - Dalí: no recenter needed — say only *"Mirá fijo el punto que te marca la experiencia unos
     segundos y avanza sola."* [Just hold your gaze on the marked point for a few seconds and
     it advances on its own.]
   - Hellblade: this project has not confirmed its recenter behavior end to end (`docs/75` —
     one pre-fix look only). If it visibly drifts, try holding the left controller's menu
     button ~3 seconds (the platform-wide shortcut); if that doesn't fix it, that's a "stop, use
     the timer, move to the next guest" case, not something to debug live.
5. **"Flying away" is a known quirk, said before it happens, not after** — this line matters
   most for Aircar specifically: *"A veces el juego te 'saca' del lugar por un segundo — no es
   que se rompió, volvés enseguida con el botón que te dije."* [Sometimes the game "kicks" you
   out of place for a second — it isn't broken, you're back right away with the button I showed
   you.]
6. **Motion-sensitivity caution, one line, every time, no exceptions for people who say
   they're fine**: *"Si sentís mareo o incomodidad, avisame y lo sacamos, no hay problema."*
   [If you feel any dizziness or discomfort, tell me and we take it off — no problem.]
7. **Set the expectation up front**: *"Esto dura entre 3 y 5 minutos."* [This lasts 3 to 5
   minutes.] Naming the short duration before they put it on heads off "wait, that's it?" and
   keeps the line moving.

**What the operator watches for, silently, during the 3-5 minutes**: sudden confusion or
"where am I" reactions in the first 75 seconds of an Aircar session (the T245 runaway window —
step in with the recenter line proactively rather than waiting for them to ask), and any
stumble/reach-for-a-wall motion (motion-sensitivity or genuine physical obstacle — check which).

---

## 2. Go/no-go: when to stop debugging and switch to Windows

**The rule, stated once so it's not re-litigated live**: this booth's job tonight is showing the
best experience, not diagnosing this project's own open bugs in front of a guest. Any sign below
means *stop, don't reseat/relaunch/investigate live, switch machines* — none of them are "quick
fixes to try first," because every one of them already has a documented history of NOT being
quick on this rig.

| Sign | Why it's a stop, not a fix-it-live | 
|---|---|
| **Panel stays on the HP logo, or shows white/color flicker with no image** | This is this project's own historical 90Hz-failure signature (`docs/13`/`docs/19`). It is supposed to be fixed — if it recurs, something regressed (driver update, symlink drift, `docs/73`) and re-diagnosing it is a multi-session lab job, not a 2-minute booth fix. |
| **Audio sink vanishes and does not come back within ~10s of the standard recovery** (kill `monado-service`, wait ~5s, relaunch) | Below that, it's the known USB2-branch cycling (`CLAUDE.md`, T052/T053) and self-resolves. Above that — repeated loss, or loss that doesn't return — is the deeper, never-root-caused USB2 storm; looping restarts is itself a known trigger for more faults. |
| **A controller is stuck at `<none>` after ONE power-cycle + ONE `jack-in-wayland.sh down`→`up`** | `docs/75` is explicit: fix it once, not in a loop — chained `monado-service` restarts trigger more USB2 faults. Second failure = stop. |
| **Machine becomes unresponsive / hard hangs** | Known, not-root-caused risk tied to 8GB VRAM on long unattended runs (`CLAUDE.md`, `docs/06`, T243-night). No live fix exists for this. Hard power-cycle, don't wait it out with a guest standing there. |
| **3+ relocations/"flying away" events in the first 2 minutes of a session, with the room visibly well-lit** | One or two in the first 75s of Aircar in normal light is within the documented envelope (T245 was in a *dim* room). Several in good light points at something else being wrong, not the known dim-light mechanism — don't try to root-cause it on the spot. |
| **Two sessions' worth of `Delivered frame` numbers look doubled, or a game that was "stopped" is still visibly rendering** | The killed-wrapper-not-the-game failure mode (`CLAUDE.md`, T244) — a second live client is running underneath. `vr-launcher.py stop all` + `status` must show clean before the next guest; if it doesn't clear on the first try, don't chase it, switch. |
| **The session is on X11 instead of Wayland-on-GNOME** (check the SDDM session picker after any reboot) | X11 has a currently-open, unresolved panel-link failure on this exact SSD (`docs/06`, 2026-08-26) and flickers at 60Hz regardless — never the demo path even if it "looks" like it's working. |

**How to actually make the switch, fast:**

1. **End the current guest's turn cleanly first** — one line: *"Tuvimos un detalle técnico,
   ¡pero mirá lo que sigue!"* [We hit a small technical hiccup — but check out what's next!]
   Take the headset off them before touching anything.
2. If the machine still responds: `./scripts/vr-launcher.py stop all` (kills the real Proton
   process tree, not just the wrapper), confirm with `status`. Skip this step entirely if the
   machine is hard-hung — don't wait on a dead shell.
3. Reboot into Windows: `sudo reboot` (or hold the power button ~5s if hung, then power back on).
   At POST, use this board's BIOS boot-menu key to pick the **Windows NVMe drive**, not the
   Linux SSD (`docs/31`/`docs/04`: this is two physically separate drives in one box, not a
   GRUB dual-boot entry — **know which key ahead of doors-open, don't discover it live**).
4. **Do not move the headset's USB cable to a different port when switching.** Oasis on this
   Windows install binds to whichever CPU-fed USB3 port was active the last time it ran
   (`docs/31`, "Function 1") — moving it means a relaunch-to-rebind step you don't want to be
   doing in front of a guest. Leave the cable exactly where it is.
5. Once in Windows: run `C:\reverb-g2\diagnostico.bat` (read-only `power-on.ps1`) and confirm
   **5/5 devices**. If it's short a device, the fix ladder is identical to the Linux one — rear
   CPU-fed USB3 port, same port rotate the C-plug 180°, then another rear port (`docs/31`
   error-108 section) — but if the first reseat doesn't clear it, that's *also* a stop condition
   for the night, not a debugging session.
6. Launch **SteamVR directly** — don't reopen the Oasis app itself; this machine's Oasis has
   already been unlocked at least once (`docs/31`'s own registry audit confirms
   `LastKnown.ActualHMDDriver = "oasis"`), so the steady state is "just start SteamVR."
   If SteamVR throws **108**, it's the USB ladder above. If it throws **422**, first check
   SteamVR → Settings → Startup/Shutdown → Manage Add-Ons → `oasis` is enabled (a prior crash
   can silently disable it) — that is the single fastest 422 fix on file (`docs/31`).
7. **The three demo titles should already be installed on the Windows side without
   re-downloading** — they live in the NTFS Steam library that Windows Steam itself created and
   that this Linux install mounts read/write for Proton (`docs/70`; Hellblade's own reinstall
   tonight landed there, per `docs/75`). Confirm they show installed in the Windows Steam
   library before the show, not during the switch — this whole runbook assumes that check
   already happened.
8. Controllers: they pair to the **headset's own radio**, not the PC, so a controller already
   paired stays paired across the OS switch — you are not re-pairing anything, just launching.
9. Continue the show from Windows for the rest of the booth session rather than switching back
   and forth — going back to Linux mid-show re-opens every one of the triggers above for no
   benefit to the guest experience.

**What this fallback does NOT cover**: Hellblade specifically has no confirmed-working session
on Windows in this project's own record (Windows testing has focused on the 90Hz/Oasis
plumbing, not this title) — if it's the one failing on Linux, the safer swap is to a title with
Windows history, or simply to Aircar/Dalí for the rest of the booth run.

---

## 3. Room-relocation checklist (moving the rig to a different room/floor mid-event)

Do this **in full, in order**, every time the headset physically moves to a new room — not just
a quick glance. A relocation is a bigger change than a between-guest handover: new lighting, new
floor space, new furniture in the tracking cameras' view, and a cold SLAM origin.

1. **Physical safety first, before any software step.** More foot traffic tonight than a solo
   lab test — walk the new space with the cable in hand: is there slack across a walkway? Tape
   it down or reroute it. Clear furniture/cables from the guest's likely walking radius (they
   can't see the room while wearing the headset).
2. **Re-check the USB seat.** Moving the whole rig risks bumping the cable at either end (visor
   connector or the PC-side plug) — this project's whole cable/seat story (`docs/22`, `CLAUDE.md`)
   is about exactly this kind of marginal contact. Run `./scripts/power-on.py` (or a plain
   `lsusb` census) and confirm the full 5-device signature before doing anything else. Don't
   assume "it worked in the last room" survives a move.
3. **Confirm the session type didn't silently change.** If anything rebooted, re-check SDDM
   picked **"GNOME on Wayland"**, not the plain "GNOME" (X11) entry — the two look identical in
   the list, and X11 has a currently-open panel-link failure on this SSD (`docs/06`). Run
   `scripts/check-lease.sh` if in doubt.
4. **Redo the low-light check for the new room, don't carry over the old room's verdict.**
   Eyeball it the same way as every handover (§1) — a room that looked fine downstairs can be
   dim upstairs and vice versa. If it's borderline, this is the one moment worth the extra 30s
   of the deeper check: `XRT_DEBUG_GUI=1 monado-service` briefly, or the blob-count method in
   `docs/56` (≤3 spurious blobs per camera with controllers hidden, no `Tracker diverged`
   resets in 30s) — then go back to the normal launcher.
5. **Fully restart the session with the headset already worn in the new play position —
   don't start it sitting on a desk.** The SLAM origin and eye height anchor wherever the
   headset physically is the moment `monado-service` starts (`docs/23`/T163; `jack-in-wayland.sh`
   prints `Eye height: X m (posture) -> origin offset Y m` on every launch — that line resets
   fresh in the new room, and a stale one means you launched before the headset was actually in
   place). `jack-in-wayland.sh down` then `up` — once, not in a retry loop.
6. **Expect a VIO-runaway-prone first ~75 seconds in the new room, same as T245, room-lighting
   dependent** — this is the documented Aircar mechanism, not a new fault: don't be alarmed by
   one or two relocations right after the origin resets, especially if the light check in step 4
   was borderline. If it happens repeatedly well past 75s or in a well-lit room, that crosses
   into the go/no-go table in §2 — don't keep re-launching hoping it clears.
7. **Re-check anything the new room adds that the old one didn't**: a portrait/vertical monitor
   nearby (Monado taking a connector in direct-mode will flatten its rotation — fix with
   `kscreen-doctor`, not `xrandr`, `CLAUDE.md`), and any new visible light source or reflective
   surface directly in a camera's view (ceiling lights, another screen — `docs/56`'s "PC status
   LEDs are perfect permanent spurious blobs" applies to any new room's furniture too, not just
   the original one).
8. **Controllers and audio, same as any handover**: confirm both controllers were powered on
   before this restart (not after — the right-controller startup race, `CLAUDE.md`), and
   `./scripts/hmd-audio.sh status` shows the sink present and unmuted in the new room before the
   first guest of that room goes in.
9. **Only once 1-8 are done, run the 2-minute onboarding script from §1** on a colleague or
   yourself first, not the next paying guest — one throwaway session confirms the new room
   before it's live.
