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
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VR = HERE.parent
if (Path.home() / "vr" / "monado").is_dir():
    VR = Path.home() / "vr"

STATS_LOG = VR / "power-on-stats.jsonl"
READY_FILE = Path.home() / ".vr-ready"


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
C_OK = "\033[1;32m" if TTY else ""
C_BAD = "\033[1;31m" if TTY else ""
C_WARN = "\033[1;33m" if TTY else ""
C_STEP = "\033[1;36m" if TTY else ""
C_DIM = "\033[2m" if TTY else ""
C_BOLD = "\033[1m" if TTY else ""
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


class Failure:
    def __init__(self):
        self.reason = None
        self.kind = None  # "physical" or "buy"
        self.part = None

    def set(self, reason, kind, part=None):
        if self.reason is None:
            self.reason, self.kind, self.part = reason, kind, part


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
            print("  Esto no cuesta plata -- es reconectar algo. Volvé a correr este script después.")
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

    # ---- 1/5: USB census ----------------------------------------------
    stats["step_reached"] = 1
    step(1, "¿Está todo conectado?")
    lsusb_text = lsusb_output()
    count = headset_count(lsusb_text)
    hub_dev = find_device_by_id("04b4", "6506") or find_device_by_id("04b4", "6504")
    superspeed_hub_present = "04b4:6504" in lsusb_text
    t126_signature = count == 4 and not superspeed_hub_present and "045e:0659" in lsusb_text
    if count >= 5:
        ok("5/5 piezas del casco responden (hub, cámaras, controlador, audio).")
    elif t126_signature:
        # T126 signature: everything except the SuperSpeed-only hub identifier --
        # structurally the max reachable on a USB2-only port, not a generic failure.
        warn("4/5 -- falta justo el hub SuperSpeed (04b4:6504): esto pasa cuando estás en")
        warn("  un puerto que no tiene carriles USB3 en absoluto (visto en docs/pruebas.jsonl T126).")
        dim("El paso 3 va a confirmar si las cámaras están limitadas de ancho de banda por esto.")
    else:
        bad(f"Solo {count}/5 piezas responden.")
        for line in lsusb_text.splitlines():
            if any(dev in line for dev in DEV_IDS):
                print(f"    {line}")
        if os.geteuid() == 0:
            dim("Corriendo como root -- intento arreglarlo solo antes de pedirte algo (reset de bus, sin tocar nada físico)...")
            lsusb_text = try_self_repair()
            count = headset_count(lsusb_text)
            if count >= 4:
                ok(f"Se arregló solo -- {count}/5 ahora, sin que tuvieras que tocar nada.")
            else:
                bad("El reset de bus tampoco alcanzó.")
        else:
            dim("Corré este script con sudo y voy a intentar un reset de bus por software solo, antes de pedirte algo.")
        if count < 4:
            jlog = run(["journalctl", "-k", "--since", "2 min ago"])
            if re.search(r"error -71|Cannot enable", jlog.stdout):
                warn("El kernel está reintentando solo y fallando (error -71) -- contacto marginal, no un cable roto del todo.")
                fail.set("El cable está reconectando solo sin llegar a agarrar bien.", "physical")
            else:
                fail.set("Nada responde y no hay reintentos -- el conector puede no estar bien asentado.", "physical")
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
    cam_dev = find_device_by_id("045e", "0659")
    if cam_dev and (cam_dev / "speed").exists():
        speed = int((cam_dev / "speed").read_text().strip() or "0")
        if speed >= 5000:
            ok(f"Cámaras a SuperSpeed real ({speed}M) -- el 6DoF/SLAM va a tener el ancho de banda que necesita.")
        else:
            bad(f"Cámaras enumeran pero solo a {speed}M (necesitan 5000M) -- puerto sin carriles SuperSpeed.")
            fail.set("Estás en un puerto USB2-only -- las cámaras 'están' pero no van a poder seguirte la cabeza bien.", "physical")
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
        dim("El logo HP puede estar prendido igual -- eso es una señal separada, no alcanza sola.")
        fail.set("El panel no responde -- probá reconectar el cable en el extremo del visor.", "physical")
    if fail.reason:
        return give_up()

    # ---- 5/5: controllers ------------------------------------------------
    stats["step_reached"] = 5
    step(5, "¿Los controles están prendidos?")
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
            warn("Prendé el/los que falten, o corré de nuevo con --skip=controllers si sabés que se perdió uno.")
            fail.set("Falta prender uno o los dos controles.", "physical")
    if fail.reason:
        return give_up()

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
    log_stats("LISTO", 5, {"mode": MODE, "tracking": TRACKING, "pre_login": PRE_LOGIN})
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
        READY_FILE.write_text(f"{MODE} {TRACKING}\n")
        print(f"{C_OK}{C_BOLD}LISTO.{C_RESET} Hardware verificado, sin login todavía.")
        print("  Andá al login y elegí 'GNOME' bajo la lista de Wayland (no X11, no KWin).")
        print("  Una vez adentro, el launcher se abre solo y trata de levantar el juego.")
        print("  Subiendo a graphical.target en 5s...")
        time.sleep(5)
        run(["systemctl", "isolate", "graphical.target"], timeout=15)
    else:
        print(f"{C_OK}{C_BOLD}LISTO.{C_RESET} Abriendo el launcher (modo {MODE}, tracking {TRACKING})...")
        launcher = HERE / "vr-launcher.py"
        os.execv(sys.executable, [sys.executable, str(launcher), MODE, TRACKING])


if __name__ == "__main__":
    main()
