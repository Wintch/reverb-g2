#!/bin/bash
# toggle-autologin.sh {off|on} -- temporarily disable/re-enable SDDM's
# autologin (98-vr-autologin.conf) so the greeter actually shows and a
# session other than "GNOME on Wayland" can be picked by hand. Renames the
# file rather than deleting it, so re-enabling is exact and can't lose the
# real config.
set -eu
CONF=/etc/sddm.conf.d/98-vr-autologin.conf
DISABLED="${CONF}.disabled"

case "${1:-}" in
    off)
        if [ -f "$CONF" ]; then
            mv "$CONF" "$DISABLED"
            echo "Autologin disabled -- restarting sddm, greeter should show now."
        else
            echo "Already disabled (or missing)."
        fi
        systemctl restart sddm
        ;;
    on)
        if [ -f "$DISABLED" ]; then
            mv "$DISABLED" "$CONF"
            echo "Autologin re-enabled -- restarting sddm."
        else
            echo "Nothing to re-enable (or already on)."
        fi
        systemctl restart sddm
        ;;
    *)
        echo "usage: $0 {off|on}" >&2
        exit 1
        ;;
esac
