# SDDM silent session failure -- root cause found (2026-09-05)

## Background

Recurring bug on iashur: some boots, SDDM/gnome-session autologin silently
never produces a usable desktop -- no crash, no error visible to the user --
and the only known fix has been `systemctl restart sddm.service` or a full
reboot. Previously worked around, never root-caused. This doc closes that
gap for the specific failure mode captured on 2026-09-05.

Not to be confused with the (separately, permanently fixed) `jack-in-wayland.sh`
SSH-session-no-display-env bug -- that one is unrelated.

## Today's occurrence

`journalctl --list-boots`: a single boot today, `97d8c0aa09904452a1bd1ebccc43c844`,
at 2026-09-05 11:49:55 -03. The 11:51:26 "restart" was a same-boot
`systemctl restart sddm.service`, not a fresh reboot.

## Root cause

**A boot-time race between Plymouth's VT1 handoff and SDDM's VT-selection
logic, which on loss lands SDDM on VT2 -- a VT this box also unconditionally
starts a getty on.** The compositor then fails to acquire the VT/session and
dies within under a second, before gnome-session/mutter ever log a single
line -- which is exactly why it looks like total, traceless silence.

### Evidence, first (failing) attempt -- VT2, ~11:49:56-57

```
11:49:56 systemd[1]: Started sddm.service
11:49:56 systemd[1]: Starting plymouth-quit-wait.service...  / Starting plymouth-quit.service...
11:49:56 systemd[1]: Received SIGRTMIN+21 from PID 430 (plymouthd) / Finished plymouth-quit-wait / Finished plymouth-quit
11:49:56 systemd[1]: Started getty@tty2.service - Getty on tty2.
11:49:56 systemd[1]: Reached target getty.target - Login Prompts.
11:49:57 sddm[1199]: Logind interface found
11:49:57 sddm[1199]: Using VT 2                      <-- NOT the usual VT1
11:49:57 sddm[1199]: Session ... selected, command: "/usr/bin/gnome-session" for VT 2
11:49:57 sddm-helper[1248]: Starting Wayland user session: "/etc/sddm/wayland-session" "/usr/bin/gnome-session"
11:49:57 sddm-helper[1442]: Jumping to VT 2 / VT mode didn't need to be fixed
11:49:57 sddm[1199]: Session started true
11:49:57 sddm-helper[1248]: Failed to write utmpx: No such file or directory
11:49:57 sddm-helper[1248]: [PAM] Closing session / [PAM] Ended.
11:49:57 sddm[1199]: Auth: sddm-helper exited with 1
11:49:57 systemd-logind[1048]: Session 1 logged out. Waiting for processes to exit. / Removed session 1.
```

`sddm.service`, `plymouth-quit(-wait).service`, and `getty@tty2.service` all
activate in the same one-second journal window. Between "Starting Wayland
user session" and "sddm-helper exited with 1" there is **zero** gnome-session,
gnome-shell, or mutter log output anywhere in the journal -- confirmed by
grepping the full unfiltered window. The whole session-1 lifecycle (start to
teardown) takes under a second. This is not a crash with a trace; it's a
compositor that never got far enough to log anything, because it couldn't
get the VT.

### Evidence, second (working) attempt -- VT1, after the manual restart at 11:51:26

```
11:51:26 sddm[1879]: Using VT 1
11:51:26 sddm[1879]: Session ... selected, command: "/usr/bin/gnome-session" for VT 1
...
11:51:26 systemd[1885]: Created slice app-gnome-session-manager.slice
11:51:26 systemd[1885]: Reached target gnome-session-wayland.target
11:51:26 gnome-shell[2029]: Running GNOME Shell (using mutter 48.7) as a Wayland display server
...
11:51:29 systemd[1885]: Reached target gnome-session-x11-services-ready.target
```

Full, normal gnome-session-wayland.target unit chain, gnome-shell actually
running. The only externally-visible difference between the two attempts is
**which VT SDDM picked** (2 vs 1) -- everything else about the machine state
(NVIDIA driver load, DRM init, etc.) is identical between them.

### Why VT2 specifically loses

`systemctl cat sddm.service` shows the stock unit only knows about VT1/VT7:

```
Conflicts=getty@tty1.service getty@tty7.service
After=getty@tty1.service getty@tty7.service
...
# If using tty1 and plymouth, sddm will fail till plymouth stops
# consider using:
## After=plymouth-quit.service
## Conflicts=plymouth-quit-wait.service
## After=plymouth-start.service plymouth-quit-wait.service
## OnFailure=plymouth-quit.service
```

The unit file's own comments document the exact plymouth/VT1 race SDDM can
lose. Normally, when SDDM loses that race and *would* fall back to VT2, there
would be nothing else on VT2 to fight over -- Debian's default only enables
`getty@tty1.service`. But on iashur:

```
/etc/systemd/system/getty.target.wants/getty@tty1.service -> ...getty@.service   (2026-08-04 17:01)
/etc/systemd/system/getty.target.wants/getty@tty2.service -> ...getty@.service   (2026-08-09 21:16)
```

`getty@tty2.service` is **explicitly, statically enabled** here (a symlink
added 5 days after the stock tty1 one -- not a distro default; likely added
during some earlier local-console debugging session and never removed).
Because `sddm.service` has no `Conflicts=`/`After=` relationship with
`getty@tty1.service`'s sibling `getty@tty2.service` (only tty1/tty7 are
covered), when SDDM's VT-picker falls back to VT2 it collides head-on with
this getty, and the compositor never gets a usable VT.

This also explains why the bug is boot-only and intermittent: the race is
between Plymouth's VT1 release and SDDM's VT probe, both of which have no
hard ordering dependency forcing one before the other -- so it doesn't
reproduce every boot, and a warm `systemctl restart sddm.service` mid-session
never hits it at all (Plymouth is long gone by then, VT1 is trivially free).

### Ruled out / not implicated

- **`nvidia-powerd`'s "unsupported system" error**: fires and exits every
  single boot regardless of outcome (confirmed present in both today's failing
  and succeeding attempts); its own systemd unit reports "Deactivated
  successfully" immediately after. Benign, unrelated -- it's a
  laptop-power-management feature quitting harmlessly on desktop hardware.
- **`sddm-helper: Failed to write utmpx`**: appears on *both* the failing
  attempt (twice, framing the abrupt PAM-close/exit(1)) and the working one
  (once, as normal PAM bookkeeping noise). Confirmed benign/unrelated to the
  failure -- it's an unrelated, permanently-present utmpx-path quirk on this
  install (harmless: nothing reads that file for a Wayland session).
- **NVIDIA driver/module load**: identical NVRM banner, identical DRM init
  sequence, in both attempts. The 2026-09-03 GPU swap and driver rebuild are
  not implicated in this specific failure -- both attempts show clean driver
  load.
- **No coredumps, no OOM, no other failed systemd unit** in the failing
  window besides the ones directly downstream of the VT collision
  (`filter-chain.service`/`wireplumber.service` dependency failures visible
  in the log belong to the *root* tty2 console session that a human opened
  later while troubleshooting -- see below -- not to the gnome-session
  failure itself).

### Aside, not part of the root cause but worth flagging

Between the two SDDM attempts, someone attempted a manual login on tty2
(`FAILED LOGIN ... FOR kingman` at 11:50:26, then a successful root login at
11:51:09) -- almost certainly a human troubleshooting the blank screen via
the physical console during the ~90s gap. That root session on tty2 is
**still open right now** (`loginctl` shows session 3, root, tty2, idle
~52 min) -- worth knowing about if anyone goes looking for stray sessions,
but it is a symptom of the outage being investigated live, not a cause of it.

## Fix

Two independent, complementary changes. The first is the actual root-cause
fix; the second removes the specific collision vector this box has that a
stock system wouldn't.

1. **Order `sddm.service` after Plymouth's VT1 handoff completes**, exactly
   as the unit file's own commentary suggests. Staged (not yet installed --
   requires root, and must not be applied by daemon-reload/restart while the
   rig is in live use) at:
   `~/Documents/reverb-g2/docs/99-sddm-silent-session-failure-plymouth-vt-race.md.staged-dropin`
   Install with:
   ```
   sudo mkdir -p /etc/systemd/system/sddm.service.d
   sudo cp docs/99-sddm-silent-session-failure-plymouth-vt-race.md.staged-dropin \
       /etc/systemd/system/sddm.service.d/99-plymouth-ordering.conf
   sudo systemctl daemon-reload
   ```
   `daemon-reload` itself does not restart sddm or touch the running
   graphical session -- it only takes effect on the *next* boot. Verify by
   watching `journalctl -b -1 -u sddm.service` after the next legitimate
   reboot: it should show `Using VT 1` on the very first attempt, with no
   restart needed.

2. **Recommended, separate decision for the user**: `getty@tty2.service` is
   not a stock default here and currently has an idle root shell attached
   from today's troubleshooting (see above) -- so don't touch it right now.
   Once that session is cleared, if there's no ongoing need for a
   statically-enabled getty on tty2 specifically (vs. the normal
   auto-VT-switch behavior everyone gets on tty2-tty6 without enabling
   anything), consider `sudo systemctl disable getty@tty2.service`. This
   removes the collision vector entirely as a second line of defense, on
   top of fix #1.

## Still needs a live reboot to confirm

Fix #1 is staged but **not installed or tested**. It cannot be verified
without a real reboot (the failure is boot-time-only and intermittent, so
even installing it doesn't prove anything until it's been observed across a
few cold boots). Do this on the next legitimate maintenance window, not as a
live experiment while the rig is in demo/dev use.
