# 20 — Headset connected breaks the KDE desktop (X11), not just the 90Hz

**Found 2026-08-06.** This is a problem distinct from the bpc bug (`docs/13-bug-6bpc.md`): it's not that the headset panel fails to light up at 90Hz, it's that
**with the headset connected, the entire Plasma desktop can become unstable**, to the point
of being left with only the wallpaper (no panel, no icons) or with a broken lock screen (only
the clock, no password field).

---

## The symptom

Clean boot (full reboot, not just relogin). KDE Plasma X11 session via SDDM. All the
expected processes are running (`Xorg`, `kwin_x11`, `plasmashell`, `kded6`) but **the UI
never renders**: you see the wallpaper and nothing else — no panel, no desktop icons, no
taskbar.

`journalctl -b` shows, repeated in bursts of 4-8 lines each time:

```
plasmashell[PID]: QRhiGles2: Context is lost.
plasmashell[PID]: Graphics device lost, cleaning up scenegraph and releasing RHI
kwin_x11[PID]: kwin_scene_opengl: Could not delete framebuffer because no context is current
```

No Xid at all in dmesg/journalctl -k (meaning: it's not a kernel-level GPU reset; the
`nvidia.ko` and `nvidia-drm` don't see anything unusual). The failure is in the Qt/RHI/EGL
layer that `plasmashell` uses for its scenegraph — it drops and rebuilds, and while it
rebuilds there's no UI. Sometimes it recovers after several cycles (leaving a functional
desktop but with broken notifications — see the `DelegatePopup.qml` binding loop in the log),
sometimes it stays stuck in the loop permanently.

## Identified root cause: DP-0 (the headset) saved as a desktop monitor at 90Hz

`xrandr` showed `DP-0 connected primary 2880x1440+0+0` running `2880x1440@90.00` —
**exactly the G2's native mode** that `docs/13-bug-6bpc.md` documents as the mode with
the unstable DisplayPort link on the unpatched driver (panel that doesn't power on or flickers
without color). That instability was the 6 bpc clamp, since fixed by
`patches/nvidia/0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch` (see
`docs/13` and `docs/19`); the analysis below describes the unpatched-driver case.

Confirmed with the saved KDE profiles in `~/.local/share/kscreen/`: the `fullname` of
`DP-0` is `xrandr-HP Inc.-<EDID-SERIAL>` (the headset's EDID). The saved profile restored at
boot had DP-0 `enabled: true` at 90Hz, saved while the headset was connected; an older
profile had it `enabled: false`. KDE kept restoring the enabled profile on every subsequent
boot.

**With the headset treated as a normal desktop monitor, any hiccup on the DP link at
90Hz (which was unstable on the unpatched driver — it's the central bug of `docs/13`) takes down
the entire compositor**, not just the headset's output. This is consistent with the
crash-loop starting as soon as the session starts: KDE tries to compose across all 4
outputs, one of them was an unstable DP link at 90Hz (unpatched driver), and `plasmashell`/`kwin`
lose the entire GL context.

### The applied fix

```bash
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
export XAUTHORITY=/run/sddm/xauth_HAltUI   # or whichever corresponds to the active session
export DISPLAY=:0
kscreen-doctor output.DP-0.disable
```

This stops it for the live session. **It persists only as long as KDE doesn't save a
profile with DP-0 enabled again** — which is exactly what caused the problem the first
time. There is (still) no mechanism to guard against this; see "What's left" below.

After the fix, no new `Context is lost` appeared for several minutes, and
`plasmashell`/`kwin_x11` remained stable on the normal desktop.

## What the fix does NOT explain: it recurred on the lock screen, with DP-0 already disabled

Minutes after disabling DP-0 the same `QRhiGles2: Context is lost` pattern appeared in the
lock screen process (`kscreenlocker_greet`): only the clock, no password field, and a password
attempt failed (`pam_unix(kde:auth): authentication failure`), consistent with the field not
being rendered. `journalctl -k` showed no hotplug or reconnection event in that window.
(Later finding: `kscreen-doctor ... disable` only changes what KScreen reports, so DP-0 was
probably never really off at the X server level; see below.)

**Conclusion: DP-0 at 90Hz as a desktop monitor is ONE confirmed cause of the crash, but may
not be the only one.** Possibly a known Plasma 6 + NVIDIA bug (driver 550.163.01, the
standard Debian package, **not** the lab's patched 595-open) where Qt Quick's QRhiGles2
backend loses the EGL/GLES context on certain recomposition events such as the lock screen
creating its own GL surface. Not resolved.

## What's left

- Prevent KDE from saving/booting with DP-0 enabled again. Untried ideas: (a) a Plasma
  autostart script running `kscreen-doctor output.DP-0.disable` at session start (but see the
  next section: the disable is not reliable); (b) a KDE way to "always remember disabled" for
  an output by EDID instead of by geometry/session.
- Discriminating test not done yet: does the crash recur with the headset physically
  disconnected? If yes it is a generic Plasma/NVIDIA bug (search bugs.kde.org for "QRhiGles2
  Context is lost" before assuming it is another manifestation of the headset problem).

## Practical rule for future sessions

**If the KDE desktop looks wrong (only wallpaper, broken panel, lock screen with no
password field) and the headset is connected: run `kscreen-doctor -o` and check whether
`DP-0` (or the output whose `fullname` contains `HP Inc.`) is `enabled` before investigating
anything else.** It's the prime suspect and has already been confirmed once.

## Later findings (2026-08-06/07)

- After a reboot DP-0 is back `enabled` at 90Hz: the profile KDE loads at boot restores it.
- **DP-0 cannot be removed from the desktop live while the headset is connected.** All three
  attempts failed: `kscreen-doctor output.DP-0.disable` returns success and KScreen reports
  `disabled`, but `xrandr` still shows `2880x1440 90.00*+`; `xrandr --output DP-0 --off` fails
  with `Configure crtc 0 failed` / `BadMatch ... RRSetScreenSize`; `nvidia-settings --assign
  CurrentMetaMode=...` without DPY-1 fails with `Attribute not available`. Untested: whether
  physically unplugging the DP cable lets X re-probe without DP-0.
- Side effect: DP-0 occupies the (0,0)-(2880,1440) rectangle of the virtual desktop, so some
  new windows open there, invisible without wearing the headset. Windows trapped there can be
  moved with a KWin script (D-Bus `org.kde.kwin.Scripting`): iterate `workspace.windowList()`,
  and for windows whose `output.name === "DP-0"` assign a plain object
  `{x, y, width, height}` to `frameGeometry`. KWin 6 scripting notes: `w.output` is read-only,
  `Qt.rect()` does not exist in that engine, run scripts with `loadScript` followed by plain
  `Scripting.start()` (`Script.run` on the returned path gives `UnknownObject`), and
  `print()` output goes to `journalctl`, not stdout.
- Forcing `GLPlatformInterface=egl` in `kwinrc` `[Compositing]` makes KWin run without a GL
  compositor (it logs `Invalid QOpenGLContext::globalShareContext()`), which hides a
  separate invisible-cursor problem but later produced black borders around windows. Remove
  that setting rather than living with it.
- **Do not try to repair the session live with `kwin_x11 --replace` (or
  `plasmashell --replace`) from a non-interactive agent shell.** Run that way, `kwin_x11`
  fell back to `nouveau` (`failed to load driver: nouveau`) despite correct session
  environment and device permissions, `plasmashell` segfaulted and its replacement fell back
  to Mesa `zink` and crash-looped with `VK_ERROR_DEVICE_LOST`. A plain reboot reliably resets
  driver/session state. If it recurs, check `__GLX_VENDOR_LIBRARY_NAME`,
  `__EGL_VENDOR_LIBRARY_FILENAMES` and the shell's cgroup/namespace. A detector or guardrail
  for this failure signature (`globalShareContext` in the `kwin_x11` log plus `zink` /
  `VK_ERROR_DEVICE_LOST` in `plasmashell`'s) was proposed but never built.
