#!/usr/bin/env python3
"""yaw-protocol-voice.py -- speak the 3-minute head-motion script for the EuRoC "yaw" recording.

The offline backend A/B (docs/80, scripts/replay-basalt-variants.py) needs ONE recorded wearer
session whose head motion is known and repeatable: a still baseline, isolated fast yaw, isolated
fast pitch, isolated roll, then free play. This reads that script aloud INTO THE HEADSET (the
wearer has it on -- voice-guide.py's --headset sink), with fixed timings, and writes the phase
boundaries with wall-clock + monotonic timestamps to ~/vr/logs/yaw-protocol-<date>.json so the
analysis can slice the recording by phase as well as by the IMU-measured rotation regime.

Run it right after pressing the dashboard's "R" button, once Aircar is up and the wearer says
they're ready. Total ~3 min 10 s. --dry-run prints the script with no audio and no waiting.

Usage: yaw-protocol-voice.py [--dry-run] [--room | --sink NAME]   (default: --headset)
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("voice_guide", HERE / "voice-guide.py")
vg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vg)

# (phase, text spoken at its start, seconds the phase lasts after the cue)
SCRIPT = [
    ("intro", "Protocolo de yaw. Quedate quieto, mirando al frente, hasta que te avise.", 30),
    ("yaw", "Ahora, diez giros rápidos de cabeza, de izquierda a derecha, como mirando los dos espejos. Rápido, uno tras otro.", 25),
    ("settle-1", "Quieto, mirando al frente.", 8),
    ("pitch", "Ahora, diez cabeceos rápidos, arriba y abajo.", 25),
    ("settle-2", "Quieto, mirando al frente.", 8),
    ("roll", "Ahora, diez inclinaciones rápidas, la oreja hacia cada hombro.", 25),
    ("settle-3", "Quieto, mirando al frente.", 8),
    ("free", "Ahora jugá libre, un minuto, moviendo la cabeza como quieras.", 60),
    ("end", "Listo. Terminó el protocolo. Cerrá el juego cuando quieras.", 0),
]


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    sink = None if dry else vg.resolve_sink(args if any(a in args for a in ("--room", "--sink")) else ["--headset"])
    out = Path.home() / "vr" / "logs" / f"yaw-protocol-{time.strftime('%Y%m%d-%H%M%S')}.json"
    phases = []
    t0_mono, t0_wall = time.monotonic(), time.time()
    print(f"sink: {sink or 'default'}  log: {out}")
    for name, text, secs in SCRIPT:
        rec = {"phase": name, "t_mono_s": round(time.monotonic() - t0_mono, 2),
               "wall": time.strftime("%Y-%m-%dT%H:%M:%S"), "unix": round(time.time(), 3), "seconds": secs}
        phases.append(rec)
        print(f"[{rec['t_mono_s']:>6.1f}s] {name:<9} {text}", flush=True)
        if not dry:
            vg.speak(text, sink)
            time.sleep(secs)
    if not dry:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"started_unix": t0_wall, "phases": phases}, indent=2))
        print(f"phase log written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
