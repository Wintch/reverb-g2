#!/bin/bash
# bootstrap-lab.sh - take a freshly installed Debian 13 to a working 90 Hz lab.
#
#   ./bootstrap-lab.sh            everything (deps + repos + patches + build)
#   ./bootstrap-lab.sh deps       apt packages only
#   ./bootstrap-lab.sh nvidia     the 595 driver only (asks for a reboot at the end)
#   ./bootstrap-lab.sh sources    clone and patch the upstream repos only
#   ./bootstrap-lab.sh build      compile monado/basalt/hello_xr only
#   ./bootstrap-lab.sh patch-nv   apply the Project-VR patches to NVIDIA's DKMS tree
#
# The real order is: deps -> nvidia -> REBOOT -> sources -> build -> patch-nv -> REBOOT.
# Running with no argument does deps+sources+build and tells you when to reboot.
#
# Runs either as a normal user (escalating with sudo) or directly as root, e.g. from
# 'sudo -i', so you do not retype the password at every step. As root it needs to know
# whose $HOME holds the repos: it infers that from $SUDO_USER, and failing that from the
# owner of this repo. Override with TARGET_USER=... Dropping to the user is NOT a
# formality: building Monado as root leaves a root-owned tree you can then neither
# rebuild nor delete without sudo.
#
# Meant to run INSIDE the lab system, not on your working system. Installing 595-open
# replaces whatever NVIDIA driver is already there — the stacks are mutually exclusive —
# so it refuses to start on a machine with a different driver already loaded.

set -u

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # reverb-g2/
NVIDIA_VER="595.71.05"

# --- Who am I and how do I escalate --------------------------------------------------------
if [ "$(id -u)" = "0" ]; then
	IS_ROOT=1
	SUDO=""
	TARGET_USER="${TARGET_USER:-${SUDO_USER:-}}"
	[ -n "$TARGET_USER" ] || TARGET_USER="$(stat -c %U "$REPO_DIR" 2>/dev/null || true)"
	if [ -z "$TARGET_USER" ] || [ "$TARGET_USER" = "root" ]; then
		echo "Running as root I cannot work out the lab user (neither \$SUDO_USER nor the" >&2
		echo "owner of $REPO_DIR helps). Run it like this instead:" >&2
		echo "    TARGET_USER=youruser $0 ${1:-}" >&2
		exit 1
	fi
	TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
	[ -n "$TARGET_HOME" ] || { echo "No such user: '$TARGET_USER'." >&2; exit 1; }
	# runuser lives in /usr/sbin, which is not on a normal user's PATH.
	RUNUSER="$(command -v runuser || true)"
	[ -n "$RUNUSER" ] || RUNUSER=/usr/sbin/runuser
	[ -x "$RUNUSER" ] || { echo "Missing 'runuser' (util-linux)." >&2; exit 1; }
else
	IS_ROOT=0
	SUDO="sudo"
	TARGET_USER="$USER"
	TARGET_HOME="$HOME"
fi
BASE="${BASE:-$TARGET_HOME/vr}"

# The steps that need no privileges (clone, patch, build) ALWAYS run as the lab user, even
# when we came in as root. It re-invokes this same script: inside, we are no longer root, so
# it takes the normal branch.
as_user_step() {
	if [ "$IS_ROOT" = "1" ]; then
		echo "    (step '$1' as $TARGET_USER, so the tree does not end up root-owned)"
		"$RUNUSER" -u "$TARGET_USER" -- env HOME="$TARGET_HOME" BASE="$BASE" "$0" "$1"
	else
		"do_$1"
	fi
}

# --- Guards --------------------------------------------------------------------------------
# Installing 595-open uninstalls whatever NVIDIA driver is currently loaded. If a different
# version is running, this is probably your working system rather than the lab.
if [ ! -f /etc/vr-lab-machine ] && command -v nvidia-smi >/dev/null 2>&1; then
	CURRENT_NV="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)"
	if [ -n "$CURRENT_NV" ] && [ "$CURRENT_NV" != "$NVIDIA_VER" ]; then
		cat >&2 <<-EOF
		STOP. This machine is already running NVIDIA $CURRENT_NV.

		Installing $NVIDIA_VER-open replaces it, and the stacks are mutually exclusive: if
		this is the system you actually work on, you will lose a working environment. The
		lab is meant to be a separate install, ideally on a separate disk.

		If this really is the lab:
		    sudo touch /etc/vr-lab-machine
		EOF
		exit 1
	fi
fi
command -v apt >/dev/null || { echo "This is for Debian/Ubuntu." >&2; exit 1; }

STEP="${1:-all}"

# --- Step: dependencies --------------------------------------------------------------------
do_deps() {
	echo "### Base packages"
	$SUDO apt update
	$SUDO apt install -y \
		build-essential dkms linux-headers-amd64 git curl ca-certificates \
		cmake ninja-build meson pkg-config glslang-tools \
		libvulkan-dev vulkan-tools vulkan-validationlayers \
		libeigen3-dev libusb-1.0-0-dev libudev-dev libhidapi-dev \
		libgl-dev libglx-dev libglvnd-dev libxcb-randr0-dev libx11-xcb-dev \
		libxrandr-dev libxxf86vm-dev libxcb-glx0-dev libwayland-dev wayland-protocols \
		libdrm-dev \
		libavcodec-dev libavformat-dev libavutil-dev libswscale-dev ffmpeg \
		libopencv-dev libboost-all-dev libtbb-dev libfmt-dev \
		libsdl2-dev python3-pil \
		x11-xserver-utils pciutils usbutils time
	# libsdl2-dev: Monado's debug GUI / compositor mirror (XRT_FEATURE_DEBUG_GUI, see
	# do_build below) silently needs SDL2, not GLFW as its symbol names might suggest -
	# cmake just leaves the feature off with no error if it's missing. Cost a rebuild cycle
	# to find (2026-08-06).
	# python3-pil: scripts/panel-cam-analyze.py (webcam-based panel state detection).
	# libdrm-dev is NOT optional even though nothing fails without it. Monado's logic is
	#   XRT_HAVE_WAYLAND DEPENDS WAYLAND_FOUND WAYLAND_SCANNER_FOUND WAYLAND_PROTOCOLS_FOUND LIBDRM_FOUND
	# so without libdrm-dev the WHOLE of Wayland drops out — and with it XRT_HAVE_WAYLAND_DIRECT,
	# which is the DRM lease backend. cmake says nothing: it just leaves the options OFF and
	# builds anyway. The symptom shows up much later, at runtime:
	#   "Could not find target factory with identifier 'direct_wayland'"
	# This cost a whole session (2026-08-04). See docs/04, the Wayland section.

	echo "### udev rules for the headset"
	$SUDO cp "$REPO_DIR/scripts/70-wmr-reverb.rules" "$REPO_DIR/scripts/71-usb-no-autosuspend.rules" /etc/udev/rules.d/
	$SUDO udevadm control --reload-rules
	$SUDO usermod -aG plugdev,adm,systemd-journal "$TARGET_USER"
	echo "    (the group change for $TARGET_USER needs a log out and back in)"
}

# --- Step: NVIDIA driver -------------------------------------------------------------------
do_nvidia() {
	echo "### NVIDIA driver $NVIDIA_VER (NVIDIA's own debian13 repo)"
	echo "    Do NOT use Debian's nvidia-driver: the stacks are mutually exclusive."
	curl -fsSL -o /tmp/cuda-keyring.deb \
		https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/cuda-keyring_1.1-1_all.deb
	$SUDO dpkg -i /tmp/cuda-keyring.deb
	$SUDO apt update
	$SUDO apt install -y "nvidia-driver-pinning-$NVIDIA_VER"
	$SUDO apt install -y nvidia-open
	echo
	echo ">>> REBOOT NOW, then: $0 sources"
}

# --- Step: source trees --------------------------------------------------------------------
# We clone upstream and apply our patches rather than vendoring whole trees: the bundle stays
# in the kilobytes and it is obvious exactly what we changed. The SHAs are the exact bases the
# patches were generated and tested against.
clone_at() {   # url dir sha
	local url="$1" dir="$2" sha="$3"
	if [ -d "$dir/.git" ]; then
		echo "    $dir already exists, leaving it alone"
		return 0
	fi
	git clone "$url" "$dir"
	git -C "$dir" checkout -B lab "$sha"
}

do_sources() {
	mkdir -p "$BASE"
	cd "$BASE" || exit 1

	echo "### Monado"
	clone_at https://gitlab.freedesktop.org/monado/monado.git monado \
		735e29e4e7552b254528dbb20e0e96ec8f32368c
	git -C monado am "$REPO_DIR/patches/monado/"*.patch || {
		echo "    The Monado patches did not apply cleanly. 'git -C monado am --abort' and look." >&2
		return 1
	}
	echo "    NOTE: the Project-VR 90 Hz patch (nominal_frame_interval 1e9/90) is still missing."
	echo "          Without it the nominal interval stays at 60 Hz. See docs/04-lab-90hz.md step 5."

	echo "### Basalt (SLAM, no patches of ours)"
	clone_at https://gitlab.freedesktop.org/mateosss/basalt.git basalt \
		df6e970c8da7636eb401a09e3317fbeaaf829b9a
	git -C basalt submodule update --init --recursive

	echo "### OpenXR-SDK-Source (the 360/VR180 player)"
	clone_at https://github.com/KhronosGroup/OpenXR-SDK-Source.git OpenXR-SDK-Source \
		c610211f38f4e1e4ac811ced6135e144eedc7cf2
	git -C OpenXR-SDK-Source am "$REPO_DIR/patches/hello_xr-player/"*.patch || {
		echo "    The player patches did not apply cleanly." >&2
		return 1
	}
}

# --- Step: build ---------------------------------------------------------------------------
do_build() {
	cd "$BASE" || { echo "$BASE does not exist, run '$0 sources' first" >&2; exit 1; }

	# Without this a failing cmake gets swallowed by the pipe (typically '| tail') and the
	# script exits 0 with half the tree unbuilt. It happened: hello_xr failed to configure
	# for want of libxxf86vm-dev and bootstrap reported success. Each step aborts explicitly.
	local step
	step() {   # step <description> <command...>
		local what="$1"; shift
		"$@" || { echo "FAILED: $what" >&2; return 1; }
	}

	echo "### Basalt"
	step "cmake basalt" cmake -S basalt -B basalt/build -GNinja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
		-DBASALT_INSTANTIATIONS_DOUBLE=OFF || return 1
	step "ninja basalt" ninja -C basalt/build || return 1

	echo "### Monado"
	step "cmake monado" cmake -S monado -B monado/build -GNinja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
		-DXRT_HAVE_BASALT=ON -DXRT_FEATURE_SERVICE=ON -DXRT_FEATURE_DEBUG_GUI=ON || return 1
	step "ninja monado" ninja -C monado/build || return 1
	echo "    XRT_FEATURE_DEBUG_GUI=ON: run monado-service with XRT_DEBUG_GUI=1 for a live"
	echo "    compositor mirror + timing panels (needs libsdl2-dev, see do_deps). Window"
	echo "    layout persists on its own in ~/.config/monado/imgui.ini after the first run."

	echo "### hello_xr (360/VR180 player)"
	step "cmake hello_xr" cmake -S OpenXR-SDK-Source -B OpenXR-SDK-Source/build -GNinja \
		-DBUILD_TESTS=ON -DBUILD_API_LAYERS=OFF -DBUILD_CONFORMANCE_TESTS=OFF || return 1
	step "ninja hello_xr" ninja -C OpenXR-SDK-Source/build hello_xr || return 1

	echo "### Launcher scripts"
	cp "$REPO_DIR/scripts/jack-in.sh" "$REPO_DIR/scripts/play360.sh" "$REPO_DIR/scripts/get360.sh" "$BASE/"
	chmod +x "$BASE"/*.sh
	echo
	echo "    jack-in.sh finds the trees on its own (VR_BASE) and snapshots the monitor"
	echo "    layout before touching any CRTC, so there are no hardcoded video outputs"
	echo "    left. If your headset is not on DP-0, pass HMD_OUTPUT=DP-x."
}

# --- Step: NVIDIA patches via DKMS ---------------------------------------------------------
do_patch_nv() {
	local SRC="/usr/src/nvidia-$NVIDIA_VER"
	[ -d "$SRC" ] || { echo "$SRC does not exist. Did you install the driver? ($0 nvidia)" >&2; exit 1; }

	echo "### Project-VR patches on NVIDIA's DKMS tree"
	$SUDO mkdir -p "$SRC/patches"
	$SUDO cp "$REPO_DIR/patches/nvidia/"000*.patch "$SRC/patches/"

	echo "### Dry run before touching anything"
	local fail=0
	for p in "$SRC/patches/"000*.patch; do
		if $SUDO patch -d "$SRC" -p1 --dry-run --force < "$p" >/dev/null 2>&1; then
			echo "    OK   $(basename "$p")"
		else
			echo "    FAIL $(basename "$p")" >&2
			fail=1
		fi
	done
	[ "$fail" = "0" ] || {
		echo "Some patch does not apply to this tree. See docs/04-lab-90hz.md: on 610.x you" >&2
		echo "have to drop the flatnessDetThresh hunks from 0001." >&2
		exit 1
	}

	if grep -q '^PATCH\[0\]' "$SRC/dkms.conf" 2>/dev/null; then
		echo "    dkms.conf already has the PATCH[] lines, not duplicating them"
	else
		# dkms's PATCH[] mechanism applies to a COPY on every build, so the source tree
		# stays clean and a kernel upgrade re-applies everything by itself.
		$SUDO tee -a "$SRC/dkms.conf" >/dev/null <<-EOF
		PATCH[0]="0001-nvkms-VESA-DisplayID-DSC-VSDB-spec-correctness-fixes.patch"
		PATCH[1]="0002-nvkms-nvidia-drm-enable-Wayland-DRM-lease-of-VR-HMDs.patch"
		PATCH[2]="0003-dp-force-maximum-link-config-for-the-HP-Reverb-G2-ED.patch"
		PATCH[3]="0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch"
		EOF
	fi

	$SUDO dkms remove "nvidia/$NVIDIA_VER" --all || true
	$SUDO dkms install "nvidia/$NVIDIA_VER"
	echo
	echo ">>> REBOOT. Then try 90 Hz:"
	echo "    XRT_COMPOSITOR_DESIRED_MODE=0 ./jack-in.sh 3dof   # native 2880x1440@90"
	echo "    (if that fails, MODE=1 = 4320x2160@90)"
	echo ">>> AND LOOK AT THE PANEL. The API reports 90 fps even when it is black."
}

case "$STEP" in
	deps)     do_deps ;;
	nvidia)   do_nvidia ;;
	sources)  as_user_step sources ;;
	build)    as_user_step build ;;
	patch-nv) do_patch_nv ;;
	all)
		do_deps       || exit 1
		as_user_step sources || exit 1
		as_user_step build   || exit 1
		echo
		echo "=== Driver still missing: '$0 nvidia', reboot, then '$0 patch-nv' ==="
		;;
	*) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
