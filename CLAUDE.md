# Context for agents working in this repo

HP Reverb G2 on Linux: patches (NVIDIA display driver, Monado WMR driver, Basalt SLAM,
xrizer, a hello_xr-based 360/VR180 player), scripts, and a procedure manual in `docs/`.
Upstream sources are not vendored: `scripts/bootstrap-lab.sh` clones them at pinned SHAs
and applies `patches/<series>/applies-on-base.txt`.

Read `docs/06-known-issues.md` before proposing anything. Several ideas were already tried
and ruled out with measurement.

## The one rule: verification is physical

90 Hz, flicker, image quality, tracking feel: anything visual is verified only by a human
looking in the headset. The Vulkan/OpenXR layer reports a clean modeset and 90.0 fps with a
dark panel. Logs, `xrandr` and fps counters are not evidence. Ask for a wear test, and
self-check with logs first so one wear test covers a whole batch of changes.

## Bring-up order

```bash
./scripts/bootstrap-lab.sh deps
./scripts/bootstrap-lab.sh nvidia      # then reboot
./scripts/bootstrap-lab.sh sources
./scripts/bootstrap-lab.sh build
sudo ./scripts/bootstrap-lab.sh patch-nv   # NVIDIA patches via DKMS, then reboot
./scripts/preflight.sh                 # READY / NOT READY, before Monado starts
./scripts/jack-in-wayland.sh 1 6dof    # needs the GNOME-on-Wayland session
./scripts/play360.sh <file-or-dir>     # or a Steam title through xrizer (docs/23)
```

If `lsusb` lacks `03f0:0580`, the problem is the USB port or cable, not the software
(`docs/00`, `docs/22`).

## Traps every user hits

- **Stale socket.** `kill -9` leaves `$XDG_RUNTIME_DIR/monado_comp_ipc`. Delete it before every
  start, and verify that the old service is really gone.
- **`found display mode` does not prove the real headset.** If the WMR builder fails, Monado
  falls back to a Simulated HMD that logs the same line. Check for `Using builder wmr`.
- **OpenVR runtime order.** A game that runs but shows nothing in the headset is usually
  `~/.config/openvr/openvrpaths.vrpath` listing SteamVR ahead of xrizer (a Steam update can
  reorder it). Run `scripts/sanity-check.sh soft --fix-vrpath`, then restart Steam.
- **Player stdin.** `hello_xr` treats stdin EOF as "end of run" and exits 0 with no error:
  use `sleep N | hello_xr ...`, never `< /dev/null`. `monado-service` needs the opposite,
  `XRT_NO_STDIN=1`.
- **`play360.sh` wraps the player in `timeout`** (default 300 s). Pass `-t <seconds>` for
  longer runs.
- **`pgrep -f` matches its own shell** when the pattern is in the command line. Bracket the
  pattern (`pgrep -f "monado[-]service"`) or use `pgrep -x`, and kill by PID.
- **Basalt can look built when it is not.** `~/vr/basalt/build/libbasalt.so` must exist
  before asking for `6dof` (`WMR_SLAM=1`).
- **Killing the Steam wrapper does not stop the game.** Use `scripts/game-stop.py`.
- **Keep xrizer's brightness gain at 1.0.** Other values produced visible panel flicker (`docs/112-flicker-resolved-two-causes.md`).

## Key docs

| Topic | File |
|---|---|
| USB topology, why the companion device disappears | `docs/00-hardware-usb.md` |
| The 90 Hz lab plan and the NVIDIA 6 bpc fix | `docs/04-lab-90hz.md`, `docs/13-bug-6bpc.md` |
| What not to chase again | `docs/06-known-issues.md` |
| Cable and connector ladder | `docs/22-cable-connector-diagnosis.md` |
| Controllers and 6DoF | `docs/03-controllers.md`, `docs/125-controller-6dof-root-cause-and-plan.md` |
| Game results via xrizer | `docs/23-game-compatibility.md` |
| Code review of the tooling and fixes still unverified | `docs/147-full-code-review-2026-10-12.md` |

Docs, comments, commit messages and filenames are in English. Measurements beat opinions:
say how you measured it.
