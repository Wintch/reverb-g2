#!/usr/bin/env python3
"""power-on.py -- friendly, narrated headset bring-up. The "AgentVR" front door:
walks through everything learned across the T110-T126 diagnostic marathon
(docs/pruebas.jsonl) in plain language, on the DESKTOP monitor (not the
headset's own display -- this runs before anything is on your face). Ends
in one of three states:

  LISTO            -> stack came up clean, ready for jack-in-wayland.sh
  TE NECESITO      -> a specific, physical, free fix (reconnect X)
  HAY QUE COMPRAR  -> a specific part + part number (docs/26)

  ./scripts/power-on.py [mode] [3dof|6dof]   (same args as jack-in-wayland.sh)

Linux-only for now (lsusb, udevadm, sysfs, journalctl) -- written in Python
specifically so the step structure and messages can become the shared core
of a future Windows-equivalent checklist, per the project's diagnostic-
toolkit direction (see agent memory / docs/26). Don't over-abstract that
now; this file is still Linux-specific end to end.

User-facing strings are deliberately Spanish for now; the English preset via
vr_i18n.py (the project's i18n path, per the English-in-git rule) is still
pending -- decided 2026-08-13, do it as its own pass, not piecemeal.
"""
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VR = HERE.parent
if (Path.home() / "vr" / "monado").is_dir():
    VR = Path.home() / "vr"

STATS_LOG = VR / "power-on-stats.jsonl"
READY_FILE = Path("/run/vr-ready")
# Not Path.home()/".vr-ready" -- this runs as root via systemd (no login shell,
# $HOME may be unset entirely, and even when it resolves it's /root, not
# /home/iam), and the reader side (vr-launcher-console.sh) runs as root too.
# /run is root-owned, unambiguous regardless of execution context, and being
# tmpfs it naturally clears on reboot instead of persisting stale state.


def log_stats(verdict, step_reached, details):
    """Append one line per run -- so results across sessions can be compared later
    instead of relying on memory (the whole point of docs/pruebas.jsonl too)."""
    entry = {
        "iso_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "verdict": verdict,
        "step_reached": step_reached,
        **details,
    }
    try:
        with open(STATS_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass

SKIP = set()
PRE_LOGIN = "--pre-login" in sys.argv
for a in sys.argv[1:]:
    if a.startswith("--skip="):
        SKIP.add(a.split("=", 1)[1])
POSITIONAL = [a for a in sys.argv[1:] if not a.startswith("--skip=") and a != "--pre-login"]
MODE = POSITIONAL[0] if len(POSITIONAL) > 0 else "1"
TRACKING = POSITIONAL[1] if len(POSITIONAL) > 1 else "3dof"

TTY = sys.stdout.isatty()
# Bright green throughout for anything that isn't a fail/warn signal -- this
# mostly runs on a bare VT before login, styled to read like a kiosk boot
# screen. C_BAD (red) and C_WARN (yellow) are untouched on purpose: those
# carry real meaning (something needs attention) and must stay visually
# distinct from "everything's fine" green, cosmetics shouldn't blur that.
C_OK = "\033[1;92m" if TTY else ""
C_BAD = "\033[1;31m" if TTY else ""
C_WARN = "\033[1;33m" if TTY else ""
C_STEP = "\033[1;92m" if TTY else ""
C_DIM = "\033[2m" if TTY else ""
C_BOLD = "\033[1;92m" if TTY else ""
C_RESET = "\033[0m" if TTY else ""

DEV_IDS = ["03f0:0580", "045e:0659", "04b4:6504", "04b4:6506", "0bda:4c15"]


def ok(msg):
    print(f"  {C_OK}✓{C_RESET} {msg}")


def bad(msg):
    print(f"  {C_BAD}✗{C_RESET} {msg}")


def warn(msg):
    print(f"  {C_WARN}!{C_RESET} {msg}")


def step(n, title):
    print(f"\n{C_STEP}▸ Paso {n}/5 -- {title}{C_RESET}")


def dim(msg):
    print(f"    {C_DIM}{msg}{C_RESET}")


def run(cmd, timeout=10, **kw):
    # A wedged USB controller (plausible given tonight's own findings) could hang
    # any of lsusb/udevadm/journalctl indefinitely -- on a bare pre-login console
    # that's the only process running, so a hang here is a dead machine, not just
    # a slow check. Bounded by default; callers needing longer (drmprops polling,
    # the self-repair sleep loop) pass their own timeout explicitly.
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, returncode=124, stdout="", stderr="timeout")


def lsusb_output():
    r = run(["lsusb"])
    return r.stdout if r.returncode == 0 else ""


def headset_count(lsusb_text):
    return sum(1 for dev in DEV_IDS if dev in lsusb_text)


def find_device_by_id(vid, pid):
    """Return the sysfs path of the first USB device matching vid:pid, or None."""
    usb_devices = Path("/sys/bus/usb/devices")
    if not usb_devices.is_dir():
        return None
    for d in usb_devices.iterdir():
        v, p = d / "idVendor", d / "idProduct"
        if v.exists() and p.exists():
            try:
                if v.read_text().strip() == vid and p.read_text().strip() == pid:
                    return d
            except OSError:
                continue
    return None


def id_path_for(dev_path):
    """Resolve a sysfs device path to its ID_PATH (e.g. pci-...-usb-0:1)."""
    if not dev_path:
        return ""
    info = run(["udevadm", "info", str(dev_path)])
    m = re.search(r"ID_PATH=(\S+)", info.stdout)
    return m.group(1) if m else ""


def try_self_repair():
    """Software-only fix, zero physical contact: unbind/rebind the USB2 root
    hub (docs/pruebas.jsonl T117/T120-T122 validated this recovers the branch
    sometimes). Root-only -- caller must check os.geteuid() first. Returns
    the new lsusb text after the attempt."""
    for bus in ("usb3", "usb1"):
        if not Path(f"/sys/bus/usb/devices/{bus}").exists():
            continue
        driver_unbind = Path("/sys/bus/usb/drivers/usb/unbind")
        driver_bind = Path("/sys/bus/usb/drivers/usb/bind")
        try:
            driver_unbind.write_text(bus)
            time.sleep(3)
            driver_bind.write_text(bus)
        except OSError:
            continue
        for _ in range(10):
            time.sleep(1)
            if headset_count(lsusb_output()) >= 4:
                break
    return lsusb_output()


def branch_flags(lsusb_text):
    """The G2's five devices split into two electrically independent pin groups
    (docs/22 anatomy): the USB2 branch (hub 6506 + companion 0580 + audio 4c15,
    on the D+/D- pair) and the SuperSpeed branch (hub 6504 + sensors 0659 at
    5 Gbps, on the SS pairs). 2026-08-13 (T171) showed a marginal C-plug/adapter
    seat engages ONE group per seating -- so report them separately: which one
    is missing decides which physical instruction actually helps."""
    usb2 = all(d in lsusb_text for d in ("04b4:6506", "03f0:0580", "0bda:4c15"))
    ss = "04b4:6504" in lsusb_text
    return usb2, ss


def reseat_instructions(usb2_ok, ss_ok):
    """Exact physical steps, most-likely-fix first. Source: the 2026-08-13
    seat-lottery diagnosis (docs/22 / T171), CONFIRMED with a controlled A/B
    protocol 2026-08-15/16 (docs/pruebas.jsonl T183): 6 cold reinsertions, 3
    per side, marked with tape so the side was known for certain, not
    remembered -- 100% reproducible both ways. SS pins live at the tip of the
    connector tongue, the USB2 pair mid-connector -- a slightly different
    seating depth/angle engages a different subset, which is why 'rotate the
    C plug 180 degrees inside the adapter' (docs/06) is a real fix and not
    superstition. T183's new finding: on THIS unit, one specific orientation
    ('matched' in that session's tape marking) reproducibly kills BOTH
    branches at once (0/5, 3/3 trials) -- a full dead census is not just a
    generic bad-seat symptom, it can be this same orientation fault, so the
    flip belongs in that branch's instructions too, not only the
    single-branch-missing cases below. The other orientation recovered the
    SuperSpeed branch every time (2/5, 3/3 trials) but never the USB2 one on
    its own -- flipping is necessary but not sufficient for a full 5/5.
    Order: port seat, then orientation, then other port, then visor-end --
    the docs/06 ladder, revalidated live."""
    steps = []
    if not usb2_ok and not ss_ok:
        steps += [
            "Desenchufá el USB del casco en la PC y volvé a meterlo DERECHO y A FONDO,",
            "  sosteniendo el peso del cable con la otra mano (cuelga y hace palanca).",
            "Usá un puerto USB3 TRASERO de la placa (los del CPU) -- los del frente no sirven.",
            "¿Sigue en 0/5? Un lado especifico de este plug USB-C mata las DOS ramas a la vez",
            "  (confirmado 3/3 -- docs/pruebas.jsonl T183): sacá el plug del adaptador,",
            "  GIRALO 180° y metelo de nuevo, firme y a fondo, ANTES de probar otro puerto.",
        ]
    elif not ss_ok:
        steps += [
            "Falta la rama SuperSpeed (las cámaras). SIN cambiar de puerto: sacá el plug",
            "  USB-C del adaptador, GIRALO 180° y metelo de nuevo, firme y a fondo.",
        ]
    else:
        steps += [
            "Falta la rama USB2 (companion/audio). SIN cambiar de puerto: sacá el plug",
            "  USB-C del adaptador, GIRALO 180° y metelo de nuevo, firme y a fondo.",
        ]
    steps += [
        "¿Sigue igual? Probá OTRO puerto A trasero (cada puerto asienta distinto).",
        "¿Nada? Reseat de la ficha del visor (detrás del gasket magnético) y después",
        "  TODO junto: USB + DP + brick 12V afuera ~1 min, reconectar (docs/22).",
    ]
    return steps


PRINTK = Path("/proc/sys/kernel/printk")
_printk_saved = None


def console_quiet(on):
    """Mute/unmute kernel messages on the VT this script owns.

    Found the hard way 2026-08-13 (T172): the very fault this script asks the
    user to fix -- a marginal seat -- makes the kernel print
    `usb usb3-port1: Cannot enable. Maybe the USB cable is bad?` about once a
    second, straight to /dev/tty1 (console_loglevel 4 lets every KERN_ERR
    through). While the user was reconnecting the cable, that wall of text
    scrolled the reseat instructions and the prompt off the screen and the
    console looked hung. Nothing is lost by muting it: printk still reaches the
    journal, only the VT stops being written to. Always restored (finally +
    SIGTERM handler) -- leaving the console muted for the rest of the boot
    would be a worse bug than the one this fixes."""
    global _printk_saved
    if os.geteuid() != 0 or not PRINTK.exists():
        return
    try:
        if on:
            if _printk_saved is None:
                _printk_saved = PRINTK.read_text().split()
            fields = list(_printk_saved)
            fields[0] = "1"  # console_loglevel: KERN_ALERT and worse only
            PRINTK.write_text(" ".join(fields) + "\n")
        elif _printk_saved is not None:
            PRINTK.write_text(" ".join(_printk_saved) + "\n")
            _printk_saved = None
    except OSError:
        pass


# Two clocks, on purpose (T172). Before anyone has answered, this may well be an
# unattended boot with the headset simply unplugged -- it must not hold the
# console hostage. Once the user presses Enter even once, a human is provably
# there with their hands in the cable, and cutting them off mid-reseat is
# exactly the failure this pair of constants exists to prevent: every Enter
# rearms the long clock.
WAIT_NO_HUMAN_S = 90
WAIT_HUMAN_S = 300


def wait_for_reseat(recheck, status_line):
    """Interactive retry loop for a physical fix. Prints nothing by itself --
    caller prints the instructions first. Polls recheck() every 3 s; the user
    can press [Enter] to recheck immediately (which also rearms the wait) or
    [s]+[Enter] to give up on VR and continue to the plain 2D desktop.
    Returns 'fixed' | 'skip' | 'giveup'.
    Unattended (no TTY on stdin): polls for ~60 s then gives up, so the
    pre-login boot path can never dead-end waiting for a human who isn't there."""
    if not sys.stdin.isatty():
        for _ in range(20):
            time.sleep(3)
            if recheck():
                return "fixed"
        return "giveup"
    print()
    warn("Esperando que reconectes. Dos teclas, cada una seguida de Enter (no al mismo tiempo):")
    dim(f"  Enter solo         -> re-chequeo ya mismo")
    dim(f"  s, después Enter   -> DEJO DE ESPERAR ya y sigo SIN VR, escritorio 2D normal")
    dim(f"Si no tocás nada: espero {WAIT_NO_HUMAN_S}s y paso igual al escritorio 2D, pero como falla")
    dim("(para que quede registrado y lo reintentes cuando quieras -- ver docs/22).")
    dim("Cada Enter reinicia el reloj de espera. Mientras tanto silencio los mensajes del kernel")
    dim("en esta consola (siguen yendo al journal) para que no te tapen estas instrucciones.")
    console_quiet(True)
    try:
        deadline = time.monotonic() + WAIT_NO_HUMAN_S
        last_status, last_print, answered = None, 0.0, False
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                print()
                if answered:
                    warn(f"Se acabó el tiempo de espera ({WAIT_HUMAN_S}s desde el último Enter).")
                else:
                    warn("Se acabó el tiempo de espera (nadie apretó nada).")
                return "giveup"
            r, _, _ = select.select([sys.stdin], [], [], min(3.0, left))
            pressed = False
            if r:
                line = sys.stdin.readline()
                if line == "":
                    return "giveup"  # stdin closed under us: don't spin on EOF
                if line.strip().lower() == "s":
                    return "skip"
                pressed = answered = True
                deadline = time.monotonic() + WAIT_HUMAN_S
            if recheck():
                return "fixed"
            status = status_line()
            now = time.monotonic()
            # Answer EVERY keypress, and repaint every 10 s even when nothing
            # changed. Silence after an Enter is indistinguishable from a hang,
            # and that is precisely what the user reported (T172).
            if pressed or status != last_status or now - last_print >= 10:
                dim(f"{status}   [{int(max(0, deadline - now))}s]")
                last_status, last_print = status, now
    finally:
        console_quiet(False)


class Failure:
    def __init__(self):
        self.reason = None
        self.kind = None  # "physical" or "buy"
        self.part = None

    def set(self, reason, kind, part=None):
        if self.reason is None:
            self.reason, self.kind, self.part = reason, kind, part

    def clear(self):
        self.reason, self.kind, self.part = None, None, None


def main():
    fail = Failure()
    stats = {"step_reached": 0}

    print(f"{C_BOLD}=== Encendiendo el HP Reverb G2 ==={C_RESET}")
    dim("Esto corre en tu monitor normal, no en el casco -- todavia no hay nada que ponerte.")

    def give_up():
        """One step failed -- print the verdict now, log it, and stop -- don't start the next step.
        In --pre-login mode this MUST still hand off to graphical.target: otherwise a
        single disconnected cable (the exact class of thing this whole project debugs)
        dead-ends the console forever, with nobody remote to recover it."""
        log_stats("TE NECESITO" if fail.kind == "physical" else "HAY QUE COMPRAR",
                   stats["step_reached"], {"reason": fail.reason, "part": fail.part})
        print(f"\n{C_BOLD}=== Veredicto ==={C_RESET}")
        if fail.kind == "physical":
            print(f"{C_WARN}{C_BOLD}TE NECESITO.{C_RESET} {fail.reason}")
            print("  Esto no cuesta plata -- es reconectar algo.")
            # Say HOW to retry, not just "retry": after this returns, the machine
            # goes to the graphical login and this console disappears. Without the
            # command there is no visible way back (T172, user: "ya no pude apretar
            # enter para volver a reintentar ni nada").
            print(f"  Para reintentar sin reiniciar: abrí una terminal y corré")
            print(f"    {C_BOLD}{HERE / 'power-on.py'}{C_RESET}")
            print("  (o Ctrl+Alt+F2 para una consola de texto, si el escritorio no llegó a arrancar).")
        else:
            print(f"{C_BAD}{C_BOLD}HAY QUE COMPRAR.{C_RESET} {fail.reason}")
            print(f"  Pieza: {fail.part} -- ver docs/26-diagnostic-toolkit-and-buying-guide.md para el link.")
        if PRE_LOGIN:
            # Explicitly clear this on every failure path -- the autostart entry
            # on the other side only opens vr-launcher.py automatically if this
            # file says the LAST run was a real LISTO. A stale file from a
            # previous successful run must not leak into a session that starts
            # right after a failed one.
            READY_FILE.unlink(missing_ok=True)
            print("  Volviendo al login gráfico en 5s (Ctrl+C para quedarte en esta consola)...")
            time.sleep(5)
            run(["systemctl", "isolate", "graphical.target"], timeout=15)

    def continue_2d():
        """User pressed [s] in a reseat loop: abandon VR bring-up on purpose and
        continue to an ordinary 2D desktop. Distinct from give_up(): this is a
        choice, not a failure, so the verdict says so and nothing red is printed."""
        log_stats("SIN_VR_2D", stats["step_reached"], {"reason": fail.reason or "user skip"})
        print(f"\n{C_BOLD}=== Veredicto ==={C_RESET}")
        print(f"{C_WARN}{C_BOLD}SIN VR POR AHORA.{C_RESET} Seguís al escritorio normal (2D).")
        print("  Cuando quieras reintentar: reconectá el casco y corré")
        print(f"    {C_BOLD}{HERE / 'power-on.py'}{C_RESET}")
        if PRE_LOGIN:
            READY_FILE.unlink(missing_ok=True)
            time.sleep(2)
            run(["systemctl", "isolate", "graphical.target"], timeout=15)
        sys.exit(0)

    # ---- 1/5: USB census ----------------------------------------------
    stats["step_reached"] = 1
    step(1, "¿Está todo conectado?")
    lsusb_text = lsusb_output()
    count = headset_count(lsusb_text)
    if count >= 5:
        ok("5/5 piezas del casco responden (hub, cámaras, controlador, audio).")
    else:
        usb2_ok, ss_ok = branch_flags(lsusb_text)
        bad(f"Solo {count}/5 piezas responden -- rama USB2 {'OK' if usb2_ok else 'AUSENTE'}, "
            f"rama SuperSpeed {'OK' if ss_ok else 'AUSENTE'}.")
        for line in lsusb_text.splitlines():
            if any(dev in line for dev in DEV_IDS):
                print(f"    {line}")
        if count > 0 and os.geteuid() == 0:
            dim("Intento primero un reset de bus por software (sin tocar nada físico)...")
            lsusb_text = try_self_repair()
            count = headset_count(lsusb_text)
        if count >= 5:
            ok("Se arregló solo -- 5/5 ahora, sin que tuvieras que tocar nada.")
        else:
            # The software reset was already shown (T171, 2026-08-13) NOT to fix a
            # marginal seat: a full xhci rebind reproduced the identical half-dead
            # state. From here the fix is physical, so say exactly what to do and
            # wait for it instead of dead-ending -- the docs/06 ladder, revalidated
            # live that day: seat, then orientation, then other port, then visor.
            jlog = run(["journalctl", "-k", "--since", "2 min ago"])
            if re.search(r"error -71|Cannot enable", jlog.stdout):
                dim("El kernel reintenta y falla (error -71): contacto marginal, no un cable roto del todo.")
            usb2_ok, ss_ok = branch_flags(lsusb_text)
            print()
            warn("Hay que reconectar. Paso a paso, en orden de probabilidad (docs/22, T171):")
            for s in reseat_instructions(usb2_ok, ss_ok):
                print(f"    {C_WARN}»{C_RESET} {s}")

            def _recheck_census():
                nonlocal lsusb_text, count
                lsusb_text = lsusb_output()
                count = headset_count(lsusb_text)
                return count >= 5

            def _status_census():
                u2, ss = branch_flags(lsusb_text)
                return (f"ahora {count}/5 -- USB2 {'✓' if u2 else '✗'} | "
                        f"SuperSpeed {'✓' if ss else '✗'}  (5/5 = listo)")

            outcome = wait_for_reseat(_recheck_census, _status_census)
            if outcome == "fixed":
                ok("¡5/5! Reconexión correcta, seguimos.")
            elif outcome == "skip":
                return continue_2d()
            else:
                fail.set("Faltan piezas del casco y la reconexión no llegó a tiempo.", "physical")
    hub_dev = find_device_by_id("04b4", "6506") or find_device_by_id("04b4", "6504")
    if fail.reason:
        return give_up()

    # ---- 2/5: which physical port --------------------------------------
    stats["step_reached"] = 2
    step(2, "¿Estás en un puerto que sabemos que funciona?")
    idpath = id_path_for(hub_dev)
    if "usb-0:1" in idpath:
        ok("Puerto conocido bueno (root port 1 -- el usado toda la sesión de anoche).")
    elif "usb-0:4" in idpath:
        bad("Puerto conocido MALO (root port 4): el USB2 de esta rama nunca enumera acá, aunque el USB3 sí.")
        fail.set("Estás en un puerto trasero que no sirve para este casco (ver docs/00, root port 4).", "physical")
    elif "02:00.0" in idpath:
        warn("Puerto USB2 del chipset (no del CPU) -- todo enumera pero sin carriles SuperSpeed (ver paso 3).")
        fail.set("Estás en el USB2 del chipset -- las cámaras no van a andar bien acá.", "physical")
    elif not idpath:
        warn("No pude identificar el puerto (¿nada conectado en el paso 1?).")
    else:
        warn(f"Puerto sin clasificar todavía ({idpath}) -- ninguno de los ya mapeados en docs/00.")
    if fail.reason:
        return give_up()

    # ---- 3/5: negotiated speed of the cameras (T126: enumerating != healthy)
    stats["step_reached"] = 3
    step(3, "¿Las cámaras tienen el ancho de banda que necesitan?")
    def camera_speed():
        # Re-find the device on every call: a reseat changes the sysfs path.
        d = find_device_by_id("045e", "0659")
        if d and (d / "speed").exists():
            try:
                return int((d / "speed").read_text().strip() or "0")
            except (OSError, ValueError):
                return 0
        return 0

    speed = camera_speed()
    if speed >= 5000:
        ok(f"Cámaras a SuperSpeed real ({speed}M) -- el 6DoF/SLAM va a tener el ancho de banda que necesita.")
    elif speed > 0:
        # Cameras attached through the USB2 face of the hub (seen live in T171):
        # they enumerate and even stream a little, but SLAM/constellation need the
        # 5 Gbps link. Same physical fix as a missing SS branch: the 180° flip.
        bad(f"Cámaras enumeran pero solo a {speed}M (necesitan 5000M) -- la rama SuperSpeed no entró.")
        warn("Fix probado (docs/06, T171): SIN cambiar de puerto, girá el plug USB-C 180°")
        warn("  dentro del adaptador y metelo firme. Si no: otro puerto A trasero.")

        def _recheck_speed():
            # Require the full census too -- a reseat that trades USB2 for SS
            # (the T171 lottery) must not count as fixed.
            return headset_count(lsusb_output()) >= 5 and camera_speed() >= 5000

        def _status_speed():
            u2, ss = branch_flags(lsusb_output())
            return (f"cámaras a {camera_speed()}M -- USB2 {'✓' if u2 else '✗'} | "
                    f"SuperSpeed {'✓' if ss else '✗'}  (5/5 y 5000M = listo)")

        outcome = wait_for_reseat(_recheck_speed, _status_speed)
        if outcome == "fixed":
            ok(f"Cámaras a SuperSpeed real ({camera_speed()}M) después de reconectar.")
        elif outcome == "skip":
            return continue_2d()
        else:
            fail.set("Las cámaras quedaron sin ancho de banda SuperSpeed.", "physical")
    else:
        dim("Cámaras no detectadas todavía (se resuelve solo si el paso 1 se arregla).")
    if fail.reason:
        return give_up()

    # ---- 4/5: panel / DP fingerprint -----------------------------------
    stats["step_reached"] = 4
    step(4, "¿El panel está despierto y es realmente el del G2?")
    panel_py = HERE / "panel.py"
    if not panel_py.exists():
        panel_py = VR / "panel.py"
    run([sys.executable, str(panel_py), "activate"])
    # Cached build: only recompile if the binary is missing or older than the source --
    # this used to rebuild on every single run, wasted time when re-checking repeatedly.
    drmprops_bin = Path("/tmp/drmprops-cache")
    drmprops_src = HERE / "drmprops.c"
    dp_ok = False
    need_build = (
        not drmprops_bin.exists()
        or drmprops_bin.stat().st_mtime < drmprops_src.stat().st_mtime
    )
    build_ok = True
    if need_build:
        build = run(["gcc", "-o", str(drmprops_bin), str(drmprops_src), "-ldrm", "-I/usr/include/libdrm"])
        build_ok = build.returncode == 0
    if build_ok:
        for _ in range(20):
            check = run([str(drmprops_bin)])
            if "fingerprint matches" in check.stdout:
                dp_ok = True
                break
            time.sleep(0.5)
    if dp_ok:
        ok("Panel real del G2 confirmado (huella EDID, no solo 'conectado').")
    else:
        bad("El panel no despertó, o lo que hay conectado no es el G2.")
        dim("El logo HP puede estar prendido igual -- es power+HID, independiente del DP; no alcanza solo.")
        warn("Hay que revisar la parte de video. En orden (docs/22):")
        print(f"    {C_WARN}»{C_RESET} El DP del casco A FONDO en la GPU (puerto trasero de la placa de video).")
        print(f"    {C_WARN}»{C_RESET} El brick de 12V enchufado y el barrel firme en la cajita del cable")
        print(f"    {C_WARN}»{C_RESET}   (el LED de la cajita NO dice nada del 12V: solo marca 5V del USB).")
        print(f"    {C_WARN}»{C_RESET} ¿Nada? Reseat de la ficha del visor (detrás del gasket magnético).")

        def _recheck_panel():
            # Re-send the activation each pass -- the panel auto-powers-off ~3 s
            # after an activation with no video, and a reseat needs a fresh one.
            if build_ok:
                run([sys.executable, str(panel_py), "activate"])
                for _ in range(5):
                    check = run([str(drmprops_bin)])
                    if "fingerprint matches" in check.stdout:
                        return True
                    time.sleep(0.5)
            return False

        outcome = wait_for_reseat(_recheck_panel, lambda: "panel todavía sin responder...")
        if outcome == "fixed":
            dp_ok = True
            ok("Panel del G2 confirmado después de reconectar.")
        elif outcome == "skip":
            return continue_2d()
        else:
            fail.set("El panel no responde -- probá reconectar el cable en el extremo del visor.", "physical")
    if fail.reason:
        return give_up()

    # ---- 5/5: controllers ------------------------------------------------
    stats["step_reached"] = 5
    step(5, "¿Los controles están prendidos?")
    gamepad_present = "045e:028e" in lsusb_output()
    if gamepad_present:
        ok("Gamepad tipo Xbox 360 detectado -- sirve de respaldo si falta un control VR")
        dim("  (fallback parcial, no todos los juegos lo aceptan -- ver docs/pruebas.jsonl T127).")
    if "controllers" in SKIP:
        warn("SALTEADO a pedido (--skip=controllers) -- consecuencia: sin control físico en la sesión.")
    else:
        ctrl_py = HERE / "controller-pair-check.py"
        if not ctrl_py.exists():
            ctrl_py = VR / "controller-pair-check.py"
        ctrl = run([sys.executable, str(ctrl_py), "3"])
        ctrl_out = ctrl.stdout + ctrl.stderr
        left_ok = bool(re.search(r"left.*online", ctrl_out))
        right_ok = bool(re.search(r"right.*online", ctrl_out))
        (ok if left_ok else warn)(f"Izquierdo: {'prendido y responde' if left_ok else 'NO responde'}")
        (ok if right_ok else warn)(f"Derecho:   {'prendido y responde' if right_ok else 'NO responde'}")
        if not (left_ok and right_ok):
            # Never blocks -- only the headset itself (steps 1-4) can stop the user.
            # Missing controllers are treated as temporary/non-fatal: they (or a
            # gamepad) can be connected later, same as on Windows. One real caveat,
            # said explicitly so it's not a silent surprise mid-session: THIS stack's
            # VR-controller hot-add doesn't work yet (docs/pruebas.jsonl T043) --
            # unlike Windows, connecting one after the session has already started
            # won't make Monado see it. Plug in before jack-in-wayland.sh actually
            # launches, or restart the session once it's on.
            extra = " -- hay gamepad de respaldo" if gamepad_present else " -- sin gamepad de respaldo tampoco"
            warn(f"Sigue sin controles por ahora{extra}. No bloquea, arrancamos igual.")
            dim("Se pueden prender/conectar después -- pero el hot-plug de controles VR todavía no anda en")
            dim("este stack (a diferencia de Windows): si los conectás con la sesión ya arrancada, Monado no")
            dim("los va a ver hasta la próxima vez que arranque.")
        # No battery check here on purpose. This step's own 0x16/0x17 status query works
        # standalone (any hidraw can be opened more than once), but the battery LEVEL only
        # travels inside each controller's 44-byte streamed input report, which only starts
        # flowing after Monado's own controller connection handshake (firmware config read,
        # then "enable status reports"/"enable IMU" commands) -- sending that from here, with
        # Monado not running yet, would mean re-implementing a chunk of that handshake with no
        # live session to validate it against, for a byte whose scale isn't even confirmed yet
        # (see docs/03-controllers.md). It's checked instead once Monado is actually up, via
        # libmonado -- see vr-launcher.py's check_controller_battery() (still before the
        # game/player itself launches) and patches/monado/0040.
            SKIP.add("controllers")

    # ---- Bonus: everything else on the USB bus, for context ---------------
    print(f"\n{C_STEP}▸ Otros dispositivos USB de la PC (contexto, no bloquea nada){C_RESET}")
    KNOWN = {
        "045e:028e": "Xbox 360 Controller",
        "046d": "Logitech (mouse/teclado/receptor)",
    }
    for line in lsusb_text.splitlines():
        if any(dev in line for dev in DEV_IDS):
            continue  # ya mostrado en el paso 1
        m = re.search(r"ID (\w{4}:\w{4})", line)
        if not m:
            continue
        pid = m.group(1)
        label = KNOWN.get(pid) or KNOWN.get(pid.split(":")[0])
        dim(f"{pid}  {label or ''}".rstrip())

    # ---- Verdict -----------------------------------------------------------
    stats["step_reached"] = 5
    controllers_ok = "controllers" not in SKIP
    log_stats("LISTO", 5, {"mode": MODE, "tracking": TRACKING, "pre_login": PRE_LOGIN, "controllers_ok": controllers_ok, "gamepad_present": gamepad_present})
    print(f"\n{C_BOLD}=== Veredicto ==={C_RESET}")
    if PRE_LOGIN:
        # Run from a bare console (multi-user.target), before any desktop session
        # exists -- there's no Wayland session here to launch into yet. Real VR
        # launch still needs the one validated path: SDDM -> "GNOME" (Wayland),
        # logged in by a human. Not automated -- no autologin path has ever been
        # tested for this project, don't invent one live tonight.
        #
        # READY_FILE is how the post-login side (a GNOME autostart entry,
        # ~/.config/autostart/vr-launcher.desktop) knows whether to open
        # vr-launcher.py automatically or leave the normal classic desktop
        # alone -- only written here, on a real LISTO, never on a failure path
        # (give_up() explicitly removes it first, see there).
        # Third and fourth fields tell vr-launcher-console.sh whether it's safe to
        # auto-open the VR launcher menu, or whether this should behave like an
        # ordinary Linux boot instead. Headset ready but no controllers AND no
        # gamepad is "let the human decide from the desktop" -- but a gamepad
        # alone is enough to launch (Aircar and others already run on gamepad
        # input only, docs/pruebas.jsonl T127) so don't force a manual desktop
        # detour just because the VR controllers specifically are off.
        # (see vr-launcher-console.sh for the actual branch).
        READY_FILE.write_text(
            f"{MODE} {TRACKING} {'1' if controllers_ok else '0'} {'1' if gamepad_present else '0'}\n"
        )
        print(f"{C_OK}{C_BOLD}LISTO.{C_RESET} Hardware verificado, sin login todavía.")
        print("  Andá al login y elegí 'GNOME' bajo la lista de Wayland (no X11, no KWin).")
        if controllers_ok:
            print(f"  {C_BOLD}Poné el casco{C_RESET} -- una vez logueado, el launcher se abre solo y levanta el juego.")
        elif gamepad_present:
            print("  Sin controles VR, pero hay gamepad de respaldo -- el launcher se abre solo igual.")
        else:
            print("  Sin controles ni gamepad todavía -- una vez logueado vas a caer al escritorio normal, sin auto-launch.")
        print("  Subiendo a graphical.target en 5s...")
        time.sleep(5)
        run(["systemctl", "isolate", "graphical.target"], timeout=15)
    else:
        print(f"{C_OK}{C_BOLD}LISTO.{C_RESET} Abriendo el launcher (modo {MODE}, tracking {TRACKING})...")
        launcher = HERE / "vr-launcher.py"
        os.execv(sys.executable, [sys.executable, str(launcher), MODE, TRACKING])


if __name__ == "__main__":
    # The wrapper (vr-boot-selector.sh) bounds this whole run with `timeout`, which
    # means SIGTERM. Turn it into a normal unwind so wait_for_reseat's finally --
    # the one that un-mutes the kernel console -- actually runs; a plain SIGTERM
    # kill would leave the VT silent for the rest of the boot.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        main()
    finally:
        console_quiet(False)
