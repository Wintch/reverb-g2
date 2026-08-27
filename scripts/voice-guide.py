#!/usr/bin/env python3
"""voice-guide.py -- spoken cues for the demo booth, in Spanish, via espeak-ng.

The demo runs many first-time guests back to back; a spoken cue ("ponete el casco", "mirá al
frente") is faster and friendlier than the operator repeating himself, and pairs with the
session recorder (docs/75). espeak-ng is already installed; this renders the cue to a WAV and
plays it through a CHOSEN sink (espeak can't target a sink itself, same trick as
reseat_audio.py) -- so "ponete el casco" can go to the room speakers while an in-headset cue
goes to the headset.

  voice-guide.py say "texto libre"            speak arbitrary text
  voice-guide.py cue <nombre>                 speak a predefined cue (see `list`)
  voice-guide.py list                         list the predefined cues
  voice-guide.py sequence [--wait]            run the guided first-timer sequence
                                              (--wait: pause for Enter between steps)

Options (any command): --sink <name>  play through a specific sink (default: the system
default sink); --room / --headset shortcuts resolve the external / USB sink by name.
Voice via VR_VOICE (default 'es+f3', a clear Spanish female); speed via VR_VOICE_SPEED (150).
"""
import os
import subprocess
import sys
import tempfile

VOICE = os.environ.get("VR_VOICE", "es+f3")
SPEED = os.environ.get("VR_VOICE_SPEED", "150")

# Spanish cues for the booth. Keep them short and plain -- these are read aloud to a guest.
CUES = {
    "ponete-casco":  "Ponete el casco, por favor. Acomodalo hasta que la imagen se vea nítida.",
    "ajusta-foco":   "Movelo despacio hacia arriba y abajo hasta que se vea lo más nítido posible.",
    "mira-frente":   "Mirá al frente, derecho.",
    "gira-cabeza":   "Girá la cabeza despacio, a un lado y al otro.",
    "recentrar":     "Si la imagen se corre de lugar, apretá el botón A para volver al centro.",
    "sonido":        "¿Escuchás el sonido bien?",
    "todo-bien":     "¿Se ve todo bien?",
    "listo":         "Listo. Ya podés empezar a disfrutar.",
    "sacate-casco":  "Cuando quieras, sacate el casco con cuidado. Gracias por probarlo.",
    "quieto-luz":    "Quedate quieto un momento mientras el seguimiento se estabiliza.",
}

# The guided flow for one guest, in order. (cue-name, seconds-to-wait-after).
SEQUENCE = [
    ("ponete-casco", 5),
    ("ajusta-foco",  4),
    ("quieto-luz",   3),
    ("mira-frente",  2),
    ("sonido",       3),
    ("todo-bien",    3),
    ("recentrar",    3),
    ("listo",        0),
]


def resolve_sink(args):
    if "--room" in args:
        return _sink_by("pci-.*07_00.4.analog-stereo|Starship|Matisse")
    if "--headset" in args:
        return _sink_by("usb.*analog-stereo")
    if "--sink" in args:
        i = args.index("--sink")
        return args[i + 1] if i + 1 < len(args) else None
    return None  # default sink


def _sink_by(pat):
    try:
        out = subprocess.run(["pactl", "list", "sinks", "short"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    import re
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and re.search(pat, parts[1], re.I):
            return parts[1]
    return None


def speak(text, sink=None):
    """espeak-ng -> WAV -> play through `sink` (or the default). espeak can't pick a sink."""
    if not text:
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        wav = tf.name
    try:
        subprocess.run(["espeak-ng", "-v", VOICE, "-s", SPEED, "-w", wav, text],
                       capture_output=True, timeout=15)
        player = "pw-play" if _which("pw-play") else ("paplay" if _which("paplay") else None)
        if player == "pw-play":
            cmd = ["pw-play"] + (["--target", sink] if sink else []) + [wav]
        elif player == "paplay":
            cmd = ["paplay"] + (["-d", sink] if sink else []) + [wav]
        else:
            # last resort: let espeak play to the default sink directly
            subprocess.run(["espeak-ng", "-v", VOICE, "-s", SPEED, text], capture_output=True, timeout=15)
            return
        subprocess.run(cmd, capture_output=True, timeout=20)
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass


def _which(b):
    return subprocess.run(["which", b], capture_output=True).returncode == 0


def main(argv):
    args = argv[1:]
    cmd = args[0] if args else "list"
    sink = resolve_sink(args)

    if cmd == "say":
        text = args[1] if len(args) > 1 else ""
        speak(text, sink)
    elif cmd == "cue":
        name = args[1] if len(args) > 1 else ""
        if name not in CUES:
            print(f"cue '{name}' no existe. Ver: voice-guide.py list", file=sys.stderr)
            return 2
        speak(CUES[name], sink)
    elif cmd == "list":
        print("Cues:")
        for k, v in CUES.items():
            print(f"  {k:14s} {v}")
        print("\nSequence:", " -> ".join(n for n, _ in SEQUENCE))
    elif cmd == "sequence":
        import time
        wait = "--wait" in args
        for name, secs in SEQUENCE:
            print(f"[voz] {name}: {CUES[name]}")
            speak(CUES[name], sink)
            if wait:
                try:
                    input("   (Enter para el siguiente cue) ")
                except EOFError:
                    time.sleep(secs)
            elif secs:
                time.sleep(secs)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
