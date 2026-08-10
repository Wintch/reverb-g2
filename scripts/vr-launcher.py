#!/usr/bin/env python3
"""vr-launcher.py -- "our own launcher", the single entry point between the boot
selector's OK verdict and something actually running in the headset.

Deliberately very simple for now: one screen, 3 options. Brings up Monado first
(jack-in-wayland.sh), then routes to whichever option was picked. Each option is
a thin proxy today, not a real content browser -- there's exactly one concrete
target wired up per category so far (the 360/VR180 player with its test content,
and Aircar as the one Steam VR title confirmed working well per
docs/23-game-compatibility.md: "first game I'd call 99%"). Option 3 (non-Steam
games) is an honest stub, not built -- nothing non-Steam has been identified or
tested yet, don't fake a working option.

Prerequisite this script does NOT and CANNOT automate: any Steam VR title's
launch options must already be set once via Steam's own UI (Properties ->
Launch Options) -- docs/23's "Trap: Steam launch options edited on disk don't
exist" already established that editing localconfig.vdf directly while Steam
runs is unreliable/dangerous.

  ./scripts/vr-launcher.py [mode] [3dof|6dof]   (passed through to jack-in-wayland.sh)
"""
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

AIRCAR_APPID = "1073390"
IPC_SOCKET = Path("/run/user/1000/monado_comp_ipc")


def bring_up_monado():
    print("=== subiendo Monado ===")
    IPC_SOCKET.unlink(missing_ok=True)  # SIGKILL de una corrida anterior no limpia esto
    r = subprocess.run(
        [str(VR / "jack-in-wayland.sh"), MODE, TRACKING],
        capture_output=True, text=True, timeout=60,
    )
    print(r.stdout)
    if r.returncode != 0 or not IPC_SOCKET.exists():
        print("jack-in-wayland.sh no dejo el socket de Monado listo.")
        print(r.stderr)
        return False
    return True


def read_choice_with_timeout(prompt, timeout):
    """Same philosophy as vr-boot-selector.sh's own a/m timeout: give a real
    choice, but don't require one -- proceed with the known-good default
    (option 2, Aircar) if nobody answers in time. This is what "arma todo
    para lanzar apps en vr" (auto keeps going, doesn't just wait forever)
    actually means once hardware is already confirmed healthy."""
    print(prompt, end="", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if ready:
        return sys.stdin.readline().strip()
    print(f"\n  (sin respuesta en {timeout}s -- sigo con la opcion 2, Aircar)")
    return "2"


def main():
    print("==================================================")
    print("  VR launcher")
    print("==================================================")
    print("  [1] Player 360/VR180 (contenido de prueba)")
    print("  [2] Juego de Steam (por ahora solo Aircar, confirmado que anda bien) -- default")
    print("  [3] Juego que no es de Steam (todavia no armado)")
    print()
    choice = read_choice_with_timeout("Elegí [1/2/3], 15s -> Aircar: ", 15)

    if choice == "3":
        print("Opcion 3 todavia no tiene nada real conectado -- no hay ningun juego")
        print("no-Steam identificado ni probado todavia. No finjo que anda.")
        return

    if choice not in ("1", "2"):
        print("Opcion invalida.")
        return

    if not bring_up_monado():
        print("No lanzo nada -- Monado no quedo listo.")
        sys.exit(1)

    if choice == "1":
        print("=== lanzando el player 360/VR180 ===")
        subprocess.Popen([str(VR / "play360.sh"), str(VR / "media" / "test-equirect.jpg"), "-s"])
    else:
        print(f"=== lanzando Aircar (Steam appid {AIRCAR_APPID}) ===")
        subprocess.Popen(["steam", "-applaunch", AIRCAR_APPID])

    print("  lanzado (queda corriendo en background, este script no espera a que cierre).")


if __name__ == "__main__":
    main()
