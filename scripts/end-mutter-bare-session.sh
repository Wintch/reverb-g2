#!/bin/bash
# end-mutter-bare-session.sh -- terminates the current "Mutter (bare, no
# shell)" SDDM session so it can be picked again FRESH, while the G2's panel
# is already lit -- tests whether mutter sees a connector that's already
# connected at its own startup (known-good per the 13:25 test) vs. a live
# hotplug after it's already running (confirmed broken, 2026-08-10).
set -u
SID="$(loginctl list-sessions --no-legend | awk '$3=="iam" && $7=="tty3" {print $1}')"
if [ -z "$SID" ]; then
    echo "Couldn't find iam's tty3 session -- check 'loginctl list-sessions'"
    exit 1
fi
echo "Terminating session $SID (iam, tty3)..."
loginctl terminate-session "$SID"
echo "Done. Should drop back to the SDDM greeter -- pick 'Mutter (bare, no shell)' again."
