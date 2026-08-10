#!/bin/bash
# vr-boot-selector.sh -- runs on a bare text console (multi-user.target), before
# any desktop session exists. Two options, DEFAULT IS NOW AUTO (changed
# 2026-08-09 after T129/T130 validated live, with real failing hardware, that
# the diagnostic hands off to graphical.target no matter what happens --
# success or failure -- so every unattended boot doubles as a live health
# check instead of silently skipping straight to login):
#
#   [a] Auto     -- (default, on timeout too) -- run power-on.py --pre-login
#                    now, in the console, no desktop running yet.
#   [m] Manual   -- skip the diagnostic, boot straight into the normal
#                    graphical login (SDDM).
#
# Hard ceiling below (coreutils `timeout`) is the actual safety net now that
# auto is unattended-default: power-on.py's own per-call timeouts (run()'s
# default 10s) bound individual subprocess calls, but there was never an
# overall ceiling on the whole diagnostic -- this adds one, so a stuck
# console still can't happen even if some future change breaks that
# per-call bounding.
#
# DRY RUN: this script is safe to run by hand in any terminal right now --
# it doesn't touch systemd targets unless you explicitly pick [a] and the
# diagnostic passes (power-on.py --pre-login does that part, see there).
# Nothing here is installed as a boot-time service yet; that's a separate,
# deliberate step (see the .service file next to this script).
#
#   ./scripts/vr-boot-selector.sh [timeout_seconds, default 10]

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMEOUT="${1:-10}"

# Bigger, bolder console font for this bare VT -- purely cosmetic, never fatal:
# on a real VT it makes the boot screen legible from a few steps away (kiosk-
# style); in any other context (xterm, ssh, CI) setfont just errors harmlessly.
setfont Lat15-TerminusBold24x12 >/dev/null 2>&1 || true

G='\033[1;92m'   # bright green -- the "matrix" accent, cosmetic only
R='\033[0m'

echo -e "${G}=================================================="
echo -e "  HP Reverb G2 -- selector de arranque"
echo -e "==================================================${R}"
echo -e "  ${G}[a] Auto${R}    -- diagnostico ahora mismo, en consola, sin escritorio"
echo -e "  ${G}[m] Manual${R}  -- arranque normal (login grafico), como siempre"
echo
echo "  Sin elegir nada en ${TIMEOUT}s -> Auto (default)."
echo

CHOICE=""
read -r -t "$TIMEOUT" -n 1 -p "Elegí [a/m]: " CHOICE || true
echo

# SDDM autologin, conditional on the choice -- found live 2026-08-09/10: the
# user's actual expectation is that Auto means "no login prompt at all,
# straight through to the game", and the visual login screen is specifically
# a Manual-mode thing. SDDM reads its config fresh each time it starts
# (hasn't started yet at this point in multi-user.target), so writing/
# removing this drop-in right here, before either branch hands off, is
# enough -- no cross-boot staleness, this script runs on every single boot.
# Session=gnome-wayland.desktop specifically (not gnome.desktop) because
# that name exists ONLY under /usr/share/wayland-sessions/ -- gnome.desktop
# exists in BOTH wayland-sessions/ and xsessions/, and this project's own
# hard-won lesson (CLAUDE.md) is that picking the wrong "GNOME" entry (X11,
# or the wrong Wayland one) breaks the DRM lease Monado needs. If SDDM can't
# honor autologin for any reason, it just falls back to its normal login
# screen -- this can't lock anyone out.
#
# TRIED AND REVERTED, 2026-08-10 (T144): pointed this at mutter-bare.desktop
# instead, on the theory that it'd finally work because THIS script's own
# power-on.py --pre-login call below already activates the panel (step 4)
# before SDDM even starts -- so mutter would see the connector already
# connected at ITS OWN startup, the one case already confirmed working live
# (T142/mutter-bare-session.sh, connector present -> lease offered
# correctly). The theory itself was never actually disproven -- what broke
# it is one level up: SDDM's AUTOLOGIN path never even tried mutter-bare.
# Manually picking "Mutter (bare, no shell)" from SDDM's own graphical
# session list worked fine (confirmed live, same night) -- proving the
# .desktop file itself is valid and discovered normally. But with
# Session=mutter-bare.desktop written into this exact file byte-for-byte
# correct (verified with `xxd`, no encoding/whitespace issue) well before
# SDDM ever starts (this printf runs synchronously long before the
# `systemctl isolate graphical.target` at the end of this script), SDDM's
# own log on the very next boot went straight to reading
# gnome-wayland.desktop -- no attempt at mutter-bare logged anywhere, not
# even a failed one. Ruled out, each confirmed live: a second write
# resetting the file, a second vr-boot-selector.service run, a race between
# this script's write and SDDM's own start (journalctl timestamps show the
# write is a full ~19s before sddm.service even starts), and any other
# script in this repo touching 98-vr-autologin.conf. Best remaining guess,
# NOT confirmed: SDDM's autologin path may resolve the session against a
# session list that's scanned/cached separately from (and earlier than) the
# interactive greeter's own live directory scan, so a .desktop file added
# the same session doesn't show up there yet -- untested, would need
# SDDM source review or a reboot with the file present from an EARLIER
# boot to distinguish "autologin never sees new sessions" from "autologin
# never works for mutter-bare specifically". Revisit with fresh eyes before
# trying this again; don't just retry the same write-and-reboot loop.
SDDM_AUTOLOGIN_CONF=/etc/sddm.conf.d/98-vr-autologin.conf
case "$CHOICE" in
    m|M)
        rm -f "$SDDM_AUTOLOGIN_CONF"
        echo "=== MANUAL -- arranque grafico normal ==="
        ;;
    *)
        # Hardcoded "iam", not `logname` -- nobody's logged in yet at this
        # point (bare console, pre-graphical.target), logname would have
        # nothing real to report. Matches vr-launcher-console.sh's own
        # VR_USER="iam" convention.
        printf '[Autologin]\nUser=iam\nSession=gnome-wayland.desktop\n' > "$SDDM_AUTOLOGIN_CONF"
        echo -e "${G}=== AUTO (default, o timeout) -- corriendo power-on.py --pre-login ===${R}"
        # No 'exec' here on purpose: power-on.py already hands off to
        # graphical.target on both its success AND failure paths, but this
        # wrapper is the actual safety net if the script crashes before
        # reaching either -- recoverability shouldn't depend on power-on.py
        # behaving correctly. `timeout` (coreutils) is the hard ceiling on
        # top of that -- 120s is generous (T129/T130's real runs took
        # 10-38s) but guarantees this console can never hang indefinitely.
        timeout 120 python3 "$HERE/power-on.py" --pre-login 1 3dof
        rc=$?
        echo
        if [ "$rc" -eq 124 ]; then
            echo "diagnostico se colgo (timeout de 120s, rc=124) -- forzado a login grafico."
        else
            echo "diagnostico termino (rc=$rc). Subiendo a login grafico en 3s..."
        fi
        sleep 3
        ;;
esac

exec systemctl isolate graphical.target
