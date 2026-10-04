#!/bin/bash
# jack-in-oasis-x11.sh - start SteamVR with the Oasis/Ignition driver on an X11 session
# (KDE Plasma X11 or GNOME on Xorg), with the HP Reverb G2 freed from the desktop first.
#
#   jack-in-oasis-x11.sh up | down | status | watchdog [--auto] [--dry-run]
#
# Why this exists (docs/117, docs/121 s4, docs/137, docs/138): on X11 the NVIDIA driver (and
# the desktop shell's display daemon) treat the G2's DisplayPort output as one more monitor
# (RandR "non-desktop" reads 0 on this rig), so the desktop is drawn on the panel and the
# compositor's vkAcquireXlibDisplayEXT cannot take it ("Failed to acquire xlib display" ->
# VRInitError_Compositor_CannotDRMLeaseDisplay). This script:
#   1. finds the live X session env (DISPLAY/XAUTHORITY) from the running shell processes,
#   2. finds the G2's output dynamically (EDID vendor HPN / non-desktop=1 / name),
#   3. waits for the bonded G2 controllers to be awake (host Bluetooth, hidraw 045E:066A),
#   4. backs up openvrpaths.vrpath + steamvr.vrsettings, puts SteamVR's runtime first and
#      forces driver_monado.enable=false,
#   5. frees the panel (kscreen-doctor when on Plasma, else xrandr --off), parks the KDE
#      screen daemon so it cannot re-enable it, waits ~8 s for the CRTC teardown,
#   6. starts Steam (PATH incl. /usr/sbin) if needed and launches SteamVR (AppID 250820),
#   7. watches the SteamVR logs ONCE for the success/failure markers and samples poses.
# It makes AT MOST ONE launch attempt per 'up' (a second 'up' refuses until 'down' ran).
# 'status' is read-only and also reports preflight problems, stale SteamVR sockets and the "stale HID"
# state of the Oasis driver (docs/139). 'watchdog' reports that state; with --auto it does ONE
# down+up when it finds it, at most 2 recoveries per hour (docs/22 stop rule), and only when the
# headset's 5 USB devices are enumerated.
# Does not touch Monado, jack-in-wayland.sh or the BT scripts.

set -u

VR_DIR="$HOME/vr"
LOG="$VR_DIR/oasis-x11.log"
STATE="$VR_DIR/oasis-x11.state"
BACKUP_DIR="$VR_DIR/oasis-x11-backup"
STEAM_ROOT="$HOME/.steam/debian-installation"
STEAMVR="$STEAM_ROOT/steamapps/common/SteamVR"
VRPATHS="$HOME/.config/openvr/openvrpaths.vrpath"
VRSETTINGS="$STEAM_ROOT/config/steamvr.vrsettings"
OASIS_DIR="${OASIS_DIR:-/mnt/videos/SteamLibrary/steamapps/common/Oasis Driver for Windows Mixed Reality}"
VRLOGS="${OASIS_VRLOGS:-$STEAM_ROOT/logs}"
WATCH_SECONDS="${OASIS_WATCH_SECONDS:-120}"
BT_WAIT="${VR_BT_CTRL_WAIT:-30}"
HMD_OUTPUT="${HMD_OUTPUT:-}"          # override only if autodetect is wrong
MONADO_JSON="${MONADO_RUNTIME_JSON:-$VR_DIR/monado/build/openxr_monado-dev.json}"
MONADO_JSON_ORIG="$BACKUP_DIR/openxr_monado-dev.json.monado-original"
SELF="$(readlink -f "${BASH_SOURCE[0]:-$0}")"

mkdir -p "$VR_DIR"
log() { local m; m="$(date '+%F %T') $*"; echo "$m"; echo "$m" >> "$LOG"; }
die() { log "ABORT: $*"; exit "${2:-1}"; }

state_get() { [ -f "$STATE" ] && sed -n "s/^$1=//p" "$STATE" | tail -1; }
state_set() { echo "$1=$2" >> "$STATE"; }

# ---- session env ---------------------------------------------------------------------
# A detached shell has no DISPLAY; XAUTHORITY is a random file. Read both from a process that
# is part of the live graphical session (the same trick gui_env.py uses, but without its
# Wayland assumptions, which are wrong on an X11 login).
find_session_env() {
	local comm pid k v
	for comm in kwin_x11 plasmashell startplasma-x11 gnome-shell mutter-x11-frames gsd-xsettings; do
		for pid in $(pgrep -u "$(id -u)" -x "$comm" 2>/dev/null); do
			[ -r "/proc/$pid/environ" ] || continue
			while IFS='=' read -r k v; do
				case "$k" in
					DISPLAY|XAUTHORITY|XDG_SESSION_TYPE|XDG_CURRENT_DESKTOP|DBUS_SESSION_BUS_ADDRESS) export "$k=$v" ;;
				esac
			done < <(tr '\0' '\n' < "/proc/$pid/environ" | grep -E '^(DISPLAY|XAUTHORITY|XDG_SESSION_TYPE|XDG_CURRENT_DESKTOP|DBUS_SESSION_BUS_ADDRESS)=')
			if [ -n "${DISPLAY:-}" ] && xrandr -q >/dev/null 2>&1; then
				export XDG_RUNTIME_DIR="/run/user/$(id -u)"
				return 0
			fi
		done
	done
	return 1
}

# ---- G2 output discovery --------------------------------------------------------------
# Prints the RandR output name of the Reverb G2. Rules, in order: EDID vendor "HPN" (HP VR
# headsets), EDID monitor name containing "Reverb"/"HP VR", RandR non-desktop=1. Never a
# hard-coded connector name (it is DP-0 here, but nothing guarantees that).
find_hmd_output() {
	xrandr --prop 2>/dev/null | python3 -c '
import re, sys
txt = sys.stdin.read()
blocks = re.split(r"(?m)^(?=\S)", txt)
best = None
for b in blocks:
    m = re.match(r"(\S+) (connected|disconnected)", b)
    if not m or m.group(2) != "connected":
        continue
    name = m.group(1)
    hexs = ""
    em = re.search(r"EDID:\s*\n((?:\t\t[0-9a-f]{32}\n?)+)", b)
    if em:
        hexs = "".join(em.group(1).split())
    score = 0
    if len(hexs) >= 256:
        raw = bytes.fromhex(hexs[:256])
        v = (raw[8] << 8) | raw[9]
        mfg = "".join(chr(((v >> s) & 31) + 64) for s in (10, 5, 0))
        mon = ""
        for off in (54, 72, 90, 108):
            d = raw[off:off + 18]
            if d[0:3] == b"\0\0\0" and d[3] == 0xFC:
                mon = d[5:].split(b"\n")[0].decode("ascii", "replace")
        if mfg == "HPN":
            score += 3
        if re.search(r"reverb|hp vr|windows mixed", mon, re.I):
            score += 3
    nd = re.search(r"non-desktop:\s*(\d)", b)
    if nd and nd.group(1) == "1":
        score += 2
    if score and (best is None or score > best[0]):
        best = (score, name)
if best:
    print(best[1])
'
}

output_active() {   # does the output currently have a CRTC/mode on the desktop?
	xrandr -q 2>/dev/null | awk -v o="$1" '$1==o { print ($3=="primary" ? $4 : $3) }' | grep -qE '^[0-9]+x[0-9]+\+'
}

# ---- JSON edits -------------------------------------------------------------------------
prep_vrpaths() {   # SteamVR runtime first
	python3 - "$VRPATHS" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
rt = d.get("runtime", [])
first = [r for r in rt if r.rstrip("/").endswith("/SteamVR")]
rest = [r for r in rt if r not in first]
if not first:
    sys.exit("no SteamVR entry in runtime[]")
d["runtime"] = first + rest
json.dump(d, open(p, "w"), indent="\t")
print("runtime[0] =", d["runtime"][0])
PY
}
prep_vrsettings() {   # driver_monado.enable=false
	python3 - "$VRSETTINGS" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d.setdefault("driver_monado", {})["enable"] = False
json.dump(d, open(p, "w"), indent=3)
print("driver_monado.enable =", d["driver_monado"]["enable"])
PY
}

# ---- Monado's OpenXR runtime json (docs/139 F6) -------------------------------------------------
# About 49 Steam titles carry LaunchOptions XR_RUNTIME_JSON=<MONADO_JSON>. Under SteamVR/Oasis that
# sends every OpenXR game (Unity OpenXR plugin: Superhot VR, ...) to Monado, which is not running
# ("XR_ERROR_RUNTIME_UNAVAILABLE", "Failed to connect to monado service process"). Rather than
# editing 49 launch options, the file they all point at is swapped for the run: 'up' saves the Monado
# original (only if no backup exists yet) and writes a SteamVR pointer, 'down' restores the original.
xr_json_kind() {   # prints STEAMVR | MONADO | OTHER | MISSING
	[ -f "$MONADO_JSON" ] || { echo MISSING; return; }
	if grep -q 'VALVE_runtime_is_steamvr\|vrclient\.so' "$MONADO_JSON"; then echo STEAMVR
	elif grep -q 'libopenxr_monado' "$MONADO_JSON"; then echo MONADO; else echo OTHER; fi
}
prep_xr_json() {
	local kind; kind=$(xr_json_kind)
	case "$kind" in
		MONADO)
			if [ ! -f "$MONADO_JSON_ORIG" ]; then
				cp -p "$MONADO_JSON" "$MONADO_JSON_ORIG" && echo "saved the Monado original to $MONADO_JSON_ORIG"
			elif ! cmp -s "$MONADO_JSON" "$MONADO_JSON_ORIG"; then
				echo "WARNING: $MONADO_JSON differs from the saved original; keeping the OLDER backup (delete it to refresh), 'down' will restore that one"
			fi ;;
		STEAMVR) echo "$MONADO_JSON already points at SteamVR (earlier swap or manual); original backup: $([ -f "$MONADO_JSON_ORIG" ] && echo present || echo MISSING)" ;;
		MISSING) echo "no $MONADO_JSON: nothing to swap"; return 0 ;;
		*) echo "WARNING: $MONADO_JSON is neither the Monado nor a SteamVR pointer; leaving it alone"; return 0 ;;
	esac
	[ -f "$MONADO_JSON_ORIG" ] || { echo "WARNING: no original backup, not swapping"; return 0; }
	cat > "$MONADO_JSON.tmp.$$" <<JSON
{
    "file_format_version": "1.0.0",
    "runtime": {
        "name": "SteamVR (temporary, Oasis session; Monado original saved in $MONADO_JSON_ORIG)",
        "VALVE_runtime_is_steamvr": true,
        "library_path": "$STEAMVR/bin/linux64/vrclient.so"
    }
}
JSON
	mv -f "$MONADO_JSON.tmp.$$" "$MONADO_JSON" && state_set XR_JSON_SWAPPED 1 && echo "$MONADO_JSON now points at SteamVR's vrclient.so (state recorded)"
}
restore_xr_json() {   # idempotent: also recovers after a 'down' that failed or a manual swap
	[ "$(xr_json_kind)" = STEAMVR ] || return 0
	if [ -f "$MONADO_JSON_ORIG" ]; then
		cp -p "$MONADO_JSON_ORIG" "$MONADO_JSON" && log "restored the Monado runtime json from $MONADO_JSON_ORIG"
	else
		log "WARNING: $MONADO_JSON points at SteamVR but $MONADO_JSON_ORIG is missing: restore it by hand"
	fi
}

# ---- controllers ------------------------------------------------------------------------
bt_ctrl_nodes() {
	local h n=0
	for h in /sys/class/hidraw/hidraw*; do
		grep -q 'HID_ID=0005:0000045E:0000066A' "$h/device/uevent" 2>/dev/null && n=$((n + 1))
	done
	echo "$n"
}
controller_preflight() {   # returns 0 ok, 2 none awake (nothing touched yet)
	command -v bluetoothctl >/dev/null 2>&1 || return 0
	local bonded n stable=0 spoke=0 i
	bonded=$(timeout 5 bluetoothctl devices Paired 2>/dev/null | grep -c 'Motion controller')
	[ "${bonded:-0}" -gt 0 ] || { log "no controllers bonded to the host adapter, skipping BT check"; return 0; }
	log "controller check: $bonded bonded, waiting up to ${BT_WAIT}s for them to be awake (LEDs steady)"
	n=0
	for i in $(seq 1 $((BT_WAIT * 2))); do
		n=$(bt_ctrl_nodes)
		if [ "$n" -ge "$bonded" ]; then stable=$((stable + 1)); else stable=0; fi
		[ "$stable" -ge 6 ] && break
		if [ "$spoke" = 0 ] && [ "$i" -ge 6 ] && command -v espeak-ng >/dev/null 2>&1; then
			spoke=1
			XDG_RUNTIME_DIR="/run/user/$(id -u)" espeak-ng -v es "Agita los joys para despertarlos" >/dev/null 2>&1 &
		fi
		sleep 0.5
	done
	if [ "$stable" -ge 6 ]; then log "  $n controller(s) awake"; return 0; fi
	if [ "$n" -gt 0 ]; then log "  WARNING: only $n of $bonded awake, continuing"; return 0; fi
	log "  no controller awake after ${BT_WAIT}s"
	return 2
}

# ---- process helpers -------------------------------------------------------------------
# Never pkill -f. A process is a VR process when its comm matches VR_COMMS, when its comm was
# renamed to "<pid>: vrstart" (vrserver does that while it waits for vrmonitor: it survived 'down'
# on 2026-10-03 and held the abstract sockets @/steamvr/*), or when its argv[0] (the binary it was
# started as, NOT any later word of the command line) lives under SteamVR/bin or the Oasis folder.
# A bash/ssh/tail whose command line merely mentions those paths is therefore never matched.
# Reads /proc with shell builtins only (no fork per process).
VR_COMMS='vrmonitor|vrserver|vrcompositor|vrcompositor-la|vrdashboard|vrwebhelper|vrstartup|vrcmd|ignition|oasis'
vr_pids() {
	local d p comm argv0
	for d in /proc/[0-9]*; do
		p=${d#/proc/}
		[ "$p" = "$$" ] && continue
		[ -O "$d" ] || continue
		comm=""; read -r comm < "$d/comm" 2>/dev/null || continue
		if [[ "$comm" =~ ^($VR_COMMS) ]] || [[ "$comm" =~ ^[0-9]+:\ vrstart ]]; then echo "$p"; continue; fi
		argv0=""; read -r -d '' argv0 < "$d/cmdline" 2>/dev/null
		case "$argv0" in "$STEAMVR"/bin/*|"$OASIS_DIR"/*) echo "$p" ;; esac
	done
}
wine_pids() {
	ps -u "$(id -u)" -o pid=,comm= | awk '$2 ~ /^(wineserver|wine64-preloader|wine-preloader|services\.exe|winedevice\.exe|explorer\.exe|plugplay\.exe|svchost\.exe|rpcss\.exe)$/ { print $1 }'
}
steam_running() { pgrep -u "$(id -u)" -x steam >/dev/null 2>&1; }

kill_all() {   # $1 = list command
	local p i
	for p in $($1); do kill -TERM "$p" 2>/dev/null; done
	for i in $(seq 1 15); do [ -z "$($1)" ] && return 0; sleep 1; done
	for p in $($1); do kill -KILL "$p" 2>/dev/null; done
	sleep 1
	[ -z "$($1)" ]
}

# ---- stale SteamVR sockets ---------------------------------------------------------------
# vrserver listens on abstract sockets @/steamvr/SteamVR_Namespace, VR_ServerPipe_<pid>, ... A
# second vrserver cannot bind while a stale one still owns them ("Unable to bind server socket
# errno=98"). Prints "<socket> <pid>" per listening socket owned by this user.
steamvr_sockets() {
	ss -xlpn 2>/dev/null | awk '$5 ~ /^@\/steamvr\// {
		pid = "?"; if (match($0, /pid=[0-9]+/)) pid = substr($0, RSTART + 4, RLENGTH - 4)
		print $5, pid }'
}

# ---- headset USB (the five devices of docs/22's known-good enumeration) ---------------------
G2_USB_IDS="04b4:6506 0bda:4c15 03f0:0580 04b4:6504 045e:0659"
usb_ids_present() {
	local d v p
	for d in /sys/bus/usb/devices/*; do
		[ -r "$d/idVendor" ] || continue
		read -r v < "$d/idVendor"; read -r p < "$d/idProduct"
		echo "$v:$p"
	done
}
g2_usb_count() {   # prints "<n> <missing ids...>"
	local have n=0 id miss=""
	have=" $(usb_ids_present | tr '\n' ' ') "
	for id in $G2_USB_IDS; do
		case "$have" in *" $id "*) n=$((n + 1)) ;; *) miss="$miss $id" ;; esac
	done
	echo "$n$miss"
}
hub_enumerations_since() {   # $1 epoch; prints "<count> <HH:MM:SS of the last one>"
	journalctl -k --since "@$1" --no-pager -o short-iso 2>/dev/null \
		| awk '/New USB device found, idVendor=04b4, idProduct=6506/ { n++; t = substr($1, 12, 8) } END { print n + 0, (t == "" ? "-" : t) }'
}

# ---- Oasis / SteamVR log scan (read-only) -----------------------------------------------------
# Counts the markers the verdict needs, using the TIMESTAMP on each log line (not the line
# number, not "whole file"): Steam's logs are appended across runs and, worse, ROTATED by size,
# and a stale Oasis HID handle writes ~2300 "Failed to get HID report" lines per second, which
# rotates vrserver.txt away within ~40 s and wipes the evidence of the run (2026-10-03). Prints
# S_<key>=<value> lines for eval. $1 = epoch lower bound (0 = everything still retained).
oasis_scan() {
	python3 - "$VRLOGS" "${1:-0}" <<'PY'
import os, re, sys, time
logs, t0 = sys.argv[1], float(sys.argv[2])
MON = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
cache = {}
def ts(line):
    k = line[4:24]                       # "Oct 03 2026 22:13:51"
    v = cache.get(k)
    if v is None:
        m = re.match(r"(\w{3}) +(\d+) (\d{4}) (\d\d):(\d\d):(\d\d)", k)
        try:
            v = time.mktime((int(m.group(3)), MON[m.group(1)], int(m.group(2)), int(m.group(4)),
                             int(m.group(5)), int(m.group(6)), 0, 0, -1)) if m else -1
        except (KeyError, ValueError):
            v = -1
        cache[k] = v
    return v
GROUPS = {
    "vrserver": (["vrserver.previous.txt", "vrserver.txt"], {
        "hmd_ok": ("Active HMD set to oasis",), "ctl_n": ("finished adding tracked device",),
        "hid": ("Failed to get HID report",), "anchor": ("Cannot locate root anchor",),
        "bind_err": ("Unable to bind server socket",), "safe": ("Not loading driver oasis because it was blocked by a previous safe mode",),
        "reg_to": ("Cannot register controller",)}),
    "vrstartup": (["vrstartup.txt"], {
        "hmd_nf": ("Hmd Not Found",), "bind_err": ("Unable to bind server socket",)}),
    "vrcompositor": (["vrcompositor.previous.txt", "vrcompositor.txt"], {
        "comp_acq": ("Acquired xlib display",), "comp_ok": ("Startup Complete",),
        "comp_err": ("CannotDRMLeaseDisplay", "Failed to acquire xlib display")}),
}
cnt = {}
for _, (_, ks) in GROUPS.items():
    for k in ks:
        cnt[k] = 0
hid_first = hid_last = 0
log_start = 0
for gname, (names, ks) in GROUPS.items():
    for name in names:
        try:
            f = open(os.path.join(logs, name), "r", errors="replace")
        except OSError:
            continue
        with f:
            first = True
            for line in f:
                if first:
                    first = False
                    if gname == "vrserver":
                        t = ts(line)
                        if t > 0 and (log_start == 0 or t < log_start):
                            log_start = t
                for k, needles in ks.items():
                    for nd in needles:
                        if nd in line:
                            if k == "ctl_n" and "Driver 'oasis'" not in line:
                                break
                            t = ts(line)
                            if t0 and t < t0:
                                break
                            cnt[k] += 1
                            if k == "hid":
                                hid_first = t if hid_first == 0 or t < hid_first else hid_first
                                hid_last = max(hid_last, t)
                            break
def hms(t):
    return time.strftime("%H:%M:%S", time.localtime(t)) if t else "-"
for k, v in cnt.items():
    print("S_%s=%d" % (k, v))
print("S_hid_first=%d\nS_hid_first_hms=%s\nS_hid_last=%d\nS_hid_last_hms=%s" % (hid_first, hms(hid_first), hid_last, hms(hid_last)))
print("S_log_start=%d\nS_log_start_hms=%s" % (log_start, hms(log_start)))
PY
}

# ---- "stale HID" diagnosis -------------------------------------------------------------------
# Signature (docs/139 F2): Oasis' vrserver keeps writing "oasis: Fatal error: HRESULT failure
# [80070005] ... Failed to get HID report" (thousands per minute) AFTER the headset hub re-enumerated
# on USB. The driver holds a dead HID handle and never reopens it; the HMD stays dead for the rest of
# that SteamVR session, and the next game says "waiting for VR device".
# Sets H_STATE = NONE | RECOVERED | HEADSET_ABSENT | USB_INCOMPLETE | STALE_HID | UNEXPLAINED
# and H_SINCE / H_NOTE. $1 = epoch lower bound (vrserver start, or the launch time of this run).
H_STATE=NONE; H_SINCE=""; H_NOTE=""
hid_diagnosis() {
	local t0=${1:-0} now usb nmiss reenum onset
	H_STATE=NONE; H_SINCE=""; H_NOTE=""
	eval "$(oasis_scan "$t0")"
	now=$(date +%s)
	[ "${S_hid:-0}" -ge 50 ] || return 0
	H_SINCE="$S_hid_first_hms"
	if [ "$S_hid_last" -gt 0 ] && [ $((now - S_hid_last)) -gt 120 ]; then
		H_STATE=RECOVERED
		H_NOTE="HID errors between $S_hid_first_hms and $S_hid_last_hms ($S_hid lines), quiet since"
		return 0
	fi
	onset=$(state_get HID_ONSET)
	[ -n "$onset" ] && [ "$onset" -gt 0 ] && H_SINCE=$(date -d "@$onset" +%H:%M:%S)
	# The retained window is short on purpose (the spam, ~2300 lines/s, rotates it away): persistent
	# means >= 20 s of continuous errors in the window, or >= 20000 retained error lines (about 9 s of
	# spam: a transient HID hiccup produces a few hundred, not tens of thousands), or a recorded onset
	# >= 30 s ago
	if [ $((S_hid_last - S_hid_first)) -lt 20 ] && [ "$S_hid" -lt 20000 ] && { [ -z "$onset" ] || [ $((now - onset)) -lt 30 ]; }; then
		H_STATE=NONE; H_NOTE="HID errors just started ($S_hid lines), not yet persistent"; return 0
	fi
	usb=$(g2_usb_count); nmiss=${usb%% *}
	if ! usb_ids_present | grep -qx '04b4:6506'; then
		H_STATE=HEADSET_ABSENT; H_NOTE="headset USB hub (04b4:6506) is not on the bus: unplugged or its USB branch is down"; return 0
	fi
	reenum=$(hub_enumerations_since "$t0")
	if [ "${reenum%% *}" -ge 1 ]; then
		# the real onset is the hub bounce, the first RETAINED error line is later (log rotation)
		[ "$(echo "$reenum" | cut -d' ' -f2)" \< "$S_hid_first_hms" ] && H_SINCE=$(echo "$reenum" | cut -d' ' -f2)
		H_STATE=STALE_HID
		H_NOTE="headset hub re-enumerated ${reenum%% *}x since this SteamVR run started (last $(echo "$reenum" | cut -d' ' -f2)); Oasis still holds the old HID handle ($S_hid errors, root-anchor lines $S_anchor)"
	else
		H_STATE=UNEXPLAINED
		H_NOTE="HID errors persist ($S_hid) but no hub re-enumeration was found in the kernel log since the run started"
	fi
	[ "$nmiss" -lt 5 ] && H_NOTE="$H_NOTE; USB devices present $nmiss/5 (missing${usb#"$nmiss"})"
	return 0
}

# ---- recovery budget (docs/22 stop rule: at most 2 recovery cycles per hour) --------------------
RECOVERY_LOG="$VR_DIR/oasis-x11-recoveries"
RECOVERY_MAX="${OASIS_RECOVERY_MAX:-2}"
recoveries_last_hour() {
	[ -f "$RECOVERY_LOG" ] || { echo 0; return; }
	awk -v lim="$(( $(date +%s) - 3600 ))" '$1 + 0 >= lim { n++ } END { print n + 0 }' "$RECOVERY_LOG"
}

# ---- preflight (read-only) -----------------------------------------------------------------------
# One line per check: [ OK ] / [WARN] / [FAIL] / [INFO]. PF_FAIL counts the ones that make 'up' abort.
PF_FAIL=0; PF_WARN=0
pf() { # level name message
	case "$1" in FAIL) PF_FAIL=$((PF_FAIL + 1)); printf '  [FAIL] %s: %s\n' "$2" "$3" ;;
		WARN) PF_WARN=$((PF_WARN + 1)); printf '  [WARN] %s: %s\n' "$2" "$3" ;;
		OK) printf '  [ OK ] %s: %s\n' "$2" "$3" ;;
		*) printf '  [INFO] %s: %s\n' "$2" "$3" ;; esac
}
do_preflight() {
	PF_FAIL=0; PF_WARN=0
	local cap n sock own use libs l miss fsout
	# 1 capability on the compositor launcher (lost on every SteamVR update)
	if ! command -v getcap >/dev/null 2>&1 && ! PATH="$PATH:/usr/sbin:/sbin" command -v getcap >/dev/null 2>&1; then
		pf FAIL getcap "not found even with /usr/sbin in PATH; SteamVR's vrsetup.sh dies with 'getcap is required' when Steam is started from ssh"
	else
		cap=$(PATH="$PATH:/usr/sbin:/sbin" getcap "$STEAMVR/bin/linux64/vrcompositor-launcher" 2>/dev/null)
		case "$cap" in *cap_sys_nice*) pf OK cap_sys_nice "present on vrcompositor-launcher" ;;
			*) pf WARN cap_sys_nice "missing on vrcompositor-launcher (a SteamVR update replaces the file): SteamVR will show a superuser popup. Manual fix: sudo setcap CAP_SYS_NICE=eip '$STEAMVR/bin/linux64/vrcompositor-launcher'" ;; esac
	fi
	# 2 safe-mode block
	if [ "$(python3 -c "import json;print(json.load(open('$VRSETTINGS')).get('driver_oasis',{}).get('blocked_by_safe_mode',False))" 2>/dev/null)" = True ]; then
		pf FAIL safe_mode "driver_oasis.blocked_by_safe_mode is true in steamvr.vrsettings: SteamVR will not load Oasis (no HMD). Fix with Steam fully closed and no pending 'down': set it to false (docs/138)"
	else
		pf OK safe_mode "driver_oasis is not blocked"
	fi
	# 3 runtime order
	use=$(python3 -c "import json;print(json.load(open('$VRPATHS'))['runtime'][0])" 2>/dev/null)
	case "$use" in */SteamVR) pf OK openvrpaths "runtime[0] is SteamVR" ;;
		*) pf INFO openvrpaths "runtime[0] is ${use:-?}, 'up' will put SteamVR first for the run and 'down' restores the original" ;; esac
	# 4 kiosk vs test settings
	python3 - "$VRSETTINGS" <<'PY' | while IFS= read -r l; do pf INFO vrsettings "$l"; done
import json, sys
d = json.load(open(sys.argv[1]))
db, sv = d.get("dashboard", {}), d.get("steamvr", {})
mode = "KIOSK (dashboard.arcadeMode on)" if db.get("arcadeMode") else "TEST/NORMAL (dashboard on)"
print("%s, steamvr.loglevel=%s%s" % (mode, sv.get("loglevel", "default"),
      " (verbose: logs rotate fast)" if str(sv.get("loglevel", 0)) not in ("0", "1", "2", "3") else ""))
PY
	# 5 monado
	[ -n "$(pgrep -x monado-service)" ] && pf FAIL monado "monado-service is running (pid $(pgrep -x monado-service | tr '\n' ' ')); stop it (not touched by this script)" || pf OK monado "no monado-service"
	# 6 stale sockets
	sock=$(steamvr_sockets)
	if [ -z "$sock" ]; then pf OK sockets "no @/steamvr/* listening socket"
	elif [ -z "$(vr_pids)" ]; then
		pf FAIL sockets "stale @/steamvr/* sockets with no VR process in the list: $(echo "$sock" | tr '\n' ';') a leftover vrserver blocks the next one ('Unable to bind server socket errno=98'); 'down' stops the owner by PID"
	else pf INFO sockets "$(echo "$sock" | wc -l) steamvr socket(s) owned by the running session"; fi
	# 7 libraries mounted + 8 disk
	miss=""
	for l in $( { sed -n 's/^[[:space:]]*"path"[[:space:]]*"\(.*\)"/\1/p' "$STEAM_ROOT/steamapps/libraryfolders.vdf" 2>/dev/null; } ); do
		[ -d "$l/steamapps" ] || miss="$miss $l"
	done
	[ -z "$miss" ] && pf OK libraries "all Steam libraries are present" || pf FAIL libraries "missing/unmounted:$miss"
	use=$(df -P / | awk 'NR==2{gsub("%","",$5); print $5}')
	if [ "$use" -ge 97 ]; then pf FAIL disk "/ is ${use}% full"
	elif [ "$use" -ge 90 ]; then pf WARN disk "/ is ${use}% full (rule: keep ~80%)"
	else pf OK disk "/ is ${use}% full"; fi
	# 9 headset USB
	n=$(g2_usb_count)
	if [ "${n%% *}" -ge 5 ]; then pf OK headset_usb "5/5 devices enumerated"
	else pf "$([ "${OASIS_SKIP_USB_CHECK:-0}" = 1 ] && echo WARN || echo FAIL)" headset_usb "${n%% *}/5 devices (missing${n#"${n%% *}"}): do not start SteamVR; PC-end USB-C unplug/replug first (docs/22). OASIS_SKIP_USB_CHECK=1 overrides"; fi
	# 9b OpenXR json
	case "$(xr_json_kind)" in
		MONADO) pf OK xr_json "Monado runtime json is the Monado original ('up' will swap it for the run and 'down' restore it)" ;;
		STEAMVR) [ -f "$MONADO_JSON_ORIG" ] && pf INFO xr_json "already pointing at SteamVR; original saved" || pf WARN xr_json "points at SteamVR and NO original backup exists at $MONADO_JSON_ORIG" ;;
		OTHER) pf WARN xr_json "$MONADO_JSON is neither Monado's nor a SteamVR pointer" ;;
		*) pf INFO xr_json "no $MONADO_JSON" ;;
	esac
	# 10 NTFS prefixes
	if [ -x "$(dirname "$0")/steam-prefix-guard.sh" ]; then
		fsout=$("$(dirname "$0")/steam-prefix-guard.sh" check 2>&1)
		if [ $? -eq 0 ]; then pf OK prefixes "no Proton prefix on an NTFS library"
		else pf WARN prefixes "$(echo "$fsout" | grep -c '^PROBLEM') Proton prefix problem(s) on NTFS libraries: new prefixes there die with Errno 22 ('../drive_c'); run steam-prefix-guard.sh fix"; fi
	fi
	return "$PF_FAIL"
}

# ---- status -----------------------------------------------------------------------------
do_status() {
	find_session_env || echo "no X11 session env found"
	echo "session: DISPLAY=${DISPLAY:-?} type=${XDG_SESSION_TYPE:-?} desktop=${XDG_CURRENT_DESKTOP:-?}"
	local o; o="${HMD_OUTPUT:-$(find_hmd_output)}"
	echo "G2 output: ${o:-<not found>}  $( [ -n "$o" ] && { output_active "$o" && echo '(ON the desktop)' || echo '(not on the desktop)'; } )"
	echo "steam: $(steam_running && echo running || echo stopped)"
	echo "vr/oasis/wine pids: $(vr_pids | tr '\n' ' ') | wine: $(wine_pids | tr '\n' ' ')"
	echo "monado-service: $(pgrep -x monado-service | tr '\n' ' ')"
	echo "controllers awake (hidraw 045E:066A): $(bt_ctrl_nodes)"
	echo "runtime[0]: $(python3 -c "import json;print(json.load(open('$VRPATHS'))['runtime'][0])" 2>/dev/null)"
	echo "Monado OpenXR json ($MONADO_JSON): $(xr_json_kind)$([ "$(xr_json_kind)" = STEAMVR ] && [ -z "$(vr_pids)" ] && echo ' (SteamVR pointer left in place with no session running: run down, or restore the saved original)')"
	echo "driver_monado.enable: $(python3 -c "import json;print(json.load(open('$VRSETTINGS')).get('driver_monado',{}).get('enable'))" 2>/dev/null)"
	if [ -f "$STATE" ]; then echo "state file ($STATE):"; sed 's/^/  /' "$STATE"; else echo "no state file (no run pending 'down')"; fi
	[ -f "$VRLOGS/vrserver.txt" ] && {
		grep -a -E "Active HMD set|finished adding tracked device" "$VRLOGS/vrserver.txt" | tail -5 | cut -c1-200 | sed 's/^/  vrserver: /'
		grep -a -c CannotDRMLease "$VRLOGS/vrcompositor.txt" 2>/dev/null | sed 's/^/  CannotDRMLease lines in vrcompositor.txt: /'
	}
	local sock; sock=$(steamvr_sockets)
	if [ -n "$sock" ]; then echo "steamvr abstract sockets: $(echo "$sock" | wc -l) listening ($(echo "$sock" | tr '\n' ';'))"; else echo "steamvr abstract sockets: none"; fi
	[ -n "$sock" ] && [ -z "$(vr_pids)" ] && echo "  STALE: sockets are held but no VR process is listed; a new vrserver would fail with 'Unable to bind server socket errno=98'"
	echo "preflight:"; do_preflight || true
	local vp t0=0 et
	vp=$(vrserver_pid)
	if [ -n "$vp" ]; then
		et=$(ps -o etimes= -p "$vp" 2>/dev/null | tr -d ' '); t0=$(( $(date +%s) - ${et:-0} ))
		echo "vrserver pid $vp up since $(date -d "@$t0" +%H:%M:%S)"
	else echo "vrserver: not running (log findings below, if any, are from an earlier run)"; fi
	hid_diagnosis "$t0"
	case "$H_STATE" in
		STALE_HID) echo "HMD driver broken (stale HID) since ${H_SINCE:-?}: $H_NOTE"
			echo "  -> recovery: '$0 watchdog' to confirm, then ONE '$0 down' + '$0 up' (or 'watchdog --auto'); if the USB check fails, PC-end USB-C unplug/replug first" ;;
		HEADSET_ABSENT) echo "HMD driver: HID errors since ${H_SINCE:-?} but the headset is not on the USB bus: $H_NOTE" ;;
		UNEXPLAINED) echo "HMD driver: HID errors since ${H_SINCE:-?} without a hub re-enumeration: $H_NOTE" ;;
		RECOVERED) echo "HMD driver: transient HID errors, recovered ($H_NOTE)" ;;
		*) echo "HMD driver: no stale-HID signature${H_NOTE:+ ($H_NOTE)}" ;;
	esac
	echo "auto-recoveries in the last hour: $(recoveries_last_hour)/$RECOVERY_MAX"
	[ "${S_log_start:-0}" -gt 0 ] && echo "oldest retained vrserver log line: ${S_log_start_hms:-?} (Steam rotates these logs by size)"
}

vrserver_pid() {   # pid of the running vrserver, also when it renamed its comm to "<pid>: vrstart"
	local p c
	for p in $(vr_pids); do
		read -r c < "/proc/$p/comm" 2>/dev/null || continue
		case "$c" in vrserver|[0-9]*": vrstart"*) echo "$p"; return 0 ;; esac
	done
	return 0
}

# ---- down -------------------------------------------------------------------------------
do_down() {
	find_session_env || log "WARNING: no X11 session env, display steps skipped"
	log "=== down ==="
	local started_steam bk hmd kscreen_parked
	started_steam=$(state_get STARTED_STEAM); bk=$(state_get BACKUP_DIR); hmd=$(state_get HMD_OUTPUT)
	kscreen_parked=$(state_get KSCREEN_PARKED)

	local gp; gp=$(state_get GUARD_PID)
	if [ -n "$gp" ] && [ -r "/proc/$gp/cmdline" ] && tr '\0' ' ' < "/proc/$gp/cmdline" | grep -q 'jack-in-oasis-x11'; then
		kill "$gp" 2>/dev/null && log "stopped the panel guard (pid $gp)"
	fi
	log "stopping SteamVR / vrserver / vrcompositor / Ignition..."
	# Ask vrmonitor first: it shuts vrserver down cleanly.
	for p in $(ps -u "$(id -u)" -o pid=,comm= | awk '$2=="vrmonitor"{print $1}'); do kill -TERM "$p" 2>/dev/null; done
	sleep 3
	kill_all vr_pids || log "  WARNING: some VR processes survived SIGKILL: $(vr_pids | tr '\n' ' ')"
	kill_all wine_pids || log "  WARNING: wine processes survived: $(wine_pids | tr '\n' ' ')"
	# Assertion (docs/139 F3): no @/steamvr/* listener may outlive 'down'. A vrserver that renamed its
	# comm once kept them and made the next vrserver fail with "Unable to bind server socket errno=98".
	local owners t
	for t in 1 2 3 4 5; do [ -z "$(steamvr_sockets)" ] && break; sleep 1; done
	if [ -n "$(steamvr_sockets)" ]; then
		owners=$(steamvr_sockets | awk '$2 ~ /^[0-9]+$/ { print $2 }' | sort -u)
		log "WARNING: @/steamvr sockets still listening, owner pid(s): ${owners:-unknown}; stopping the owners by PID"
		for t in $owners; do log "  pid $t comm=$(cat "/proc/$t/comm" 2>/dev/null)"; kill -TERM "$t" 2>/dev/null; done
		sleep 3
		for t in $owners; do kill -0 "$t" 2>/dev/null && kill -KILL "$t" 2>/dev/null; done
		sleep 1
	fi
	if [ -z "$(steamvr_sockets)" ]; then log "assertion ok: no @/steamvr/* socket left"
	else log "ASSERTION FAILED: @/steamvr sockets still held: $(steamvr_sockets | tr '\n' ';') (see docs/139 F3)"; DOWN_RC=5; fi

	if [ "$started_steam" = 1 ] && steam_running; then
		log "shutting down Steam (this script started it)..."
		steam -shutdown >/dev/null 2>&1 < /dev/null &
		for _ in $(seq 1 40); do steam_running || break; sleep 1; done
		steam_running && log "  WARNING: Steam still running after 40s (left alone)"
	fi

	if [ -n "$bk" ] && [ -f "$bk/openvrpaths.vrpath" ]; then
		cp -p "$bk/openvrpaths.vrpath" "$VRPATHS" && log "restored openvrpaths.vrpath from $bk"
	fi
	if [ -n "$bk" ] && [ -f "$bk/steamvr.vrsettings" ]; then
		cp -p "$bk/steamvr.vrsettings" "$VRSETTINGS" && log "restored steamvr.vrsettings from $bk"
	fi

	restore_xr_json

	if [ "$kscreen_parked" = 1 ]; then
		qdbus6 org.kde.kded6 /kded org.kde.kded6.loadModule kscreen >/dev/null 2>&1 \
			&& log "kscreen kded module loaded again"
	fi
	log "G2 output ${hmd:-?} left OFF the desktop on purpose (set RESTORE_DESKTOP_OUTPUT=1 to re-enable it)."
	if [ "${RESTORE_DESKTOP_OUTPUT:-0}" = 1 ] && [ -n "$hmd" ]; then
		if command -v kscreen-doctor >/dev/null 2>&1 && [ "${XDG_CURRENT_DESKTOP:-}" = KDE ]; then
			kscreen-doctor "output.$hmd.enable" >/dev/null 2>&1
		else
			xrandr --output "$hmd" --auto
		fi
	fi
	rm -f "$STATE"
	log "down complete. leftovers: vr=[$(vr_pids | tr '\n' ' ')] wine=[$(wine_pids | tr '\n' ' ')] steam=$(steam_running && echo up || echo stopped) sockets=[$(steamvr_sockets | tr '\n' ' ')]"
	return "${DOWN_RC:-0}"
}

# ---- up ---------------------------------------------------------------------------------
do_up() {
	log "=== up (one launch attempt) ==="
	[ -f "$STATE" ] && die "state file $STATE exists: a previous run was not torn down. Run '$0 down' first (one attempt per cycle on purpose)." 3
	find_session_env || die "no X11 session env found (is an X11 session logged in on this seat?)"
	[ "${XDG_SESSION_TYPE:-}" = x11 ] || log "WARNING: XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unset}, expected x11"
	log "session: DISPLAY=$DISPLAY desktop=${XDG_CURRENT_DESKTOP:-?}"
	[ -n "$(pgrep -x monado-service)" ] && die "monado-service is running; stop it first (not touched by this script)"
	[ -n "$(vr_pids)" ] && die "SteamVR/Oasis processes already running: $(vr_pids | tr '\n' ' ')"
	[ -f "$OASIS_DIR/bin/linux64/driver_oasis.so" ] || die "Oasis driver_oasis.so missing under $OASIS_DIR (update pending?)"
	grep -qF "$OASIS_DIR" "$VRPATHS" || die "Oasis dir is not in external_drivers of $VRPATHS"
	[ -x "$STEAMVR/bin/linux64/vrserver" ] || die "SteamVR not installed at $STEAMVR"
	export PATH="$PATH:/usr/sbin:/sbin"
	local pfout pfrc
	pfout=$(do_preflight); pfrc=$?
	log "preflight:"; printf '%s\n' "$pfout" | tee -a "$LOG"
	[ "$pfrc" -gt 0 ] && die "preflight found $pfrc blocking problem(s) (see above); nothing was changed" 4
	# Proton prefixes must not live on the NTFS libraries (docs/139 F5): move any that appeared and pre-create
	# ext4-backed ones for installed apps that have none yet, so a game's first launch works. OASIS_PREFIX_AUTOFIX=0 disables.
	if [ "${OASIS_PREFIX_AUTOFIX:-1}" = 1 ] && [ -x "$(dirname "$0")/steam-prefix-guard.sh" ]; then
		log "prefix guard: relocating/pre-seeding Proton prefixes off the NTFS libraries"
		"$(dirname "$0")/steam-prefix-guard.sh" fix --apply 2>&1 | sed 's/^/  /' | tee -a "$LOG"
		"$(dirname "$0")/steam-prefix-guard.sh" preseed --apply 2>&1 | sed 's/^/  /' | tee -a "$LOG"
	fi

	[ -z "$HMD_OUTPUT" ] && HMD_OUTPUT=$(find_hmd_output)
	if [ -n "$HMD_OUTPUT" ]; then
		echo "$HMD_OUTPUT" > "$VR_DIR/oasis-x11.hmd"
	elif [ -s "$VR_DIR/oasis-x11.hmd" ]; then
		# An asleep panel shows up as "disconnected": use the name remembered from the last run.
		HMD_OUTPUT=$(cat "$VR_DIR/oasis-x11.hmd")
		log "G2 output not connected right now (panel asleep); using remembered name $HMD_OUTPUT"
	else
		die "could not find the G2's output in xrandr (is the headset connected and awake? no remembered name yet)"
	fi
	log "G2 output: $HMD_OUTPUT (on desktop now: $(output_active "$HMD_OUTPUT" && echo yes || echo no))"

	controller_preflight; case $? in 2) die "no controller awake; nothing was changed. Shake the joys and retry." 2 ;; esac

	# ---- point of no return: from here on the state file exists and 'down' must be run ----
	local ts bk; ts=$(date +%Y%m%d-%H%M%S); bk="$BACKUP_DIR/$ts"; mkdir -p "$bk"
	cp -p "$VRPATHS" "$bk/openvrpaths.vrpath" && cp -p "$VRSETTINGS" "$bk/steamvr.vrsettings" \
		|| die "backup failed"
	: > "$STATE"
	state_set BACKUP_DIR "$bk"; state_set HMD_OUTPUT "$HMD_OUTPUT"; state_set STARTED_AT "$ts"; state_set STARTED_EPOCH "$(date +%s)"
	log "backups in $bk"
	prep_vrpaths | sed 's/^/  /' | tee -a "$LOG"
	prep_vrsettings | sed 's/^/  /' | tee -a "$LOG"
	prep_xr_json | sed 's/^/  /' | tee -a "$LOG"

	# ---- free the panel -----------------------------------------------------------------
	if [ "${XDG_CURRENT_DESKTOP:-}" = KDE ] && command -v kscreen-doctor >/dev/null 2>&1; then
		log "freeing $HMD_OUTPUT via kscreen-doctor (persists in KDE's screen config)"
		kscreen-doctor "output.$HMD_OUTPUT.disable" >> "$LOG" 2>&1
		# park KScreen so it cannot re-enable the output when the headset re-announces itself
		if qdbus6 org.kde.kded6 /kded org.kde.kded6.unloadModule kscreen >/dev/null 2>&1; then
			state_set KSCREEN_PARKED 1; log "kscreen kded module parked for the run"
		fi
	fi
	output_active "$HMD_OUTPUT" && { log "  still active, falling back to xrandr --off"; xrandr --output "$HMD_OUTPUT" --off; }
	log "waiting 8 s for the CRTC teardown (vkAcquireXlibDisplayEXT races it otherwise)"
	sleep 8
	if output_active "$HMD_OUTPUT"; then
		log "WARNING: $HMD_OUTPUT is still on the desktop; direct mode will probably fail"
	else
		log "$HMD_OUTPUT is off the desktop. xrandr: $(xrandr -q | grep -E "^$HMD_OUTPUT " )"
	fi

	# ---- Steam + SteamVR -------------------------------------------------------------------
	if steam_running; then
		if tr '\0' '\n' < "/proc/$(pgrep -u "$(id -u)" -xo steam)/environ" 2>/dev/null | grep '^PATH=' | grep -q '/usr/sbin'; then
			log "Steam already running with /usr/sbin in PATH"
		else
			log "WARNING: running Steam lacks /usr/sbin in PATH: SteamVR may show the 'getcap is required' popup"
		fi
		state_set STARTED_STEAM 0
	else
		log "starting Steam (-silent) with PATH+GUI env"
		( setsid nohup steam -silent >> "$VR_DIR/oasis-x11-steam.log" 2>&1 < /dev/null & disown )
		state_set STARTED_STEAM 1
		for _ in $(seq 1 90); do
			pgrep -u "$(id -u)" -x steamwebhelper >/dev/null && [ -e "$HOME/.steam/steam.pipe" ] && break
			sleep 1
		done
		sleep 8
		steam_running || die "Steam did not come up (see $VR_DIR/oasis-x11-steam.log); run 'down'"
	fi

	# Panel guard (UNTESTED, added after the first measured attempt): Oasis wakes the panel when
	# the driver starts, the output reappears, and the desktop re-enables it ~3 s BEFORE the
	# compositor probes (Xorg log: DP-0 modeset at 19:32:24, compositor RandR probe 19:32:27,
	# "Failed to acquire xlib display"). The guard re-frees it each time that happens until the
	# watch ends. OASIS_PANEL_GUARD=0 disables it.
	GUARD_PID=""
	if [ "${OASIS_PANEL_GUARD:-1}" = 1 ]; then
		# The guard also ends by itself when 'down' removed the state file. It is killed when the
		# watch ends unless OASIS_GUARD_PERSIST=1 (then 'down' stops it by the PID in the state file):
		# tonight's 14 runs showed it firing once (19:38:12, the panel's first wake) and the output
		# was never back on the desktop at the next 'up', so persistence stays opt-in (docs/139 F4).
		(
			local_sleep=0.3; [ "${OASIS_GUARD_PERSIST:-0}" = 1 ] && local_sleep=1
			while [ -f "$STATE" ]; do
				if output_active "$HMD_OUTPUT"; then
					echo "$(date '+%F %T')   guard: $HMD_OUTPUT came back on the desktop, freeing it again" >> "$LOG"
					xrandr --output "$HMD_OUTPUT" --off >> "$LOG" 2>&1
				fi
				sleep "$local_sleep"
			done
		) &
		GUARD_PID=$!
		state_set GUARD_PID "$GUARD_PID"
		log "panel guard running (pid $GUARD_PID, $([ "${OASIS_GUARD_PERSIST:-0}" = 1 ] && echo 'persists until down' || echo 'stops when the watch ends'))"
	fi
	local t0; t0=$(date +%s)
	state_set LAUNCH_EPOCH "$t0"
	log "launching SteamVR: steam steam://run/250820"
	setsid nohup steam steam://run/250820 >> "$VR_DIR/oasis-x11-steam.log" 2>&1 < /dev/null & disown

	# ---- watch (one pass, no retries) ----------------------------------------------------
	# Evidence is counted from log lines TIMESTAMPED after this launch (oasis_scan): the SteamVR logs
	# are appended across runs and rotated by size. The flags are sticky: once something was seen it
	# stays seen, because a stale-HID spam rotates the very lines that proved it (docs/139 F4).
	local i res=PENDING cause="" hmd_ok=0 ctl_n=0 comp_ok=0 comp_acq=0 comp_err=0 bind_err=0 safe=0 hmd_nf=0
	local want_ctl="${OASIS_EXPECT_TRACKED:-3}" onset_set=0
	for i in $(seq 1 "$WATCH_SECONDS"); do
		sleep 1
		[ -f "$VRLOGS/vrserver.txt" ] && [ "$(stat -c %Y "$VRLOGS/vrserver.txt")" -ge "$t0" ] || continue
		eval "$(oasis_scan "$t0")"
		[ "$S_hmd_ok" -gt "$hmd_ok" ] && hmd_ok=$S_hmd_ok
		[ "$S_ctl_n" -gt "$ctl_n" ] && ctl_n=$S_ctl_n
		[ "$S_comp_ok" -gt "$comp_ok" ] && comp_ok=$S_comp_ok
		[ "$S_comp_acq" -gt "$comp_acq" ] && comp_acq=$S_comp_acq
		[ "$S_comp_err" -gt "$comp_err" ] && comp_err=$S_comp_err
		[ "$S_bind_err" -gt "$bind_err" ] && bind_err=$S_bind_err
		[ "$S_safe" -gt "$safe" ] && safe=$S_safe
		[ "$S_hmd_nf" -gt "$hmd_nf" ] && hmd_nf=$S_hmd_nf
		if [ "$S_hid" -ge 50 ] && [ "$onset_set" = 0 ]; then state_set HID_ONSET "$S_hid_first"; onset_set=1; fi
		if [ "$hmd_ok" -ge 1 ] && [ "$ctl_n" -ge "$want_ctl" ] && [ "$comp_acq" -ge 1 ] && [ "$comp_ok" -ge 1 ]; then res=OK; break; fi
		# fail fast on conditions that cannot heal by waiting
		[ "$bind_err" -gt 0 ] && break
		[ "$safe" -gt 0 ] && break
		[ "$S_hid" -ge 2000 ] && [ "$S_hid_last" -gt 0 ] && [ $((S_hid_last - S_hid_first)) -ge 20 ] && break
		[ $((i % 15)) = 0 ] && log "  t+${i}s: active-hmd=$hmd_ok tracked-devices=$ctl_n compositor=$([ "$comp_ok" -ge 1 ] && echo up || { [ "$comp_err" -gt 0 ] && echo errors || echo pending; }) hid-errors=$S_hid"
	done
	if [ -n "$GUARD_PID" ] && [ "${OASIS_GUARD_PERSIST:-0}" != 1 ]; then kill "$GUARD_PID" 2>/dev/null; state_set GUARD_PID ""; fi
	local cause_note=""
	if [ "$res" != OK ]; then
		hid_diagnosis "$t0"
		if [ "$bind_err" -gt 0 ]; then
			res=STALE_SOCKET; cause="a previous vrserver still owns the @/steamvr sockets (errno=98): 'down' (it stops socket owners by PID), then 'up' once"
		elif [ "$safe" -gt 0 ]; then
			res=SAFE_MODE; cause="SteamVR blocked the Oasis driver after an abrupt end (blocked_by_safe_mode); set it to false in steamvr.vrsettings with Steam closed (docs/138)"
		elif [ "$H_STATE" = STALE_HID ]; then
			res=STALE_HID; cause="HMD driver broken (stale HID) since ${H_SINCE:-?}: $H_NOTE. Fix: down, check USB 5/5 (PC-end USB-C replug if not), then one up"
		elif [ "$H_STATE" = HEADSET_ABSENT ]; then
			res=HMD_MISSING; cause="$H_NOTE"
		elif [ "$hmd_ok" -lt 1 ]; then
			res=HMD_MISSING; cause="Oasis never selected the headset in $i s${hmd_nf:+ (SteamVR said 'Hmd Not Found' $hmd_nf x)}; check headset USB 5/5, the brick, the safe-mode flag"
		elif [ "$comp_err" -gt 0 ] && [ "$comp_ok" -lt 1 ]; then
			res=COMPOSITOR_FAILED; cause="the compositor could not take the panel (DRM lease/xlib display): is $HMD_OUTPUT back on the desktop? (xrandr below)"
		elif [ "$comp_ok" -lt 1 ]; then
			res=COMPOSITOR_PENDING; cause="HMD found but the compositor had not finished starting after $i s"
		elif [ "$ctl_n" -lt "$want_ctl" ]; then
			res=CONTROLLERS_MISSING; cause="SteamVR, HMD and compositor are healthy; only $((ctl_n > 0 ? ctl_n - 1 : 0)) controller(s) registered (asleep or out of range?). Touch/shake them, Oasis registers them by itself; no restart needed"
		else
			res=TIMEOUT; cause="no known failure signature matched; read the markers below"
		fi
	fi
	log "--- result: $res (t+${i}s) ---"
	[ -n "$cause" ] && log "cause: $cause"
	{
		echo "vrserver.txt markers:"; grep -a -E "Active HMD set|finished adding tracked device|Cannot register controller|Unable to load driver|safe mode|Unable to bind" "$VRLOGS/vrserver.txt" | cut -c1-200 | tail -12
		echo "vrcompositor.txt markers:"; grep -a -E "direct display|Direct mode|direct mode|Selected mode|Failed to|CannotDRM|VRInitError" "$VRLOGS/vrcompositor.txt" | cut -c1-200 | tail -12
	} 2>/dev/null | sed 's/^/  /' | tee -a "$LOG"
	log "xrandr after launch: $(xrandr -q | grep -E "^$HMD_OUTPUT " )"

	if [ "$res" = OK ] || [ "$res" = CONTROLLERS_MISSING ]; then
		log "sampling poses for 8 s (move the joys)"
		command -v espeak-ng >/dev/null && XDG_RUNTIME_DIR="/run/user/$(id -u)" espeak-ng -v es "Mueve los joys" >/dev/null 2>&1 &
		( cd "$STEAMVR" && LD_LIBRARY_PATH=bin/linux64:bin/linux64/qt/lib timeout 8 bin/linux64/vrcmd --pollposes 2>/dev/null ) \
			| awk -F, 'NF>=7 { n[$1]++; if (!(($0) in seen)) { seen[$0]=1; d[$1]++ } } END { for (k in n) printf "  pollposes %-28s samples=%d distinct=%d\n", k, n[k], d[k] }' | tee -a "$LOG"
	fi
	log "attempt finished: $res. Run '$0 down' to tear down and restore the backups."
	case "$res" in OK) return 0 ;; CONTROLLERS_MISSING) return 4 ;; *) return 1 ;; esac
}

# ---- watchdog -------------------------------------------------------------------------------
# watchdog            report only: is the running SteamVR session stale-HID broken? (exit 0 healthy / nothing
#                     running, 10 stale HID, 11 headset absent/USB incomplete, 12 HID errors unexplained)
# watchdog --dry-run  with --auto: print what it would do, change nothing
# watchdog --auto     on stale HID: ONE 'down' + 'up', only if the headset's 5 USB devices are present and fewer
#                     than OASIS_RECOVERY_MAX (2) recoveries happened in the last hour (docs/22 stop rule:
#                     every activation cycle can loosen the marginal visor-end contact). Otherwise it stops and
#                     tells you to reseat the cable. Never loops: invoke it again if you want another check.
do_watchdog() {
	local auto=0 dry=0 a vp t0=0 et n usb rc
	for a in "$@"; do
		case "$a" in --auto) auto=1 ;; --dry-run) dry=1 ;; *) echo "usage: $(basename "$0") watchdog [--auto] [--dry-run]" >&2; return 2 ;; esac
	done
	vp=$(vrserver_pid)
	if [ -z "$vp" ]; then echo "watchdog: no vrserver running, nothing to check or recover"; return 0; fi
	et=$(ps -o etimes= -p "$vp" 2>/dev/null | tr -d ' '); t0=$(( $(date +%s) - ${et:-0} ))
	hid_diagnosis "$t0"
	echo "watchdog: vrserver pid $vp (up since $(date -d "@$t0" +%H:%M:%S)), state=$H_STATE${H_SINCE:+, since $H_SINCE}"
	[ -n "$H_NOTE" ] && echo "  $H_NOTE"
	case "$H_STATE" in
		NONE|RECOVERED) echo "  healthy: no stale-HID signature"; return 0 ;;
		HEADSET_ABSENT) echo "  headset not on the USB bus: replug it (PC-end USB-C first, docs/22), then restart the session once"; return 11 ;;
		UNEXPLAINED) echo "  HID errors without a hub re-enumeration: not auto-recovered, look at it by hand (docs/139 F2)"; return 12 ;;
	esac
	# STALE_HID
	if [ "$auto" = 0 ]; then
		echo "  action: '$0 watchdog --auto' (or down, then up) after verifying USB 5/5; at most $RECOVERY_MAX per hour"
		return 10
	fi
	n=$(recoveries_last_hour)
	if [ "$n" -ge "$RECOVERY_MAX" ]; then
		echo "  STOP: $n recovery cycle(s) in the last hour (limit $RECOVERY_MAX). Reseat the cable instead: PC-end USB-C unplug/replug, then visor-end if needed (docs/22). Nothing was restarted."
		return 13
	fi
	usb=$(g2_usb_count)
	if [ "${usb%% *}" -lt 5 ]; then
		echo "  STOP: only ${usb%% *}/5 headset USB devices present (missing${usb#"${usb%% *}"}). Restarting SteamVR on a half-enumerated headset makes it worse: PC-end USB-C replug first. Nothing was restarted."
		return 13
	fi
	if [ "$dry" = 1 ]; then
		echo "  DRY RUN: would record recovery $((n + 1))/$RECOVERY_MAX, run '$SELF down', wait 5 s, run '$SELF up' (one launch attempt)"
		return 10
	fi
	echo "$(date +%s) $(date '+%F %T') stale-HID since ${H_SINCE:-?}" >> "$RECOVERY_LOG"
	log "watchdog: stale HID since ${H_SINCE:-?}, recovery $((n + 1))/$RECOVERY_MAX: down + up"
	"$SELF" down; sleep 5
	"$SELF" up; rc=$?
	log "watchdog: up finished with rc=$rc"
	return "$rc"
}

[ "${JACK_IN_OASIS_SOURCE_ONLY:-0}" = 1 ] && return 0 2>/dev/null   # tests source the functions only
case "${1:-}" in
	up|start) do_up ;;
	down|stop) do_down ;;
	status) do_status ;;
	watchdog) shift; do_watchdog "$@" ;;
	*) echo "usage: $(basename "$0") up|down|status|watchdog [--auto] [--dry-run]" >&2; exit 2 ;;
esac
