#!/bin/bash
# play360.sh - show a 360 / VR180 / flat video or photo in the headset.
#
#   ./play360.sh video.mp4              play it on a loop (5 minutes, then quit)
#   ./play360.sh carpeta/               play every video in the carpeta, one after another
#   ./play360.sh -t 60 video.mp4        play for 60 seconds
#   ./play360.sh -s foto.jpg            a still photo instead of a video
#   ./play360.sh -p 180 -e sbs v.mp4    force the projection / stereo layout
#   ./play360.sh -f 180x180 v.mp4       force the arc the 180 frame covers
#   ./play360.sh -w 45 v.mp4            width of the virtual screen, in degrees (flat mode)
#   ./play360.sh -q video.mp4           without the per-second timing stats
#
# The player prints what it detected before drawing anything:
#
#     MODO: VR180 3D (side-by-side)
#     Archivo: 7680x4096  ->  3840x4096 por ojo  |  59.94 fps  |  av1
#
# If that line is wrong the picture will still look plausible - a VR180 file read as 360 just
# looks like a strangely cropped panorama - so check it before blaming the footage. Override
# with -p (360 | 180 | flat) and -e (mono | sbs | tb).
#
# Transport keys (they need this script run from a real terminal, not piped or backgrounded -
# the player reads them from stdin):
#
#   espacio  pausa / seguir            (mando: gatillo)
#   [  ]     mas lento / mas rapido (0.125x .. 4x)
#   1        velocidad normal
#   h  l     seek -10s / +10s          (mando: stick a los costados)
#   enter    recentrar "adelante"      (mando: apretar fuerte el grip)
#   n        siguiente video de la playlist
#   q        salir                     (mando: mantener menu izquierdo ~1.5s, barra roja)
#
# HELLO_XR_THEME=night pinta de negro el espacio vacio fuera del video (default: gris claro).
#
# Requires the stack to be up: ./jack-in.sh 3dof

set -u

# Dónde viven los árboles. El sistema principal los tiene en ~/Documents/linux_vr_base; el lab
# (bootstrap-lab.sh) en ~/vr. Misma autodetección que jack-in.sh — hasta el 2026-08-04 esto estaba
# hardcodeado al sistema principal y en el lab fallaba con "falta compilar hello_xr". VR_BASE=...
# lo fuerza.
if [ -n "${VR_BASE:-}" ]; then
	:
elif [ -d "$HOME/Documents/linux_vr_base/monado/build" ]; then
	VR_BASE="$HOME/Documents/linux_vr_base"
else
	VR_BASE="$HOME/vr"
fi
MONADO_BUILD="$VR_BASE/monado/build"
HELLO_XR="$VR_BASE/OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr"

SECONDS_TO_RUN=300
PHOTO=0
STATS=1
ENV_EXTRA=()

while getopts "t:sp:e:f:w:qh" opt; do
	case "$opt" in
		t) SECONDS_TO_RUN="$OPTARG" ;;
		s) PHOTO=1 ;;
		p) ENV_EXTRA+=("HELLO_XR_PROJECTION=$OPTARG") ;;
		e) ENV_EXTRA+=("HELLO_XR_STEREO=$OPTARG") ;;
		f) ENV_EXTRA+=("HELLO_XR_PANO_FOV=$OPTARG") ;;
		w) ENV_EXTRA+=("HELLO_XR_SCREEN_FOV=$OPTARG") ;;
		q) STATS=0 ;;
		h|*) sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
	esac
done
shift $((OPTIND - 1))

if [ $# -lt 1 ]; then
	echo "usage: $0 [-t SEGUNDOS] [-s] [-p 360|180|flat] [-e mono|sbs|tb] [-f AxB] [-w GRADOS] [-q] <archivo>" >&2
	exit 1
fi
FILE="$1"
# A directory is a playlist: every video in it plays in turn, sorted by name, wrapping at the
# end. A single file loops forever instead.
[ -e "$FILE" ] || { echo "no existe: $FILE" >&2; exit 1; }
[ -f "$FILE" ] || [ -d "$FILE" ] || { echo "no es un archivo ni un directorio: $FILE" >&2; exit 1; }
FILE=$(readlink -f "$FILE")

[ -x "$HELLO_XR" ] || { echo "falta compilar hello_xr ($HELLO_XR)" >&2; exit 1; }
if ! pgrep -f "targets/service/monado-service" >/dev/null; then
	echo "Monado no está corriendo. Levantá el stack primero:  ./jack-in.sh 3dof" >&2
	exit 1
fi

if [ "$PHOTO" = "1" ]; then
	ENV_EXTRA+=("HELLO_XR_PHOTO360=$FILE")
else
	ENV_EXTRA+=("HELLO_XR_VIDEO360=$FILE")
fi
[ "$STATS" = "1" ] && ENV_EXTRA+=("HELLO_XR_VIDEO_STATS=1")

# IPC_IGNORE_VERSION is needed because hello_xr was built against an older Monado than the
# service (client v25.1.0-706 vs service v25.1.0-708).
#
# Two launch modes, because the transport keys need the real terminal on stdin:
#
#  - Interactive terminal: hand hello_xr the tty so espacio/[/]/n/q work, with `timeout
#    --foreground` as the time bound (--foreground keeps it in the tty's process group, so
#    it can read keys and Ctrl-C reaches it). The player puts the terminal in raw no-echo
#    mode; if it dies uncleanly (timeout's SIGTERM, Ctrl-C) the atexit restore never runs,
#    so ALWAYS run `stty sane` afterwards or the shell is left half-mute.
#
#  - Piped/backgrounded (tests, automation): the old form - a timed `sleep` on stdin, and
#    the run ends when the pipe hits EOF. No keys, same behavior as always.
RUNTIME_ENV=(
	XR_RUNTIME_JSON="$MONADO_BUILD/openxr_monado-dev.json"
	IPC_IGNORE_VERSION=1
)
if [ -t 0 ]; then
	echo "Reproduciendo $(basename "$FILE") - maximo ${SECONDS_TO_RUN}s."
	echo "Teclas: [espacio] pausa | [ ] velocidad | 1 normal | h/l -10s/+10s | enter recentra | n siguiente | q salir"
	echo "Mando: gatillo pausa | stick seek | grip recentra | menu izq sostenido ~1.5s sale"
	timeout --foreground "$SECONDS_TO_RUN" env \
		"${RUNTIME_ENV[@]}" "${ENV_EXTRA[@]}" \
		stdbuf -oL -eL "$HELLO_XR" --graphics Vulkan2
	RC=$?
	stty sane 2>/dev/null
	exit "$RC"
else
	echo "Reproduciendo $(basename "$FILE") durante ${SECONDS_TO_RUN}s (sin teclado: stdin no es una terminal)."
	sleep "$SECONDS_TO_RUN" | env \
		"${RUNTIME_ENV[@]}" "${ENV_EXTRA[@]}" \
		stdbuf -oL -eL "$HELLO_XR" --graphics Vulkan2
fi
