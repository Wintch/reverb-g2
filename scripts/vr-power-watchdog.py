#!/usr/bin/env python3
"""vr-power-watchdog.py -- keeps the machine at minimum watts at rest and switches it to
full performance the moment a VR session or a game is actually running, automatically.

Why this exists (2026-08-23, T246): scripts/vr-power-setup.sh already knew how to pin the
box to performance for a session (--apply) -- what was missing was the OTHER direction, and
doing it without a human remembering to run anything. The user's framing: "arrancar light,
prender la maquina full solo cuando el juego realmente esta andando" (start light, only go
full when the game is really running). This is deliberately reactive/poll-based rather than
hooked into every possible launch path (vr-launcher.py, jack-in-wayland.sh, the pmadminka
run-queue, or a game started by hand from the Steam UI) -- there is no single choke point
all of those share, but there IS a single answer to "is anything actually running right
now", and that's cheaper and more robust than chasing every launcher.

"Active" = a monado-service process is alive, OR game-stop.py's scan() finds a live Proton
game tree (imported directly, not shelled out, same trick pmadminka-agent.py already uses
for the same module -- the filename has a hyphen so it can't be a normal import).

KNOWN GAP (2026-08-23, found running Unigine Heaven/Superposition benchmarks in a
standalone Proton prefix outside Steam): game_stop.scan() only recognizes processes Steam
itself launched (it matches on the SteamAppId/STEAM_COMPAT_DATA_PATH env vars Steam sets).
A Windows .exe run via a hand-built `STEAM_COMPAT_DATA_PATH=... proton run ...` invocation,
with no Steam appmanifest at all, is invisible to this watchdog -- it will sit in `saver`
even while such a benchmark is actually GPU-bound. Not fixed here; a caller doing that kind
of standalone run should bracket it with vr-power-setup.sh --apply/--saver itself (see
q2rtx-power-sweep.sh for the pattern), the same way it already has to hold this watchdog
stopped for a controlled measurement.

Debounce: going TO performance is immediate (more watts is never disruptive). Going back to
saver waits for IDLE_DEBOUNCE_TICKS consecutive idle checks, so a brief gap between one
game's exit and the next launch (or a Monado restart cycle) doesn't cause flapping.

Writes the current mode to STATE_FILE (world-readable, root-owned dir) so unprivileged
readers -- pmadminka-agent.py's heartbeat, status-dashboard.py's /api/status -- can report
it without needing root themselves. Deliberately root's job alone to touch sysfs/nvidia-smi;
see vr-power-setup.sh for why persistence mode is never touched here (display modeset risk
on a box where the desktop monitor lives on the same GPU).

Run by hand to watch it decide: sudo python3 vr-power-watchdog.py
Normal install: vr-power-watchdog.service (systemd system unit, root, boots enabled).
"""
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POWER_SETUP = os.path.join(SCRIPT_DIR, "vr-power-setup.sh")
STATE_FILE = "/run/vr-power-mode"

POLL_INTERVAL_S = 10
IDLE_DEBOUNCE_TICKS = 3  # ~30s of confirmed idle before dropping back to saver


def _load_game_stop():
    import importlib.util

    path = os.path.join(SCRIPT_DIR, "game-stop.py")
    spec = importlib.util.spec_from_file_location("game_stop_lib", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


game_stop = _load_game_stop()


def monado_running():
    # Bracket trick per this repo's own pgrep gotcha: a bare "monado-service" pattern can
    # match this process's own cmdline in some shells.
    r = subprocess.run(["pgrep", "-f", "monado[-]service"], capture_output=True, text=True)
    return r.returncode == 0


def game_running():
    try:
        return bool(game_stop.scan())
    except Exception as e:
        print(f"[watchdog] game_stop.scan() failed: {e}", file=sys.stderr)
        return False


def is_active():
    return monado_running() or game_running()


def set_mode(mode):
    flag = "--apply" if mode == "performance" else "--saver"
    r = subprocess.run([POWER_SETUP, flag], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[watchdog] {flag} failed: {r.stderr.strip()}", file=sys.stderr)
        return False
    try:
        with open(STATE_FILE, "w") as f:
            f.write(mode + "\n")
        os.chmod(STATE_FILE, 0o644)
    except OSError as e:
        print(f"[watchdog] could not write {STATE_FILE}: {e}", file=sys.stderr)
    print(f"[watchdog] -> {mode}")
    return True


def main():
    if os.geteuid() != 0:
        print("this needs root (writes sysfs/nvidia-smi directly)", file=sys.stderr)
        return 1

    current_mode = None  # unknown -- force the first tick to act
    idle_streak = 0

    while True:
        active = is_active()

        if active:
            idle_streak = 0
            if current_mode != "performance":
                if set_mode("performance"):
                    current_mode = "performance"
        else:
            idle_streak += 1
            if current_mode != "saver" and (current_mode is None or idle_streak >= IDLE_DEBOUNCE_TICKS):
                if set_mode("saver"):
                    current_mode = "saver"

        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    sys.exit(main())
