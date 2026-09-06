# 106 - Autologin/keyring fix status, VR-off state verification, and a multi-user idea for later

## 1. SDDM fix: fully applied, pending a reboot test

All three pieces from `docs/99`/today's research are now live on disk (applied by the user via
`apply-sddm-keyring-fix.sh`, verified directly 2026-09-06 ~12:00):

- `/etc/pam.d/sddm-autologin`: `-session optional pam_gnome_keyring.so auto_start` +
  `-session optional pam_kwallet5.so auto_start` added right after the second `pam_selinux.so
  open` line (same position as `/etc/pam.d/sddm`'s own layout). Backup at
  `/etc/pam.d/sddm-autologin.bak-20260906-120032`.
- `getty@tty2.service`: disabled + inactive (was a stray, non-default-enabled unit, the second
  contender in the VT race documented in `docs/99`'s 2026-09-06 entry).
- `/etc/systemd/system/sddm.service.d/98-no-tty2-race.conf`: `Conflicts=`/`After=
  getty@tty2.service` -- generalizes Debian's own tty1 fix (bug #916398) to tty2. Confirmed
  merged into `sddm.service`'s effective `[Unit]` alongside the pre-existing
  `99-plymouth-ordering.conf` (`After=plymouth-quit-wait.service`).

**Not yet re-tested with a reboot since these were applied.** The one real reboot test so far
(docs/99, 2026-09-06 ~11:05) was BEFORE the PAM keyring line and the getty@tty2 fix existed --
that test showed the autologin failing once (landed on VT2, `sddm-helper exited with 5`, manual
greeter login needed). Next reboot is the actual test of whether these three combined actually
close it. Do this whenever convenient, ideally the next real cold boot rather than a special test
reboot, and check the same three things as before: `journalctl -b -u sddm.service` (does it land
on VT1 first try now?), whether autologin completes silently, and whether any keyring-unlock
prompt appears once at the desktop (expected if the keyring still has a real password, see
section 2).

## 2. Keyring blank-password conversion: PAUSED, not done -- open decision for the user

**Seahorse ("Passwords and Keys") is not installed on this box** (`dpkg -l seahorse` finds
nothing) -- the GUI steps given earlier assumed it was present and were wrong for this specific
machine. The user tried GNOME Settings' own Users panel instead ("deshabilitar el login") but
that path also does not accept a blank password.

**A headless, no-GUI-needed alternative is ready but not yet run**: `~/blank-login-keyring.py`
(deployed 2026-09-06, not tracked in git -- ad-hoc on this box), using the D-Bus
`org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface.ChangeWithMasterPassword` call
(source-verified against `gnome-keyring`'s own `gkd-secret-service.c`, see the research done
earlier this session). Asks for the CURRENT password interactively via `getpass` (hidden input,
never an argv/env value, never sent anywhere) before doing anything, and requires typing `YES` to
confirm. Run it yourself: `python3 ~/blank-login-keyring.py`.

**Reconsideration raised by the user, genuinely open, not yet decided**: the whole disk on this
machine is already LUKS-encrypted (`/dev/sdb5`, `iashur-vg`, see
[[reference_vr_lab_topology]]) -- which already fully protects the keyring file (and everything
else) against the *powered-off/stolen-drive* threat model. Blanking the keyring's password only
adds protection against a *different, narrower* threat: some other local process or account,
while the machine is live/unlocked, reading this account's keyring file directly off disk
(bypassing the normal D-Bus Secret Service API, which enforces per-app polkit/session checks
regardless of the keyring's own password). Whether that narrower threat is worth trading away
against the autologin-prompt annoyance is the user's call, not decided here. **Do not blank it
proactively -- wait for an explicit go-ahead.**

## 3. VR-off state verification, per the user's explicit ask ("es importante que la máquina entienda bien que está off")

Checked right after the user powered the headset off, 2026-09-06 ~12:01-12:04:

- **USB: 0/5 known G2 devices enumerated** -- confirms the headset is genuinely disconnected at
  the hardware level, not just idle.
- **DRM: all three `card0-DP-*` connectors read `disconnected`** -- correct/expected once nothing
  holds a lease.
- **No stray processes**: `monado-service`, `hello_xr`, `jack-in`, and this session's own
  `joy-marker.py` test tool were all confirmed gone (`pgrep` clean) after an explicit teardown +
  cleanup pass.
- **A real, if minor, false alarm along the way**: `vr-state.sh` twice reported
  `monado-service UP, pid <N>, up 00:00` with a different PID each time, while a direct `ps -p
  <pid>` on that exact PID moments later found nothing. Root cause, confirmed by re-running
  `vr-state.sh` in isolation (with no other SSH commands running concurrently) and getting a
  clean `monado-service DOWN`: `vr-state.sh`'s own `pgrep -f "monado[-]service"` (a full-cmdline
  match, by design, to catch a process under any wrapper) was transiently matching **this
  session's own diagnostic SSH commands**, which themselves contained the literal text
  "monado-service" as a `pgrep`/`pkill` pattern argument -- the same class of gotcha as
  [[feedback_pkill_f_self_kill_ssh]], just manifesting as a false-positive *detection* here
  instead of a self-kill. Not a real respawn, not a real bug in the VR stack's own shutdown path.
- **A separate, real (but harmless) `vr-state.sh` design limitation, worth knowing about**: its
  "openxr session OPEN/no session" line is computed by `grep -c BEGIN_SESSION`/`grep -c
  END_SESSION` over the *entire, non-rotating* `jack-in-wayland.log` file, not the current live
  state -- confirmed today's log shows `2 BEGIN_SESSION` / `1 END_SESSION` (one of today's many
  test sessions was killed abruptly rather than shut down cleanly, unsurprising given how much
  forceful `pkill -9`/SIGKILL cycling happened during the presence-RESTORE test harness
  debugging). Once any single session in the log's history ends uncleanly, this line will show
  "session OPEN" forever after, regardless of current reality -- it is not a reliable live
  indicator and shouldn't be read as one. The real, trustworthy signals are `monado-service`
  UP/DOWN (live `pgrep`) and the USB/DRM checks above, both of which correctly read "off" right
  now.

**Bottom line for the user's question: yes, the machine correctly understands the VR stack is
off right now** -- checked via the signals that actually reflect live state, not the
`vr-state.sh` "openxr session" line (which is stale/historical by design and not worth trusting
or fixing urgently, though a future cleanup could make it look at only the last begin/end pair
instead of a cumulative count).

## 4. New idea, captured for later, not scoped: separate "davinci" user + 2 autologins for Moonlight

User's idea, raised in passing while discussing the autologin/keyring work: split the DaVinci
Resolve (video editing) workflow onto its own user account, separate from the VR/gaming account
this whole investigation has been about -- motivated by wanting Moonlight (paired with the
`sunshine` streaming host already running on this box, see `ps aux` -- `/usr/bin/sunshine`) to
work reliably, which apparently needs **two simultaneously-autologin-capable accounts** to do
properly (plausibly: one account driving the local physical session Sunshine streams from, a
second for whatever DaVinci-side session/workflow needs its own independent desktop).

**Not investigated or scoped at all yet** -- genuinely a "for later" idea, worth revisiting once
the current single-autologin SDDM/keyring work is settled, since a second autologin account
would directly interact with everything in sections 1-2 above (PAM autologin config, VT
allocation, `sddm.conf.d`'s `[Autologin]` block currently hardcoded to `User=iam`). Whoever picks
this up should re-read this doc's section 1 first, since a second autologin account needs its
own equivalent `sddm-autologin` PAM treatment and its own VT, and could reopen or interact with
the same VT-allocation race class documented in `docs/99`.

## 2026-09-06 ~12:18 -03 — real reboot test: BOTH fixes confirmed working end to end

Genuine fresh reboot (uptime 3 min, boot at 12:18, confirmed via `who -b` -- the previous
"reboot" check earlier had found the machine still on its 11:05 boot, no new boot had actually
happened yet at that point; this one is real).

**SDDM autologin (section 1's fix): clean success, no failure at all.** `journalctl -b 0 -u
sddm.service` shows a single, uninterrupted attempt: authenticate -> session opened -> Wayland
session starting -> `Session started true` -> gnome-session up. No `sddm-helper exited with 5`,
no fallback to the greeter, no manual login needed -- the exact failure from the first test
(docs/99, 2026-09-06 ~11:05) did not recur. Note: sddm still picks **VT 2** (not VT1) on this
boot -- the underlying "why VT2" question from docs/99 remains unexplained -- but this no longer
matters: whatever used to race and fail on that VT now just works. `getty@tty2.service` confirmed
disabled+inactive throughout.

**Keyring blank-password (section 2): confirmed live, real proof this time, not just
circumstantial.** The boot log shows `sddm-helper[...]: gkr-pam: couldn't unlock the login
keyring` -- expected noise, not a failure: `pam_gnome_keyring`'s own unlock attempt has no
password to work with in an autologin flow (same reason its `auth` phase would be a no-op,
per the original research), so it correctly reports it couldn't do anything -- but that's not
the mechanism that actually matters here. Queried the collection directly over D-Bus right
after this fresh boot, before anyone manually touched anything: **`Locked: 0`**. A locked,
real-password keyring would read `Locked: 1` until something supplies the right password;
reading `0` on a session nobody has unlocked by hand is direct proof the keyring is genuinely
passwordless and auto-opens on its own now.

**Net result: both of today's fixes are done and verified, not just applied.** The original
complaint (repeated keyring "cancel" prompts blocking an unattended autologin boot, needed for
the monitoring web dashboard to come up on its own) is resolved on both fronts -- the session
starts reliably, and the keyring no longer has anything to prompt for.

**Remaining open items, unrelated to this fix being done**: (1) why sddm picks VT2 instead of
VT1 is still unexplained (cosmetic/curiosity at this point, not a problem); (2) the
davinci/multi-user idea (section 4) is still just an idea, unscoped; (3) if the user later
decides the blank-keyring tradeoff (section 2's LUKS-already-encrypts-the-disk reconsideration)
isn't worth it after all, `scripts/blank-login-keyring.py`'s same `ChangeWithMasterPassword`
mechanism can set a real password back (current="" empty, new=<a real password>) -- not written
as a ready-made "re-lock" script, but the same tool covers it with different arguments.
