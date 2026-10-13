#!/bin/bash
# vrpath.sh review|restore -- point OpenVR's first runtime at ~/vr/xrizer-review, or put the backup back.
set -eu
F=~/.config/openvr/openvrpaths.vrpath; B=~/vr/backups/openvrpaths.vrpath.20261013
case "$1" in
review)
    [ -f "$B" ] || cp -a "$F" "$B"
    python3 - "$F" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
d["runtime"] = ["/home/iam/vr/xrizer-review/target/release"] + [r for r in d["runtime"] if r != "/home/iam/vr/xrizer-review/target/release"]
json.dump(d, open(p, "w"), indent="\t")
PY
    ;;
restore) cp -a "$B" "$F" ;;
esac
python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["runtime"])' "$F"
