#!/usr/bin/env bash
# wmr-camera-teardown-cycles.sh -- teardown stress for the WMR camera path, no compositor, no wearer.
#
#   wmr-camera-teardown-cycles.sh <label> <count> [per-cycle timeout s]
#
# Each cycle runs a separate `monado-cli probe` process with WMR_SLAM=1: it creates the HMD, which
# starts SLAM and therefore the camera stream, then destroys everything -- so wmr_camera_stop()
# (break_apart) and the wmr_camera_free() join (destroy) both run every cycle. ~5 s per cycle on a
# G2. Classifies each run as ok / SIGSEGV / HANG-killed / other and checks the log for the camera
# actually starting and stopping. Written 2026-09-18 for Monado MR "wmr-camera-stop-drain"
# (docs/127 s10): 120 cycles, 0 crashes, on upstream main 09741cbcb with and without the fix.
#
#   MONADO_CLI   path to monado-cli (default: ~/vr/monado-camstop/build/src/xrt/targets/cli/monado-cli)
#   BASALT_LIB   libbasalt.so (default: ~/vr/basalt/build/libbasalt.so)
#   OUT_ROOT     where per-cycle logs go (default: ~/vr/camstop-test)
#
# The headset must be plugged in and the controllers may be off; the panel is activated briefly
# each cycle. Do not run while a wearer session is live.
set -u
label=${1:?label}; count=${2:?count}; tmo=${3:-90}
CLI=${MONADO_CLI:-$HOME/vr/monado-camstop/build/src/xrt/targets/cli/monado-cli}
OUT=${OUT_ROOT:-$HOME/vr/camstop-test}/$label; mkdir -p "$OUT"
export WMR_SLAM=1 VIT_SYSTEM_LIBRARY_PATH=${BASALT_LIB:-$HOME/vr/basalt/build/libbasalt.so}
export WMR_LOG=info XRT_NO_STDIN=1 WMR_HANDTRACKING=0
ok=0 segv=0 hang=0 other=0 nocam=0
for i in $(seq 1 "$count"); do
  log=$OUT/cycle-$(printf %03d "$i").log
  t0=$(date +%s.%N)
  timeout -s KILL "$tmo" "$CLI" probe > "$log" 2>&1
  rc=$?
  dt=$(echo "$(date +%s.%N) - $t0" | bc)
  started=$(grep -c "WMR camera started" "$log"); stopped=$(grep -c "WMR camera stopped" "$log")
  case $rc in
    0) cls=ok; ok=$((ok+1)) ;;
    139) cls=SIGSEGV; segv=$((segv+1)) ;;
    137) cls=HANG-killed; hang=$((hang+1)) ;;
    *) cls="rc=$rc"; other=$((other+1)) ;;
  esac
  [ "$started" -ge 1 ] || nocam=$((nocam+1))
  printf '%s cycle %03d %-12s %6.1fs started=%d stopped=%d\n' "$label" "$i" "$cls" "$dt" "$started" "$stopped" | tee -a "$OUT/summary.txt"
  sleep 3
done
echo "== $label: ok=$ok segv=$segv hang=$hang other=$other cycles-without-camera=$nocam" | tee -a "$OUT/summary.txt"
