#!/bin/bash
# bootstrap-lab.sh - deja un Debian 13 recién instalado listo para el lab de 90Hz.
#
#   ./bootstrap-lab.sh            todo (deps + repos + parches + build)
#   ./bootstrap-lab.sh deps       solo los paquetes apt
#   ./bootstrap-lab.sh nvidia     solo el driver 595 (pide reboot al final)
#   ./bootstrap-lab.sh sources    solo clonar y parchear los repos
#   ./bootstrap-lab.sh build      solo compilar monado/basalt/hello_xr
#   ./bootstrap-lab.sh patch-nv   aplicar los parches Project-VR al DKMS de NVIDIA
#
# El orden real es: deps -> nvidia -> REBOOT -> sources -> build -> patch-nv -> REBOOT.
# Corriendo sin argumentos hace deps+sources+build y te dice cuándo reiniciar.
#
# Pensado para correr DENTRO del sistema del lab, no en el sistema principal. Se niega a
# arrancar si detecta que está en el principal: instalar el 595-open ahí rompería el 550
# que hoy funciona (los stacks son excluyentes) y perderíamos el único entorno que anda.

set -u

BASE="${BASE:-$HOME/vr}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # reverb-g2-linux/
NVIDIA_VER="595.71.05"

# --- Guardas ------------------------------------------------------------------------------
if [ "$(id -u)" = "0" ]; then
	echo "No lo corras como root: usa sudo internamente y necesita tu \$HOME." >&2
	exit 1
fi
if [ -d /home/brunduk/Documents/linux_vr_base/monado ] && [ ! -f /etc/vr-lab-machine ]; then
	cat >&2 <<-EOF
	ALTO. Esto parece el sistema PRINCIPAL, no el lab.

	Instalar el driver 595-open acá reemplaza el 550 que hoy funciona y te quedás sin
	entorno andando. El lab es una instalación aparte, en el otro disco.

	Si de verdad estás en el lab y la detección se equivocó:
	    sudo touch /etc/vr-lab-machine
	EOF
	exit 1
fi
command -v apt >/dev/null || { echo "Esto es para Debian/Ubuntu." >&2; exit 1; }

STEP="${1:-all}"

# --- Paso: dependencias --------------------------------------------------------------------
do_deps() {
	echo "### Paquetes base"
	sudo apt update
	sudo apt install -y \
		build-essential dkms linux-headers-amd64 git curl ca-certificates \
		cmake ninja-build meson pkg-config glslang-tools \
		libvulkan-dev vulkan-tools vulkan-validationlayers \
		libeigen3-dev libusb-1.0-0-dev libudev-dev libhidapi-dev \
		libgl-dev libglx-dev libglvnd-dev libxcb-randr0-dev libx11-xcb-dev \
		libxrandr-dev libwayland-dev wayland-protocols \
		libavcodec-dev libavformat-dev libavutil-dev libswscale-dev ffmpeg \
		libopencv-dev libboost-all-dev libtbb-dev libfmt-dev \
		x11-xserver-utils pciutils usbutils

	echo "### Reglas udev del casco"
	sudo cp "$REPO_DIR/scripts/70-wmr-reverb.rules" "$REPO_DIR/scripts/71-usb-no-autosuspend.rules" /etc/udev/rules.d/
	sudo udevadm control --reload-rules
	sudo usermod -aG plugdev,adm,systemd-journal "$USER"
	echo "    (el cambio de grupos necesita cerrar y abrir sesión)"
}

# --- Paso: driver NVIDIA -------------------------------------------------------------------
do_nvidia() {
	echo "### Driver NVIDIA $NVIDIA_VER (repo oficial de NVIDIA para debian13)"
	echo "    NO usar el nvidia-driver de Debian: los stacks son excluyentes."
	curl -fsSL -o /tmp/cuda-keyring.deb \
		https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/cuda-keyring_1.1-1_all.deb
	sudo dpkg -i /tmp/cuda-keyring.deb
	sudo apt update
	sudo apt install -y "nvidia-driver-pinning-$NVIDIA_VER"
	sudo apt install -y nvidia-open
	echo
	echo ">>> REINICIAR AHORA, y después: $0 sources"
}

# --- Paso: código fuente -------------------------------------------------------------------
# Se clona de upstream y se aplican nuestros parches, en vez de traer los árboles enteros:
# el bundle queda en kilobytes y se ve exactamente qué cambiamos nosotros. Los SHA son las
# bases exactas contra las que los parches fueron generados y probados.
clone_at() {   # url dir sha
	local url="$1" dir="$2" sha="$3"
	if [ -d "$dir/.git" ]; then
		echo "    $dir ya existe, no lo toco"
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
		826fb91ffdfbb2808d0821e07fff18025e9ec3fa
	git -C monado am "$REPO_DIR/patches/monado/"*.patch || {
		echo "    Los parches de Monado no aplicaron limpio. 'git -C monado am --abort' y revisar." >&2
		return 1
	}
	echo "    NOTA: falta además el parche 90Hz de Project-VR (nominal_frame_interval 1e9/90)."
	echo "          Sin él el intervalo nominal queda en 60Hz. Ver docs/04-lab-90hz.md paso 5."

	echo "### Basalt (SLAM, sin parches nuestros)"
	clone_at https://gitlab.freedesktop.org/mateosss/basalt.git basalt \
		df6e970c8da7636eb401a09e3317fbeaaf829b9a
	git -C basalt submodule update --init --recursive

	echo "### OpenXR-SDK-Source (el player 360/VR180)"
	clone_at https://github.com/KhronosGroup/OpenXR-SDK-Source.git OpenXR-SDK-Source \
		c610211f38f4e1e4ac811ced6135e144eedc7cf2
	git -C OpenXR-SDK-Source am "$REPO_DIR/patches/hello_xr-player/"*.patch || {
		echo "    Los parches del player no aplicaron limpio." >&2
		return 1
	}
}

# --- Paso: compilar ------------------------------------------------------------------------
do_build() {
	cd "$BASE" || { echo "No existe $BASE, corré '$0 sources' primero" >&2; exit 1; }

	echo "### Basalt"
	cmake -S basalt -B basalt/build -GNinja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
		-DBASALT_INSTANTIATIONS_DOUBLE=OFF
	ninja -C basalt/build

	echo "### Monado"
	cmake -S monado -B monado/build -GNinja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
		-DXRT_HAVE_BASALT=ON -DXRT_FEATURE_SERVICE=ON
	ninja -C monado/build

	echo "### hello_xr (player 360/VR180)"
	cmake -S OpenXR-SDK-Source -B OpenXR-SDK-Source/build -GNinja \
		-DBUILD_TESTS=ON -DBUILD_API_LAYERS=OFF -DBUILD_CONFORMANCE_TESTS=OFF
	ninja -C OpenXR-SDK-Source/build hello_xr

	echo "### Scripts de arranque"
	cp "$REPO_DIR/scripts/jack-in.sh" "$REPO_DIR/scripts/play360.sh" "$REPO_DIR/scripts/get360.sh" "$BASE/"
	chmod +x "$BASE"/*.sh
	echo
	echo "    OJO: jack-in.sh tiene hardcodeadas las salidas de video del sistema principal"
	echo "    (HDMI-1 / DP-3 / HDMI-0). En el lab hay que ajustar reassert_monitors() a lo"
	echo "    que diga 'xrandr --query' acá."
}

# --- Paso: parches de NVIDIA vía DKMS -------------------------------------------------------
do_patch_nv() {
	local SRC="/usr/src/nvidia-$NVIDIA_VER"
	[ -d "$SRC" ] || { echo "No existe $SRC. ¿Instalaste el driver? ($0 nvidia)" >&2; exit 1; }

	echo "### Parches Project-VR sobre el árbol DKMS de NVIDIA"
	sudo mkdir -p "$SRC/patches"
	sudo cp "$REPO_DIR/patches/nvidia/"000*.patch "$SRC/patches/"

	echo "### Verificando en seco antes de tocar nada"
	local fail=0
	for p in "$SRC/patches/"000*.patch; do
		if sudo patch -d "$SRC" -p1 --dry-run --force < "$p" >/dev/null 2>&1; then
			echo "    OK   $(basename "$p")"
		else
			echo "    FALLA $(basename "$p")" >&2
			fail=1
		fi
	done
	[ "$fail" = "0" ] || {
		echo "Algún parche no aplica sobre este árbol. Ver docs/04-lab-90hz.md: en 610.x hay" >&2
		echo "que dropear los hunks de flatnessDetThresh del 0001." >&2
		exit 1
	}

	if grep -q '^PATCH\[0\]' "$SRC/dkms.conf" 2>/dev/null; then
		echo "    dkms.conf ya tiene los PATCH[], no lo duplico"
	else
		# El mecanismo PATCH[] de dkms aplica sobre una COPIA en cada build, así que el
		# árbol fuente queda limpio y un upgrade de kernel re-aplica todo solo.
		sudo tee -a "$SRC/dkms.conf" >/dev/null <<-EOF
		PATCH[0]="0001-nvkms-VESA-DisplayID-DSC-VSDB-spec-correctness-fixes.patch"
		PATCH[1]="0002-nvkms-nvidia-drm-enable-Wayland-DRM-lease-of-VR-HMDs.patch"
		PATCH[2]="0003-dp-force-maximum-link-config-for-the-HP-Reverb-G2-ED.patch"
		EOF
	fi

	sudo dkms remove "nvidia/$NVIDIA_VER" --all || true
	sudo dkms install "nvidia/$NVIDIA_VER"
	echo
	echo ">>> REINICIAR. Después probar 90Hz:"
	echo "    XRT_COMPOSITOR_DESIRED_MODE=0 ./jack-in.sh 3dof   # 2880x1440@90 nativo"
	echo "    (si falla, MODE=1 = 4320x2160@90)"
	echo ">>> Y MIRAR EL PANEL FÍSICAMENTE. La API reporta 90fps aunque esté negro."
}

case "$STEP" in
	deps)     do_deps ;;
	nvidia)   do_nvidia ;;
	sources)  do_sources ;;
	build)    do_build ;;
	patch-nv) do_patch_nv ;;
	all)
		do_deps
		do_sources
		do_build
		echo
		echo "=== Falta el driver: '$0 nvidia', reiniciar, y después '$0 patch-nv' ==="
		;;
	*) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
