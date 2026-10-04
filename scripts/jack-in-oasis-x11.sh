#!/bin/bash
# jack-in-oasis-x11.sh - start SteamVR with the Oasis/Ignition driver on an X11 session
# (KDE Plasma X11 or GNOME on Xorg), with the HP Reverb G2 freed from the desktop first.
#
#   jack-in-oasis-x11.sh up | down | status
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
VRLOGS="$STEAM_ROOT/logs"
WATCH_SECONDS="${OASIS_WATCH_SECONDS:-120}"
BT_WAIT="${VR_BT_CTRL_WAIT:-30}"
HMD_OUTPUT="${HMD_OUTPUT:-}"          # override only if autodetect is wrong

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
# Never pkill -f: match on the exact command name (comm) or on a wine process whose command
# line references the Oasis driver, by PID. vrserver renames its own comm to "<pid>: vrstart"
# while waiting for vrmonitor, so a comm match alone missed it (2026-10-03): also match the SteamVR binary path.
VR_COMMS='vrmonitor|vrserver|vrcompositor|vrcompositor-la|vrdashboard|vrwebhelper|vrstartup|vrcmd|ignition|oasis'
vr_pids() {
	ps -u "$(id -u)" -o pid=,comm=,args= | awk -v re="^($VR_COMMS)" -v oas="$OASIS_DIR" '
		{ pid=$1; comm=$2; if (comm ~ re) { print pid; next }
		  if (index($0, "Oasis Driver") || index($0, "ignition") || index($0, "SteamVR/bin/linux64/")) { if (comm !~ /^(awk|ps|bash|grep|sshd)/) print pid } }'
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
	echo "driver_monado.enable: $(python3 -c "import json;print(json.load(open('$VRSETTINGS')).get('driver_monado',{}).get('enable'))" 2>/dev/null)"
	if [ -f "$STATE" ]; then echo "state file ($STATE):"; sed 's/^/  /' "$STATE"; else echo "no state file (no run pending 'down')"; fi
	[ -f "$VRLOGS/vrserver.txt" ] && {
		grep -E "Active HMD set|finished adding tracked device" "$VRLOGS/vrserver.txt" | tail -5 | sed 's/^/  vrserver: /'
		grep -c CannotDRMLease "$VRLOGS/vrcompositor.txt" 2>/dev/null | sed 's/^/  CannotDRMLease lines in vrcompositor.txt: /'
	}
}

# ---- down -------------------------------------------------------------------------------
do_down() {
	find_session_env || log "WARNING: no X11 session env, display steps skipped"
	log "=== down ==="
	local started_steam bk hmd kscreen_parked
	started_steam=$(state_get STARTED_STEAM); bk=$(state_get BACKUP_DIR); hmd=$(state_get HMD_OUTPUT)
	kscreen_parked=$(state_get KSCREEN_PARKED)

	log "stopping SteamVR / vrserver / vrcompositor / Ignition..."
	# Ask vrmonitor first: it shuts vrserver down cleanly.
	for p in $(ps -u "$(id -u)" -o pid=,comm= | awk '$2=="vrmonitor"{print $1}'); do kill -TERM "$p" 2>/dev/null; done
	sleep 3
	kill_all vr_pids || log "  WARNING: some VR processes survived SIGKILL: $(vr_pids | tr '\n' ' ')"
	kill_all wine_pids || log "  WARNING: wine processes survived: $(wine_pids | tr '\n' ' ')"

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
	log "down complete. leftovers: vr=[$(vr_pids | tr '\n' ' ')] wine=[$(wine_pids | tr '\n' ' ')] steam=$(steam_running && echo up || echo stopped)"
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
	command -v getcap >/dev/null || die "getcap not found even with /usr/sbin in PATH"
	getcap "$STEAMVR/bin/linux64/vrcompositor-launcher" | grep -q cap_sys_nice \
		|| log "WARNING: vrcompositor-launcher lacks cap_sys_nice; SteamVR will show a superuser popup"

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
	state_set BACKUP_DIR "$bk"; state_set HMD_OUTPUT "$HMD_OUTPUT"; state_set STARTED_AT "$ts"
	log "backups in $bk"
	prep_vrpaths | sed 's/^/  /' | tee -a "$LOG"
	prep_vrsettings | sed 's/^/  /' | tee -a "$LOG"

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
		(
			while :; do
				if output_active "$HMD_OUTPUT"; then
					echo "$(date '+%F %T')   guard: $HMD_OUTPUT came back on the desktop, freeing it again" >> "$LOG"
					xrandr --output "$HMD_OUTPUT" --off >> "$LOG" 2>&1
				fi
				sleep 0.3
			done
		) &
		GUARD_PID=$!
		log "panel guard running (pid $GUARD_PID)"
	fi
	local t0; t0=$(date +%s)
	# Only judge the compositor by lines written AFTER this launch: the SteamVR logs are appended
	# across runs, so an older run's CannotDRMLeaseDisplay used to make a good launch "fail".
	local comp_base=0
	[ -f "$VRLOGS/vrcompositor.txt" ] && comp_base=$(wc -l < "$VRLOGS/vrcompositor.txt")
	log "launching SteamVR: steam steam://run/250820"
	setsid nohup steam steam://run/250820 >> "$VR_DIR/oasis-x11-steam.log" 2>&1 < /dev/null & disown

	# ---- watch (one pass, no retries) ----------------------------------------------------
	local i fresh=0 compfresh=0 res=PENDING hmd_ok ctl_n comp_err
	for i in $(seq 1 "$WATCH_SECONDS"); do
		sleep 1
		[ -f "$VRLOGS/vrserver.txt" ] && [ "$(stat -c %Y "$VRLOGS/vrserver.txt")" -ge "$t0" ] && fresh=1
		[ "$fresh" = 1 ] || continue
		hmd_ok=$(grep -c 'Active HMD set to oasis' "$VRLOGS/vrserver.txt")
		ctl_n=$(grep -c "Driver 'oasis' finished adding tracked device" "$VRLOGS/vrserver.txt")
		comp_err=0; compfresh=0
		[ -f "$VRLOGS/vrcompositor.txt" ] && [ "$(stat -c %Y "$VRLOGS/vrcompositor.txt")" -ge "$t0" ] && compfresh=1
		local comp_new=""
		[ "$compfresh" = 1 ] && comp_new=$(tail -n +$((comp_base + 1)) "$VRLOGS/vrcompositor.txt" 2>/dev/null)
		comp_err=$(printf '%s\n' "$comp_new" | grep -c 'CannotDRMLeaseDisplay\|Failed to acquire xlib display')
		# Success = the compositor acquired the panel and finished starting, whatever failed before
		# (it restarts itself: a first failed start followed by a good one is normal here).
		if [ "${hmd_ok:-0}" -ge 1 ] && [ "${ctl_n:-0}" -ge 3 ] && printf '%s\n' "$comp_new" | grep -q 'Acquired xlib display' && printf '%s\n' "$comp_new" | grep -q 'Startup Complete'; then res=OK; break; fi
		[ $((i % 15)) = 0 ] && log "  t+${i}s: active-hmd=$hmd_ok tracked-devices=$ctl_n compositor-errors=${comp_err:-0}"
	done
	[ -n "$GUARD_PID" ] && kill "$GUARD_PID" 2>/dev/null
	if [ "$res" = PENDING ]; then
		if [ "${comp_err:-0}" -gt 0 ]; then res=COMPOSITOR_FAILED; else res=TIMEOUT; fi
	fi
	log "--- result: $res (t+${i}s) ---"
	{
		echo "vrserver.txt markers:"; grep -E "Active HMD set|finished adding tracked device|Cannot register controller|Unable to load driver|safe mode" "$VRLOGS/vrserver.txt" | tail -12
		echo "vrcompositor.txt markers:"; grep -E "direct display|Direct mode|direct mode|Selected mode|Failed to|CannotDRM|VRInitError" "$VRLOGS/vrcompositor.txt" | tail -12
	} 2>/dev/null | sed 's/^/  /' | tee -a "$LOG"
	log "xrandr after launch: $(xrandr -q | grep -E "^$HMD_OUTPUT " )"

	if [ "$res" = OK ] || [ "${hmd_ok:-0}" -ge 1 ]; then
		log "sampling poses for 8 s (move the joys)"
		command -v espeak-ng >/dev/null && XDG_RUNTIME_DIR="/run/user/$(id -u)" espeak-ng -v es "Mueve los joys" >/dev/null 2>&1 &
		( cd "$STEAMVR" && LD_LIBRARY_PATH=bin/linux64:bin/linux64/qt/lib timeout 8 bin/linux64/vrcmd --pollposes 2>/dev/null ) \
			| awk -F, 'NF>=7 { n[$1]++; if (!(($0) in seen)) { seen[$0]=1; d[$1]++ } } END { for (k in n) printf "  pollposes %-28s samples=%d distinct=%d\n", k, n[k], d[k] }' | tee -a "$LOG"
	fi
	log "attempt finished: $res. Run '$0 down' to tear down and restore the backups."
	[ "$res" = OK ]
}

case "${1:-}" in
	up|start) do_up ;;
	down|stop) do_down ;;
	status) do_status ;;
	*) echo "usage: $(basename "$0") up|down|status" >&2; exit 2 ;;
esac
