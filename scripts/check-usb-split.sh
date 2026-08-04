#!/usr/bin/env bash
# check-usb-split.sh — verifica, después de bootear, si el SSD raíz quedó
# separado del controlador xHCI que usa el casco.
#
# Objetivo: sda en 0000:02:00.0 (chipset A520), casco en 0000:07:00.3 (Matisse).

# El disco raíz puede no llamarse sda una vez movido a SATA: resolverlo desde el
# punto de montaje de /, no por nombre fijo.
ROOTDEV=$(findmnt -no SOURCE / 2>/dev/null)
ROOTDISK=$(lsblk -no PKNAME "$ROOTDEV" 2>/dev/null | head -1)
[ -n "$ROOTDISK" ] || ROOTDISK=$(basename "$ROOTDEV")

SYSPATH=$(readlink -f "/sys/block/$ROOTDISK")
CTRL_SSD=$(echo "$SYSPATH" | grep -o '0000:[0-9a-f]*:[0-9a-f]*\.[0-9a-f]*' | tail -1)
TRAN=$(lsblk -dno TRAN "/dev/$ROOTDISK" 2>/dev/null)
BUS_SSD=$(echo "$SYSPATH" | grep -o 'usb[0-9]*/[0-9]*-[0-9.]*' | head -1 | cut -d/ -f2)
SPD=$(cat "/sys/bus/usb/devices/$BUS_SSD/speed" 2>/dev/null)

if [ "$TRAN" = "usb" ]; then
  echo "Disco raíz ($ROOTDISK): tran=usb  bus=$BUS_SSD  speed=${SPD}M  ctrl=$CTRL_SSD"
else
  echo "Disco raíz ($ROOTDISK): tran=$TRAN  ctrl=$CTRL_SSD"
fi
echo
echo "Casco:"
for d in /sys/bus/usb/devices/*; do
  [ -f "$d/idVendor" ] || continue
  case "$(cat "$d/idVendor"):$(cat "$d/idProduct")" in
    03f0:0580|045e:0659|04b4:6504|04b4:6506)
      echo "  $(basename "$d")  $(cat "$d/idVendor"):$(cat "$d/idProduct")  $(cat "$d/product" 2>/dev/null)  ctrl=$(readlink -f "$d" | grep -o '0000:[0-9a-f]*:[0-9a-f]*\.[0-9a-f]*' | tail -1)";;
  esac
done
echo
if [ "$TRAN" != "usb" ]; then
  echo "RESULTADO: OK — el disco raíz ya NO está en USB (tran=$TRAN, ctrl=$CTRL_SSD)."
  echo "El casco tiene su xHCI para él solo. Causa raíz del cuelgue eliminada."
  echo
  echo "Siguiente: test de estrés (manual cap. 00, procedimiento 4)."
elif [ "$CTRL_SSD" = "0000:02:00.0" ]; then
  echo "RESULTADO: PARCIAL — el SSD sigue en USB pero en otro xHCI que el casco."
  [ "$SPD" -ge 5000 ] 2>/dev/null \
    && echo "Velocidad OK (${SPD}M, SuperSpeed)." \
    || echo "ATENCION: ${SPD}M — puerto USB2. Mover a un conector USB3 de 02:00.0."
  echo
  echo "Sirve como mitigación, pero el fix de fondo es pasarlo a SATA (cap. 00, proc. 1)."
else
  echo "RESULTADO: NO — el disco raíz sigue en $CTRL_SSD, el mismo xHCI que el casco."
  echo "Mover de puerto USB ya se probó y NO alcanza: los 4 USB3 traseros son todos"
  echo "de 07:00.3 y los del chipset solo salen por headers internos no cableados."
  echo "Fix real: pasar el SSD a SATA (manual cap. 00, procedimiento 1)."
fi
echo
echo "--- extras ---"
echo "grupos: $(id -nG)"
echo "journalctl -k: $(journalctl -k -n1 --no-pager -q >/dev/null 2>&1 && echo accesible || echo 'sin acceso (falta relogin o el grupo adm)')"
echo "autosuspend:"
for d in /sys/bus/usb/devices/*; do
  [ -f "$d/idVendor" ] || continue
  case "$(cat "$d/idVendor")" in
    152d|03f0|045e) echo "  $(basename "$d") $(cat "$d/idVendor"):$(cat "$d/idProduct") power/control=$(cat "$d/power/control" 2>/dev/null)";;
  esac
done
