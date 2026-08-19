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
#
# PER-BOX CONFIG: an optional ~/vr/power.conf (KEY=VALUE, one per line) lets a box carry its
# own validated numbers without hardcoding them here. --apply and a bare --gpu-limit both
# read it. Recognized keys:
#   GPU_LIMIT_PCT   percent, applied by --apply right after it sets full-performance watts;
#                   also the fallback value for `--gpu-limit` with no explicit argument.
#   RAPL_PUBLIC     1 to have --apply chmod the RAPL energy counter world-readable so
#                   power-log.sh can report real CPU watts unprivileged (see below).
# Lines that don't match KEY=VALUE are ignored with a warning; nothing here is box-specific.

set -u

MODE="${1:-report}"
STATE_DIR="/var/lib/vr-power-setup"
STATE="$STATE_DIR/saved-state"

C_OK=$'\033[1;32m'; C_WARN=$'\033[1;33m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'

HMD_USB_IDS="03f0:0580 045e:0659 04b4:6506 04b4:6504 0bda:4c15"

RAPL_ENERGY_FILE="/sys/class/powercap/intel-rapl:0/energy_uj"
RAPL_ENERGY_FILE_SUBZONE="/sys/class/powercap/intel-rapl:0:0/energy_uj"

# Under sudo, $HOME is root's home unless the caller preserved the environment -- resolve
# the invoking user's real home via SUDO_USER so ~/vr/power.conf means the same file
# whether this runs plain or under sudo.
user_home() {
	local u="" h=""
	# Plain sudo sets SUDO_USER; a root shell (sudo -i / su) does not -- fall back to
	# logname, then to the owner of this script file itself (caught live 2026-08-18:
	# --apply from a root shell resolved /root/vr and silently skipped power.conf).
	u="${SUDO_USER:-}"
	[ -z "$u" ] && u="$(logname 2>/dev/null || true)"
	[ -z "$u" ] || [ "$u" = "root" ] && u="$(stat -c %U "${BASH_SOURCE[0]}" 2>/dev/null || true)"
	if [ -n "$u" ] && [ "$u" != "root" ]; then
		h="$(getent passwd "$u" 2>/dev/null | cut -d: -f6)"
	fi
	echo "${h:-$HOME}"
}
CONF_FILE="$(user_home)/vr/power.conf"

GPU_LIMIT_PCT=""
RAPL_PUBLIC=""

load_power_conf() {
	[ -f "$CONF_FILE" ] || return 0
	local line key val
	while IFS= read -r line || [ -n "$line" ]; do
		case "$line" in
			''|'#'*) continue ;;
		esac
		if [[ ! "$line" =~ ^[A-Z_]+=[A-Za-z0-9.%-]*$ ]]; then
			echo "vr-power-setup: ignoring malformed line in $CONF_FILE: $line" >&2
			continue
		fi
		key="${line%%=*}"
		val="${line#*=}"
		case "$key" in
			GPU_LIMIT_PCT) GPU_LIMIT_PCT="$val" ;;
			RAPL_PUBLIC)   RAPL_PUBLIC="$val" ;;
			*) : ;; # unknown key -- forward-compatible, ignore silently
		esac
	done < "$CONF_FILE"
}

gpu_max_w()  { nvidia-smi --query-gpu=power.max_limit --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1; }
gpu_cur_w()  { nvidia-smi --query-gpu=power.limit     --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1; }

# True (exit 0) if $1's "other" permission bit is readable. Checked via the mode bits, not
# a plain `[ -r ]`, so the report is accurate regardless of whether it's run as root.
rapl_readable_by_others() {
	local mode
	mode="$(stat -c %a "$1" 2>/dev/null)" || return 2
	case "${mode: -1}" in
		[4-7]) return 0 ;;
		*) return 1 ;;
	esac
}

# Shared by --apply's config-driven cap and the standalone --gpu-limit command.
set_gpu_limit_pct() {
	local pct="$1"
	case "$pct" in
		''|*[!0-9]*) echo "invalid GPU_LIMIT_PCT '$pct' -- must be a whole percent" >&2; return 1 ;;
	esac
	local max target min
	max="$(gpu_max_w)"
	if [ -z "$max" ]; then
		echo "gpu power limit: could not read max watts (nvidia-smi unavailable?) -- skipped" >&2
		return 1
	fi
	target=$(( max * pct / 100 ))
	min="$(nvidia-smi --query-gpu=power.min_limit --format=csv,noheader,nounits 2>/dev/null | head -1 | cut -d. -f1)"
	if [ "$target" -lt "${min:-0}" ]; then
		echo "$pct% of ${max}W is ${target}W, below the card's ${min}W floor -- refusing" >&2
		return 1
	fi
	nvidia-smi -pl "$target" >/dev/null 2>&1 && echo "gpu power limit -> ${target} W (${pct}% of ${max} W)"
}

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

	if [ -e "$RAPL_ENERGY_FILE" ]; then
		if rapl_readable_by_others "$RAPL_ENERGY_FILE"; then
			printf "  rapl energy    %sreadable unprivileged (power-log.sh will see real CPU watts)%s\n" "$C_OK" "$C_OFF"
		else
			printf "  rapl energy    %sroot-only -- power-log.sh will read 0 CPU watts%s\n" "$C_WARN" "$C_OFF"
		fi
	else
		printf "  rapl energy    %sno RAPL energy_uj found on this box%s\n" "$C_DIM" "$C_OFF"
	fi

	if [ -f "$CONF_FILE" ]; then
		printf "  power.conf     %s  (GPU_LIMIT_PCT=%s RAPL_PUBLIC=%s)\n" \
		       "$CONF_FILE" "${GPU_LIMIT_PCT:-unset}" "${RAPL_PUBLIC:-unset}"
	else
		printf "  power.conf     %snot present at %s -- no per-box overrides%s\n" "$C_DIM" "$CONF_FILE" "$C_OFF"
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
		[ -e "$f" ] && echo performance > "$f" 2>/dev/null
	done
	for f in /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference; do
		# Doesn't exist under acpi-cpufreq (no EPP knob there) -- guard instead of letting
		# the redirect fail silently into 2>/dev/null every time.
		[ -e "$f" ] && echo performance > "$f" 2>/dev/null
	done
	echo 1 > /sys/devices/system/cpu/cpufreq/boost 2>/dev/null
	echo performance > /sys/module/pcie_aspm/parameters/policy 2>/dev/null

	# Full watts by default. The point of --apply is "remove every variable"; deciding the GPU
	# can do the same work on fewer watts is a separate, measured decision (--gpu-limit).
	nvidia-smi -pm 1 >/dev/null 2>&1
	local max; max="$(gpu_max_w)"
	[ -n "$max" ] && nvidia-smi -pl "$max" >/dev/null 2>&1

	# Per-box cap from ~/vr/power.conf, applied AFTER the full-power baseline above so it's
	# a deliberate cap on top of "everything else full", not a substitute for it.
	if [ -n "$GPU_LIMIT_PCT" ]; then
		set_gpu_limit_pct "$GPU_LIMIT_PCT"
	fi

	# Make the RAPL CPU-energy counter world-readable so power-log.sh can report real CPU
	# watts unprivileged. It's 0400 root-only by default and resets on every boot, which is
	# why this lives in --apply rather than a one-time chmod.
	if [ "${RAPL_PUBLIC:-0}" = 1 ]; then
		for f in "$RAPL_ENERGY_FILE" "$RAPL_ENERGY_FILE_SUBZONE"; do
			[ -e "$f" ] && chmod o+r "$f" 2>/dev/null
		done
	fi

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
		[ -e "$f" ] && echo "${governor:-powersave}" > "$f" 2>/dev/null
	done
	for f in /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference; do
		# Same guard as --apply: the knob does not exist under acpi-cpufreq, and an
		# unmatched glob leaves the literal path with a '*' in it. Restore must be at
		# least as careful as apply, or the box is left on whatever apply set.
		[ -e "$f" ] && echo "${epp:-balance_performance}" > "$f" 2>/dev/null
	done
	echo "${aspm:-default}" > /sys/module/pcie_aspm/parameters/policy 2>/dev/null
	[ -n "${gpu_w:-}" ] && nvidia-smi -pl "$gpu_w" >/dev/null 2>&1
	rm -f "$STATE"
	echo "restored."
}

gpu_limit() {
	need_root "$@"
	local pct="${2:-}"
	# No explicit argument -- fall back to this box's ~/vr/power.conf, if it set one.
	[ -z "$pct" ] && pct="$GPU_LIMIT_PCT"
	if [ -z "$pct" ]; then
		echo "usage: sudo $0 --gpu-limit <percent>  (or set GPU_LIMIT_PCT in $CONF_FILE)" >&2
		exit 1
	fi
	set_gpu_limit_pct "$pct" || exit 1
	echo
	echo "Now re-measure, three windows minimum:  ./frame-pacing.sh"
	echo "If the pacing numbers are unchanged, the watts were not buying anything."
}

load_power_conf

case "$MODE" in
	report)       report ;;
	--apply)      apply "$@" ;;
	--restore)    restore "$@" ;;
	--gpu-limit)  gpu_limit "$@" ;;
	*) echo "usage: $0 [--apply|--restore|--gpu-limit <pct>]" >&2; exit 1 ;;
esac
