#!/bin/bash
# light-preflight.sh -- detached, no-wearer check of "is there enough light in this room for
# 6dof right now?" Brings Monado + the 360 player up, headset resting on the desk, for a short
# window; reads Basalt's per-frame landmark/keypoint counts (VIT_COLLAPSE_LOG=1, parsed the same
# way soak-variant.py's parse_vit() does) and grades the room against the at-rest soak baselines
# on file (docs/80): daytime base config landmarks p50 16 (base, 08-27 11:46) / 64 (base2, 08-27
# 16:32); the SAME base config run twice in the dark before dawn (base-i2/i3, 08-29 00:01/00:37)
# collapsed to landmarks p50 0 / 1 and tripped the speed guard 142 / 107 times in 15 min each
# (docs/80 ~line 1308 names "80-89% of frames under 5 landmarks" as the dark floor). Thresholds
# below sit strictly between the two known-dark points (0, 1) and the two known-daytime points
# (16, 64) -- margin on both sides of the only calibration data on hand. NOT a wearer-in-motion
# measurement -- it only answers "is the room obviously too dark to bother trying".
#
# Structural mirror of soak-sequence.sh: same rig_clean/force_down/attention helpers, same
# unconditional EXIT trap so the rig never stays up no matter how this exits, same
# setsid-nohup-only contract -- a foreground ssh session dying mid-run must not orphan monado.
#
# Usage (always detached, never foreground):
#   cd ~/Documents/reverb-g2 && setsid nohup scripts/light-preflight.sh [SECONDS] \
#       > ~/vr/logs/preflight/launch.out 2>&1 < /dev/null &
#   SECONDS defaults to 60. Progress: light-<stamp>.log (last line = verdict). Result:
#   light-<stamp>.json. End marker: light-<stamp>.done ("ok"/"failed" -- "ok" means the
#   measurement completed cleanly; DARK is a legitimate, successful verdict, not a failure).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SECS=${1:-60}
case "$SECS" in ''|*[!0-9]*) echo "SECONDS must be a positive integer, got '$SECS'" >&2; exit 2;; esac
PRE=$HOME/vr/logs/preflight
mkdir -p "$PRE"
RUNTIME=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
SOCKET=$RUNTIME/monado_comp_ipc
STAMP=$(date +%Y%m%d-%H%M%S)
LOG=$PRE/light-$STAMP.log
JSON=$PRE/light-$STAMP.json
DONE=$PRE/light-$STAMP.done
RAWLOG=$PRE/light-$STAMP-jack-in.log
DASH=http://127.0.0.1:8765
MEDIA=$HOME/vr/media/test-equirect.jpg

log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
attention() { curl -s -m 5 -X POST "$DASH/api/attention" -H 'Content-Type: application/json' -d "$1" >/dev/null 2>&1 || true; }
rig_clean() { ! pgrep -x monado-service >/dev/null && [ ! -e "$SOCKET" ]; }
force_down() {
    log "forcing the rig down (jack-in down, then kill by pid)"
    "$HOME/vr/jack-in-wayland.sh" down >/dev/null 2>&1 || true
    sleep 5
    for p in $(pgrep -x monado-service); do kill "$p" 2>/dev/null; done
    sleep 5
    for p in $(pgrep -x monado-service); do kill -9 "$p" 2>/dev/null; done
    rm -f "$SOCKET"
}

STATUS=failed
VERDICT="ERROR: no data collected"
cleanup() {
    kill "${PLAYER_PID:-}" 2>/dev/null
    rig_clean || force_down
    attention '{"active": false}'
    log "light preflight end: status=$STATUS verdict=$VERDICT"
    echo "$STATUS $(date '+%F %T')" > "$DONE"
}
trap cleanup EXIT

attention "{\"active\": true, \"message\": \"Light preflight running (~${SECS}s, headset on the desk, nobody wearing it) -- do not touch the headset. Log: $LOG\"}"
log "light preflight start: ${SECS}s"

ST=$(python3 "$HERE/game-stop.py" status 2>/dev/null)
if [ -n "$ST" ] && [ "$ST" != "no Proton game trees running" ]; then
    log "refusing: a game is running -- $ST"; exit 1
fi
rig_clean || { log "rig not clean at start"; force_down; sleep 5; }

# Live-discover the Wayland/X env (gui_env.py: DISPLAY/XAUTHORITY can't be hardcoded, they're
# per-session) and reuse soak-variant.py's own Aircar 6dof PROFILE_ENV (incl. VIT_COLLAPSE_LOG=1,
# XRT_COMPOSITOR_SCALE_PERCENTAGE=100) so this run is the same config the calibration data above
# was measured under.
ENVLINES=$(python3 - "$HERE" <<'PY'
import sys, importlib.util
d = sys.argv[1]
sys.path.insert(0, d)
spec = importlib.util.spec_from_file_location("soak_variant", d + "/soak-variant.py")
sv = importlib.util.module_from_spec(spec)
sys.modules["soak_variant"] = sv
spec.loader.exec_module(sv)
e = sv.gui_env.get()
for k in ("XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY"):
    print(f"{k}={e[k]}")
for k, v in sv.PROFILE_ENV.items():
    print(f"{k}={v}")
PY
)
[ -z "$ENVLINES" ] && { log "could not read gui_env/PROFILE_ENV from soak-variant.py, aborting"; exit 1; }
while IFS='=' read -r k v; do [ -n "$k" ] && export "$k=$v"; done <<< "$ENVLINES"

log "jack-in-wayland.sh up 1 6dof"
"$HOME/vr/jack-in-wayland.sh" up 1 6dof >>"$LOG" 2>&1
if [ $? -ne 0 ] || [ ! -e "$SOCKET" ]; then
    log "jack-in-wayland.sh did not leave the socket ready"; exit 1
fi
log "monado-service pid $(pgrep -x monado-service | head -1)"

# The 360 player, same as soak-variant.py: a real OpenXR client on a static image so the camera
# and tracking pipeline runs exactly as it does for a wearer; nobody has to hold anything.
"$HOME/vr/play360.sh" -t "$((SECS + 30))" "$MEDIA" < /dev/null >"$PRE/light-$STAMP-player.log" 2>&1 &
PLAYER_PID=$!

sleep "$SECS"
log "sampling window complete"
cp -f "$HOME/vr/jack-in-wayland.log" "$RAWLOG" 2>/dev/null || log "warning: could not copy jack-in-wayland.log"
kill "$PLAYER_PID" 2>/dev/null
"$HOME/vr/jack-in-wayland.sh" down >>"$LOG" 2>&1

# Reuse soak-variant.py's parse_vit() for landmarks/keypoints p50/p10 (its fused-line skip is
# why the K soak, 2026-08-27, isn't still losing results to lines like "0.93003432.9358"); it has
# no "% frames under 5 landmarks" or raw trip count, so those two are pulled with the same rules.
LINE=$(python3 - "$HERE" "$RAWLOG" "$SECS" "$JSON" <<'PY'
import sys, re, json, importlib.util
d, log_path, secs, json_path = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
sys.path.insert(0, d)
spec = importlib.util.spec_from_file_location("soak_variant", d + "/soak-variant.py")
sv = importlib.util.module_from_spec(spec)
sys.modules["soak_variant"] = sv
spec.loader.exec_module(sv)
stats = sv.parse_vit(log_path)

lm = []
for line in open(log_path, errors="replace"):
    if line.count("vit_") > 1:  # two threads' lines fused: skip, same rule as parse_vit()
        continue
    if line.startswith("vit_vio"):
        m = re.search(r"landmarks=(\d+)", line)
        if m:
            try:
                lm.append(int(m.group(1)))
            except ValueError:
                pass
pct_lt5 = round(100.0 * sum(1 for v in lm if v < 5) / len(lm), 1) if lm else None
trips = sum(1 for l in open(log_path, errors="replace") if "Tracker diverged" in l)

frames = stats.get("frames") or 0
p50 = stats.get("landmarks_p50")
if frames == 0:
    verdict = "ERROR: no vit_vio frames parsed (VIT_COLLAPSE_LOG lines missing)"
elif p50 is None or p50 < 5:
    verdict = "DARK"
elif p50 < 15:
    verdict = "DIM"
else:
    verdict = "OK"

result = {
    "tag": "light", "seconds": secs, "frames": frames,
    "landmarks_p50": p50, "landmarks_p10": stats.get("landmarks_p10"),
    "keypoints_p50": stats.get("keypoints_p50"),
    "pct_frames_lt5_landmarks": pct_lt5, "diverged_trips": trips, "verdict": verdict,
}
json.dump(result, open(json_path, "w"), indent=2)
# '|'-delimited, not space-delimited: an ERROR verdict has spaces/parens of its own.
print(f"RESULT|{verdict}|landmarks_p50={p50} p10={stats.get('landmarks_p10')} "
      f"keypoints_p50={stats.get('keypoints_p50')} pct_lt5={pct_lt5}% trips={trips} frames={frames}")
PY
)
log "$LINE"
VERDICT=$(echo "$LINE" | cut -d'|' -f2)
[ -z "$VERDICT" ] && VERDICT="ERROR: parse step produced no RESULT line"
case "$VERDICT" in OK|DIM|DARK) STATUS=ok ;; *) STATUS=failed ;; esac
exit 0
