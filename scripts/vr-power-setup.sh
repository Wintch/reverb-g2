#!/bin/bash
# vr-power-setup.sh - take every power-saving decision away from the machine before a VR
# session, so frame timing is decided by the workload and not by a governor changing its
# mind mid-turn.
#
#   ./vr-power-setup.sh              report current state (no root needed, changes nothing)
#   sudo ./vr-power-setup.sh --apply     set everything to full performance
#   sudo ./vr-power-setup.sh --restore   put the defaults back
#   sudo ./vr-power-setup.sh --gpu-limit 80    cap the GPU at 80% of its max watts
#
# Why this exists (2026-08-12, T163): a dropped frame in VR is not a statistic, it is the
# compositor re-showing the previous frame, which the wearer sees as the view snapping back
# while turning. Anything that can add latency non-deterministically -- a governor ramping,
# a link entering a low-power state, a device autosuspending -- can produce exactly that,
# and none of it is visible in an average.
#
# THE GPU WATTS QUESTION IS DELIBERATELY SEPARATE and is an experiment, not a setting:
# NVIDIA cards can deliver identical frame timing across a wide power range, so capping them
# costs nothing but heat and noise IF that holds here. It has to be measured, not assumed --
# --gpu-limit sets the cap, then re-run scripts/frame-pacing.sh and compare. Work downwards
# (80%, then 70%) only while the pacing numbers stay put, and remember the per-window
# variance measured on this rig is wide: 3.44% and 7.22% came out of back-to-back windows in
# an identical configuration. Three windows per data point, minimum.

set -u

MODE="${1:-report}"
STATE_DIR="/var/lib/vr-power-setup"
STATE="$STATE_DIR/saved-state"

C_OK=$'\033[1;32m'; C_WARN=$'\033[1;33m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'

HMD_USB_IDS="03f0:0580 045e:0659 04b4:6506 04b4:6504 0bda:4c15"

gpu_max_w()  { nvidia-smi --query-gpu=power.max_limit --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1; }
gpu_cur_w()  { nvidia-smi --query-gpu=power.limit     --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1; }

report() {
	echo "=== power state ==="
	local gov epp drv aspm
	gov="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)"
	drv="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver 2>/dev/null)"
	epp="$(cat /sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference 2>/dev/null)"
	aspm="$(sed 's/.*\[\(.*\)\].*/\1/' /sys/module/pcie_aspm/parameters/policy 2>/dev/null)"

	printf "  cpu governor   %s%s%s   (driver %s)\n" \
	       "$([ "$gov" = performance ] && echo "$C_OK" || echo "$C_WARN")" "${gov:-?}" "$C_OFF" "${drv:-?}"
	printf "  cpu epp        %s%s%s\n" \
	       "$([ "${epp:-}" = performance ] && echo "$C_OK" || echo "$C_WARN")" "${epp:-n/a}" "$C_OFF"
	printf "  cpu boost      %s\n" "$(cat /sys/devices/system/cpu/cpufreq/boost 2>/dev/null || echo n/a)"
	printf "  pcie aspm      %s%s%s\n" \
	       "$([ "${aspm:-}" = performance ] && echo "$C_OK" || echo "$C_WARN")" "${aspm:-?}" "$C_OFF"

	local cur max
	cur="$(gpu_cur_w)"; max="$(gpu_max_w)"
	if [ -n "$cur" ] && [ -n "$max" ]; then
		printf "  gpu power      %s W of %s W max  (%s%%)\n" "$cur" "$max" "$(( cur * 100 / max ))"
		printf "  gpu persist    %s\n" \
		       "$(nvidia-smi --query-gpu=persistence_mode --format=csv,noheader 2>/dev/null | head -1)"
	fi

	local bad=0
	for id in $HMD_USB_IDS; do
		local v="${id%%:*}" p="${id##*:}"
		for d in /sys/bus/usb/devices/*/; do
			[ "$(cat "$d/idVendor" 2>/dev/null)" = "$v" ] || continue
			[ "$(cat "$d/idProduct" 2>/dev/null)" = "$p" ] || continue
			[ "$(cat "$d/power/control" 2>/dev/null)" = "auto" ] && bad=1
		done
	done
	if [ "$bad" = 1 ]; then
		printf "  hmd usb        %ssome devices set to autosuspend%s\n" "$C_WARN" "$C_OFF"
	else
		printf "  hmd usb        %sautosuspend off on every headset device%s\n" "$C_OK" "$C_OFF"
	fi
	# Only meaningful when this ran as a plain report; after --apply it would say the exact
	# opposite of what just happened.
	if [ "${REPORT_ONLY:-1}" = 1 ]; then
		echo
		echo "  ${C_DIM}--apply needs root. Nothing above has been changed.${C_OFF}"
	fi
}

need_root() {
	[ "$(id -u)" = 0 ] || { echo "this needs root: sudo $0 $*" >&2; exit 1; }
}

apply() {
	need_root "$@"
	mkdir -p "$STATE_DIR"
	# Save once, so --restore puts back what was really there rather than a guess at defaults.
	if [ ! -f "$STATE" ]; then
		{
			echo "governor=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)"
			echo "epp=$(cat /sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference 2>/dev/null)"
			echo "aspm=$(sed 's/.*\[\(.*\)\].*/\1/' /sys/module/pcie_aspm/parameters/policy 2>/dev/null)"
			echo "gpu_w=$(gpu_cur_w)"
		} > "$STATE"
		echo "saved previous state -> $STATE"
	fi

	for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
		echo performance > "$f" 2>/dev/null
	done
	for f in /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference; do
		echo performance > "$f" 2>/dev/null
	done
	echo 1 > /sys/devices/system/cpu/cpufreq/boost 2>/dev/null
	echo performance > /sys/module/pcie_aspm/parameters/policy 2>/dev/null

	# Full watts by default. The point of --apply is "remove every variable"; deciding the GPU
	# can do the same work on fewer watts is a separate, measured decision (--gpu-limit).
	nvidia-smi -pm 1 >/dev/null 2>&1
	local max; max="$(gpu_max_w)"
	[ -n "$max" ] && nvidia-smi -pl "$max" >/dev/null 2>&1

	# Headset devices must never autosuspend: the USB2 branch on this cable is already
	# marginal (docs/22), and a suspended companion looks exactly like the cable fault.
	for id in $HMD_USB_IDS; do
		local v="${id%%:*}" p="${id##*:}"
		for d in /sys/bus/usb/devices/*/; do
			[ "$(cat "$d/idVendor" 2>/dev/null)" = "$v" ] || continue
			[ "$(cat "$d/idProduct" 2>/dev/null)" = "$p" ] || continue
			echo on > "$d/power/control" 2>/dev/null
		done
	done

	echo "applied."
	echo
	REPORT_ONLY=0 report
}

restore() {
	need_root "$@"
	[ -f "$STATE" ] || { echo "no saved state at $STATE -- nothing to restore" >&2; exit 1; }
	# shellcheck disable=SC1090
	. "$STATE"
	for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
		echo "${governor:-powersave}" > "$f" 2>/dev/null
	done
	for f in /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference; do
		echo "${epp:-balance_performance}" > "$f" 2>/dev/null
	done
	echo "${aspm:-default}" > /sys/module/pcie_aspm/parameters/policy 2>/dev/null
	[ -n "${gpu_w:-}" ] && nvidia-smi -pl "$gpu_w" >/dev/null 2>&1
	rm -f "$STATE"
	echo "restored."
}

gpu_limit() {
	need_root "$@"
	local pct="${2:-}"
	case "$pct" in
		''|*[!0-9]*) echo "usage: sudo $0 --gpu-limit <percent>" >&2; exit 1 ;;
	esac
	local max target
	max="$(gpu_max_w)"
	target=$(( max * pct / 100 ))
	local min; min="$(nvidia-smi --query-gpu=power.min_limit --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1)"
	if [ "$target" -lt "${min:-0}" ]; then
		echo "$pct% of ${max}W is ${target}W, below the card's ${min}W floor -- refusing" >&2
		exit 1
	fi
	nvidia-smi -pl "$target" >/dev/null 2>&1 && echo "gpu power limit -> ${target} W (${pct}% of ${max} W)"
	echo
	echo "Now re-measure, three windows minimum:  ./frame-pacing.sh"
	echo "If the pacing numbers are unchanged, the watts were not buying anything."
}

case "$MODE" in
	report)       report ;;
	--apply)      apply "$@" ;;
	--restore)    restore "$@" ;;
	--gpu-limit)  gpu_limit "$@" ;;
	*) echo "usage: $0 [--apply|--restore|--gpu-limit <pct>]" >&2; exit 1 ;;
esac
