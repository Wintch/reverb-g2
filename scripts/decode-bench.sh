#!/bin/bash
# decode-bench.sh - video decode throughput per file: NVDEC (hardware) vs CPU (software),
# with GPU power/utilisation sampled alongside. Answers "can THIS GPU feed the 360/VR180
# player with THIS file?" before anyone puts a headset on.
#
#   ./decode-bench.sh [-o OUTDIR] [-m hw|cuvid|sw|all] [-n NICE] FILE...
#
#   -o OUTDIR   where to write results (default: $VR_LOGS/decode-bench-<stamp>/,
#               $VR_LOGS = ~/vr/logs if it exists, else ./logs)
#   -m MODE     hw     ffmpeg -hwaccel cuda (NVDEC via the hwaccel path; falls back to
#                      software silently on an unsupported codec -- the CSV flags that as
#                      status=sw-fallback by reading the decoder utilisation)
#               cuvid  ffmpeg -c:v <codec>_cuvid (explicit NVDEC decoder; hard failure on an
#                      unsupported codec, e.g. AV1 on Pascal -> status=unsupported)
#               sw     ffmpeg default software decoder, all threads
#               all    the three above, in that order (default)
#   -n NICE     nice level for ffmpeg (default 10, so a desktop stays usable)
#
# Output: OUTDIR/results.csv with one row per (file, mode):
#   file,codec,width,height,fps_nominal,mode,decoder,frames,seconds,fps,speed_x,
#   cpu_cores_used,gpu_w_avg,gpu_util_avg,dec_util_avg,sm_mhz_avg,vid_mhz_avg,status
# plus OUTDIR/meta.txt (GPU, driver, CPU, kernel, ffmpeg version) and one ffmpeg log +
# one nvidia-smi sample CSV per row. speed_x = fps / fps_nominal; anything under 1.0 cannot
# play in real time on this machine, whatever the player does.
#
# Notes:
# - frames/seconds come from ffmpeg's own -progress output and -benchmark rtime, not from a
#   stopwatch around the process (demux/probe time is excluded).
# - cpu_cores_used = (utime+stime)/rtime from -benchmark: 1.0 means one core saturated.
# - Decoder utilisation (nvidia-smi utilization.decoder) is the honest signal that NVDEC did
#   the work; util.gpu alone can be high on the software path because of the upload/colour
#   conversion into -f null.
# - No sudo, no config file, nothing machine-specific. Safe to run on any NVIDIA box with
#   ffmpeg built with cuda/cuvid (Debian's is). AMD/Intel boxes: only -m sw is meaningful.
set -u

MODE=all
NICE=10
OUT=""
while getopts "o:m:n:h" opt; do
    case "$opt" in
        o) OUT="$OPTARG" ;;
        m) MODE="$OPTARG" ;;
        n) NICE="$OPTARG" ;;
        h) sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) exit 2 ;;
    esac
done
shift $((OPTIND - 1))
[ $# -ge 1 ] || { echo "usage: $0 [-o OUTDIR] [-m hw|cuvid|sw|all] FILE..." >&2; exit 2; }

case "$MODE" in
    hw|cuvid|sw) MODES=("$MODE") ;;
    all) MODES=(hw cuvid sw) ;;
    *) echo "unknown mode '$MODE'" >&2; exit 2 ;;
esac

STAMP=$(date +%Y%m%d-%H%M%S)
if [ -z "$OUT" ]; then
    if [ -d "$HOME/vr/logs" ]; then OUT="$HOME/vr/logs/decode-bench-$STAMP"; else OUT="./logs/decode-bench-$STAMP"; fi
fi
mkdir -p "$OUT"
CSV="$OUT/results.csv"
echo "file,codec,width,height,fps_nominal,mode,decoder,frames,seconds,fps,speed_x,cpu_cores_used,gpu_w_avg,gpu_util_avg,dec_util_avg,sm_mhz_avg,vid_mhz_avg,status" > "$CSV"

HAVE_NVSMI=0
command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1 && HAVE_NVSMI=1

{
    echo "date: $(date -Is)"
    echo "host: $(hostname)"
    echo "kernel: $(uname -r)"
    echo "cpu: $(lscpu | awk -F: '/Model name/ {gsub(/^ +/, "", $2); print $2; exit}') x$(nproc)"
    if [ "$HAVE_NVSMI" = 1 ]; then
        echo "gpu: $(nvidia-smi --query-gpu=name,driver_version,memory.total,power.limit,power.max_limit --format=csv,noheader)"
    else
        echo "gpu: (no nvidia-smi)"
    fi
    echo "ffmpeg: $(ffmpeg -version 2>/dev/null | head -1)"
    echo "modes: ${MODES[*]}  nice: $NICE"
} > "$OUT/meta.txt"
echo "== decode-bench: $(sed -n 's/^gpu: //p' "$OUT/meta.txt")"
echo "   results -> $CSV"

avg_col() {  # avg_col FILE COLUMN  (csv, nounits, skips non-numeric)
    awk -F, -v c="$2" 'NR>0 { v=$c; gsub(/ /,"",v); if (v ~ /^[0-9.]+$/) { s+=v; n++ } } END { if (n) printf "%.1f", s/n; else print "" }' "$1"
}

for f in "$@"; do
    [ -r "$f" ] || { echo "skip (unreadable): $f" >&2; continue; }
    base=$(basename "$f")
    probe=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate -of csv=p=0 "$f" 2>/dev/null)
    codec=$(echo "$probe" | cut -d, -f1); w=$(echo "$probe" | cut -d, -f2); h=$(echo "$probe" | cut -d, -f3)
    rfr=$(echo "$probe" | cut -d, -f4); fps_nom=$(awk -F/ -v r="$rfr" 'BEGIN { split(r, a, "/"); if (a[2] > 0) printf "%.3f", a[1]/a[2]; else print "" }')
    [ -n "$codec" ] || { echo "skip (ffprobe failed): $f" >&2; continue; }

    for mode in "${MODES[@]}"; do
        tag="${base%.*}-$mode"
        log="$OUT/$tag.ffmpeg.log"; prog="$OUT/$tag.progress"; smp="$OUT/$tag.nvsmi.csv"
        decoder=""
        case "$mode" in
            hw)    args=(-hwaccel cuda -hwaccel_output_format cuda); decoder="hwaccel-cuda" ;;
            cuvid) args=(-c:v "${codec}_cuvid"); decoder="${codec}_cuvid" ;;
            sw)    args=(-threads 0); decoder="software" ;;
        esac
        echo "-- $base [$codec ${w}x${h} @ $fps_nom] mode=$mode"

        SMI_PID=""
        if [ "$HAVE_NVSMI" = 1 ]; then
            nvidia-smi --query-gpu=power.draw,utilization.gpu,utilization.decoder,clocks.sm,clocks.video \
                --format=csv,noheader,nounits -lms 500 > "$smp" 2>/dev/null &
            SMI_PID=$!
        fi
        # Wall clock around ffmpeg only (probe is separate). /usr/bin/time gives CPU% and
        # RSS when present; ffmpeg's own -progress speed=Nx is the throughput of record
        # (the demux/startup overhead a wall stopwatch adds is why fps is derived from it).
        TIMEF="$OUT/$tag.time"
        if command -v /usr/bin/time >/dev/null 2>&1; then TW=(/usr/bin/time -o "$TIMEF" -f "%e %P %M"); else TW=(); fi
        t0=$(date +%s.%N)
        nice -n "$NICE" "${TW[@]}" ffmpeg -hide_banner -nostats -loglevel warning -progress "$prog" \
            "${args[@]}" -i "$f" -an -f null - > "$log" 2>&1
        rc=$?
        t1=$(date +%s.%N)
        [ -n "$SMI_PID" ] && { kill "$SMI_PID" 2>/dev/null; wait "$SMI_PID" 2>/dev/null; }

        frames=$(grep '^frame=' "$prog" 2>/dev/null | tail -1 | cut -d= -f2)
        pspeed=$(grep -oE 'speed=[0-9.]+x' "$prog" 2>/dev/null | tail -1 | tr -dc '0-9.')
        wall=$(awk -v a="$t0" -v b="$t1" 'BEGIN { printf "%.2f", b-a }')
        cpupct=""; [ -s "$TIMEF" ] && cpupct=$(awk 'NR==1{print $2}' "$TIMEF" | tr -dc '0-9')
        fps=""; speed=""; cores=""
        if [ -n "$frames" ] && [ "${frames:-0}" -gt 0 ] && awk -v w="$wall" 'BEGIN { exit !(w > 0) }'; then
            speed="$pspeed"
            if [ -n "$speed" ] && [ -n "$fps_nom" ]; then
                fps=$(awk -v s="$speed" -v b="$fps_nom" 'BEGIN { printf "%.2f", s*b }')
            else
                fps=$(awk -v f="$frames" -v w="$wall" 'BEGIN { printf "%.2f", f/w }')
                [ -n "$fps_nom" ] && speed=$(awk -v a="$fps" -v b="$fps_nom" 'BEGIN { if (b > 0) printf "%.2f", a/b }')
            fi
        fi
        [ -n "$cpupct" ] && cores=$(awk -v p="$cpupct" 'BEGIN { printf "%.2f", p/100 }')
        rtime="$wall"
        gw=""; gu=""; du=""; sm=""; vid=""
        if [ -s "$smp" ]; then
            gw=$(avg_col "$smp" 1); gu=$(avg_col "$smp" 2); du=$(avg_col "$smp" 3); sm=$(avg_col "$smp" 4); vid=$(avg_col "$smp" 5)
        fi
        status=ok
        if [ "$rc" -ne 0 ] || [ -z "$frames" ] || [ "${frames:-0}" -eq 0 ]; then
            status=unsupported
            grep -q -i -E "not supported|No capable devices|Failed to create|Codec not supported|Unsupported" "$log" || status=failed
        elif [ "$mode" = hw ] && [ -n "$du" ] && awk -v d="$du" 'BEGIN { exit !(d < 1) }'; then
            status=sw-fallback
        fi
        echo "$base,$codec,$w,$h,$fps_nom,$mode,$decoder,${frames:-0},${rtime:-},${fps:-},${speed:-},${cores:-},${gw:-},${gu:-},${du:-},${sm:-},${vid:-},$status" >> "$CSV"
        printf "   %-12s frames=%-6s %6ss  %8s fps  %6sx  cpu=%5s cores  gpu=%5s W  dec=%4s%%  %s\n" \
            "$mode" "${frames:-0}" "${rtime:--}" "${fps:--}" "${speed:--}" "${cores:--}" "${gw:--}" "${du:--}" "$status"
    done
done
echo "== done: $CSV"
