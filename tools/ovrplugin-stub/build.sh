#!/bin/bash
# Build libOVRPlugin.so (the stub) and optionally install it into a game.
#
#   ./build.sh                          build only, into this directory
#   ./build.sh <path/to/Game_Data>      build and install into <Game_Data>/Mono/x86_64/
#
# See ovrplugin_stub.c for why this exists. Short version: InCell VR and InMind VR are
# native Linux Unity builds that call Oculus's OVRPlugin before anything else; that
# library never existed on Linux, Mono throws DllNotFoundException and the game aborts in
# under a second. The stub answers "no HMD" so the game's own OVRSwitcher can fall through
# to OpenVR, where xrizer is waiting.
#
# Installing only ADDS a file the game already looks for and does not find; nothing is
# overwritten. Remove the .so to undo.

set -eu
cd "$(dirname "${BASH_SOURCE[0]}")"

OUT="libOVRPlugin.so"

cc -shared -fPIC -O2 -Wall -Wextra -o "$OUT" ovrplugin_stub.c
echo "built $(pwd)/$OUT"
echo "exports: $(nm -D --defined-only "$OUT" | grep -c ' T ovrp_')"

if [ $# -ge 1 ]; then
    DATA="$1"
    DEST="$DATA/Mono/x86_64"
    [ -d "$DEST" ] || { echo "No such directory: $DEST" >&2; exit 1; }
    if [ -e "$DEST/$OUT" ]; then
        echo "note: $DEST/$OUT already exists, replacing the stub"
    fi
    cp "$OUT" "$DEST/$OUT"
    echo "installed -> $DEST/$OUT"
    echo
    echo "Run the game with OVRSTUB_TRACE=1 to see which symbols it actually calls."
    echo "Remove with: rm '$DEST/$OUT'"
fi
