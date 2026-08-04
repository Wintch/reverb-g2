#!/usr/bin/env bash
# find-port.sh — identifica a qué controlador xHCI pertenece cada puerto físico.
#
# Uso: correrlo y ENCHUFAR/DESENCHUFAR un dispositivo USB cualquiera (pendrive,
# receptor Logitech, mouse) en los puertos del gabinete, uno por uno. Cada vez
# que aparece algo nuevo imprime el bus y el controlador PCI.
#
# Buscamos un puerto que reporte  ctrl=0000:02:00.0  (chipset A520).
# El SSD raíz NO se toca en caliente: primero se encuentra el puerto con este
# script, después se apaga la máquina y se mueve el cable.
#
# Ctrl-C para salir.

snapshot() {
  for d in /sys/bus/usb/devices/[0-9]*-[0-9]*; do
    [ -f "$d/idVendor" ] || continue
    echo "$(basename "$d")"
  done | sort
}

describe() {
  local d="/sys/bus/usb/devices/$1"
  local ctrl
  ctrl=$(readlink -f "$d" | grep -o '0000:[0-9a-f]*:[0-9a-f]*\.[0-9a-f]*' | tail -1)
  printf '  %-10s %s:%s  %-6s speed=%sM  ctrl=%s' \
    "$1" "$(cat "$d/idVendor")" "$(cat "$d/idProduct")" \
    "$(cat "$d/version" 2>/dev/null | tr -d ' ')" \
    "$(cat "$d/speed" 2>/dev/null)" "$ctrl"
  if [ "$ctrl" = "0000:02:00.0" ]; then
    printf '   <<< ESTE PUERTO SIRVE\n'
  else
    printf '   (mismo xHCI que el casco, NO sirve)\n'
  fi
}

echo "Vigilando USB. Enchufá/desenchufá un dispositivo de prueba en cada puerto."
echo "Objetivo: ctrl=0000:02:00.0 . Ctrl-C para salir."
echo
prev=$(snapshot)
while true; do
  sleep 1
  cur=$(snapshot)
  if [ "$cur" != "$prev" ]; then
    while read -r dev; do
      [ -n "$dev" ] && { echo "[+] conectado:"; describe "$dev"; }
    done < <(comm -13 <(echo "$prev") <(echo "$cur"))
    while read -r dev; do
      [ -n "$dev" ] && echo "[-] desconectado: $dev"
    done < <(comm -23 <(echo "$prev") <(echo "$cur"))
    prev="$cur"
  fi
done
