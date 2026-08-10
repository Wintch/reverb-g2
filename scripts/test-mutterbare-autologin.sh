#!/bin/bash
# test-mutterbare-autologin.sh -- points SDDM's real autologin at
# mutter-bare.desktop instead of gnome-wayland.desktop, to test the
# hypothesis that mutter-bare works fine when the panel is ALREADY
# activated (as power-on.py's pre-login step 4 always does) before the
# session starts -- unlike the live-hotplug-after-startup case already
# confirmed broken earlier tonight (docs/pruebas.jsonl T142).
#
# Only touches the autologin TARGET, not whether autologin is enabled --
# disabling it outright (98-vr-autologin.conf.disabled) mysteriously didn't
# stop autologin earlier tonight (still landed in GNOME, cause not found --
# some AccountsService/remembered-session mechanism, not confirmed). This
# sidesteps that entirely by keeping autologin ON and just changing what it
# targets.
set -eu
CONF=/etc/sddm.conf.d/98-vr-autologin.conf
cp "$CONF" "${CONF}.gnome-backup"
cp /home/iam/vr/98-vr-autologin-mutterbare.conf "$CONF"
echo "Autologin now targets mutter-bare.desktop. Restarting sddm..."
systemctl restart sddm
