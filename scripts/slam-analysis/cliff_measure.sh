#!/bin/bash
# ONE measurement window for the visibility-cliff amplitude sweep. Never self-starting: the
# operator is already in position and has said so before this is run.
#
#   $1 = label (e.g. "g255-d100")
#   $2 = seconds (default 20)
#
# Reports three things, and the third is the one the sweep exists for:
#   - raw constellation samples (docs/126's cliff metric, pre-gate)
#   - solved distance, i.e. the hand-to-camera range the solve reports
#   - BLOB telemetry: were there blobs at all, and how big/bright were they
#
# A zero-sample window with blobs present is a CORRESPONDENCE failure; a zero-sample window with
# no blobs is a DETECTION failure. Amplitude only helps the second. Nothing before patch 0111
# could tell them apart.
set -u
LABEL="$1"
SECS="${2:-20}"
L="$HOME/vr/jack-in-wayland.log"
SAMPLE_PAT="raw constellation sample \[HP Reverb G2 Right"
BLOB_PAT="blobs: t="
OUT="/mnt/vrtmp/cliffsweep"
mkdir -p "$OUT"

say() { espeak-ng -v es -s 150 "$1" >/dev/null 2>&1; }

GUI_PID=$(pgrep -u "$(id -un)" -f gnome-session-binary | head -1)
[ -n "$GUI_PID" ] || { echo "!! no GUI session" >&2; exit 1; }
while IFS= read -r -d '' kv; do
    case "$kv" in
        XDG_RUNTIME_DIR=*|DBUS_SESSION_BUS_ADDRESS=*|WAYLAND_DISPLAY=*|DISPLAY=*) export "${kv?}" ;;
    esac
done < "/proc/$GUI_PID/environ"

pgrep -x monado-service >/dev/null || { echo "!! monado-service not running" >&2; exit 1; }

# grep -c exits 1 on zero matches, so never chain it with `|| echo 0` -- that yields "0\n0" and
# breaks the arithmetic below. It did exactly that once already.
count() { local c; c=$(grep -c "$1" "$L" 2>/dev/null); echo "${c:-0}"; }

say "Preparate."
sleep 5
S0=$(count "$SAMPLE_PAT"); B0=$(count "$BLOB_PAT")
say "Ya. Quieto."
sleep "$SECS"
S1=$(count "$SAMPLE_PAT"); B1=$(count "$BLOB_PAT")
say "Listo. Bajá el brazo."

NS=$((S1 - S0)); NB=$((B1 - B0))
grep "$SAMPLE_PAT" "$L" | tail -n "$NS" > "$OUT/$LABEL.samples.txt" 2>/dev/null
grep "$BLOB_PAT"   "$L" | tail -n "$NB" > "$OUT/$LABEL.blobs.txt"   2>/dev/null

echo "label: $LABEL   window: ${SECS}s"
echo "constellation samples: $NS  ($(python3 -c "print(f'{$NS/$SECS:.1f}')")/s)"
echo "blob observations:     $NB"

if [ "$NS" -gt 0 ]; then
    grep -oE "dist=[0-9.]+" "$OUT/$LABEL.samples.txt" | cut -d= -f2 | python3 -c "
import sys, statistics
v=[float(x) for x in sys.stdin if x.strip()]
if v:
    v.sort()
    print(f'  dist_m  n={len(v)} p50={statistics.median(v):.3f} min={v[0]:.3f} max={v[-1]:.3f}')
"
fi

if [ "$NB" -gt 0 ]; then
    python3 - "$OUT/$LABEL.blobs.txt" <<'PY'
import re, sys, statistics
zero = 0
counts, means, mins, brights = [], [], [], []
for line in open(sys.argv[1]):
    # \bn= deliberately. A bare "n=0" substring test also matches inside "min=0", which misread
    # every real line as an empty frame and produced a confidently wrong verdict once already.
    mn = re.search(r"\bn=(\d+)", line)
    if not mn:
        continue
    n = int(mn.group(1))
    counts.append(n)
    if n == 0:
        zero += 1
        continue
    m = re.search(r"size_px min=([\d.]+) mean=([\d.]+) max=([\d.]+) bright min=([\d.]+) mean=([\d.]+)", line)
    if m:
        mins.append(float(m.group(1)))
        means.append(float(m.group(2)))
        brights.append(float(m.group(5)))
tot = len(counts)
if tot:
    print(f"  frames        {tot}, {zero} with ZERO blobs ({100*zero/tot:.1f}%)")
    print(f"  blobs/frame   mean {statistics.mean(counts):.2f}  max {max(counts)}")
if means:
    print(f"  blob size px  p50 {statistics.median(means):.2f}  min {min(mins):.2f}  max {max(means):.2f}")
    print(f"  brightness    p50 {statistics.median(brights):.3f}  min {min(brights):.3f}  max {max(brights):.3f}")
    print("  -> blobs ARE present. If samples are 0, this is CORRESPONDENCE, not detection.")
elif tot:
    print("  -> no blobs in any frame: DETECTION limit. Amplitude is the lever.")
PY
fi
