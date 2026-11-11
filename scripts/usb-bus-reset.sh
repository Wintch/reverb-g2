#!/bin/bash
# Software-level reset of the headset's USB2 bus (kernel unbind/rebind of the root hub),
# WITHOUT touching any physical connector -- step 3 of the zero-touch escalation ladder
# from docs/pruebas.jsonl T116. Needs root (unbind/bind under /sys/bus/usb/drivers/usb/
# is root-only).
#
# Targets the whole root hub ("usb3"), not a single downstream port: when the branch is
# fully dead (nothing enumerated at all, not even a retry storm in journalctl -k), there
# is no live device node for a specific port like "3-1" to unbind -- confirmed live
# 2026-08-09, "No such device" when trying that path directly.
#
# Prints device count before and after so the result is a plain before/after comparison,
# not something to eyeball from raw lsusb output.
#
#   sudo ./scripts/usb-bus-reset.sh [trials, default 1] [bus-root, default usb3]
#
# Runs N independent trials (default 1) so a single lucky/unlucky result doesn't get
# over-read -- prints a per-trial line plus a summary table at the end. Also dumps xHCI
# debugfs port state around each trial when available (root-only, /sys/kernel/debug/usb),
# which distinguishes "port genuinely sees nothing" from "host controller disabled this
# port after repeated failures" -- lsusb alone can't tell those apart.

set -u
TRIALS="${1:-1}"
BUS="${2:-usb3}"
DEV_RE="03f0:0580|045e:0659|04b4:650[46]|0bda:4c15"

if [ "$(id -u)" -ne 0 ]; then
    echo "Needs root (unbind/bind under /sys/bus/usb/drivers/usb/). Run with sudo." >&2
    exit 1
fi

DRIVER_PATH="/sys/bus/usb/drivers/usb"
if [ ! -e "/sys/bus/usb/devices/$BUS" ]; then
    echo "!! $BUS does not exist in /sys/bus/usb/devices/ -- nothing to reset." >&2
    exit 1
fi

dump_xhci_debugfs() {
    local found=0
    shopt -s nullglob
    for d in /sys/kernel/debug/usb/*"${BUS#usb}"* /sys/kernel/debug/usb/*xhci*; do
        [ -e "$d" ] || continue
        found=1
        echo "  debugfs: $d"
        find "$d" -maxdepth 1 -type f 2>/dev/null | while read -r f; do
            printf '    %-20s ' "$(basename "$f")"
            head -c 200 "$f" 2>/dev/null | tr '\n' ' '
            echo
        done
    done
    [ "$found" = 0 ] && echo "  (no xhci entries in /sys/kernel/debug/usb -- not available on this kernel/build)"
}

# An interrupted run (Ctrl-C, ssh drop, failed bind) between unbind and bind would leave the
# whole bus unbound, keyboard, mouse and disks on it included: rebind on the way out.
UNBOUND=0
rebind() {
    [ "$UNBOUND" = 1 ] || return 0
    for _ in 1 2 3; do
        echo -n "$BUS" > "$DRIVER_PATH/bind" 2>/dev/null && { UNBOUND=0; echo "  $BUS rebound on exit"; return 0; }
        sleep 2
    done
    echo "!! $BUS is still unbound: replug or reboot" >&2
}
trap rebind EXIT
trap 'exit 130' INT TERM HUP

RESULTS=()
for t in $(seq 1 "$TRIALS"); do
    echo "########## TRIAL $t/$TRIALS ##########"

    echo "=== BEFORE ==="
    BEFORE=$(lsusb | grep -cE "$DEV_RE")
    echo "  $BEFORE/5 headset devices enumerated."
    lsusb | grep -E "$DEV_RE" | sed 's/^/    /'
    dump_xhci_debugfs

    echo
    echo "=== unbind $BUS ==="
    echo -n "$BUS" > "$DRIVER_PATH/unbind" 2>&1 || { echo "!! unbind failed"; RESULTS+=("trial $t: unbind FAILED"); continue; }
    UNBOUND=1
    echo "  ok."

    sleep 3

    echo
    echo "=== bind $BUS ==="
    if echo -n "$BUS" > "$DRIVER_PATH/bind" 2>&1; then
        UNBOUND=0
    else
        echo "!! bind failed"; RESULTS+=("trial $t: bind FAILED")
        rebind   # retries; leaving the bus unbound for the next trial would test nothing
        continue
    fi
    echo "  ok."

    echo
    echo "=== waiting for re-enumeration (up to 10s) ==="
    for i in $(seq 1 10); do
        sleep 1
        COUNT=$(lsusb | grep -cE "$DEV_RE")
        [ "$COUNT" -ge "$BEFORE" ] && [ "$COUNT" -ge 1 ] && break
    done

    echo
    echo "=== AFTER ==="
    AFTER=$(lsusb | grep -cE "$DEV_RE")
    echo "  $AFTER/5 headset devices enumerated."
    lsusb | grep -E "$DEV_RE" | sed 's/^/    /'
    dump_xhci_debugfs

    if [ "$AFTER" -gt "$BEFORE" ]; then
        VERDICT="IMPROVED ($BEFORE -> $AFTER)"
    elif [ "$AFTER" -eq "$BEFORE" ]; then
        VERDICT="unchanged ($BEFORE -> $AFTER)"
    else
        VERDICT="WORSE ($BEFORE -> $AFTER)"
    fi
    echo
    echo "--- trial $t: $VERDICT ---"
    RESULTS+=("trial $t: $VERDICT")

    if [ "$t" -lt "$TRIALS" ]; then
        echo
        echo "(5s pause before the next trial)"
        sleep 5
    fi
    echo
done

echo "########## SUMMARY ($TRIALS trial(s)) ##########"
for r in "${RESULTS[@]}"; do echo "  $r"; done
