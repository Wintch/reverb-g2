#!/usr/bin/env python3
"""vr-launcher.py -- "our own launcher", the single entry point between the boot
selector's OK verdict and something actually running in the headset.

Brings up Monado first (jack-in-wayland.sh), then routes to whichever option was
picked: the 360/VR180 player, or one of the Steam VR titles confirmed working in
docs/23-game-compatibility.md's "Working" table (GAMES below is that table,
copied by hand -- keep them in sync if a game's status there changes). Aircar
stays the timeout default: user's own verdict was "first game I'd call 99%".
The non-Steam option is an honest stub, not built -- nothing non-Steam has been
identified or tested yet, don't fake a working option.

Prerequisite this script does NOT and CANNOT automate: any Steam VR title's
launch options must already be set once via Steam's own UI (Properties ->
Launch Options) -- docs/23's "Trap: Steam launch options edited on disk don't
exist" already established that editing localconfig.vdf directly while Steam
runs is unreliable/dangerous.

  ./scripts/vr-launcher.py [mode] [3dof|6dof]   (passed through to jack-in-wayland.sh)
"""
import os
import select
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VR = HERE.parent
if (Path.home() / "vr" / "monado").is_dir():
    VR = Path.home() / "vr"

MODE = sys.argv[1] if len(sys.argv) > 1 else "1"
TRACKING = sys.argv[2] if len(sys.argv) > 2 else "3dof"

IPC_SOCKET = Path("/run/user/1000/monado_comp_ipc")

# Verbose logging, per the docs/27 survey -- turned ON here (not left as a
# someday-maybe) because that's what was asked for after the survey landed.
# Rule from docs/23's own trap: anything that needs to reach the actual
# Proton/game process must be exported BEFORE the `steam` client starts, not
# set via per-game Launch Options -- so this has to happen here, in the env
# passed to the Popen call, not anywhere downstream. XR_LOADER_DEBUG applies
# to any OpenXR client (the 360 player too, not just Steam titles) since
# it's read by libopenxr_loader.so regardless of who links it.
LOG_DIR = VR / "logs"
LOG_DIR.mkdir(exist_ok=True)
GAME_ENV = {
    **os.environ,
    "XR_LOADER_DEBUG": "all",
    "PROTON_LOG": "1",
    "PROTON_LOG_DIR": str(LOG_DIR),
    # Proton's own base set (+timestamp,+pid,+tid,+seh,+unwind,+debugstr,
    # +loaddll,+mscoree) plus +env/+file per docs/27 -- setting this
    # ourselves, since an explicit WINEDEBUG here would otherwise just get
    # overridden by whichever value Proton auto-picks when PROTON_LOG=1 sees
    # nothing already set.
    "WINEDEBUG": "+timestamp,+pid,+tid,+seh,+unwind,+debugstr,+loaddll,+mscoree,+env,+file",
    "DXVK_LOG_LEVEL": "info",
    "VKD3D_DEBUG": "warn",
}
# NOT automated here, on purpose: Unreal Engine's own -log/-LogCmds flags
# (Aircar) need to reach the game binary itself, which only happens via
# Steam's per-game Launch Options UI -- docs/23's "Trap: Steam launch
# options edited on disk don't exist" already established that editing
# localconfig.vdf directly while Steam runs is unreliable/dangerous. Add
# "-log -LogCmds=\"LogInit Verbose, LogHMD Verbose\"" there by hand if
# UE-level detail is ever needed. Unity's Player.log needs no flag at all --
# it's already produced every run at ~/.config/unity3d/<Company>/<Product>/
# Player.log, just go read it.

# name, Steam AppID -- from docs/23-game-compatibility.md's "Working" table only.
# Order matches the doc (roughly discovery order, not a ranking).
GAMES = [
    ("International Space Station Tour VR", "797200"),
    ("Aliens Attack VR", "932190"),
    ("Cosmic Flow: A Relaxing VR Experience", "1267950"),
    ("VRSailing by BeTomorrow", "579050"),
    ("SUPERHOT VR", "617830"),
    ("VRChat", "438100"),
    ("Propagation VR", "1363430"),
    ("Aircar", "1073390"),
    ("Google Earth VR", "348250"),
    ("Dead Herring VR", "1498490"),
    ("Tank Mechanic Simulator VR", "1463010"),
    ("SafeZoneVR", "1701090"),
]
DEFAULT_GAME = "Aircar"


JACKIN_OUT_LOG = LOG_DIR / "jack-in-launcher.log"


def _save_jackin_output(stdout, stderr, rc):
    """Persist jack-in-wayland.sh's OWN output (not Monado's log -- that one
    already lands in ~/vr/jack-in-wayland.log).

    Real gap found 2026-08-11 (T145): this launcher runs jack-in-wayland.sh with
    capture_output=True and only echoes it to tty4, which nothing records. When the
    boot chain failed that night with "Found no connectors available for direct
    mode", the ONE piece of evidence that would have discriminated between "the
    panel/DP never came up" and "the connector was up but mutter didn't offer it
    for lease yet" was jack-in-wayland.sh's own pre-flight lines ("HMD connector
    (non-desktop=1) up." vs. the "!!" warnings) -- printed to a VT that had already
    been overwritten by agetty by the time anyone looked. /tmp/vr-launcher-console-
    debug.log stayed empty precisely because capture_output=True swallows this
    stream before it can reach that redirect. Same lesson as the tty-hides-stderr
    trap in vr-launcher-console.sh: cheap file, harmless, keep it permanently."""
    try:
        stamp = subprocess.run(["date", "-Iseconds"], capture_output=True, text=True).stdout.strip()
        with open(JACKIN_OUT_LOG, "a") as f:
            f.write(f"\n===== {stamp}  mode={MODE} tracking={TRACKING} rc={rc} =====\n")
            f.write(stdout or "")
            if stderr:
                f.write("----- stderr -----\n")
                f.write(stderr)
    except OSError as e:
        print(f"(could not save the jack-in log: {e})")


def bring_up_monado():
    print("=== subiendo Monado ===")
    IPC_SOCKET.unlink(missing_ok=True)  # SIGKILL de una corrida anterior no limpia esto
    # 180s, no 60s -- encontrado en vivo 2026-08-10: jack-in-wayland.sh's propio
    # peor caso (10s de poll de DP + hasta 3 intentos de ~50s cada uno con 3s de
    # settle entre reintentos) puede superar los 166s. Con 60s, un TimeoutExpired
    # sin capturar tiraba todo el launcher abajo a mitad de un reintento legitimo
    # y dejaba un monado-service huerfano corriendo (subprocess.run mata al hijo
    # directo en el timeout, pero setsid dentro de jack-in-wayland.sh ya habia
    # desacoplado a monado-service de ese proceso).
    try:
        r = subprocess.run(
            [str(VR / "jack-in-wayland.sh"), MODE, TRACKING],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired as e:
        print(f"jack-in-wayland.sh no termino en 180s -- abortando y limpiando.")
        partial = e.stdout if isinstance(e.stdout, (str, type(None))) else e.stdout.decode(errors="replace")
        _save_jackin_output(partial, "(timeout a los 180s)", "timeout")
        if partial:
            print(partial)
        # pgrep + kill, not pkill -- matches jack-in-wayland.sh's own convention
        # elsewhere in this project (pkill isn't consistently available/safe here).
        pids = subprocess.run(["pgrep", "-f", "monado[-]service"], capture_output=True, text=True).stdout.split()
        for pid in pids:
            subprocess.run(["kill", "-9", pid])
        IPC_SOCKET.unlink(missing_ok=True)
        return False
    _save_jackin_output(r.stdout, r.stderr, r.returncode)
    print(r.stdout)
    if r.returncode != 0 or not IPC_SOCKET.exists():
        print("jack-in-wayland.sh no dejo el socket de Monado listo.")
        print(r.stderr)
        return False
    return True


def check_controller_battery():
    """Runs controller-battery-check.py right after Monado is up, before anything is
    actually launched -- see docs/03-controllers.md's "Battery status" section and
    patches/monado/0040 for why this can't happen earlier (in power-on.py, before
    Monado exists) or via a lighter standalone HID query like controller-pair-check.py's.
    Never blocks: same philosophy as the controller-presence check in power-on.py step
    5 -- only the headset itself (jack-in-wayland.sh's own DP/USB checks) stops the
    user, battery is informational. A missing/old libmonado build without the patch
    just prints "no data" and moves on, it doesn't fail the launch."""
    check_py = HERE / "controller-battery-check.py"
    try:
        r = subprocess.run([sys.executable, str(check_py)], timeout=10)
        if r.returncode != 0:
            print("(controller-battery-check.py salio con error -- no bloquea, sigo igual)")
    except subprocess.TimeoutExpired:
        print("(controller-battery-check.py no termino en 10s -- no bloquea, sigo igual)")
    except OSError as e:
        print(f"(no pude correr controller-battery-check.py: {e} -- no bloquea, sigo igual)")


def find_steamapps_dir():
    """A handful of real, common install locations -- Steam itself has used
    different ones across distros/versions. None found -> None, callers must
    fall back to showing the full catalog unfiltered rather than crash."""
    for candidate in (
        Path.home() / ".steam" / "debian-installation" / "steamapps",
        Path.home() / ".steam" / "steam" / "steamapps",
        Path.home() / ".local" / "share" / "Steam" / "steamapps",
    ):
        if candidate.is_dir():
            return candidate
    return None


def installed_games():
    """"mapeamos lo que hay" -- don't just trust the hardcoded catalog, check
    which of those AppIDs are actually installed right now (an
    appmanifest_<id>.acf really exists), so an uninstalled/removed title never
    shows up as pickable. Falls back to the full catalog if steamapps can't be
    found at all -- better to offer something than nothing."""
    steamapps = find_steamapps_dir()
    if steamapps is None:
        return list(GAMES)
    return [
        (name, appid) for name, appid in GAMES
        if (steamapps / f"appmanifest_{appid}.acf").exists()
    ]


def read_choice_with_timeout(prompt, timeout, default_choice, default_label):
    """Same philosophy as vr-boot-selector.sh's own a/m timeout: give a real
    choice, but don't require one -- proceed with a known-good default if
    nobody answers in time. This is what "arma todo para lanzar apps en vr"
    (auto keeps going, doesn't just wait forever) actually means once hardware
    is already confirmed healthy."""
    print(prompt, end="", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if ready:
        return sys.stdin.readline().strip()
    print(f"\n  (sin respuesta en {timeout}s -- sigo con {default_label})")
    return default_choice


def main():
    games = installed_games()

    print("==================================================")
    print("  VR launcher")
    print("==================================================")
    print("  [1] Player 360/VR180 (contenido de prueba)")
    default_n = None
    for i, (name, _appid) in enumerate(games):
        n = 2 + i
        tag = "  -- default" if name == DEFAULT_GAME else ""
        print(f"  [{n}] {name}{tag}")
        if name == DEFAULT_GAME:
            default_n = n
    stub_n = 2 + len(games)
    print(f"  [{stub_n}] Juego que no es de Steam (todavia no armado)")
    print()

    if default_n is None:
        # DEFAULT_GAME isn't installed right now -- fall back to the player,
        # never point the unattended default at a game that can't launch.
        default_n, default_label = 1, "el player 360"
    else:
        default_label = DEFAULT_GAME
    choice = read_choice_with_timeout(
        f"Elegí [1-{stub_n}], 15s -> {default_label}: ", 15, str(default_n), default_label,
    )

    if choice == str(stub_n):
        print(f"Opcion {stub_n} todavia no tiene nada real conectado -- no hay ningun juego")
        print("no-Steam identificado ni probado todavia. No finjo que anda.")
        return

    try:
        choice_n = int(choice)
    except ValueError:
        choice_n = -1

    if choice_n == 1:
        selected = ("__player__", None)
    elif 2 <= choice_n <= stub_n - 1:
        selected = games[choice_n - 2]
    else:
        print("Opcion invalida.")
        return

    if not bring_up_monado():
        print("No lanzo nada -- Monado no quedo listo.")
        sys.exit(1)

    check_controller_battery()

    name, appid = selected
    if name == "__player__":
        print("=== lanzando el player 360/VR180 ===")
        subprocess.Popen([str(VR / "play360.sh"), str(VR / "media" / "test-equirect.jpg"), "-s"], env=GAME_ENV)
    else:
        print(f"=== lanzando {name} (Steam appid {appid}) ===")
        subprocess.Popen(["steam", "-applaunch", appid], env=GAME_ENV)

    print("  lanzado (queda corriendo en background, este script no espera a que cierre).")


if __name__ == "__main__":
    main()
