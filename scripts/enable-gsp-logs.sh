#!/bin/bash
# Habilita los logs del firmware GSP en dmesg. Esta GPU (GA104) corre la mayor parte de la
# logica del resource manager en ese firmware, no en el modulo abierto -- por eso el
# parametro nvidia_modeset.debug (usado antes) esta topeado en 7 lineas: la logica
# interesante ocurre en un microcontrolador dentro de la GPU, no en el kernel de Linux.
#
# NVreg_EnableGpuFirmwareLogs hace que ESE firmware mande sus logs al host. Por default,
# en un build de release, esta deshabilitado (nv-reg.h: solo se activa solo si el driver es
# un build DEBUG/DEVELOP). Hay que forzarlo con valor 1.
#
#   sudo ./scripts/enable-gsp-logs.sh
#   sudo ./scripts/enable-gsp-logs.sh --revert
#
# REQUIERE REINICIAR. El parametro es del modulo "nvidia" (core), que carga antes que
# nvidia-modeset y nvidia-drm -- no se puede activar en caliente como el debug de modeset.

set -eu
[ "$(id -u)" -eq 0 ] || { echo "necesita root: sudo $0" >&2; exit 1; }

CONF=/etc/modprobe.d/99-nvidia-gsp-logs.conf

if [ "${1:-}" = "--revert" ]; then
    rm -f "$CONF"
    echo "revertido: $CONF eliminado. REINICIAR para que tome efecto."
    exit 0
fi

cat > "$CONF" <<'EOF'
# Logs del firmware GSP al dmesg -- ver scripts/enable-gsp-logs.sh y docs/13-bug-6bpc.md
options nvidia NVreg_EnableGpuFirmwareLogs=1
EOF

echo "escrito: $CONF"
cat "$CONF"
echo
update-initramfs -u -k "$(uname -r)" 2>&1 | tail -5 || true
echo
echo "LISTO. HAY QUE REINICIAR (el parametro es del modulo 'nvidia' core, se lee al cargar)."
echo "Despues del reboot: sudo /home/iam/Documents/reverb-g2-linux/scripts/collect-nv.sh"
echo "y buscar en los dmesg-*.txt cualquier cosa nueva (RPC, GSP, DPU, link training, etc)."
