#!/bin/bash
# replay-euroc.sh -- run one SLAM/prediction config against a RECORDED dataset, headless.
#
#   replay-euroc.sh <dataset_dir> <label> [KEY=VAL ...]
#
# No headset, no wearer, no compositor, no OpenXR client: `monado-cli slambatch` streams the
# recorded cameras + IMU straight through the REAL tracker and the REAL prediction code, so every
# config sees byte-identical input. That is what a worn A/B can never give -- the 2026-09-13
# SLAM_PRED_NECK_ARM_MM sweep needed four separate donnings whose head motion all differed, and
# had to be binned by angular rate just to be comparable at all.
#
# Record a dataset first with record-euroc.sh.
#
# Four things had to be fixed before this path worked; do not undo them:
#   * lab patch 0106 raises the runner's pose poll rate (SLAM_BATCH_POLL_HZ, default 170). Upstream
#     polls at 5 Hz just to notice tracking stopped, and PREDICTION only runs inside
#     get_tracked_pose -- at 5 Hz prediction.csv is ~34x too sparse to characterise.
#   * lab patch 0106 also sizes the tracker off playback.cam_count, not dataset.cam_count. A G2
#     dataset records all 4 cameras while SLAM runs on 2, and upstream waits for cam2 forever.
#   * cam-calib in the TOML. Live, the WMR driver reads the headset's factory calibration and hands
#     it to the tracker; slambatch builds a DEFAULT config with no calibration, so Basalt aborts
#     with "Missing IMU calibration". calib-g2-2cam.json is the G2's own dump trimmed to the 2
#     cameras SLAM actually uses (the 4-camera file trips calib_cam_count == cam_count).
#   * stdin must stay OPEN. The runner spawns a thread on getchar() to let you quit with enter, so
#     </dev/null is an instant EOF and the run exits before it starts.
#
# Replay stays at 1x (EUROC_MAX_SPEED=0) on purpose: the prediction horizon is the wall-clock gap
# between the anchor and "now", so accelerating the dataset would change the quantity being
# measured. EUROC_USE_SOURCE_TS=0 re-stamps frames to the current clock for the same reason.
set -u
DS="${1:?usage: replay-euroc.sh <dataset_dir> <label> [KEY=VAL ...]}"
LABEL="${2:?need a label}"
shift 2

CLI=~/vr/monado/build/src/xrt/targets/cli/monado-cli
OUT=/mnt/vrtmp/replay-$LABEL-$(date +%H%M%S)
TOOL=~/Documents/reverb-g2/scripts/slam-analysis/predict-error.py
CALIB=${SLAM_CAM_CALIB:-$HOME/vr/logs/calib-g2-2cam.json}

[ -d "$DS/mav0" ] || { echo "!! $DS is not a euroc dataset"; exit 2; }
mkdir -p "$OUT"

# Derive the 2-camera calibration from the G2's own 4-camera dump if it isn't there yet, rather
# than making the harness depend on a file someone has to remember to create.
if [ ! -r "$CALIB" ]; then
	FULL=$HOME/vr/logs/calib-g2.json
	[ -r "$FULL" ] || { echo "!! no basalt calibration at $CALIB and none to derive from at $FULL"; exit 2; }
	python3 - "$FULL" "$CALIB" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
v = d["value0"]
for k in ("T_imu_cam", "intrinsics", "resolution", "vignette"):
    if isinstance(v.get(k), list):
        v[k] = v[k][:2]
json.dump(d, open(sys.argv[2], "w"), indent=2)
PY
	echo "derived $CALIB from $FULL (first 2 cameras)"
fi

TOML=$OUT/basalt-g2.toml
cat > "$TOML" <<EOF
show-gui=0
config-path="$HOME/vr/basalt-g2-config-d30x2.json"
cam-calib="$CALIB"
marg-data=""
print-queue=0
use-double=0
deterministic=0
num-threads=6
EOF

# The runner stops when two poses 0.2 s apart compare equal. With prediction enabled the predicted
# pose keeps moving after the dataset ends (it extrapolates against an ever-newer `when_ns`), so
# that condition never fires and the run hangs forever once playback is done. Bound it by the
# dataset's own length instead; the data is complete well before the deadline and `timeout`'s 124
# is the expected exit here, not a failure.
DUR=$(python3 - "$DS" <<'PY'
import sys
ts = [int(l.split(",")[0]) for l in open(sys.argv[1] + "/mav0/cam0/data.csv") if not l.startswith("#")]
print(int((ts[-1] - ts[0]) / 1e9) + 40)
PY
)

echo "replaying $LABEL for up to ${DUR}s ($*)"
cd ~/vr
sleep 36000 | timeout "$DUR" env \
	VIT_SYSTEM_LIBRARY_PATH="$HOME/vr/basalt/build/libbasalt.so" \
	EUROC_CAM_COUNT=2 EUROC_MAX_SPEED=0 EUROC_USE_SOURCE_TS=0 EUROC_PRINT_PROGRESS=0 \
	SLAM_CONFIG="$TOML" SLAM_CONFIG_PIPELINE_ONLY=1 \
	SLAM_THREADS=6 \
	SLAM_SESSION_ANCHOR_RADIUS_CM=300 \
	SLAM_QUAT_NORM_CHECK=1 \
	SLAM_FILTER=one_euro SLAM_FILTER_ROT_MIN_CUTOFF=20 \
	"$@" \
	"$CLI" slambatch "$DS" "$TOML" "$OUT/out" > "$OUT/run.log" 2>&1
rc=$?

# The runner exits 0 even when Basalt aborted on a config problem, so check the artefacts.
rows=$(wc -l < "$OUT/out/prediction.csv" 2>/dev/null || echo 0)
if [ "$rows" -lt 100 ]; then
	echo "!! only $rows prediction rows (rc=$rc) -- run log:"
	grep -viE '^playback' "$OUT/run.log" | tail -15
	exit 1
fi

echo
python3 "$TOOL" "$OUT/out" --label="$LABEL" --segments="$DS"
echo
echo "csvs: $OUT/out"
