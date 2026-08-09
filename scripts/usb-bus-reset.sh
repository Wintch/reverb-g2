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
    echo "Necesita root (unbind/bind en /sys/bus/usb/drivers/usb/). Corré con sudo." >&2
    exit 1
fi

DRIVER_PATH="/sys/bus/usb/drivers/usb"
if [ ! -e "/sys/bus/usb/devices/$BUS" ]; then
    echo "!! $BUS no existe en /sys/bus/usb/devices/ -- nada que resetear." >&2
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
    [ "$found" = 0 ] && echo "  (sin entradas xhci en /sys/kernel/debug/usb -- no disponible en este kernel/build)"
}

RESULTS=()
for t in $(seq 1 "$TRIALS"); do
    echo "########## INTENTO $t/$TRIALS ##########"

    echo "=== ANTES ==="
    BEFORE=$(lsusb | grep -cE "$DEV_RE")
    echo "  $BEFORE/5 dispositivos del headset enumerados."
    lsusb | grep -E "$DEV_RE" | sed 's/^/    /'
    dump_xhci_debugfs

    echo
    echo "=== unbind $BUS ==="
    echo -n "$BUS" > "$DRIVER_PATH/unbind" 2>&1 || { echo "!! unbind fallo"; RESULTS+=("intento $t: unbind FALLO"); continue; }
    echo "  ok."

    sleep 3

    echo
    echo "=== bind $BUS ==="
    echo -n "$BUS" > "$DRIVER_PATH/bind" 2>&1 || { echo "!! bind fallo"; RESULTS+=("intento $t: bind FALLO"); continue; }
    echo "  ok."

    echo
    echo "=== esperando re-enumeracion (hasta 10s) ==="
    for i in $(seq 1 10); do
        sleep 1
        COUNT=$(lsusb | grep -cE "$DEV_RE")
        [ "$COUNT" -ge "$BEFORE" ] && [ "$COUNT" -ge 1 ] && break
    done

    echo
    echo "=== DESPUES ==="
    AFTER=$(lsusb | grep -cE "$DEV_RE")
    echo "  $AFTER/5 dispositivos del headset enumerados."
    lsusb | grep -E "$DEV_RE" | sed 's/^/    /'
    dump_xhci_debugfs

    if [ "$AFTER" -gt "$BEFORE" ]; then
        VERDICT="MEJORO ($BEFORE -> $AFTER)"
    elif [ "$AFTER" -eq "$BEFORE" ]; then
        VERDICT="sin cambios ($BEFORE -> $AFTER)"
    else
        VERDICT="EMPEORO ($BEFORE -> $AFTER)"
    fi
    echo
    echo "--- intento $t: $VERDICT ---"
    RESULTS+=("intento $t: $VERDICT")

    if [ "$t" -lt "$TRIALS" ]; then
        echo
        echo "(pausa de 5s antes del siguiente intento)"
        sleep 5
    fi
    echo
done

echo "########## RESUMEN ($TRIALS intento(s)) ##########"
for r in "${RESULTS[@]}"; do echo "  $r"; done
