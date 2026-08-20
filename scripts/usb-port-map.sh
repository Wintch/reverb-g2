#!/usr/bin/env bash
# Which physical USB socket can the Reverb G2 actually use, answered from Linux alone.
#
# THE PROBLEM. On this hardware some rear USB3 sockets work with the headset and some do not,
# and the motherboard manual does not say which -- the split is by USB CONTROLLER, and a cheap
# board's manual never mentions that its rear ports are wired to two different xHCI controllers.
# Until now the only knowledge of which sockets work came from Windows and from the user's
# memory. That is not something you can hand to someone else.
#
# WHY THE OBVIOUS METHOD FAILED. docs/00 tried to tell sockets apart with ID_PATH and could not:
# two physically different sockets both resolved to pci-0000:07:00.3-usb-0:1. The fix is to stop
# asking for a device path and read the ROOT-HUB PORT TOPOLOGY instead -- /sys/bus/usb/devices/
# usbN/N-0:1.0/usbN-portM exists for every physical port, occupied or not, so every socket has a
# stable name (usb4-port2) whether or not anything is plugged into it.
#
#   map      -- name every physical port and its controller. Needs NO headset; run it once per
#               machine, then plug anything into a socket to learn which port it is.
#   qualify  -- with the headset plugged in NOW, walk the ladder (SuperSpeed branch -> USB2
#               branch -> activation -> DP hotplug), say exactly where it stopped, and append the
#               verdict to the ledger so the map becomes knowledge instead of memory.
#
# The ledger is per machine on purpose: the port map is a property of the BOARD, not of the
# headset. docs/00's own table was written on a different box (A520 chipset, xHCI at 07:00.3)
# than the one this was written on (B450, xHCI at 09:00.3), and copying one board's answer onto
# another is exactly the mistake this file exists to prevent.

set -uo pipefail

LEDGER="${USB_PORT_LEDGER:-$HOME/vr/usb-port-ledger.jsonl}"
PANEL_PY="${PANEL_PY:-$(dirname "${BASH_SOURCE[0]}")/panel.py}"
G2_IDS="03f0:0580 045e:0659 04b4:6504 04b4:6506 0bda:4c15"

board() { cat /sys/devices/virtual/dmi/id/board_name 2>/dev/null || echo unknown; }

controller_of() {  # root hub name -> "PCI  description"
    local hub="$1" pci desc
    pci=$(basename "$(readlink -f "/sys/bus/usb/devices/$hub/.." 2>/dev/null)")
    desc=$(lspci -s "${pci#0000:}" 2>/dev/null | cut -d: -f3- | sed 's/^ *//')
    echo "$pci|${desc:-unknown}"
}

cmd_map() {
    echo "board: $(board)"
    echo
    for hub in /sys/bus/usb/devices/usb*; do
        local h ctl pci desc speed
        h=$(basename "$hub")
        IFS='|' read -r pci desc <<<"$(controller_of "$h")"
        speed=$(cat "$hub/speed" 2>/dev/null)
        printf "%s  [%s]  %s Mbps\n" "$h" "$pci" "$speed"
        printf "    %s\n" "$desc"
        for p in "$hub"/*-0:1.0/"$h"-port*; do
            [ -e "$p" ] || continue
            local pn state occupant dev
            pn=$(basename "$p")
            state=$(cat "$p/state" 2>/dev/null)
            occupant=""
            # The port's device symlink, when something is attached, names the bus path (e.g. 4-2).
            dev=$(basename "$(readlink -f "$p/device" 2>/dev/null)" 2>/dev/null)
            if [ -n "$dev" ] && [ -e "/sys/bus/usb/devices/$dev/idVendor" ]; then
                occupant="$(cat "/sys/bus/usb/devices/$dev/idVendor"):$(cat "/sys/bus/usb/devices/$dev/idProduct")"
                occupant="$dev  $occupant  $(cat "/sys/bus/usb/devices/$dev/product" 2>/dev/null)"
            fi
            printf "      %-14s %-14s %s\n" "$pn" "$state" "$occupant"
        done
        echo
    done
    echo "Two controllers with rear sockets on both is the whole point: sockets on different"
    echo "controllers are NOT interchangeable for this headset. Plug a mouse into a socket to"
    echo "learn which usbN-portM it is, then check the ledger:"
    echo "  $LEDGER"
}

g2_census() {  # prints "n/5" and sets G2_PRESENT/G2_MISSING
    local n=0
    G2_MISSING=""
    for id in $G2_IDS; do
        if lsusb | grep -q "$id"; then n=$((n + 1)); else G2_MISSING="$G2_MISSING $id"; fi
    done
    echo "$n"
}

g2_port() {  # the root-hub port one of the headset's own hubs sits on -- its stable address
    # Tries the SuperSpeed hub first and the USB2 hub second, because WHICH of them appears is
    # exactly what varies between socket types: a USB2-only socket has no SuperSpeed hub to find,
    # and looking only for that one reported "no socket" for the very case being diagnosed.
    local want d dev
    for want in 6504 6506; do
        for d in /sys/bus/usb/devices/*; do
            [ -e "$d/idVendor" ] || continue
            if [ "$(cat "$d/idVendor")" = "04b4" ] && [ "$(cat "$d/idProduct")" = "$want" ]; then
                dev=$(basename "$d")
                echo "${dev%%.*}"   # 4-2.1 -> 4-2, the socket itself and not the internal hub
                return
            fi
        done
    done
    echo ""
}

have() { lsusb | grep -q "$1"; }

# The plain-language line, from the project's shared translation layer (scripts/vr_i18n.py), so
# the person holding the cable gets an instruction and not a diagnosis. The technical verdict
# still goes to the ledger -- both audiences are real, they are just not the same audience.
say() {
    python3 - "$(dirname "${BASH_SOURCE[0]}")" "$1" <<'PY' 2>/dev/null
import sys
sys.path.insert(0, sys.argv[1])
try:
    from vr_i18n import t
    print(t(sys.argv[2]))
except Exception:
    pass
PY
}
action() { local m; m=$(say "$1"); [ -n "$m" ] && { echo; echo "   >> $m"; }; }

cmd_qualify() {
    local label="${1:-}"
    [ -z "$label" ] && { echo "usage: $0 qualify \"<name you can say out loud, e.g. 'trasero abajo junto al HDMI'>\"" >&2; exit 2; }

    # The window deliberately reaches BACKWARDS. Enumeration happens when the cable goes in,
    # which is seconds-to-minutes before anyone gets to a terminal to run this -- a window that
    # starts "now" reports a silent port for every real failure and calls it the quiet variant.
    # Found by running it: the first bad-socket capture printed "nothing above" while the kernel
    # had logged four "Cannot enable" lines a minute earlier.
    local since; since="${QUALIFY_LOG_WINDOW:-10 min ago}"
    echo "board: $(board)   label: $label   kernel window: $since"
    echo

    # --- rung 1: does anything of the headset enumerate at all ---
    # Verbose on purpose while this is still being learned: the five devices are not
    # interchangeable and "3/5" hides WHICH three, which is the entire diagnosis. Each line says
    # what that device is for, so a missing one reads as a lost capability and not as a number.
    local n port ctl pci desc
    n=$(g2_census)
    port=$(g2_port)
    echo "1. USB census: $n/5"
    for spec in "04b4:6504|SuperSpeed hub|the USB3 side of the cable's active hub" \
                "045e:0659|HoloLens Sensors|cameras, IMU and the controller tunnel -- ALL tracking" \
                "04b4:6506|USB2 hub|the USB2 side of the same hub" \
                "03f0:0580|companion|panel on/off, activation, IPD, proximity/presence" \
                "0bda:4c15|audio|headphones and mic"; do
        IFS='|' read -r id nm what <<<"$spec"
        if lsusb | grep -q "$id"; then
            printf "     [ok]      %-11s %-18s %s\n" "$id" "$nm" "$what"
        else
            printf "     [MISSING] %-11s %-18s %s\n" "$id" "$nm" "$what"
        fi
    done
    if [ "$n" = 0 ]; then
        verdict="DEAD: nothing enumerates. Wrong socket, unpowered headset, or a dead cable."
        echo "   -> $verdict"; action usb_action_nothing; ledger "$label" "" "" "$n" "$verdict"; return
    fi

    if [ -n "$port" ]; then
        local hub="usb${port%%-*}" spd
        IFS='|' read -r pci desc <<<"$(controller_of "$hub")"
        spd=$(cat "/sys/bus/usb/devices/$hub/speed" 2>/dev/null)
        echo
        echo "   socket      : $port  (root hub $hub, ${spd} Mbps)"
        echo "   controller  : $pci"
        echo "                 $desc"
        # The sibling root hub is what says whether this physical socket has a SuperSpeed side
        # at all -- a black USB2 socket simply has no 10 Gbps partner behind it.
        echo "   this controller's root hubs:"
        for h in /sys/bus/usb/devices/usb*; do
            local hn hp
            hn=$(basename "$h")
            hp=$(controller_of "$hn" | cut -d'|' -f1)
            [ "$hp" = "$pci" ] || continue
            printf "                 %-6s %6s Mbps\n" "$hn" "$(cat "$h/speed" 2>/dev/null)"
        done
    fi

    # --- rung 2: the USB2 branch, the one that actually distinguishes sockets ---
    # The SuperSpeed pair can come up on a socket where the USB2 pair never will. That asymmetry
    # is the documented signature of a socket the headset cannot use (docs/22), and it is why a
    # census of 2/5 is a VERDICT and not a transient.
    if [ "$n" -lt 5 ]; then
        # WHICH branch is missing is the diagnosis, not how many devices are missing. The two
        # partial states mean opposite things and send the user to opposite places.
        local ss=no usb2=no hint=usb_action_cable
        have 04b4:6504 && have 045e:0659 && ss=yes
        have 04b4:6506 && have 03f0:0580 && usb2=yes
        echo "2. INCOMPLETE ($n/5): SuperSpeed branch=$ss, USB2 branch=$usb2 -- kernel, last $since:"
        echo "   -- kernel lines that name a failure --"
        journalctl -k --since "$since" 2>/dev/null | grep -iE "usb|xhci" | grep -iE "error -[0-9]+|cannot enable|not accepting address|unable to enumerate|device descriptor read" | tail -10 | sed 's/^/     /'
        echo "     (nothing above = the 'quiet' variant: the port never even tries. Also a fail.)"
        echo "   -- everything the kernel said about USB in this window, for context --"
        # Serial numbers are stripped: this output gets pasted into chats and issues, and the
        # headset's USB serial is exactly the kind of identifier that should not travel.
        journalctl -k --since "$since" 2>/dev/null | grep -iE "usb ?[0-9]|xhci" | sed 's/SerialNumber: .*/SerialNumber: <redacted>/' | tail -20 | sed 's/^/     /'
        if [ "$ss" = yes ] && [ "$usb2" = no ]; then
            if [ "$pci" = "$(controller_of "usb${port%%-*}" | cut -d'|' -f1)" ]; then hint=usb_action_wrong_socket; fi
            verdict="BAD SOCKET ($n/5): SuperSpeed came up, the USB2 branch never did -- no companion, so no panel, no activation, no audio, no IPD, no presence. If the controller above is the CHIPSET xHCI, move to a CPU-controller socket ('$0 map'). If it is already the CPU one, the socket is fine and the cable/connector is next (docs/22)."
            hint=usb_action_wrong_socket
        elif [ "$usb2" = yes ] && [ "$ss" = no ]; then
            hint=usb_action_usb2_only
            verdict="USB2-ONLY SOCKET ($n/5): the companion side came up and the SuperSpeed pair did not, so there are no cameras, no IMU and no controller tunnel -- the panel may light while nothing can ever be tracked. This is a black USB2 port; the headset needs a blue USB3 one."
        else
            hint=usb_action_cable
            verdict="PARTIAL ($n/5), neither branch complete: treat as a bad socket and re-seat before concluding anything."
        fi
        echo "   -> $verdict"; action "$hint"; ledger "$label" "$port" "$pci" "$n" "$verdict"; return
    fi
    echo "2. all five devices present"

    # --- rung 3: activation. Enumerating is not the same as usable. ---
    echo "3. activating the panel ($PANEL_PY activate)"
    if ! python3 "$PANEL_PY" activate >/tmp/usb-port-qualify.$$ 2>&1; then
        sed 's/^/     /' /tmp/usb-port-qualify.$$; rm -f /tmp/usb-port-qualify.$$
        verdict="ENUMERATES BUT DOES NOT ACTIVATE: all five devices present and the activation sequence failed. Companion HID is reachable but not answering -- see docs/22's ladder."
        echo "   -> $verdict"; ledger "$label" "$port" "$pci" "$n" "$verdict"; return
    fi
    rm -f /tmp/usb-port-qualify.$$

    # --- rung 4: the only proof that matters -- the panel's own connector APPEARS ---
    # Baselined before activation on purpose: desktop monitors also read "connected", so the
    # headset is not "a connected DP" -- it is the connector that was NOT there a second ago.
    # Counting all connected outputs would have declared success on any machine with a monitor.
    local i conn="" before
    before=$(for c in /sys/class/drm/card*-DP-*; do
                 [ "$(cat "$c/status" 2>/dev/null)" = connected ] && basename "$c"
             done | sort | tr '\n' ' ')
    for i in $(seq 1 20); do
        sleep 0.5
        for c in /sys/class/drm/card*-DP-*; do
            [ "$(cat "$c/status" 2>/dev/null)" = connected ] || continue
            case " $before " in *" $(basename "$c") "*) continue ;; esac
            conn="$conn $(basename "$c")"
        done
        [ -n "$conn" ] && break
    done
    echo "   (already connected before activating:${before:- none})"
    echo "4. DP connectors that APPEARED after activating:${conn:- none}"
    # Three outcomes, deliberately not collapsed into two. The middle one is the trap: if the
    # panel was already awake from an earlier activation its connector is already present, so
    # "no new connector" is not a failure -- but it is also not a proof, and reporting it as
    # GOOD would be a check that cannot fail. Power-cycle the headset and re-run to get a real
    # rung 4.
    if [ -n "$conn" ]; then
        verdict="GOOD SOCKET: 5/5, activation accepted, panel connector appeared ($conn). Proven end to end."
    elif [ -n "$before" ]; then
        verdict="GOOD SO FAR, RUNG 4 NOT PROVEN: 5/5 and activation accepted, but a DP connector was already present before activating ($before), so this run could not observe the hotplug. Power-cycle the headset and re-run to prove it."
    else
        verdict="ENUMERATES AND ACTIVATES BUT NO PANEL: 5/5, activation accepted, and no DP connector ever appeared. This is the docs/22 dark-panel class, not a socket problem -- check the cable's video side."
    fi
    echo "   -> $verdict"
    [ -n "$conn" ] && action usb_action_ok
    ledger "$label" "$port" "$pci" "$n" "$verdict"
}

ledger() {
    mkdir -p "$(dirname "$LEDGER")"
    python3 - "$LEDGER" "$(board)" "$1" "$2" "$3" "$4" "$5" <<'PY'
import json, sys, datetime
path, board, label, port, pci, census, verdict = sys.argv[1:8]
row = dict(when=datetime.datetime.now().isoformat(timespec="seconds"), board=board,
           label=label, port=port, controller=pci, census=census, verdict=verdict)
with open(path, "a") as f:
    f.write(json.dumps(row, ensure_ascii=False) + "\n")
print(f"\nrecorded in {path}")
PY
}

case "${1:-map}" in
    map) cmd_map ;;
    qualify) shift; cmd_qualify "$@" ;;
    *) echo "usage: $0 [map | qualify \"<socket label>\"]" >&2; exit 2 ;;
esac
