#!/bin/bash
# machine-specs.sh - capture what this machine IS, so tuning can be derived from it
# instead of hardcoded to whatever box happened to be under the desk.
#
#   ./machine-specs.sh              print the profile
#   ./machine-specs.sh --json       machine-readable, for scripts
#   ./machine-specs.sh --save       write machine-specs.json next to this repo's docs/
#
# Written 2026-08-12 (T163). The motivating case is real and was found the same session:
# jack-in-wayland.sh handed Basalt `num-threads=1`, a literal, and with T162's denser
# detection settings that pinned ONE core at 99.4% while the other eleven idled at 26%
# total -- measured with a game running, and worth 7.2-7.7% late frames against 2.8% for
# the same title with SLAM off. A constant that happens to be survivable on a 12-core box
# is a different constant on an 8-core one, and nothing in the tree said so.
#
# The existing environment fingerprint (backup-steam-config.sh) already records kernel,
# NVIDIA driver and GPU. It does NOT record the CPU, the core count or RAM, which are
# exactly the numbers the tuning above depends on. This fills that gap; the two are
# complementary, not duplicates.

set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-print}"

# --- raw facts -------------------------------------------------------------------------
cpu_model="$(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -1)"
cpu_threads="$(nproc)"
cpu_cores="$(lscpu 2>/dev/null | awk -F: '/^Core\(s\) per socket/{c=$2} /^Socket\(s\)/{s=$2} END{gsub(/ /,"",c); gsub(/ /,"",s); if (c && s) print c*s}')"
cpu_cores="${cpu_cores:-$cpu_threads}"
cpu_mhz_max="$(lscpu 2>/dev/null | awk -F: '/^CPU max MHz/{gsub(/ /,"",$2); printf "%.0f", $2}')"
ram_gb="$(awk '/^MemTotal:/{printf "%.1f", $2/1024/1024}' /proc/meminfo)"
kernel="$(uname -r)"
os="$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
gpu="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
gpu_vram_mb="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)"
nvidia_ver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)"
governor="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)"

# --- derived VR budget -----------------------------------------------------------------
# The SLAM tracker is the one component here that will take every core it is given while
# the compositor and the game still need theirs. Leave the compositor a core, leave the
# game the bulk, and give SLAM a bounded slice that scales with the machine.
#
# NOT yet proven to be the best split -- what IS measured is that 1 thread saturates a core
# and costs late frames. Treat the formula as a starting point that at least moves with the
# hardware, and override with SLAM_THREADS when measuring alternatives.
slam_threads=$(( cpu_threads / 4 ))
[ "$slam_threads" -lt 1 ] && slam_threads=1
[ "$slam_threads" -gt 4 ] && slam_threads=4

if [ "$MODE" = "--json" ] || [ "$MODE" = "--save" ]; then
	json=$(cat <<EOF
{
  "captured": "$(date -Iseconds)",
  "cpu": {
    "model": "${cpu_model}",
    "cores": ${cpu_cores},
    "threads": ${cpu_threads},
    "max_mhz": ${cpu_mhz_max:-0},
    "governor": "${governor}"
  },
  "ram_gb": ${ram_gb},
  "gpu": {
    "name": "${gpu}",
    "vram_mb": ${gpu_vram_mb:-0},
    "driver": "${nvidia_ver}"
  },
  "os": "${os}",
  "kernel": "${kernel}",
  "derived": {
    "slam_threads": ${slam_threads},
    "note": "slam_threads = threads/4, clamped to 1..4. Starting point, not a measured optimum."
  }
}
EOF
)
	if [ "$MODE" = "--save" ]; then
		printf '%s\n' "$json" > "$REPO/machine-specs.json"
		echo "wrote $REPO/machine-specs.json"
	else
		printf '%s\n' "$json"
	fi
	exit 0
fi

cat <<EOF
=== machine profile ===
  CPU        ${cpu_model}
             ${cpu_cores} cores / ${cpu_threads} threads${cpu_mhz_max:+, max ${cpu_mhz_max} MHz}, governor ${governor:-?}
  RAM        ${ram_gb} GB
  GPU        ${gpu:-?}${gpu_vram_mb:+ (${gpu_vram_mb} MB)}, driver ${nvidia_ver:-?}
  OS         ${os:-?}
  kernel     ${kernel}

=== derived for VR ===
  SLAM threads   ${slam_threads}   (threads/4, clamped 1..4; override with SLAM_THREADS)

  Measured 2026-08-12 on this box (12 threads): Basalt with num-threads=1 pinned a single
  core at 99.4% while the machine sat at 26% overall, and Aircar showed 7.2-7.7% late
  frames in 6dof against 2.8% with SLAM off. The thread count is the lever; the split above
  is a starting point that scales with the machine rather than a proven optimum.
EOF
