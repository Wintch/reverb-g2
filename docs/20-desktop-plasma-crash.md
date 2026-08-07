# 20 — Headset connected breaks the KDE desktop (X11), not just the 90Hz

**Found on 2026-08-06, session with the agent.** This is a new problem, distinct from the
bpc bug (`docs/13`): it's not that the headset panel fails to light up at 90Hz, it's that
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
the unstable DisplayPort link (panel that doesn't power on or flickers without color).

Confirmed with the saved KDE profiles in `~/.local/share/kscreen/`: the `fullname` of
`DP-0` is literally `xrandr-HP Inc.-3958133002` — the headset's EDID. The profile active at
this morning's boot (`b1daa19a6590a34be81df4a5d763a943`, the boot timestamp) had it
`enabled: true` at 90Hz. An older profile (`92b2326774024e554276dd6dba98d565`, from
yesterday 19:46) had it `enabled: false` — at some point in the lab it got left on by
accident (probably while saving the display config with the headset connected for some
test) and KDE kept booting with that setting on every subsequent boot.

**With the headset treated as a normal desktop monitor, any hiccup on the DP link at
90Hz (which we already know is unstable — it's the central bug of `docs/13`) takes down
the entire compositor**, not just the headset's output. This is consistent with the
crash-loop starting as soon as the session starts: KDE tries to compose across all 4
outputs, one of them is a chronically unstable DP link at 90Hz, and `plasmashell`/`kwin`
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

At 00:16:39 (more than 6 minutes after disabling DP-0, and ~2.5 minutes after
`kscreenlocker_greet` started at 00:14:08) **the exact same `QRhiGles2: Context is lost`
pattern appeared again**, this time in the lock screen process. Visible result: lock screen
showing only the clock, with no user/password field. A password attempt at 00:16:47 failed
(`pam_unix(kde:auth): authentication failure`), consistent with the field having no focus or
not being rendered.

`journalctl -k` in the 00:13–00:17 window shows no hotplug or reconnection event — nothing
that explains why it triggered right there. `kscreen-doctor -o` confirmed that DP-0 was
still disabled at that moment.

**Conclusion: DP-0 at 90Hz as a desktop monitor is ONE confirmed cause of the crash, but
not the only one.** There's something broader going on — probably a known Plasma 6 + NVIDIA
bug (driver 550.163.01, the standard Debian package, **not** the lab's patched 595-open,
which is not loaded — confirmed with `dkms status` and `nvidia-smi`) where Qt Quick's
QRhiGles2 backend loses the EGL/GLES context on certain recomposition events (such as the
lock screen starting, which also creates its own GL surface). This is not resolved — see
"What's left".

## Side note: leftover GSP debug config

`/etc/modprobe.d/99-nvidia-gsp-logs.conf` (`NVreg_EnableGpuFirmwareLogs=1`) has been in
place since the 2026-08-05 investigation (see `docs/13`, section "Enabling GSP firmware
logs"). It was confirmed there that it **does nothing** on this system —
`gsp_log_ga10x.bin` doesn't exist anywhere, the driver reports it as a non-fatal failure and
keeps running normally. It doesn't seem related to this bug (no GSP messages in the crash
logs), but it's leftover debug config that already served its purpose. Candidate for
removal with `sudo rm /etc/modprobe.d/99-nvidia-gsp-logs.conf` next time the module is
rebuilt, to avoid carrying debug parameters around for no reason.

## What's left

- [ ] **Prevent KDE from saving/booting with DP-0 enabled again.** Ideas, not tried
      yet: (a) a Plasma autostart script that unconditionally runs `kscreen-doctor
      output.DP-0.disable` on session start; (b) investigate whether KDE has a way to
      "always remember disabled" for an output by EDID instead of by geometry/session.
      Option (a) is the simplest and the one most in line with what this repo already
      does (idempotent scripts, see `scripts/`).
- [ ] **The second crash (lock screen, DP-0 already disabled) remains unexplained.** If
      it happens again with the headset not connected at all, it's a generic Plasma/NVIDIA
      bug, not specific to this project — search bugs.kde.org for "QRhiGles2 Context is
      lost" before assuming it's another manifestation of the same headset problem.
- [ ] **Confirm whether it happens the same way with the headset physically
      disconnected.** This is the test that discriminates between "it's 100% the headset"
      and "there's a second independent bug". Not done yet because the session got stuck
      before it could be tested.

## Practical rule for future sessions

**If the KDE desktop looks wrong (only wallpaper, broken panel, lock screen with no
password field) and the headset is connected: run `kscreen-doctor -o` and check whether
`DP-0` (or the output whose `fullname` contains `HP Inc.`) is `enabled` before investigating
anything else.** It's the prime suspect and has already been confirmed once.

## Follow-up (2026-08-06, same night): DP-0 can't be turned off live, and it "drags" windows along

After the reboot suggested in the previous session, the desktop came back (normal panel
and icons), but **DP-0 had gone back to `enabled` at 90Hz** — confirming the suspicion
from "What's left" above: the profile KDE loads at boot brings it back on. Nobody needed
to reconnect it by hand; the reboot alone was enough to bring it back.

Side effect not documented before: **since DP-0 occupies the (0,0)-(2880,1440) rectangle
of the virtual desktop, some new apps open their window there** — literally on the headset
panel, invisible to the user without putting it on. This happened with Telegram, a Chrome
window, and the desktop/icons view for that screen.

### Attempt to turn off DP-0 live: failed across all three approaches

1. `kscreen-doctor output.DP-0.disable` — the command returns success, but **it doesn't
   take effect**: `kscreen-doctor -o` still shows it as `enabled` immediately afterward, and
   `xrandr` confirms the 90Hz mode is still active (`2880x1440 90.00*+`). This had already
   happened once in the previous session (which is why the crash "recurred" with DP-0
   "already disabled" — it probably was never truly disabled at the X server level, only at
   the config level that KWin reports).
2. Direct `xrandr --output DP-0 --off` (bypassing KWin/KScreen) — fails with:
   ```
   xrandr: Configure crtc 0 failed
   X Error of failed request:  BadMatch (invalid parameter attributes)
   Minor opcode of failed request:  7 (RRSetScreenSize)
   ```
   Same error with a combined command that reasserts the other 3 outputs at once. The
   NVIDIA driver rejects the virtual framebuffer resize while the headset remains
   electrically connected to that connector.
3. `nvidia-settings --assign CurrentMetaMode=...` with a new MetaMode that omits DPY-1
   (=DP-0) entirely, both with an explicit `DPY-1: NULL` and by omitting it — fails with
   `Attribute not available` in both cases, with or without an explicit `--ctrl-display=:0`.

**Conclusion: while the headset is physically connected, we found no way to remove DP-0
from the desktop live — not through KWin/KScreen, not through raw RandR, not through
NVIDIA's native mechanism.** Suspicion (unconfirmed): it could be a `DynamicTwinView`
effectively `off` for this combination of outputs, or a restriction specific to driver
550.163.01 for panels marked non-desktop/HMD. **Not tested yet: whether physically
unplugging the DP cable (a real hotplug) does allow X to re-probe without DP-0** — this is
the most obvious test for the next session, and it would explain why `DP-1`/`DP-2`
(genuinely disconnected) do show a clean `disconnected` in xrandr while DP-0 never does no
matter how many times it's asked to turn off in software.

### Workaround that did work: moving windows with a KWin script, without touching the display

Instead of removing DP-0 from the layout, the windows trapped there were left in place and
moved by hand via KWin scripting (D-Bus, `org.kde.kwin.Scripting`):

```js
var outs = workspace.screens;
var target = null;
for (var i = 0; i < outs.length; i++) {
    if (outs[i].name !== "DP-0") { target = outs[i]; break; }
}
var wins = workspace.windowList();
var moved = [];
if (target) {
    var tg = target.geometry;
    var offset = 0;
    for (var j = 0; j < wins.length; j++) {
        var w = wins[j];
        if (w.output && w.output.name === "DP-0") {
            var g = w.frameGeometry;
            w.frameGeometry = { x: tg.x + 40 + offset, y: tg.y + 40 + offset, width: g.width, height: g.height };
            offset += 30;
            moved.push(w.caption);
        }
    }
}
print("MOVED:" + JSON.stringify(moved) + " TARGET:" + (target ? target.name : "none"));
```

Loaded and run like this (the `print()` goes to `journalctl`, not stdout):

```bash
qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript /path/to/script.js "some-name"
qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.start
journalctl -b --since "1 minute ago" | grep 'kwin_scripting\|js:'
```

Notes on the KWin 6 scripting API (this took some trial and error to figure out, writing
it down):

- `w.output = target` **fails** — `output` is read-only (`Cannot assign to read-only
  property "output"`). You have to move via geometry (`frameGeometry`), not by direct
  output assignment.
- `Qt.rect(...)` **doesn't exist** in this engine (`Qt is not defined`) — you have to pass
  a plain `{x, y, width, height}` object to `frameGeometry`, not a hand-built `QRect`.
- `qdbus6 .../Scripting/<id> .../Script.run` with the path returned by `loadScript`
  **doesn't work** (`UnknownObject`) — the correct flow is plain `Scripting.start()`, which
  runs all loaded scripts.
- `workspace.windowList()` includes the desktop/icons view as just another "window"
  (`"Desktop @ QRect(...)"`) — this isn't a bug, it's expected to show up in the listing.

With this, Chrome reappeared. **Still need to confirm whether Telegram (and DP-0's desktop
view) also became visible** — this wasn't explicitly checked before ending the session.

### What to pick back up tomorrow

- [ ] Test whether physically disconnecting the headset's DP allows X to re-probe without
      DP-0 (and whether, after reconnecting it later with the session already running, it
      does NOT get added back as a desktop output — that would signal the problem is only at
      X's initial probing).
- [ ] Put together the Plasma autostart script (`kscreen-doctor output.DP-0.disable` on
      session start) that was left pending from the previous session — although given
      today's finding (that the disable doesn't really take effect) it may not be enough on
      its own; evaluate whether it's better to instead automate the move-windows script as a
      safety net, also running it when the headset reconnects.
- [ ] Visually confirm that Telegram and everything else that was on DP-0 are now visible
      on a real screen.
- [ ] Still pending from the previous session: test whether the `QRhiGles2: Context is
      lost` crash recurs with the headset fully disconnected (to find out whether there's a
      second, generic Plasma/NVIDIA bug not specific to this project).

## Follow-up (2026-08-06, later session with Claude Code): KWin compositor disabled, new unconfirmed hypothesis

In a different session, with no apparent connection to the 90Hz issue, the user asked to
fix the **invisible mouse cursor** across the whole desktop (a separate bug, not documented
here before). The fix that ended up working was forcing `GLPlatformInterface=egl` in
`kwinrc` (`[Compositing]`) — that makes KWin **fail** to start the OpenGL compositor
(`kwin_scene_opengl: Creating the OpenGL rendering failed: "Invalid QOpenGLContext::
globalShareContext()"`) and, since on this host `platformRequiresCompositing=false`, it
keeps running **without a compositor** instead of crashing. With that, the cursor is
visible (Xorg draws it directly, since `HWCursor false` has been set since before).

The user later noticed that the headset appeared "as just another screen" and asked
whether that was related to the bug in this document. **It's a reasonable hypothesis,
still unconfirmed:**

- With the compositor off, `DP-0` remains `enabled`/`connected` at `2880x1440@90` in
  `kscreen-doctor -o` and `xrandr`, same as documented above — that didn't change.
- `kscreen-doctor output.DP-0.disable` behaved **the same as before**: KScreen switched to
  reporting `disabled`, but `xrandr` kept showing `2880x1440 90.00 +` as the active mode.
  Same desync already documented, not investigated further since the alternative
  approaches (`xrandr --off`, NVIDIA MetaMode) are already ruled out above and it doesn't
  make sense to repeat them.
- Checked with the same KWin scripting mechanism (D-Bus) whether there were windows
  trapped on `DP-0`: **none** at the time of the check.
- **No `QRhiGles2: Context is lost` was observed during this session so far** with the
  compositor off and `DP-0` active. Short observation window, not conclusive.

**Why this might be relevant:** the original crash log cited both `plasmashell` and
`kwin_x11` losing the GL context. If the KWin compositor is completely off, half of the
failure mechanism documented above (`kwin_scene_opengl: Could not delete framebuffer
because no context is current`) has no context to lose — it doesn't exist. **But
`plasmashell` maintains its own `QRhiGles2`/RHI independent of the compositor**, so this
does NOT explain or rule out the second crash (the lock screen one, with DP-0 already
disabled) that was left unexplained above.

**Not verified, don't assume:** the system wasn't left running for a long time with the
compositor off + headset connected to confirm whether the crash-loop reappears or not. If
in a future session the crash does NOT happen again with this config, that's strong
evidence the KWin compositor (not Plasma/NVIDIA in general) was the mechanism. If it DOES
happen again, that confirms the problem lives elsewhere (probably `plasmashell`) and that
turning off the compositor doesn't fix anything underlying, it just changed the visible
symptom (cursor yes, but desktop with the headset "stuck" as a 4th screen).

**Side effect to monitor:** with no compositor, there are no visual effects, no
transparency, and none of the KWin logic that apparently used to make `DP-0` less visible
in the composited desktop. This might explain why the user says "it never looked like this
before" — with the compositor active, even though `DP-0` was technically `enabled`, the
composited rendering might have been hiding it or presenting it differently. Not confirmed,
this is just the simplest reading of the evidence available now.

## Follow-up (2026-08-07): the `GLPlatformInterface=egl` workaround caused black borders around windows later, and the agent made it worse trying to fix it live

**The exact "not verified, don't assume" risk flagged above materialized**, in a session
unrelated to the headset (mid-DP-1-hardware-diagnosis, see `docs/pruebas.jsonl` T030-T034):
after some time running with `~/.config/kwinrc`'s `[Compositing] GLPlatformInterface=egl`
still in place (leftover from the invisible-cursor fix above), the user reported **black
borders around windows**. `kwin_x11`'s own log confirmed the compositor still wasn't
starting (`Creating the OpenGL rendering failed: "Invalid QOpenGLContext::
globalShareContext()"`), consistent with the deliberate no-compositor workaround, but now
visibly degrading window rendering, not just hiding the cursor fix's tradeoff.

**Do NOT try to fix this live by running `kwin_x11 --replace` from the Claude Code agent's
Bash tool.** Tried exactly that, twice, second time with the full correct session
environment copied byte-for-byte from a genuinely running `plasmashell` process
(`DISPLAY=:0`, real `XAUTHORITY` from `/proc/<pid>/environ` — not the SDDM greeter's auth
file used the first time, `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus`,
`XDG_RUNTIME_DIR`). **Both times `kwin_x11` fell back to `nouveau` instead of the NVIDIA
driver** (`failed to load driver: nouveau`), even though `/dev/dri/card0` and `renderD128`
have correct `video`/`render` group permissions and `glxinfo` run from the same shell shows
the identical failure — so it isn't a stale-cookie or missing-env-var problem, something
about GLX/EGL vendor resolution genuinely doesn't work for a compositor launched from this
agent's shell context on this box. **Collateral damage that session:** `plasmashell`
segfaulted (SIGSEGV, `drkonqi` caught it) and its KDE-auto-restarted replacement fell back
to Mesa's `zink` (OpenGL-over-Vulkan) instead of the NVIDIA Vulkan ICD, which then hit
`VK_ERROR_DEVICE_LOST` and kept crash-looping. Opening a plain X11 app (`konsole`) from the
same shell DID work fine throughout (it doesn't need GLX) — so simple app-launching from
the agent's shell is fine, only compositor/heavy-GL processes are the problem.

**What actually worked: a plain reboot.** Not attempted this same session (ran out of
time), but this project has already established (see the DP-1 hotplug saga, same day) that
a clean reboot reliably resets driver/session state here when live poking doesn't.

**Still unexplained, for whoever picks this up:** why GLX/EGL vendor resolution picks
`nouveau` specifically when driven from this shell context, when the underlying device
nodes and permissions look identical to a normal login session. Worth checking, if it
recurs: `__GLX_VENDOR_LIBRARY_NAME`, `__EGL_VENDOR_LIBRARY_FILENAMES`, and whether the
agent's shell sits in a different cgroup/namespace than the graphical session that would
explain a DRI device visibility difference despite `ls -la /dev/dri` looking normal.

**Requested follow-up, not yet built:** the user asked for this incident to feed into a
future "survival script" — not designed yet as of this note. Whoever builds it should scope
it explicitly: is it (a) a *detector* that recognizes this failure signature (`kwin_x11`
log's `globalShareContext` line + `zink`/`VK_ERROR_DEVICE_LOST` in `plasmashell`'s log) and
recommends/performs a safe recovery instead of more live tinkering, (b) a hard *guardrail*
that refuses to let an agent run compositor-replacing commands (`kwin_x11 --replace`,
`plasmashell --replace`, similar) from a non-interactive shell at all, or (c) both. Ask the
user which scope they meant before building it — don't assume.
