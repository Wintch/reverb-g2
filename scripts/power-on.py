#!/usr/bin/env python3
"""power-on.py -- friendly, narrated headset bring-up. The "AgentVR" front door:
walks through everything learned across the T110-T126 diagnostic marathon
(docs/pruebas.jsonl) in plain language, on the DESKTOP monitor (not the
headset's own display -- this runs before anything is on your face). Ends
in one of three states:

  READY            -> stack came up clean, ready for jack-in-wayland.sh
  I NEED YOU       -> a specific, physical, free fix (reconnect X)
  PART NEEDED      -> a specific part + part number (docs/26)

(The on-screen verdict banners are English; the verdict tokens written to
power-on-stats.jsonl keep their original values "LISTO" / "TE NECESITO" /
"HAY QUE COMPRAR" so existing log history stays comparable.)

  ./scripts/power-on.py [mode] [3dof|6dof]   (same args as jack-in-wayland.sh)

This (no --pre-login) is the on-demand "diagnose, then launch" entry point for a human
at a terminal -- run it by hand any time hardware is in doubt. NOT wired into
status-dashboard.py's "Start compositor" button (tried 2026-08-23, reverted same day:
that button needs a BARE compositor for its separate "Launch <game>" buttons, but this
script always ends by launching one specific title via vr-launcher.py's picker, which
also doesn't handle a non-interactive stdin the button's subprocess gives it -- see
status-dashboard.py's ACTIONS["compositor-up"] comment for the full story).
`--pre-login` mode (below) is DEPRECATED and unused as of the same date:
it used to run unconditionally at every boot via vr-boot-selector.service, which woke
the panel (step 4/5) before anyone had decided to use VR that session -- a real wear
cost per docs/22, not just watts, and the console's own downstream payoff
(~/.config/autostart's auto-open-the-picker step) turned out to be dead code anyway
(its target script was never committed). Boot now goes straight to graphical.target;
vr-boot-selector.service is disabled but left in the repo as reference/history. The
--pre-login code path itself is left in place, not deleted, in case a future need for
an unattended pre-login console comes back.

Linux-only for now (lsusb, udevadm, sysfs, journalctl) -- written in Python
specifically so the step structure and messages can become the shared core
of a future Windows-equivalent checklist, per the project's diagnostic-
toolkit direction (see docs/26). Don't over-abstract that
now; this file is still Linux-specific end to end.

User-facing strings are English (the English-in-git rule); a Spanish/Russian preset
via vr_i18n.py (the project's i18n path) is still possible as its own pass.
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
# the operator's home), and the reader side (vr-launcher-console.sh) runs as root too.
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
    # A wedged USB controller (plausible on a marginal USB link) could hang
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


def headset_buses(lsusb_text):
    """Root hubs ("usb3", ...) of the buses that show at least one headset device now."""
    buses = []
    for line in lsusb_text.splitlines():
        m = re.match(r"Bus (\d+) Device \d+: ID (\S+)", line)
        if m and m.group(2) in DEV_IDS:
            bus = f"usb{int(m.group(1))}"
            if bus not in buses:
                buses.append(bus)
    return buses


def try_self_repair():
    """Software-only fix, zero physical contact: unbind/rebind the USB2 root
    hub (docs/pruebas.jsonl T117/T120-T122 validated this recovers the branch
    sometimes). Root-only -- caller must check os.geteuid() first. Returns
    the new lsusb text after the attempt.

    Only the buses the headset currently shows on are reset; usb3/usb1 (the lab
    box's layout) are the fallback when none of its devices is visible. Stops at
    the first bus that brings the headset back, and retries a failed rebind
    rather than leave a root hub (and everything on it) unbound."""
    buses = headset_buses(lsusb_output())
    if not buses:
        print("  no headset device visible on any bus: falling back to usb3, usb1 (lab layout)")
        buses = ["usb3", "usb1"]
    driver_unbind = Path("/sys/bus/usb/drivers/usb/unbind")
    driver_bind = Path("/sys/bus/usb/drivers/usb/bind")
    for bus in buses:
        if not Path(f"/sys/bus/usb/devices/{bus}").exists():
            continue
        try:
            driver_unbind.write_text(bus)
        except OSError:
            continue
        time.sleep(3)
        for attempt in range(3):
            try:
                driver_bind.write_text(bus)
                break
            except OSError as e:
                print(f"  rebind of {bus} failed ({e}), attempt {attempt + 1}/3")
                time.sleep(2)
        else:
            print(f"  !! {bus} is still unbound: replug the headset or reboot")
        for _ in range(10):
            time.sleep(1)
            if headset_count(lsusb_output()) >= 4:
                return lsusb_output()
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
            "Unplug the headset USB from the PC and plug it back in STRAIGHT and ALL THE WAY,",
            "  holding the cable weight with your other hand (it hangs and levers the plug).",
            "Use a REAR USB3 port on the motherboard (the CPU-fed ones) -- the front ones do not work.",
            "Still 0/5? One specific side of this USB-C plug kills BOTH branches at once",
            "  (confirmed 3/3 -- docs/pruebas.jsonl T183): pull the plug out of the adapter,",
            "  ROTATE it 180° and reinsert it firmly and fully, BEFORE trying another port.",
        ]
    elif not ss_ok:
        steps += [
            "The SuperSpeed branch is missing (the cameras). WITHOUT changing port: pull the",
            "  USB-C plug out of the adapter, ROTATE it 180° and reinsert it firmly and fully.",
        ]
    else:
        steps += [
            "The USB2 branch is missing (companion/audio). WITHOUT changing port: pull the",
            "  USB-C plug out of the adapter, ROTATE it 180° and reinsert it firmly and fully.",
        ]
    steps += [
        "Still the same? Try ANOTHER rear A port (every port seats differently).",
        "Nothing? Reseat the connector at the visor end (behind the magnetic gasket), then",
        "  everything together: USB + DP + 18.5 V brick out for ~1 min, then reconnect (docs/22).",
    ]
    return steps


PRINTK = Path("/proc/sys/kernel/printk")
_printk_saved = None


def console_quiet(on):
    """Mute/unmute kernel messages on the VT this script owns.

    Found in testing (T172): the very fault this script asks the
    user to fix -- a marginal seat -- makes the kernel print
    `usb usb3-port1: Cannot enable. Maybe the USB cable is bad?` about once a
    second, straight to /dev/tty1 (console_loglevel 4 lets every KERN_ERR
    through). While the cable is being reconnected, that wall of text
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
    warn("Waiting for you to reconnect. Two keys, each followed by Enter (not at the same time):")
    dim("  Enter alone        -> recheck right now")
    dim("  s, then Enter      -> STOP WAITING now and continue WITHOUT VR, normal 2D desktop")
    dim(f"If you touch nothing: I wait {WAIT_NO_HUMAN_S}s and go on to the 2D desktop anyway, but as a failure")
    dim("(so it is logged and you can retry whenever you like -- see docs/22).")
    dim("Every Enter restarts the wait clock. Meanwhile I silence kernel messages")
    dim("on this console (they still go to the journal) so they do not bury these instructions.")
    console_quiet(True)
    try:
        deadline = time.monotonic() + WAIT_NO_HUMAN_S
        last_status, last_print, answered = None, 0.0, False
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                print()
                if answered:
                    warn(f"Wait timed out ({WAIT_HUMAN_S}s since the last Enter).")
                else:
                    warn("Wait timed out (nobody pressed anything).")
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
            # and that was observed in practice (T172).
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

    print(f"{C_BOLD}=== Powering on the HP Reverb G2 ==={C_RESET}")
    dim("This runs on your normal monitor, not in the headset -- there is nothing to put on yet.")

    def give_up():
        """One step failed -- print the verdict now, log it, and stop -- don't start the next step.
        In --pre-login mode this MUST still hand off to graphical.target: otherwise a
        single disconnected cable (the exact class of thing this whole project debugs)
        dead-ends the console forever, with nobody remote to recover it."""
        log_stats("TE NECESITO" if fail.kind == "physical" else "HAY QUE COMPRAR",
                   stats["step_reached"], {"reason": fail.reason, "part": fail.part})
        print(f"\n{C_BOLD}=== Verdict ==={C_RESET}")
        if fail.kind == "physical":
            print(f"{C_WARN}{C_BOLD}I NEED YOU.{C_RESET} {fail.reason}")
            print("  This costs no money -- it is a matter of reconnecting something.")
            # Say HOW to retry, not just "retry": after this returns, the machine
            # goes to the graphical login and this console disappears. Without the
            # command there is no visible way back (T172: the operator could not
            # press Enter to retry once the console was gone).
            print("  To retry without rebooting: open a terminal and run")
            print(f"    {C_BOLD}{HERE / 'power-on.py'}{C_RESET}")
            print("  (or Ctrl+Alt+F2 for a text console, if the desktop never came up).")
        else:
            print(f"{C_BAD}{C_BOLD}PART NEEDED.{C_RESET} {fail.reason}")
            print(f"  Part: {fail.part} -- see docs/26-diagnostic-toolkit-and-buying-guide.md for the link.")
        if PRE_LOGIN:
            # Explicitly clear this on every failure path -- the autostart entry
            # on the other side only opens vr-launcher.py automatically if this
            # file says the LAST run was a real LISTO. A stale file from a
            # previous successful run must not leak into a session that starts
            # right after a failed one.
            READY_FILE.unlink(missing_ok=True)
            print("  Returning to the graphical login in 5s (Ctrl+C to stay on this console)...")
            time.sleep(5)
            run(["systemctl", "isolate", "graphical.target"], timeout=15)

    def continue_2d():
        """User pressed [s] in a reseat loop: abandon VR bring-up on purpose and
        continue to an ordinary 2D desktop. Distinct from give_up(): this is a
        choice, not a failure, so the verdict says so and nothing red is printed."""
        log_stats("SIN_VR_2D", stats["step_reached"], {"reason": fail.reason or "user skip"})
        print(f"\n{C_BOLD}=== Verdict ==={C_RESET}")
        print(f"{C_WARN}{C_BOLD}NO VR FOR NOW.{C_RESET} Continuing to the normal (2D) desktop.")
        print("  When you want to retry: reconnect the headset and run")
        print(f"    {C_BOLD}{HERE / 'power-on.py'}{C_RESET}")
        if PRE_LOGIN:
            READY_FILE.unlink(missing_ok=True)
            time.sleep(2)
            run(["systemctl", "isolate", "graphical.target"], timeout=15)
        sys.exit(0)

    # ---- 1/5: USB census ----------------------------------------------
    stats["step_reached"] = 1
    step(1, "Is everything connected?")
    lsusb_text = lsusb_output()
    count = headset_count(lsusb_text)
    if count >= 5:
        ok("5/5 headset parts respond (hub, cameras, controller, audio).")
    else:
        usb2_ok, ss_ok = branch_flags(lsusb_text)
        bad(f"Only {count}/5 parts respond -- USB2 branch {'OK' if usb2_ok else 'MISSING'}, "
            f"SuperSpeed branch {'OK' if ss_ok else 'MISSING'}.")
        for line in lsusb_text.splitlines():
            if any(dev in line for dev in DEV_IDS):
                print(f"    {line}")
        if count > 0 and os.geteuid() == 0:
            dim("Trying a software bus reset first (without touching anything physical)...")
            lsusb_text = try_self_repair()
            count = headset_count(lsusb_text)
        if count >= 5:
            ok("Fixed itself -- 5/5 now, without you having to touch anything.")
        else:
            # The software reset was already shown (T171, 2026-08-13) NOT to fix a
            # marginal seat: a full xhci rebind reproduced the identical half-dead
            # state. From here the fix is physical, so say exactly what to do and
            # wait for it instead of dead-ending -- the docs/06 ladder, revalidated
            # live that day: seat, then orientation, then other port, then visor.
            jlog = run(["journalctl", "-k", "--since", "2 min ago"])
            if re.search(r"error -71|Cannot enable", jlog.stdout):
                dim("The kernel retries and fails (error -71): marginal contact, not a fully broken cable.")
            usb2_ok, ss_ok = branch_flags(lsusb_text)
            print()
            warn("You need to reconnect. Step by step, most likely fix first (docs/22, T171):")
            for s in reseat_instructions(usb2_ok, ss_ok):
                print(f"    {C_WARN}»{C_RESET} {s}")

            def _recheck_census():
                nonlocal lsusb_text, count
                lsusb_text = lsusb_output()
                count = headset_count(lsusb_text)
                return count >= 5

            def _status_census():
                u2, ss = branch_flags(lsusb_text)
                return (f"now {count}/5 -- USB2 {'✓' if u2 else '✗'} | "
                        f"SuperSpeed {'✓' if ss else '✗'}  (5/5 = ready)")

            outcome = wait_for_reseat(_recheck_census, _status_census)
            if outcome == "fixed":
                ok("5/5! Reconnected correctly, moving on.")
            elif outcome == "skip":
                return continue_2d()
            else:
                fail.set("Headset parts are missing and the reconnection did not happen in time.", "physical")
    hub_dev = find_device_by_id("04b4", "6506") or find_device_by_id("04b4", "6504")
    if fail.reason:
        return give_up()

    # ---- 2/5: which physical port --------------------------------------
    stats["step_reached"] = 2
    step(2, "Are you on a port we know works?")
    idpath = id_path_for(hub_dev)
    if "usb-0:1" in idpath:
        ok("Known-good port (root port 1 -- validated on this machine).")
    elif "usb-0:4" in idpath:
        bad("Known-BAD port (root port 4): the USB2 of this branch never enumerates here, although the USB3 does.")
        fail.set("You are on a rear port that does not work for this headset (see docs/00, root port 4).", "physical")
    elif "02:00.0" in idpath:
        warn("Chipset USB2 port (not CPU-fed) -- everything enumerates but without SuperSpeed lanes (see step 3).")
        fail.set("You are on the chipset USB2 -- the cameras will not work well here.", "physical")
    elif not idpath:
        warn("Could not identify the port (nothing connected in step 1?).")
    else:
        warn(f"Port not classified yet ({idpath}) -- none of those already mapped in docs/00.")
    if fail.reason:
        return give_up()

    # ---- 3/5: negotiated speed of the cameras (T126: enumerating != healthy)
    stats["step_reached"] = 3
    step(3, "Do the cameras have the bandwidth they need?")
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
        ok(f"Cameras at real SuperSpeed ({speed}M) -- 6DoF/SLAM will have the bandwidth it needs.")
    elif speed > 0:
        # Cameras attached through the USB2 face of the hub (seen live in T171):
        # they enumerate and even stream a little, but SLAM/constellation need the
        # 5 Gbps link. Same physical fix as a missing SS branch: the 180° flip.
        bad(f"Cameras enumerate but only at {speed}M (they need 5000M) -- the SuperSpeed branch did not come up.")
        warn("Proven fix (docs/06, T171): WITHOUT changing port, rotate the USB-C plug 180°")
        warn("  inside the adapter and seat it firmly. If that fails: another rear A port.")

        def _recheck_speed():
            # Require the full census too -- a reseat that trades USB2 for SS
            # (the T171 lottery) must not count as fixed.
            return headset_count(lsusb_output()) >= 5 and camera_speed() >= 5000

        def _status_speed():
            u2, ss = branch_flags(lsusb_output())
            return (f"cameras at {camera_speed()}M -- USB2 {'✓' if u2 else '✗'} | "
                    f"SuperSpeed {'✓' if ss else '✗'}  (5/5 and 5000M = ready)")

        outcome = wait_for_reseat(_recheck_speed, _status_speed)
        if outcome == "fixed":
            ok(f"Cameras at real SuperSpeed ({camera_speed()}M) after reconnecting.")
        elif outcome == "skip":
            return continue_2d()
        else:
            fail.set("The cameras are left without SuperSpeed bandwidth.", "physical")
    else:
        dim("Cameras not detected yet (this resolves itself if step 1 gets fixed).")
    if fail.reason:
        return give_up()

    # ---- 4/5: panel / DP fingerprint -----------------------------------
    stats["step_reached"] = 4
    step(4, "Is the panel awake, and is it really the G2's?")
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
        ok("Real G2 panel confirmed (EDID fingerprint, not just 'connected').")
    else:
        bad("The panel did not wake up, or what is connected is not the G2.")
        dim("The HP logo may be lit anyway -- that is power+HID, independent of DP; it is not enough on its own.")
        warn("The video side needs checking. In order (docs/22):")
        print(f"    {C_WARN}»{C_RESET} The headset DP plug ALL THE WAY into the GPU (a port on the card's rear bracket).")
        print(f"    {C_WARN}»{C_RESET} The 18.5 V brick plugged in and the barrel jack firm in the cable's little box")
        print(f"    {C_WARN}»{C_RESET}   (the box LED says NOTHING about the 18.5 V: it only reflects USB 5V).")
        print(f"    {C_WARN}»{C_RESET} Nothing? Reseat the connector at the visor end (behind the magnetic gasket).")

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

        outcome = wait_for_reseat(_recheck_panel, lambda: "panel still not responding...")
        if outcome == "fixed":
            dp_ok = True
            ok("G2 panel confirmed after reconnecting.")
        elif outcome == "skip":
            return continue_2d()
        else:
            fail.set("The panel does not respond -- try reconnecting the cable at the visor end.", "physical")
    if fail.reason:
        return give_up()

    # ---- 5/5: controllers ------------------------------------------------
    stats["step_reached"] = 5
    step(5, "Are the controllers on?")
    gamepad_present = "045e:028e" in lsusb_output()
    if gamepad_present:
        ok("Xbox 360-type gamepad detected -- works as a fallback if a VR controller is missing")
        dim("  (partial fallback, not every game accepts it -- see docs/pruebas.jsonl T127).")
    if "controllers" in SKIP:
        warn("SKIPPED on request (--skip=controllers) -- consequence: no physical controller in the session.")
    else:
        ctrl_py = HERE / "controller-pair-check.py"
        if not ctrl_py.exists():
            ctrl_py = VR / "controller-pair-check.py"
        ctrl = run([sys.executable, str(ctrl_py), "3"])
        ctrl_out = ctrl.stdout + ctrl.stderr
        left_ok = bool(re.search(r"left.*online", ctrl_out))
        right_ok = bool(re.search(r"right.*online", ctrl_out))
        (ok if left_ok else warn)(f"Left:  {'on and responding' if left_ok else 'NOT responding'}")
        (ok if right_ok else warn)(f"Right: {'on and responding' if right_ok else 'NOT responding'}")
        if not (left_ok and right_ok):
            # Never blocks -- only the headset itself (steps 1-4) can stop the user.
            # Missing controllers are treated as temporary/non-fatal: they (or a
            # gamepad) can be connected later, same as on Windows. One real caveat,
            # said explicitly so it's not a silent surprise mid-session: THIS stack's
            # VR-controller hot-add doesn't work yet (docs/pruebas.jsonl T043) --
            # unlike Windows, connecting one after the session has already started
            # won't make Monado see it. Plug in before jack-in-wayland.sh actually
            # launches, or restart the session once it's on.
            extra = " -- a fallback gamepad is present" if gamepad_present else " -- and no fallback gamepad either"
            warn(f"Still no controllers for now{extra}. Not blocking, starting anyway.")
            dim("They can be switched on / connected later -- but VR-controller hot-plug does not work in")
            dim("this stack yet (unlike Windows): if you connect them with the session already running,")
            dim("Monado will not see them until the next time it starts.")
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
    print(f"\n{C_STEP}▸ Other USB devices on the PC (context only, blocks nothing){C_RESET}")
    KNOWN = {
        "045e:028e": "Xbox 360 Controller",
        "046d": "Logitech (mouse/keyboard/receiver)",
    }
    for line in lsusb_text.splitlines():
        if any(dev in line for dev in DEV_IDS):
            continue  # already shown in step 1
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
    print(f"\n{C_BOLD}=== Verdict ==={C_RESET}")
    if PRE_LOGIN:
        # Run from a bare console (multi-user.target), before any desktop session
        # exists -- there's no Wayland session here to launch into yet. Real VR
        # launch still needs the one validated path: SDDM -> "GNOME" (Wayland),
        # logged in by a human. Not automated -- no autologin path has ever been
        # tested for this project, don't invent one here.
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
        print(f"{C_OK}{C_BOLD}READY.{C_RESET} Hardware verified, not logged in yet.")
        print("  Go to the login screen and pick 'GNOME' under the Wayland list (not X11, not KWin).")
        if controllers_ok:
            print(f"  {C_BOLD}Put the headset on{C_RESET} -- once logged in, the launcher opens by itself and starts the game.")
        elif gamepad_present:
            print("  No VR controllers, but a fallback gamepad is present -- the launcher still opens by itself.")
        else:
            print("  No controllers or gamepad yet -- once logged in you will land on the normal desktop, no auto-launch.")
        print("  Switching to graphical.target in 5s...")
        time.sleep(5)
        run(["systemctl", "isolate", "graphical.target"], timeout=15)
    else:
        print(f"{C_OK}{C_BOLD}READY.{C_RESET} Opening the launcher (mode {MODE}, tracking {TRACKING})...")
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
