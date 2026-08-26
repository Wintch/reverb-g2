# 76 — Demo day final prep: gaps, RAM/cache calls, onboarding, Windows fallback, relocation

**Read this one document tonight.** It consolidates three research passes run right before
doors open. Full backing detail lives in `docs/78-ram-vs-cache-demo-night-checklist.md` and
`docs/79-demo-booth-onboarding-and-fallback.md` (both originally landed as `docs/76-*` from
the same parallel research round as this file — renumbered to 78/79 right after, since three
files can't share one doc number) — you should not need to open either during the show.

Titles tonight (`docs/75`): **Aircar** (1073390, Xbox pad), **Dreams of Dalí** (591360,
headset-only gaze-dwell), **Hellblade: Senua's Sacrifice VR Edition** (747350, motion
controllers, one good pre-fix look only).

---

## 1. New doc-vs-reality gaps found tonight

Ranked by urgency. First one needs action **before doors open**, the rest are FYI/low-risk.

### URGENT — do this now, before the first guest
The machine is **not** in the clean pre-show state `docs/75` §1 requires. Live check just
now: `game-stop.py status` shows Dreams of Dalí (591360) still running (~11+ min, 17
processes) and `monado-service` (PID 19043) still up — leftover from this session's own
testing, not a real fault. Fix:
```bash
python3 /home/iam/vr/vr-launcher.py stop all
python3 /home/iam/vr/vr-launcher.py status     # must say clean
pgrep -af "monado[-]service"                    # must print nothing
```

### MEDIUM — verify, probably fine, but check once
**Aircar has a duplicate, un-triggered install on the flaky Kingston drive.**
`appmanifest_1073390.acf` exists both on root ext4 (the active copy Steam actually uses,
newer mtime) and on `/mnt/win5` (NTFS, stale, mtime Aug 13) — and the NTFS copy has **no**
`compatdata/1073390` at all. If Steam's library resolution ever pointed a launch at the NTFS
copy, it would create a fresh Proton prefix straight on NTFS and hit the exact
empty-`dosdevices/` failure that already took out Dalí once and is still blocking Hellblade
(see §6). Not expected to trigger tonight — just don't manually re-point anything at
`/mnt/win5/SteamLibrary/steamapps/common/Aircar`. Verify current state anytime:
```bash
find / -iname 'appmanifest_1073390.acf' 2>/dev/null   # expect 2 hits
ls /mnt/win5/SteamLibrary/steamapps/compatdata/1073390 2>&1   # expect: No such file
```

### LOW — harmless tonight, sync when there's a quiet moment
- `/home/iam/vr/vr-power-setup.sh` (deployed copy) is missing the `--saver` mode and
  `hmd_usb_no_autosuspend()` refactor that the repo copy has. **Not live-broken**: the
  power watchdog's `ExecStart` points at the repo's own `scripts/vr-power-watchdog.py`,
  which resolves the up-to-date script by its own path. Only bites if someone runs
  `~/vr/vr-power-setup.sh --saver` by hand expecting it to work — it currently falls through
  to a usage error. Fix when convenient: `cp /home/iam/Documents/reverb-g2/scripts/vr-power-setup.sh /home/iam/vr/vr-power-setup.sh`.
- `/home/iam/vr/jack-in-wayland.sh` has two stale comments (still says "10G tmpfs" post the
  RAM upgrade to 20G). Cosmetic only, no logic differs.
- `vr-launcher.py`'s `NO_HANDS_TITLES` comment for Dalí (591360, ~line 154) still says
  "unconfirmed static evidence," contradicting the corrected `TITLE_PROFILES` comment right
  above it (~line 144, "worn-confirmed 2026-08-26"). Code values are correct either way,
  just a stale comment worth a one-line fix so nobody re-litigates an already-answered
  question.

Nothing else checked out as a gap — `vr-power-watchdog.service`, the three shared scripts
(byte-identical live vs. repo), the secondary-Steam-library fix, Hellblade's appmanifest
numbers, and Dalí's compatdata symlink fix all match what the docs claim.

---

## 2. Per-title RAM-vs-cache: what to actually run tonight

Full method and rationale: `docs/78-ram-vs-cache-demo-night-checklist.md`. The short version:

| Title | RAM-mode status | Tonight's job |
|---|---|---|
| **Aircar** (1073390, 852MB, root ext4) | Already tested (T246): `ram` wins — 51fps vs 24fps in the load-transition window, reaches steady 90fps sooner | **Confirm-and-reuse**, one spot-check pair, don't re-derive: `python3 bench-launcher.py aircar --tracking 6dof` then `--prewarm-ram` |
| **Dreams of Dalí** (591360, 1.4GB, `/mnt/win5`) | Never tested | Full A/B, by hand (no `bench-launcher.py` target) — commands below |
| **Hellblade** (747350, 24GB, `/mnt/win5`) | **Structurally can't** — 24GB exceeds `vr-prewarm.sh`'s hardcoded 16G `RAM_SIZE_LIMIT_BYTES`; `--mode ram` refuses outright. Don't raise the cap tonight — that's a deliberate maintainer call, not a demo-night workaround | Cache-vs-baseline only |

Kingston fill-risk (`docs/74`'s drive, hosts Dalí+Hellblade): **low tonight** — `ram` mode
only reads *off* that drive into tmpfs, never writes onto it. The only real risk is a fresh
install/download onto `win5`/`videos` during the show. Headroom is healthy (291G/209G free);
just don't skip `df -h /mnt/win5 /mnt/videos` before/after any install step.

Manual A/B for Dalí and Hellblade (expect to need a human wearing the headset to clear
intro/menu content, same as every other first-look title):
```bash
cd /home/iam/Documents/reverb-g2/scripts
APPID=591360   # or 747350

./vr-prewarm.sh --status                       # nothing already swapped
./vr-prewarm.sh $APPID --dry-run && ./vr-prewarm.sh $APPID     # ARM A: cache
export U_PACING_APP_LOG=debug
./jack-in-wayland.sh up 1 3dof
steam -applaunch $APPID
./app-fps.sh 2 10 ~/vr/jack-in-wayland.log     # 2s windows x10
./jack-in-wayland.sh down

# ARM B: ram — SKIP for Hellblade (dry-run will refuse; that IS the expected result)
./vr-prewarm.sh $APPID --mode ram --dry-run && ./vr-prewarm.sh $APPID --mode ram
./jack-in-wayland.sh up 1 3dof
steam -applaunch $APPID
./app-fps.sh 2 10 ~/vr/jack-in-wayland.log
./jack-in-wayland.sh down
./vr-prewarm.sh $APPID --restore               # always, before ending
```

**Measure both**, not fps alone (Quake II RTX's ram-mode regression was invisible in
steady-state fps and only showed in launch time): (1) `app-fps.sh`'s early windows vs. the
title's own known ceiling (Hellblade: 45fps, not 90 — pre-fix data point, `docs/23:54`; Dalí
has no prior number, first run sets it), and (2) wall-clock from `steam -applaunch` to first
`Delivered frame`/`BEGIN_SESSION` in the log. Keep `ram` as default only if it's clearly
better on both (or one, with no regression on the other); otherwise default to `cache`.

Close out every session: `./vr-prewarm.sh --status` (nothing left swapped) + `df -h
/mnt/win5 /mnt/videos`.

---

## 3. First-timer onboarding — read this aloud

**30-second operator check before every handover, not just the first**: eyeball the room —
if it looks dim to you, it's dim for the tracker (Aircar's own worn test hit 3 tracking
runaways in the first 75s in a dim room, T245/`docs/56`). Fix the light before anything
else. Also glance at `hmd-audio.sh status` — the sink gets rebuilt on every USB2
re-enumeration and can land muted.

Spoken lines (Spanish, English gloss in brackets):

1. **Fit**: *"Te lo voy a ajustar — apoyalo en la frente primero, después bajalo, y yo te
   ajusto la rueda de atrás para que quede firme pero no apretado."*
2. **Focus/IPD**: *"Girá esta rueda de abajo hasta que la imagen se vea nítida y sea una
   sola imagen, no dos superpuestas."* Ask directly: *"¿La ves nítida?"* — don't assume yes.
3. **Wear sensor**: *"El casco se prende solo apenas lo tenés puesto bien — no hay que
   tocar nada más."* If the picture doesn't start, the fix is "seat it properly," not
   "something broke" — the session only opens once the nose-bridge sensor fires.
4. **Recenter** (say the one matching the title about to launch):
   - Aircar: *"Si en algún momento te ves 'afuera' del lugar donde deberías estar, apretá
     el botón A del control y volvés a tu lugar. Es un detalle conocido, no un error."*
   - Dalí: *"Mirá fijo el punto que te marca la experiencia unos segundos y avanza sola."*
     (no recenter needed)
   - Hellblade: recenter behavior is **unconfirmed** end to end. If it drifts, try holding
     the left controller's menu button ~3s; if that doesn't fix it, stop and move to the
     next guest — don't debug live.
5. **"Flying away" pre-empted** (Aircar especially): *"A veces el juego te 'saca' del lugar
   por un segundo — no es que se rompió, volvés enseguida con el botón que te dije."*
6. **Motion sensitivity, every time, no exceptions**: *"Si sentís mareo o incomodidad,
   avisame y lo sacamos, no hay problema."*
7. **Set expectations**: *"Esto dura entre 3 y 5 minutos."*

**While they play**: watch for confusion in Aircar's first 75s (step in with the recenter
line proactively) and for any stumble/reach-for-a-wall motion.

---

## 4. Windows fallback — go/no-go and switch steps

**Rule**: any sign below means *stop, switch machines* — none are "try a quick fix first."
Each has a documented history of NOT being quick on this rig.

| Sign | Why stop, not fix-live |
|---|---|
| Panel stuck on HP logo, or white/color flicker, no image | This project's historical 90Hz-failure signature (`docs/13`/`docs/19`). A recurrence = a regression, multi-session lab job to re-diagnose. |
| Audio doesn't recover within ~10s of one restart (kill `monado-service`, wait ~5s, relaunch) | Beyond that it's the un-root-caused USB2 storm, not the normal self-resolving cycling (T052/T053). Looping restarts is itself a known trigger for more faults. |
| A controller stuck `<none>` after ONE power-cycle + ONE `jack-in-wayland.sh down`→`up` | Second failure = stop, don't loop restarts. |
| Machine hard-hangs | Known 8GB-VRAM risk, no live fix. Hard power-cycle, don't wait it out with a guest present. |
| 3+ relocations/"flying away" in the first 2 min, room visibly well-lit | 1-2 in the first 75s in normal light is within the T245 envelope; several in good light is a different, undiagnosed problem. |
| Doubled `Delivered frame` numbers, or a "stopped" game still visibly rendering | Killed-wrapper-not-the-game failure (T244) — a second live client is under it. `stop all` + `status` must show clean; if not clean on the first try, switch. |
| Session is X11, not "GNOME on Wayland" | X11 has an open, unresolved panel-link failure on this SSD (`docs/06`, 2026-08-26) and flickers at 60Hz regardless. |

**Switch steps:**
1. End the guest's turn: *"Tuvimos un detalle técnico, ¡pero mirá lo que sigue!"* Headset off
   them before touching anything.
2. If responsive: `./scripts/vr-launcher.py stop all`, confirm `status`. Skip if hard-hung.
3. Reboot; at POST use this board's BIOS boot-menu key for the **Windows NVMe** (a second
   physical drive, not a GRUB entry). **Confirm that key before doors open**, not live — it
   is not documented anywhere in this repo.
4. **Don't move the USB cable to a different port.** Oasis binds to whichever CPU-fed USB3
   port was active last (`docs/31`) — moving it forces a relaunch-to-rebind you don't want
   mid-show.
5. In Windows: `C:\reverb-g2\diagnostico.bat`, confirm 5/5. Short a device → same ladder as
   Linux (rear CPU-fed USB3 port, rotate C-plug 180°, try another rear port) — if the first
   reseat doesn't clear it, that's also a stop for the night.
6. Launch **SteamVR directly** (Oasis already unlocked, `docs/31`'s registry audit). Error
   108 → the USB ladder above. Error 422 → check SteamVR → Settings → Manage Add-Ons →
   `oasis` enabled first — fastest known 422 fix.
7. The three titles should already show installed in Windows Steam (shared NTFS library,
   `docs/70`) — confirm this **before the show**, not during a live switch.
8. Controllers stay paired across the OS switch (they pair to the headset's radio, not the
   PC) — just launch, don't re-pair.
9. Stay on Windows for the rest of the booth session — bouncing back to Linux mid-show
   re-opens every trigger above for no benefit to the guest.

**Not covered**: Hellblade has no confirmed working session on Windows in this project's
record. If it's the one that failed, swap to Aircar/Dalí instead, not Hellblade-on-Windows.

---

## 5. Room relocation ("moving upstairs") checklist

Do all of this, in order, every time the rig physically moves — not a quick glance.

1. **Safety first**: walk the new space with the cable in hand, tape down slack across
   walkways, clear the guest's likely walking radius.
2. **Re-check the USB seat** — a move risks bumping either end of the cable. Run
   `./scripts/power-on.py` (or `lsusb`) and confirm the full 5-device signature before
   anything else.
3. **Confirm the session is "GNOME on Wayland," not plain "GNOME" (X11)** if anything
   rebooted — they look identical in SDDM's list. `scripts/check-lease.sh` if in doubt.
4. **Redo the low-light check for the new room** — don't carry over the old room's verdict.
   If borderline, spend the extra 30s: `XRT_DEBUG_GUI=1 monado-service` or the blob-count
   method in `docs/56` (≤3 spurious blobs/camera, no `Tracker diverged` in 30s).
5. **Restart with the headset already worn in the new play position**, not sitting on a
   desk — SLAM origin/eye-height anchor at that moment. `jack-in-wayland.sh` prints `Eye
   height: X m -> origin offset Y m` on launch; a stale-looking line means you launched too
   early. `down` then `up`, once — not a retry loop.
6. **Expect a VIO-runaway-prone first ~75s in the new room** (same T245 mechanism,
   light-dependent) — don't be alarmed by one or two early relocations if the light check
   was borderline. Repeated well past 75s, or in good light, crosses into §4's go/no-go.
7. **Scan the new room's camera view** for anything the old room didn't have: a portrait
   monitor (fix rotation with `kscreen-doctor`, not `xrandr`), new lights/reflective
   surfaces.
8. **Controllers + audio**: both powered on *before* this restart (right-controller startup
   race), `hmd-audio.sh status` shows the sink present and unmuted.
9. **Dry-run the onboarding script (§3) on a colleague first**, not the next paying guest.

---

## What's still not done (nobody has acted on these yet)

- **Hellblade's Proton prefix is still broken** — `compatdata/747350/pfx/dosdevices/` is
  empty, the same class of fault Dalí hit and got fixed for via a symlink into
  `~/proton-prefixes-external`. Hellblade has not received the equivalent fix; it needs one
  before its retest can happen at all.
- **Hellblade full retest post-T244 pacer fix** — one data point exists (T243-night, pre-fix,
  45fps ceiling). `docs/67 §4`'s own B5 track already names this gap; nobody has picked it up.
- **Aircar's 30-min soak + relocation/recenter acceptance criterion** — never run (`docs/75`
  §4).
- **Dalí has zero recorded fps/pacing metrics** — subjectively good, worn-confirmed, but no
  `app-fps.sh`/`frame-pacing.sh` numbers on file yet.
- **The three cosmetic/low-risk gaps in §1** (power-setup script sync, jack-in-wayland.sh
  stale comment, vr-launcher.py stale comment) — harmless tonight, unfixed.
- **The Aircar NTFS duplicate install** (§1, MEDIUM) — not cleaned up, just verified inert.
