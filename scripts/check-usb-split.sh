#!/usr/bin/env bash
# check-usb-split.sh — verifies, after booting, whether the root SSD ended up
# separated from the xHCI controller used by the headset.
#
# Goal: sda on 0000:02:00.0 (A520 chipset), headset on 0000:07:00.3 (Matisse).

# The root disk may not be called sda once moved to SATA: resolve it from the
# mount point of /, not by a fixed name.
ROOTDEV=$(findmnt -no SOURCE / 2>/dev/null)
ROOTDISK=$(lsblk -no PKNAME "$ROOTDEV" 2>/dev/null | head -1)
[ -n "$ROOTDISK" ] || ROOTDISK=$(basename "$ROOTDEV")

SYSPATH=$(readlink -f "/sys/block/$ROOTDISK")
CTRL_SSD=$(echo "$SYSPATH" | grep -o '0000:[0-9a-f]*:[0-9a-f]*\.[0-9a-f]*' | tail -1)
TRAN=$(lsblk -dno TRAN "/dev/$ROOTDISK" 2>/dev/null)
BUS_SSD=$(echo "$SYSPATH" | grep -o 'usb[0-9]*/[0-9]*-[0-9.]*' | head -1 | cut -d/ -f2)
SPD=$(cat "/sys/bus/usb/devices/$BUS_SSD/speed" 2>/dev/null)

if [ "$TRAN" = "usb" ]; then
  echo "Root disk ($ROOTDISK): tran=usb  bus=$BUS_SSD  speed=${SPD}M  ctrl=$CTRL_SSD"
else
  echo "Root disk ($ROOTDISK): tran=$TRAN  ctrl=$CTRL_SSD"
fi
echo
echo "Headset:"
for d in /sys/bus/usb/devices/*; do
  [ -f "$d/idVendor" ] || continue
  case "$(cat "$d/idVendor"):$(cat "$d/idProduct")" in
    03f0:0580|045e:0659|04b4:6504|04b4:6506)
      echo "  $(basename "$d")  $(cat "$d/idVendor"):$(cat "$d/idProduct")  $(cat "$d/product" 2>/dev/null)  ctrl=$(readlink -f "$d" | grep -o '0000:[0-9a-f]*:[0-9a-f]*\.[0-9a-f]*' | tail -1)";;
  esac
done
echo
if [ "$TRAN" != "usb" ]; then
  echo "RESULT: OK — the root disk is NO LONGER on USB (tran=$TRAN, ctrl=$CTRL_SSD)."
  echo "The headset has its xHCI all to itself. Root cause of the hang eliminated."
  echo
  echo "Next: stress test (manual chapter 00, procedure 4)."
elif [ "$CTRL_SSD" = "0000:02:00.0" ]; then
  echo "RESULT: PARTIAL — the SSD is still on USB but on a different xHCI than the headset."
  [ "$SPD" -ge 5000 ] 2>/dev/null \
    && echo "Speed OK (${SPD}M, SuperSpeed)." \
    || echo "WARNING: ${SPD}M — USB2 port. Move to a USB3 connector on 02:00.0."
  echo
  echo "Works as a mitigation, but the real fix is moving it to SATA (chapter 00, proc. 1)."
else
  echo "RESULT: NO — the root disk is still on $CTRL_SSD, the same xHCI as the headset."
  echo "Moving USB ports was already tried and is NOT enough: all 4 rear USB3 ports are"
  echo "on 07:00.3 and the chipset's only come out through unwired internal headers."
  echo "Real fix: move the SSD to SATA (manual chapter 00, procedure 1)."
fi
echo
echo "--- extras ---"
echo "groups: $(id -nG)"
echo "journalctl -k: $(journalctl -k -n1 --no-pager -q >/dev/null 2>&1 && echo accessible || echo 'no access (needs relogin or the adm group)')"
echo "autosuspend:"
for d in /sys/bus/usb/devices/*; do
  [ -f "$d/idVendor" ] || continue
  case "$(cat "$d/idVendor")" in
    152d|03f0|045e) echo "  $(basename "$d") $(cat "$d/idVendor"):$(cat "$d/idProduct") power/control=$(cat "$d/power/control" 2>/dev/null)";;
  esac
done
