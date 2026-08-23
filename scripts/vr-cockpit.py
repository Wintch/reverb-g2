#!/usr/bin/env python3
"""vr-cockpit.py -- pre-session calibration cockpit for the reverb-g2 showcase.

A full-screen, GO/WARN/BLOCK dashboard meant to be glanced at BEFORE putting the
headset on: is the hardware census clean, are the controllers registered, which
tracking-quality fixes are actually active in the running session's environment,
and is the box tuned for a real VR session (governor, GPU power cap, RAPL).

  ./scripts/vr-cockpit.py                 one-shot render, full color if a tty
  ./scripts/vr-cockpit.py --watch 5        redraw every 5s (alt-screen, like a HUD)
  ./scripts/vr-cockpit.py --plain          no ANSI color/clear codes -- CI/log friendly
  COLUMNS=100 ./scripts/vr-cockpit.py --plain   deterministic width for captured output

VISUAL LANGUAGE, borrowed from ~/Documents/selectorai (a retro terminal picker for
CLI-AI provider selection) -- NOT imported as a dependency, this file is stdlib-only
and standalone. What's adapted, credited at each site below:
  - big block-letter titles (sai/bigfont.py's hand-built glyph idiom -- this file's
    FONT dict below adds a few letters selectorai never needed: B, P, W)
  - boxed HUD panels with a colored border carrying the panel's own verdict
    (sai/ui/picker.py's "mother" theme: green-phosphor CRT, round-corner boxes)
  - entries grouped by status, problems visibly separated but never hidden
    (sai/ui/plain.py's online/warning-together vs. offline-behind-a-separator
    split -- ported here as GO+WARN panels first, a BLOCKING section only if
    something is actually BLOCK, never silently dropped)

HARDWARE CHECK REUSE: scripts/power-on.py already has the USB-census logic for this
exact headset (which vendor:product IDs make up the USB3 pair vs. the USB2 trio, how
to tell them apart in `lsusb`) -- that module is imported directly below (not
reimplemented) for lsusb_output()/headset_count()/branch_flags()/DEV_IDS. The DP
panel fingerprint check reuses the same drmprops-cache build-and-run recipe as
power-on.py's step 4 (adapted, not a straight import, since that logic lives inside
main()'s nested closures there).

Every data source (no live monado-service, no log file, no nvidia-smi, no RAPL, a
`docs/battery.jsonl` that's never been touched) is optional -- each panel degrades to
its own WARN line instead of crashing the whole tool. Nothing here writes anything;
every check is read-only.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent  # always the reverb-g2 checkout -- docs/*.md, docs/battery.jsonl live here
VR = REPO
if (Path.home() / "vr" / "monado").is_dir():
    VR = Path.home() / "vr"  # the lab's flat deployment dir -- logs/monado live here instead

DRMPROPS_BIN = Path("/tmp/drmprops-cache")

# --------------------------------------------------------------------------------
# Reuse scripts/power-on.py's hardware-check functions instead of reimplementing
# the USB vendor:product census. Imported via importlib (the filename has a dash,
# so a plain `import` can't reach it) with sys.argv sandboxed during exec_module --
# power-on.py parses sys.argv at module scope (SKIP/PRE_LOGIN/MODE/TRACKING) but
# never *acts* on argv until main() runs, which this file never calls, so the only
# risk is polluting those unused module-level vars with our own args instead of
# power-on.py's.
# --------------------------------------------------------------------------------
def _load_power_on():
    path = HERE / "power-on.py"
    spec = importlib.util.spec_from_file_location("_vr_cockpit_power_on", str(path))
    mod = importlib.util.module_from_spec(spec)
    saved_argv = sys.argv
    try:
        sys.argv = [str(path)]
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved_argv
    return mod


# ==================================================================================
# Status model: GO < WARN < BLOCK, matching sai/health.py's ONLINE/WARNING/OFFLINE
# three-state idiom (unknown/absent data is WARN, never silently GO -- "unknown is
# not the same as healthy", same rule sai/ui/picker.py's _health_for docstring states).
# ==================================================================================
GO, WARN, BLOCK = "GO", "WARN", "BLOCK"
_SEV = {GO: 0, WARN: 1, BLOCK: 2}


def worse(a, b):
    return a if _SEV[a] >= _SEV[b] else b


def worst_of(statuses):
    result = GO
    for s in statuses:
        result = worse(result, s)
    return result


# ==================================================================================
# Big block-letter font -- adapted from sai/bigfont.py's FONT dict (same 6-row,
# hand-built-and-verified idiom; letters A/C/G/I/K/L/N/O/R/T/V copied verbatim from
# there). B, P, W added here for "VR COCKPIT" / "GO" / "WARN" / "BLOCK", which
# selectorai's own title ("SELECTOR AI") never needed.
# ==================================================================================
FONT = {
    "A": [" ██ ", "█  █", "█  █", "████", "█  █", "█  █"],
    "B": ["███ ", "█  █", "███ ", "█  █", "█  █", "███ "],
    "C": [" ███", "█   ", "█   ", "█   ", "█   ", " ███"],
    "G": [" ███", "█   ", "█ ██", "█  █", "█  █", " ███"],
    "I": ["████", " █  ", " █  ", " █  ", " █  ", "████"],
    "K": ["█  █", "█ █ ", "██  ", "█ █ ", "█  █", "█  █"],
    "L": ["█   ", "█   ", "█   ", "█   ", "█   ", "████"],
    "N": ["█  █", "██ █", "█ ██", "█  █", "█  █", "█  █"],
    "O": [" ██ ", "█  █", "█  █", "█  █", "█  █", " ██ "],
    "P": ["███ ", "█  █", "███ ", "█   ", "█   ", "█   "],
    "R": ["███ ", "█  █", "███ ", "█ █ ", "█  █", "█  █"],
    "T": ["████", " █  ", " █  ", " █  ", " █  ", " █  "],
    "V": ["█  █", "█  █", "█  █", "█  █", " ██ ", " ██ "],
    "W": ["█   █", "█   █", "█ █ █", "█ █ █", "██ ██", "█   █"],
    " ": ["  ", "  ", "  ", "  ", "  ", "  "],
}


def render_big(text):
    rows = ["" for _ in range(6)]
    for ch in text.upper():
        glyph = FONT.get(ch, FONT[" "])
        for i in range(6):
            rows[i] += glyph[i] + " "
    return [r.rstrip() for r in rows]


# ==================================================================================
# Battery voltage model -- docs/46-battery-management.md section 2. Two chemistry-
# grounded anchors (fresh NiMH surface charge ~1.475V at raw byte 153, NiMH plateau
# 1.2V nominal at byte 112.5) fit a straight line; checked (not fit) against two more
# points from the same night's data. The cliff itself is UNOBSERVED -- ~65-83 is an
# extrapolation, flagged as such every place it's shown, per that doc's own section 6.
# ==================================================================================
BATTERY_SLOPE = 0.00679          # V per raw count
BATTERY_OFFSET = 0.436           # V
BATTERY_PLATEAU_BYTE = 112.5
BATTERY_CLIFF_LOW = 65           # predicted, NOT observed (docs/46 S2/S6)
BATTERY_CLIFF_HIGH = 83
BATTERY_WARN_MARGIN = 15         # start warning this many counts above the cliff band
BATTERY_FALLBACK_DRAIN_PER_H = 10.0  # counts/hour -- used only when this session hasn't
# run long enough yet to measure its own drain rate; not independently validated as a
# steady-state constant (docs/46 never ran a full timed discharge), it's a conservative
# placeholder so the countdown line has SOMETHING to say for a session that just started.


def battery_voltage(raw_byte):
    return BATTERY_SLOPE * raw_byte + BATTERY_OFFSET


def battery_countdown(current_byte, elapsed_hours, initial_byte):
    """Hours left before `current_byte` is predicted to reach the cliff band's high
    end, at whatever drain rate can be measured THIS session (first reading vs. now),
    falling back to BATTERY_FALLBACK_DRAIN_PER_H when there isn't enough of a session
    yet to measure one. Returns (hours_left, rate_per_h, source_label)."""
    rate, source = None, "assumed"
    if initial_byte is not None and elapsed_hours and elapsed_hours > 0.05 and initial_byte > current_byte:
        rate = (initial_byte - current_byte) / elapsed_hours
        source = "measured this session"
    if not rate or rate <= 0:
        rate = BATTERY_FALLBACK_DRAIN_PER_H
        source = "assumed, no measurable drain yet this session"
    counts_to_cliff = max(0.0, current_byte - BATTERY_CLIFF_HIGH)
    hours_left = counts_to_cliff / rate if rate > 0 else None
    return hours_left, rate, source


def latest_cell_assignment(path):
    """Last `cell_assignment` event in docs/battery.jsonl -- {"left": [...], "right":
    [...]} cell names, or None if the file is absent/empty/never had one."""
    if not path.exists():
        return None
    assignment = None
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("event") == "cell_assignment":
                    assignment = {"left": d.get("left"), "right": d.get("right")}
    except OSError:
        return None
    return assignment


# ==================================================================================
# Live monado-service process: found by scanning /proc for comm == "monado-service"
# rather than shelling out to pgrep -- CLAUDE.md's own standing lesson is that
# `pgrep -f` matches its own invocation in this environment's shell, and a pure
# /proc scan sidesteps that whole class of bug rather than working around it.
# ==================================================================================
def find_monado_pid():
    proc = Path("/proc")
    try:
        candidates = [p for p in proc.iterdir() if p.name.isdigit()]
    except OSError:
        return None
    for p in candidates:
        try:
            comm = (p / "comm").read_text().strip()
        except OSError:
            continue
        if comm == "monado-service":
            return int(p.name)
    return None


def read_environ(pid):
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    env = {}
    for part in raw.split(b"\0"):
        if not part:
            continue
        k, _, v = part.decode("utf-8", "replace").partition("=")
        env[k] = v
    return env


def process_start_epoch(pid):
    """Wall-clock epoch the process started, from /proc/<pid>/stat's starttime field
    (in clock ticks since boot) plus /proc/uptime. None on any failure -- callers
    treat that as 'can't measure elapsed time', not zero."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        after = stat.rsplit(")", 1)[1].split()
        starttime_ticks = int(after[19])  # stat field 22 overall; state(3) is after[0]
        clk_tck = os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime") as f:
            uptime = float(f.read().split()[0])
        boot_epoch = time.time() - uptime
        return boot_epoch + starttime_ticks / clk_tck
    except (OSError, IndexError, ValueError):
        return None


# ==================================================================================
# Session log parsing -- scripts/jack-in-wayland.sh always writes to this exact path
# with `>` (truncate), never `>>`, so it's inherently "the newest" without needing to
# glob timestamped variants; it corresponds to whatever monado-service is (or was
# last) running.
#
# The battery-byte log line (`Controller battery raw byte: OLD -> NEW`) carries no
# hand tag of its own -- only the surrounding context does (a `Reading left/right
# controller config` line earlier in the stream). Each hand's FIRST-ever reading logs
# as "0 -> byte" (last_input->battery starts at struct-zero); matched to whichever
# hand's context was current. Every later reading is matched by continuity: OLD
# equals whichever hand's last known value was OLD.
# ==================================================================================
_LEFT_RE = re.compile(r"^\s*left:\s*(.+)$")
_RIGHT_RE = re.compile(r"^\s*right:\s*(.+)$")
_BATTERY_RE = re.compile(r"Controller battery raw byte:\s*(\d+)\s*->\s*(\d+)")
_STICK_AUTOCENTER_RE = re.compile(
    r"stick autocenter (\w+): offset=\(([-\d.]+),\s*([-\d.]+)\)\s*\[(\d+) samples"
)


def _strip_paren_suffix(raw):
    return re.sub(r"\s*\(.*\)\s*$", "", raw).strip()


def parse_session_log(path):
    result = {
        "left_registered": False, "right_registered": False,
        "left_name": None, "right_name": None,
        "battery_first": {"left": None, "right": None},
        "battery_last": {"left": None, "right": None},
        "stick_autocenter": {},
        "exists": path.exists(),
    }
    if not result["exists"]:
        return result

    hand_ctx = None
    battery_first = result["battery_first"]
    battery_last = result["battery_last"]
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                if "Reading left controller config" in line:
                    hand_ctx = "left"
                elif "Reading right controller config" in line:
                    hand_ctx = "right"

                m = _LEFT_RE.match(line)
                if m:
                    name = _strip_paren_suffix(m.group(1))
                    result["left_registered"] = bool(name) and name.lower() != "none"
                    result["left_name"] = name

                m = _RIGHT_RE.match(line)
                if m:
                    name = _strip_paren_suffix(m.group(1))
                    result["right_registered"] = bool(name) and name.lower() != "none"
                    result["right_name"] = name

                m = _BATTERY_RE.search(line)
                if m:
                    old, new = int(m.group(1)), int(m.group(2))
                    if old == 0:
                        target = hand_ctx if battery_last.get(hand_ctx) is None else None
                        if target is None:
                            other = "right" if hand_ctx == "left" else "left"
                            target = other if battery_last.get(other) is None else hand_ctx
                        if target:
                            battery_first[target] = new
                            battery_last[target] = new
                    else:
                        for h in ("left", "right"):
                            if battery_last[h] == old:
                                battery_last[h] = new
                                break

                m = _STICK_AUTOCENTER_RE.search(line)
                if m:
                    hand = m.group(1)
                    result["stick_autocenter"][hand] = (
                        float(m.group(2)), float(m.group(3)), int(m.group(4))
                    )
    except OSError:
        pass
    return result


# ==================================================================================
# DP panel fingerprint check -- adapted from power-on.py's step 4 (build-cache the
# drmprops helper, run it, look for "fingerprint matches" in its stdout). Not a
# straight import: that logic lives inside power-on.py's main()'s nested closures,
# tied to its own interactive wait_for_reseat() loop, which this one-shot dashboard
# has no business calling.
# ==================================================================================
def check_dp_panel():
    result = {"matched": False, "any_connected": False, "error": None}
    drmprops_src = HERE / "drmprops.c"
    if not drmprops_src.exists():
        result["error"] = "drmprops.c not found -- can't check the DP fingerprint"
        return result

    need_build = (
        not DRMPROPS_BIN.exists()
        or DRMPROPS_BIN.stat().st_mtime < drmprops_src.stat().st_mtime
    )
    if need_build:
        try:
            build = subprocess.run(
                ["gcc", "-o", str(DRMPROPS_BIN), str(drmprops_src), "-ldrm", "-I/usr/include/libdrm"],
                capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            result["error"] = f"drmprops build failed: {e}"
            return result
        if build.returncode != 0:
            result["error"] = f"drmprops build failed: {build.stderr.strip()[:200]}"
            return result

    try:
        check = subprocess.run([str(DRMPROPS_BIN)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        result["error"] = f"drmprops run failed: {e}"
        return result

    out = check.stdout
    result["matched"] = "fingerprint matches" in out
    result["any_connected"] = "CONNECTED" in out
    return result


# ==================================================================================
# Panel data gatherers. Each returns {"status", "lines" (list of (marker, text)),
# "reasons" (list of str, only the ones worth surfacing on the big VERDICT panel)}.
# Every one is wrapped in a try/except at the call site (see build_panels()) so a
# single broken check degrades to a WARN panel instead of crashing the whole tool.
# ==================================================================================
def gather_headset(power_on_mod):
    lines, reasons = [], []

    lsusb_text = power_on_mod.lsusb_output()
    count = power_on_mod.headset_count(lsusb_text)
    usb2_ok, ss_ok = power_on_mod.branch_flags(lsusb_text)

    lines.append((
        "ok" if ss_ok else "bad",
        f"USB3 SuperSpeed pair (hub 04b4:6504 + cameras 045e:0659): {'present' if ss_ok else 'MISSING'}",
    ))
    lines.append((
        "ok" if usb2_ok else "bad",
        f"USB2 trio (hub 04b4:6506 + companion 03f0:0580 + audio 0bda:4c15): {'present' if usb2_ok else 'MISSING'}",
    ))
    lines.append(("dim", f"census: {count}/5 headset USB devices respond in lsusb"))

    if not ss_ok:
        reasons.append("SuperSpeed branch missing -- no cameras, no 6DoF/SLAM, no constellation tracking")
    if not usb2_ok:
        reasons.append("USB2 branch missing -- no panel HID control, no headset audio, no companion telemetry")

    dp = check_dp_panel()
    if dp["matched"]:
        lines.append(("ok", "DP panel: G2 fingerprint confirmed (real headset display, not a monitor)"))
    elif dp["any_connected"]:
        lines.append(("warn", "DP: some connector is CONNECTED but its EDID didn't match the G2 panel"))
    else:
        lines.append(("bad", "DP panel: no matching connector found -- panel is almost certainly dark"))
    if dp["error"]:
        lines.append(("dim", dp["error"][:140]))

    if count == 0:
        status = BLOCK
        reasons.insert(0, "no headset USB devices detected at all -- check the cable (docs/22)")
    elif not dp["matched"]:
        status = BLOCK
        reasons.insert(0, "headset display not confirmed by fingerprint -- panel is very likely dark "
                          "(this project's #1 rule: verification is physical, put the headset on to be sure)")
    elif count < 5:
        status = WARN
    else:
        status = GO

    return {"status": status, "lines": lines, "reasons": reasons}


def gather_controllers():
    lines, reasons = [], []
    status = GO

    pid = find_monado_pid()
    log_data = parse_session_log(VR / "jack-in-wayland.log")

    if pid is None:
        lines.append(("warn", "monado-service: not running"))
        reasons.append("no live session -- controller registration/battery can't be checked live")
        if log_data["exists"] and (log_data["left_name"] or log_data["right_name"]):
            lines.append((
                "dim",
                f"last known from {VR / 'jack-in-wayland.log'} (STALE, no process behind it): "
                f"left={log_data['left_name'] or '?'}  right={log_data['right_name'] or '?'}",
            ))
        elif not log_data["exists"]:
            lines.append(("dim", f"no session log at {VR / 'jack-in-wayland.log'} either"))
        return {"status": WARN, "lines": lines, "reasons": reasons}

    lines.append(("ok", f"monado-service: running (pid {pid})"))

    if not log_data["exists"]:
        lines.append(("warn", "session log not found -- registration/battery unknown despite a live process"))
        reasons.append("jack-in-wayland.log missing -- can't confirm controller registration")
        return {"status": worse(status, WARN), "lines": lines, "reasons": reasons}

    cells = latest_cell_assignment(REPO / "docs" / "battery.jsonl")
    start_epoch = process_start_epoch(pid)
    elapsed_hours = max(0.0, (time.time() - start_epoch) / 3600.0) if start_epoch else None

    for hand in ("left", "right"):
        registered = log_data[f"{hand}_registered"]
        name = log_data[f"{hand}_name"]
        if registered:
            lines.append(("ok", f"{hand}: registered ({name})"))
        else:
            seen = f" (last status line: '{name}')" if name else " (never registered this session)"
            lines.append(("warn", f"{hand}: NOT registered{seen}"))
            reasons.append(f"{hand} controller not registered this session -- no 6DoF/hand tracking for that hand")
            status = worse(status, WARN)

        raw = log_data["battery_last"].get(hand)
        first = log_data["battery_first"].get(hand)
        cell_label = ""
        if cells and cells.get(hand):
            cell_label = " [" + "+".join(cells[hand]) + "]"
        if raw is None:
            lines.append(("dim", f"{hand} battery{cell_label}: no reading yet this session"))
            continue

        v = battery_voltage(raw)
        if raw <= BATTERY_CLIFF_HIGH:
            pos, marker = "AT/BELOW the predicted (unobserved) cliff band", "bad"
        elif raw <= BATTERY_CLIFF_HIGH + BATTERY_WARN_MARGIN:
            pos, marker = "approaching the predicted cliff band", "warn"
        elif raw >= BATTERY_PLATEAU_BYTE:
            pos, marker = "at/above the NiMH plateau", "ok"
        else:
            pos, marker = "below plateau, above the cliff band", "ok"

        lines.append(("dim" if marker == "dim" else marker,
                       f"{hand} battery{cell_label}: raw={raw}  (~{v:.2f}V modeled, {pos})"))
        if marker in ("warn", "bad"):
            status = worse(status, WARN)
            reasons.append(f"{hand} battery raw={raw} ({pos}) -- charge before a long session")

        if elapsed_hours is not None and elapsed_hours > 0.02:
            hours_left, rate, source = battery_countdown(raw, elapsed_hours, first)
            lines.append((
                "dim",
                f"  drain ~{rate:.1f} counts/h ({source}) -> ~{hours_left:.1f}h to the predicted cliff band",
            ))

    return {"status": status, "lines": lines, "reasons": reasons}


# label, value if not set -- verified directly against the DEBUG_GET_ONCE_* defaults
# in wmr_controller_hp.c / wmr_controller_base.c, not guessed.
CALIBRATION_KEYS = [
    ("WMR_CONTROLLER_LEFT_YAW_GYRO_INVERT", "left yaw-gyro invert (T206/T207)", "false"),
    ("WMR_CONTROLLER_LEFT_GYRO_FIT", "left gyro matrix refit (T209)", "false"),
    ("WMR_CONTROLLER_SOLVE_YAW_CORRECT", "solve-yaw correction gain", "0.0"),
    ("SLAM_CORRECTION_SPREAD_MS", "SLAM correction spread (ms)", "unset -- code default applies"),
    ("WMR_STICK_DEADZONE", "stick deadzone", "unset -- code default applies"),
    ("WMR_STICK_AUTOCENTER", "stick autocenter (per-stick center calibration)", "false"),
]


def gather_calibration():
    pid = find_monado_pid()
    if pid is None:
        return {
            "status": WARN,
            "lines": [("warn", "monado-service not running -- can't read the live session environment")],
            "reasons": ["no live session -- calibration fixes unknown"],
        }

    env = read_environ(pid)
    lines = []
    for key, label, default in CALIBRATION_KEYS:
        val = env.get(key)
        if val is None:
            lines.append(("dim", f"{label}: not set ({default})"))
        else:
            lines.append(("ok", f"{label}: {val}"))

    log_data = parse_session_log(VR / "jack-in-wayland.log")
    if log_data["stick_autocenter"]:
        for hand, (ox, oy, n) in sorted(log_data["stick_autocenter"].items()):
            lines.append(("ok", f"{hand} stick autocenter measured offset: ({ox:+.3f}, {oy:+.3f}) over {n} samples"))
    elif env.get("WMR_STICK_AUTOCENTER") == "1":
        lines.append(("dim", "stick autocenter enabled but no offset logged yet (still sampling, or aborted)"))

    return {"status": GO, "lines": lines, "reasons": []}


def gather_power():
    lines, reasons = [], []
    status = GO

    # vr-power-watchdog.py (2026-08-23, T246) pins performance automatically the moment a
    # session/game is live and drops to powersave at rest -- powersave while idle is now the
    # NORMAL expected state, not a problem. Only escalate when the watchdog itself thinks
    # performance should be in effect (or isn't installed at all, the pre-watchdog world)
    # and the governor disagrees -- that's a real fault, not idle housekeeping.
    watchdog_mode = None
    try:
        watchdog_mode = Path("/run/vr-power-mode").read_text().strip()
    except OSError:
        pass
    session_active = find_monado_pid() is not None

    governor = None
    try:
        governor = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip()
    except OSError:
        pass
    if governor:
        ok = governor == "performance"
        expect_performance = watchdog_mode == "performance" or session_active or watchdog_mode is None
        if ok:
            lines.append(("ok", f"CPU governor: {governor}"))
        elif expect_performance:
            lines.append(("warn", f"CPU governor: {governor}"))
            status = worse(status, WARN)
            reasons.append(f"CPU governor is '{governor}', not 'performance' -- can add scheduling jitter")
        else:
            lines.append(("dim", f"CPU governor: {governor} (idle, watchdog will pin performance once a session starts)"))
    else:
        lines.append(("warn", "CPU governor: unreadable (no cpufreq on this machine?)"))
        status = worse(status, WARN)
        reasons.append("CPU governor unreadable")

    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=power.draw,power.limit,power.max_limit,persistence_mode",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
            if len(parts) >= 4:
                draw, limit, maxlim, persist = parts[:4]
                lines.append(("ok", f"GPU power: {draw}W draw / {limit}W cap (max {maxlim}W), persistence={persist}"))
                try:
                    if float(limit) < float(maxlim) * 0.95:
                        lines.append((
                            "dim",
                            "  capped below max -- T209 measured 105W==210W for VR pacing, this is a feature",
                        ))
                except ValueError:
                    pass
            else:
                lines.append(("warn", "nvidia-smi: unexpected output format"))
        else:
            lines.append(("warn", "nvidia-smi: no GPU reported"))
            status = worse(status, WARN)
            reasons.append("nvidia-smi returned no GPU data")
    except (OSError, subprocess.TimeoutExpired):
        lines.append(("warn", "nvidia-smi: not available"))
        status = worse(status, WARN)
        reasons.append("nvidia-smi not available -- no GPU power telemetry")

    rapl = Path("/sys/class/powercap/intel-rapl:0/energy_uj")
    if rapl.exists():
        try:
            rapl.read_text()
            lines.append(("ok", "RAPL (CPU package energy): readable"))
        except (OSError, PermissionError):
            lines.append((
                "warn",
                "RAPL: present but not world-readable (chmod pending -- scripts/vr-power-setup.sh --apply)",
            ))
            status = worse(status, WARN)
            reasons.append("RAPL energy counter not readable -- CPU watts won't be logged")
    else:
        lines.append(("dim", "RAPL: not present on this machine"))

    conf = VR / "power.conf"
    if conf.exists():
        lines.append(("ok", f"power.conf: {conf}"))
    else:
        lines.append(("warn", f"power.conf: not found at {conf} -- no saved per-box GPU cap profile"))
        status = worse(status, WARN)
        reasons.append("no power.conf -- GPU power cap isn't being applied from a saved profile")

    return {"status": status, "lines": lines, "reasons": reasons}


# ==================================================================================
# Rendering. Colors are basic ANSI SGR (same codes power-on.py already uses in this
# repo: bright-green ok, yellow warn, red bad) rather than the mother.tcss theme's
# truecolor hex, for terminal-compatibility parity with the rest of this project's
# tooling -- selectorai's CONTRIBUTION here is the box/grouping/big-font IDIOM, not
# its literal color values.
# ==================================================================================
class Palette:
    def __init__(self, enabled):
        if enabled:
            self.ok = "\033[1;92m"
            self.warn = "\033[1;33m"
            self.bad = "\033[1;31m"
            self.dim = "\033[2m"
            self.bold = "\033[1m"
            self.reset = "\033[0m"
        else:
            self.ok = self.warn = self.bad = self.dim = self.bold = self.reset = ""

    def for_status(self, status):
        return {GO: self.ok, WARN: self.warn, BLOCK: self.bad}[status]

    def for_marker(self, marker):
        return {"ok": self.ok, "warn": self.warn, "bad": self.bad, "dim": self.dim}[marker]


MARK_GLYPH = {"ok": "✓", "warn": "!", "bad": "✗", "dim": "·"}


def box_width(term_width):
    return max(44, min(term_width - 2, 98))


def panel_content_rows(lines, inner_width, pal):
    """lines: list of (marker, text). Returns list of (plain_text, color) rows,
    each already <= inner_width, wrapped with a blank-marker continuation indent."""
    rows = []
    for marker, text in lines:
        glyph = MARK_GLYPH[marker]
        color = pal.for_marker(marker)
        prefix = f"{glyph} "
        avail = max(8, inner_width - len(prefix))
        wrapped = textwrap.wrap(text, width=avail) or [""]
        rows.append((prefix + wrapped[0], color))
        for cont in wrapped[1:]:
            rows.append(("  " + cont, color))
    return rows


def render_panel(title, status, lines, width, pal):
    color = pal.for_status(status)
    inner = width - 4  # "│ " ... " │"
    label = f" {title} [{status}] "
    dash_count = max(1, width - 2 - len(label) - 1)
    top = f"{color}╭─{label}{'─' * dash_count}╮{pal.reset}"
    bottom = f"{color}╰{'─' * (width - 2)}╯{pal.reset}"

    out = [top]
    for text, line_color in panel_content_rows(lines, inner, pal):
        pad = max(0, inner - len(text))
        colored = f"{line_color}{text}{pal.reset}" if line_color else text
        out.append(f"{color}│{pal.reset} {colored}{' ' * pad} {color}│{pal.reset}")
    out.append(bottom)
    return out


def render_verdict(status, reasons, width, pal):
    color = pal.for_status(status)
    big = render_big(status)
    out = [f"{color}{pal.bold}{line}{pal.reset}" for line in big]
    if reasons:
        out.append("")
        label = "BLOCKING REASONS" if status == BLOCK else "REASONS"
        out.append(f"{color}{pal.bold}{label}:{pal.reset}")
        for r in reasons:
            wrapped = textwrap.wrap(r, width=max(20, width - 2), initial_indent="- ", subsequent_indent="  ")
            for wline in wrapped:
                out.append(f"{color}{wline}{pal.reset}")
    else:
        out.append("")
        out.append(f"{pal.dim}no blocking or warning conditions found{pal.reset}")
    return out


def build_panels(power_on_mod):
    """Runs every gather_* with its own try/except so one broken check can't take
    the rest of the dashboard down with it -- degrades that single panel to WARN
    with the exception folded in as its own reason line, same 'unknown, not
    unhealthy-by-default, but never silently GO either' rule as sai/health.py."""
    specs = [
        ("HEADSET", lambda: gather_headset(power_on_mod)),
        ("CONTROLLERS", gather_controllers),
        ("CALIBRATION", gather_calibration),
        ("POWER", gather_power),
    ]
    panels = []
    for title, fn in specs:
        try:
            data = fn()
        except Exception as e:  # noqa: BLE001 -- deliberately broad, see docstring
            data = {
                "status": WARN,
                "lines": [("warn", f"internal check failed: {e}")],
                "reasons": [f"{title} panel: internal check failed ({e})"],
            }
        panels.append({"title": title, **data})
    return panels


def render_dashboard(width, pal, plain):
    try:
        power_on_mod = _load_power_on()
    except Exception as e:  # noqa: BLE001
        power_on_mod = None
        load_error = str(e)
    else:
        load_error = None

    lines_out = []
    lines_out.append(f"{pal.ok}{pal.bold}")
    for row in render_big("VR COCKPIT"):
        lines_out.append(row)
    lines_out.append(pal.reset)

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    lines_out.append(f"{pal.dim}reverb-g2 pre-session cockpit -- {now}{pal.reset}")
    lines_out.append("")

    if power_on_mod is None:
        panels = [{
            "title": "HEADSET", "status": BLOCK,
            "lines": [("bad", f"could not load scripts/power-on.py: {load_error}")],
            "reasons": [f"power-on.py failed to load: {load_error}"],
        }]
    else:
        panels = build_panels(power_on_mod)

    go_warn = [p for p in panels if p["status"] != BLOCK]
    blocking = [p for p in panels if p["status"] == BLOCK]

    for p in go_warn:
        lines_out += render_panel(p["title"], p["status"], p["lines"], width, pal)
        lines_out.append("")

    if blocking:
        sep_label = " ⚠ BLOCKING -- these stop a real VR session "
        dash_count = max(1, width - len(sep_label))
        lines_out.append(f"{pal.bad}{pal.bold}{sep_label}{'─' * dash_count}{pal.reset}")
        lines_out.append("")
        for p in blocking:
            lines_out += render_panel(p["title"], p["status"], p["lines"], width, pal)
            lines_out.append("")

    overall = worst_of(p["status"] for p in panels) if panels else WARN
    all_reasons = [r for p in panels for r in p["reasons"]]
    lines_out += render_verdict(overall, all_reasons, width, pal)
    lines_out.append("")
    lines_out.append(f"{pal.dim}--watch N to auto-refresh, --plain for a log-friendly render{pal.reset}")

    return "\n".join(lines_out)


def get_terminal_width():
    import shutil
    return shutil.get_terminal_size(fallback=(100, 24)).columns


def main(argv):
    plain = "--plain" in argv
    watch_seconds = None
    for i, a in enumerate(argv):
        if a == "--watch":
            if i + 1 < len(argv):
                try:
                    watch_seconds = float(argv[i + 1])
                except ValueError:
                    pass
        elif a.startswith("--watch="):
            try:
                watch_seconds = float(a.split("=", 1)[1])
            except ValueError:
                pass
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0

    is_tty = sys.stdout.isatty()
    use_color = is_tty and not plain
    pal = Palette(use_color)
    width = box_width(get_terminal_width())

    if watch_seconds is None:
        print(render_dashboard(width, pal, plain))
        return 0

    alt_screen = is_tty and not plain
    try:
        while True:
            width = box_width(get_terminal_width())
            frame = render_dashboard(width, pal, plain)
            if alt_screen:
                sys.stdout.write("\033[2J\033[H")
            print(frame)
            if not alt_screen:
                print(f"\n-- refreshing every {watch_seconds:g}s, Ctrl+C to stop --")
            time.sleep(max(0.5, watch_seconds))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
