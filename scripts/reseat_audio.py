#!/usr/bin/env python3
"""Audible feedback for the reseat ladder -- because your eyes are behind the PC.

Born 2026-08-13 (T174), from the user's own observation while fixing a seat: the
headset's audio device stays perfectly stable through the whole procedure, and
when both hands are on a connector behind the tower nobody can read a terminal.
So the census speaks.

The mapping is designed to be learnable in one run, without memorising anything:
MORE BEEPS = CLOSER.

    1 beep, low     nothing enumerated at all
    2 beeps         exactly one branch is up (the T171 seat lottery)
    3 beeps         everything is up but the cameras are on the USB2 face (480M)
    rising arpeggio + "ready to jack in"    5/5 with the cameras at 5 Gbps

If `espeak-ng` is installed the states are also spoken; without it the beeps
carry the whole message and nothing breaks. Install with:

    sudo apt install espeak-ng

TWO REAL LIMITATIONS, stated rather than discovered later:
  * The G2's own speakers hang off the USB2 branch. If that branch is the one
    missing, the sound comes out of whatever the system default is instead --
    which is fine (you are at the tower, not wearing the headset) but it does
    mean the audio path itself is not a reliable indicator.
  * At the bare pre-login console (power-on.py --pre-login) nobody is logged in,
    so there is no PipeWire to play into and this degrades to silence. It works
    from a desktop session, which is where a human does a reseat anyway.

Standalone:  ./scripts/reseat_audio.py        # loop until "ready to jack in"
As a library: announce(key) / classify(...) -- see power-on.py's wait_for_reseat.
"""

import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

RATE = 44100
# Deliberately quiet. This can end up playing through headphones that are on or
# next to a head, and the sink jumps to the headset the instant it enumerates
# (docs/06's "startling right next to your ears" note). Loudness is not the
# point -- distinguishability is.
AMP = 0.12

# key -> (number of beeps, base frequency, spoken phrase)
# The beep count is the whole UI: 1 -> 2 -> 3 -> 4 -> arpeggio is monotonic
# progress towards a working headset, so it needs no memorising and no screen.
STATES = {
    "none":  (1, 262.0, "no headset"),
    "one":   (2, 392.0, "one branch only"),
    "slow":  (3, 523.0, "cameras at low speed"),
    "dark":  (4, 587.0, "panel dark"),
    "lit":   (5, 698.0, "panel ignited"),
    "ready": (0, 0.0,   "ready to jack in"),
}
# "panel ignited" and "ready to jack in" are deliberately TWO stages, because
# they are two different physical facts and the difference is the one this
# project keeps re-learning: the HP logo is power + HID and lights with no video
# whatsoever, while the panel itself only shows anything once a compositor is
# scanning out. Logo on with a dark panel is the normal intermediate state, not
# a fault (docs/22). So: ignited = let go of the cable. Ready = a session is
# live and the backlight is really on.

# Edge-triggered extras: said ONCE, when they first show up. These are not
# states -- nothing about them blocks the headset -- so they must not enter the
# beep-count ladder above or they'd break its "more beeps = closer" meaning.
EVENTS = {
    "gamepad":    (1, 880.0, "gamepad found"),
    "left":       (1, 880.0, "left controller found"),
    "right":      (1, 880.0, "right controller found"),
    "nocontrols": (1, 330.0, "no controllers"),
}

_cache = {}
_last_key = None
_last_time = 0.0
_enabled = None


def _player():
    """pw-play first (this is a PipeWire box), then the compatibility shims."""
    for cmd in ("pw-play", "paplay", "ffplay"):
        p = shutil.which(cmd)
        if p:
            return p
    return None


def pick_sink():
    """Play into something that is NOT the headset.

    The G2's own speakers become the system default the instant they enumerate,
    which makes them the worst possible target for this particular tool: they
    hang off the very branch being diagnosed (so they vanish exactly when there
    is something to report), and during a reseat the human is at the tower with
    the headset lying on a desk. Preference: motherboard analog out, then any
    non-USB sink, then whatever the default is. Override with
    REVERB_AUDIO_SINK=<node name>."""
    forced = os.environ.get("REVERB_AUDIO_SINK")
    if forced:
        return forced
    if "sink" in _cache:
        return _cache["sink"]
    names = []
    if shutil.which("pactl"):
        try:
            out = subprocess.run(["pactl", "list", "short", "sinks"], env=_env(),
                                 capture_output=True, text=True, timeout=5).stdout
            names = [l.split("\t")[1] for l in out.splitlines() if "\t" in l]
        except (OSError, subprocess.TimeoutExpired, IndexError):
            names = []
    choice = None
    for n in names:
        if "usb" not in n.lower() and "analog" in n.lower():
            choice = n
            break
    if not choice:
        for n in names:
            if "usb" not in n.lower():
                choice = n
                break
    _cache["sink"] = choice
    return choice


def available():
    """True if anything can be played at all. Cached -- called in a poll loop."""
    global _enabled
    if _enabled is None:
        _enabled = _player() is not None
    return _enabled


def _env():
    """Let a root-run script reach the logged-in user's sound server. Does NOT
    help at the pre-login console (no session exists there yet), by design --
    it only covers `sudo ./power-on.py` from a desktop."""
    env = dict(os.environ)
    if os.geteuid() == 0 and Path("/run/user/1000/pipewire-0").exists():
        env.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
    return env


def _tone_file(freqs, beep_ms=110, gap_ms=70):
    """Render a short beep sequence to a WAV once and reuse it. Each beep gets a
    5 ms fade in/out: a raw square start clicks, and a click is exactly the kind
    of noise that reads as 'something broke' in a diagnostic tool."""
    key = (tuple(freqs), beep_ms, gap_ms)
    if key in _cache:
        return _cache[key]
    frames = bytearray()
    fade = int(RATE * 0.005)
    for f in freqs:
        n = int(RATE * beep_ms / 1000)
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade)
            v = int(AMP * env * math.sin(2 * math.pi * f * i / RATE) * 32767)
            frames += struct.pack("<h", v)
        frames += b"\x00\x00" * int(RATE * gap_ms / 1000)
    path = Path(tempfile.gettempdir()) / (
        "reverb-tone-%s.wav" % "-".join(str(int(f)) for f in freqs)
    )
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    _cache[key] = path
    return path


def _play(path):
    p = _player()
    if not p:
        return
    sink = pick_sink()
    if p.endswith("ffplay"):
        cmd = [p, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
    elif p.endswith("paplay"):
        cmd = [p] + (["-d", sink] if sink else []) + [str(path)]
    else:
        cmd = [p] + (["--target", sink] if sink else []) + [str(path)]
    try:
        subprocess.run(cmd, timeout=8, env=_env(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass


# Voice: espeak-ng's variants, "+f1".."+f5" being the female ones. Override the
# whole thing with REVERB_VOICE (e.g. "es+f3" for Spanish, "en" for the default
# male). Rendered to a WAV instead of letting espeak play it directly -- espeak
# has no way to pick a sink, and the whole point here is to stay off the
# headset's own output.
VOICE = os.environ.get("REVERB_VOICE", "en+f3")


def _speak(phrase):
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if not espeak:
        return
    key = ("say", phrase, VOICE)
    path = _cache.get(key)
    if path is None:
        path = Path(tempfile.gettempdir()) / (
            "reverb-say-%s.wav" % "".join(c if c.isalnum() else "_" for c in phrase)
        )
        try:
            subprocess.run([espeak, "-v", VOICE, "-a", "80", "-s", "150",
                            "-w", str(path), phrase], timeout=10, env=_env(),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return
        if not path.exists():
            return
        _cache[key] = path
    _play(path)


def announce(key, repeat_after=5.0, force=False):
    """Say/play the state. Repeats itself every `repeat_after` seconds while the
    state doesn't change: with your head behind the tower, silence is
    indistinguishable from a crashed script."""
    global _last_key, _last_time
    if not available():
        return
    now = time.monotonic()
    if not force and key == _last_key and now - _last_time < repeat_after:
        return
    _last_key, _last_time = key, now
    beeps, freq, phrase = STATES.get(key, STATES["none"])
    if key == "ready":
        _play(_tone_file([523.25, 659.25, 783.99, 1046.5], beep_ms=90, gap_ms=20))
    else:
        _play(_tone_file([freq] * beeps))
    _speak(phrase)


def event(key):
    """One-shot announcement for something that appeared (a controller, the
    gamepad). Does not touch the state repeater above."""
    if not available() or key not in EVENTS:
        return
    beeps, freq, phrase = EVENTS[key]
    _play(_tone_file([freq] * beeps, beep_ms=80, gap_ms=40))
    _speak(phrase)


def classify(usb2_ok, ss_ok, camera_speed, dp_ok=False, session_up=False):
    """The states the ear needs to tell apart, in the vocabulary of docs/22's
    branch split. 'slow' is the trap this exists for: 4 of 5 devices present
    looks like success and is useless -- the cameras are hanging off the hub's
    USB2 face at 480M and SLAM will starve on that."""
    if not usb2_ok and not ss_ok:
        return "none"
    if not usb2_ok or not ss_ok:
        return "one"
    if camera_speed < 5000:
        return "slow"
    # A LIVE SESSION OUTRANKS SYSFS, and this order is load-bearing. Once mutter
    # hands the connector to Monado as a DRM lease, the connector stops reading
    # `connected` to everyone else -- so a running session looks exactly like a
    # dead panel from /sys/class/drm. Checking dp_ok first made this report
    # "panel dark" during a perfectly healthy 90 Hz session (caught live
    # 2026-08-13) and, worse, the caller would then keep firing panel.py
    # activate into a session that is already presenting.
    if session_up:
        return "ready"
    return "lit" if dp_ok else "dark"


# ---- standalone loop -------------------------------------------------------

HERE = Path(__file__).resolve().parent
GAMEPAD_ID = "045e:028e"


def _census():
    """Own, minimal census so this runs without importing the bigger script."""
    try:
        out = subprocess.run(["lsusb"], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False, False, 0, False
    usb2 = all(d in out for d in ("04b4:6506", "03f0:0580", "0bda:4c15"))
    ss = "04b4:6504" in out
    gamepad = GAMEPAD_ID in out
    speed = 0
    devs = Path("/sys/bus/usb/devices")
    if devs.is_dir():
        for d in devs.iterdir():
            try:
                if (d / "idVendor").read_text().strip() == "045e" and \
                   (d / "idProduct").read_text().strip() == "0659":
                    speed = int((d / "speed").read_text().strip() or "0")
                    break
            except (OSError, ValueError):
                continue
    return usb2, ss, speed, gamepad


def _dp_ok():
    """The G2's panel raises hotplug only after the WMR activation, and its full
    EDID is 384 bytes. Anything shorter on a DP connector is some other sink."""
    for c in Path("/sys/class/drm").glob("card*-DP-*"):
        try:
            if (c / "status").read_text().strip() == "connected" and \
               (c / "edid").stat().st_size >= 384:
                return True
        except OSError:
            continue
    return False


def _session_up():
    try:
        r = subprocess.run(["pgrep", "-f", "monado[-]service"],
                           capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _activate_panel():
    panel = HERE / "panel.py"
    if not panel.exists():
        return
    try:
        subprocess.run([sys.executable, str(panel), "activate"], timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _controllers():
    """(left_ok, right_ok). Costs ~3 s, so it is called once on arrival at a
    lit panel, never inside the poll loop."""
    script = HERE / "controller-pair-check.py"
    if not script.exists():
        return False, False
    try:
        r = subprocess.run([sys.executable, str(script), "3"],
                           capture_output=True, text=True, timeout=25)
    except (OSError, subprocess.TimeoutExpired):
        return False, False
    out = r.stdout + r.stderr
    import re
    return (bool(re.search(r"left.*online", out)),
            bool(re.search(r"right.*online", out)))


def main():
    stop_at_panel = "--stop-at-panel" in sys.argv
    if not available():
        print("No hay reproductor de audio (pw-play/paplay/ffplay). Sin sonido.")
    if not (shutil.which("espeak-ng") or shutil.which("espeak")):
        print("Sin espeak-ng: solo tonos. Para voz: sudo apt install espeak-ng")
    sink = pick_sink()
    print(f"Salida: {sink or 'la default del sistema'}  (cambiar con REVERB_AUDIO_SINK=)")
    print(f"Voz: {VOICE}  (cambiar con REVERB_VOICE=, ej. es+f3)")
    print("Escalera: 1 pitido nada | 2 una rama | 3 cámaras lentas | 4 panel oscuro |")
    print("          5 'panel ignited' (soltá el cable) | arpegio 'ready to jack in'")
    print("Ctrl+C para salir.\n")
    said = set()
    last_activate = 0.0
    # A healthy bring-up walks the whole ladder in about two seconds, and
    # narrating all of it would be noise on every good day. So intermediate
    # states stay SILENT until they have persisted this long: the ladder only
    # speaks when something is actually stuck, which is the only time it has
    # anything to say. Terminal states announce immediately.
    QUIET_GRACE = 6.0
    key, first_seen = None, time.monotonic()
    try:
        while True:
            usb2, ss, speed, gamepad = _census()
            dp = _dp_ok()
            prev, key = key, classify(usb2, ss, speed, dp, _session_up())
            if key != prev:
                first_seen = time.monotonic()
            print(f"  USB2 {'OK' if usb2 else '--'} | SS {'OK' if ss else '--'} | "
                  f"cám {speed}M | DP {'OK' if dp else '--'} -> {key}     ",
                  end="\r", flush=True)
            terminal = key == "ready" or (stop_at_panel and key == "lit")
            if terminal or time.monotonic() - first_seen >= QUIET_GRACE:
                announce(key)

            if gamepad and "gamepad" not in said:
                said.add("gamepad")
                event("gamepad")

            # USB is complete but the panel hasn't raised hotplug: send the
            # activation again. Not once -- the panel powers itself back off a
            # few seconds after an activation with no video behind it.
            if key == "dark" and time.monotonic() - last_activate > 8:
                last_activate = time.monotonic()
                _activate_panel()

            if key in ("lit", "ready") and "controls" not in said:
                said.add("controls")
                left, right = _controllers()
                if left:
                    event("left")
                if right:
                    event("right")
                if not (left or right):
                    event("nocontrols")

            if key == "lit" and stop_at_panel:
                print("\n  Panel encendido. (--stop-at-panel)")
                return 0
            if key == "ready":
                print("\n  Sesión viva y panel escaneando. Listo.")
                return 0
            time.sleep(1.5)
    except KeyboardInterrupt:
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
