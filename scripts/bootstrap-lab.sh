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
# Se puede correr como usuario normal (escala con sudo) o directamente como root, por
# ejemplo desde 'sudo -i', para no tipear la password en cada paso. Como root necesita
# saber de quién es el $HOME donde viven los repos: lo deduce de $SUDO_USER, y si no, del
# dueño de este repo. Se puede forzar con TARGET_USER=... El paso a usuario NO es una
# formalidad: compilar Monado como root deja un árbol root-owned que después no podés ni
# recompilar ni borrar sin sudo.
#
# Pensado para correr DENTRO del sistema del lab, no en el sistema principal. Se niega a
# arrancar si detecta que está en el principal: instalar el 595-open ahí rompería el 550
# que hoy funciona (los stacks son excluyentes) y perderíamos el único entorno que anda.

set -u

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # reverb-g2-linux/
NVIDIA_VER="595.71.05"

# --- Quién soy y cómo escalo ---------------------------------------------------------------
if [ "$(id -u)" = "0" ]; then
	IS_ROOT=1
	SUDO=""
	TARGET_USER="${TARGET_USER:-${SUDO_USER:-}}"
	[ -n "$TARGET_USER" ] || TARGET_USER="$(stat -c %U "$REPO_DIR" 2>/dev/null || true)"
	if [ -z "$TARGET_USER" ] || [ "$TARGET_USER" = "root" ]; then
		echo "Corriendo como root no puedo deducir el usuario del lab (ni \$SUDO_USER ni el" >&2
		echo "dueño de $REPO_DIR sirven). Repetilo así:" >&2
		echo "    TARGET_USER=tuusuario $0 ${1:-}" >&2
		exit 1
	fi
	TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
	[ -n "$TARGET_HOME" ] || { echo "El usuario '$TARGET_USER' no existe." >&2; exit 1; }
	# runuser vive en /usr/sbin, que no está en el PATH de un usuario normal.
	RUNUSER="$(command -v runuser || true)"
	[ -n "$RUNUSER" ] || RUNUSER=/usr/sbin/runuser
	[ -x "$RUNUSER" ] || { echo "Falta 'runuser' (util-linux)." >&2; exit 1; }
else
	IS_ROOT=0
	SUDO="sudo"
	TARGET_USER="$USER"
	TARGET_HOME="$HOME"
fi
BASE="${BASE:-$TARGET_HOME/vr}"

# Los pasos que no necesitan privilegios (clonar, parchear, compilar) se corren SIEMPRE como
# el usuario del lab, aunque hayamos entrado como root. Reinvoca este mismo script: adentro
# ya no somos root, así que cae por la rama normal.
as_user_step() {
	if [ "$IS_ROOT" = "1" ]; then
		echo "    (paso '$1' como $TARGET_USER, para no dejar el árbol root-owned)"
		"$RUNUSER" -u "$TARGET_USER" -- env HOME="$TARGET_HOME" BASE="$BASE" "$0" "$1"
	else
		"do_$1"
	fi
}

# --- Guardas ------------------------------------------------------------------------------
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
	$SUDO apt update
	$SUDO apt install -y \
		build-essential dkms linux-headers-amd64 git curl ca-certificates \
		cmake ninja-build meson pkg-config glslang-tools \
		libvulkan-dev vulkan-tools vulkan-validationlayers \
		libeigen3-dev libusb-1.0-0-dev libudev-dev libhidapi-dev \
		libgl-dev libglx-dev libglvnd-dev libxcb-randr0-dev libx11-xcb-dev \
		libxrandr-dev libxxf86vm-dev libxcb-glx0-dev libwayland-dev wayland-protocols \
		libavcodec-dev libavformat-dev libavutil-dev libswscale-dev ffmpeg \
		libopencv-dev libboost-all-dev libtbb-dev libfmt-dev \
		x11-xserver-utils pciutils usbutils time

	echo "### Reglas udev del casco"
	$SUDO cp "$REPO_DIR/scripts/70-wmr-reverb.rules" "$REPO_DIR/scripts/71-usb-no-autosuspend.rules" /etc/udev/rules.d/
	$SUDO udevadm control --reload-rules
	$SUDO usermod -aG plugdev,adm,systemd-journal "$TARGET_USER"
	echo "    (el cambio de grupos de $TARGET_USER necesita cerrar y abrir sesión)"
}

# --- Paso: driver NVIDIA -------------------------------------------------------------------
do_nvidia() {
	echo "### Driver NVIDIA $NVIDIA_VER (repo oficial de NVIDIA para debian13)"
	echo "    NO usar el nvidia-driver de Debian: los stacks son excluyentes."
	curl -fsSL -o /tmp/cuda-keyring.deb \
		https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/cuda-keyring_1.1-1_all.deb
	$SUDO dpkg -i /tmp/cuda-keyring.deb
	$SUDO apt update
	$SUDO apt install -y "nvidia-driver-pinning-$NVIDIA_VER"
	$SUDO apt install -y nvidia-open
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

	# Sin esto un cmake que falla se lo come el pipe (típicamente '| tail') y el script
	# termina en 0 con medio árbol sin compilar. Pasó: hello_xr no configuró por falta de
	# libxxf86vm-dev y el bootstrap dio "todo bien". Cada paso aborta explícito.
	local step
	step() {   # step <descripción> <comando...>
		local what="$1"; shift
		"$@" || { echo "FALLO: $what" >&2; return 1; }
	}

	echo "### Basalt"
	step "cmake basalt" cmake -S basalt -B basalt/build -GNinja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
		-DBASALT_INSTANTIATIONS_DOUBLE=OFF || return 1
	step "ninja basalt" ninja -C basalt/build || return 1

	echo "### Monado"
	step "cmake monado" cmake -S monado -B monado/build -GNinja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
		-DXRT_HAVE_BASALT=ON -DXRT_FEATURE_SERVICE=ON || return 1
	step "ninja monado" ninja -C monado/build || return 1

	echo "### hello_xr (player 360/VR180)"
	step "cmake hello_xr" cmake -S OpenXR-SDK-Source -B OpenXR-SDK-Source/build -GNinja \
		-DBUILD_TESTS=ON -DBUILD_API_LAYERS=OFF -DBUILD_CONFORMANCE_TESTS=OFF || return 1
	step "ninja hello_xr" ninja -C OpenXR-SDK-Source/build hello_xr || return 1

	echo "### Scripts de arranque"
	cp "$REPO_DIR/scripts/jack-in.sh" "$REPO_DIR/scripts/play360.sh" "$REPO_DIR/scripts/get360.sh" "$BASE/"
	chmod +x "$BASE"/*.sh
	echo
	echo "    jack-in.sh detecta solo dónde están los árboles (VR_BASE) y saca una foto del"
	echo "    layout de monitores antes de tocar los CRTC, así que ya no hay salidas de video"
	echo "    hardcodeadas. Si el casco no cuelga de DP-0, pasarle HMD_OUTPUT=DP-x."
}

# --- Paso: parches de NVIDIA vía DKMS -------------------------------------------------------
do_patch_nv() {
	local SRC="/usr/src/nvidia-$NVIDIA_VER"
	[ -d "$SRC" ] || { echo "No existe $SRC. ¿Instalaste el driver? ($0 nvidia)" >&2; exit 1; }

	echo "### Parches Project-VR sobre el árbol DKMS de NVIDIA"
	$SUDO mkdir -p "$SRC/patches"
	$SUDO cp "$REPO_DIR/patches/nvidia/"000*.patch "$SRC/patches/"

	echo "### Verificando en seco antes de tocar nada"
	local fail=0
	for p in "$SRC/patches/"000*.patch; do
		if $SUDO patch -d "$SRC" -p1 --dry-run --force < "$p" >/dev/null 2>&1; then
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
		$SUDO tee -a "$SRC/dkms.conf" >/dev/null <<-EOF
		PATCH[0]="0001-nvkms-VESA-DisplayID-DSC-VSDB-spec-correctness-fixes.patch"
		PATCH[1]="0002-nvkms-nvidia-drm-enable-Wayland-DRM-lease-of-VR-HMDs.patch"
		PATCH[2]="0003-dp-force-maximum-link-config-for-the-HP-Reverb-G2-ED.patch"
		EOF
	fi

	$SUDO dkms remove "nvidia/$NVIDIA_VER" --all || true
	$SUDO dkms install "nvidia/$NVIDIA_VER"
	echo
	echo ">>> REINICIAR. Después probar 90Hz:"
	echo "    XRT_COMPOSITOR_DESIRED_MODE=0 ./jack-in.sh 3dof   # 2880x1440@90 nativo"
	echo "    (si falla, MODE=1 = 4320x2160@90)"
	echo ">>> Y MIRAR EL PANEL FÍSICAMENTE. La API reporta 90fps aunque esté negro."
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
		echo "=== Falta el driver: '$0 nvidia', reiniciar, y después '$0 patch-nv' ==="
		;;
	*) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
