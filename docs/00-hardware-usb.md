# 00 — Topología USB: separar el disco raíz del casco

## Por qué esto va primero

El 2026-08-04 la máquina se colgó entera (pantallas muertas salvo una, errores USB en
consola, reset a mano). Causa: el **SSD raíz** (Crucial BX500 en enclosure USB JMicron)
y el **HP Reverb G2 completo** cuelgan del **mismo controlador xHCI** (`07:00.3`, Matisse),
mientras el segundo controlador (`02:00.0`, chipset A520) está casi vacío. Cuando el bus
se atraganta (companion board del casco re-enumerando + transcodes escribiendo a disco),
se lleva puesto el enlace del disco raíz → I/O a `/` congelado → cuelgue total, y los
archivos a medio escribir quedan truncados (así perdimos dos descargas .mp4, sin moov atom).

Topología medida ese día:

```
xHCI 07:00.3 (Matisse, CPU)  → usb3 (480M) + usb4 (10G)
   usb4/4-1     HP WMR hub → 4-1.1 HoloLens Sensors (cámaras, 5G, stream continuo)
   usb4/4-2     Hub VIA → 4-2.1 JMicron JMS578 → sda = DISCO RAÍZ  ← PROBLEMA
   usb3/3-1     Hub Cypress del casco → QHMD companion (03f0:0580) + audio
xHCI 02:00.0 (chipset A520)  → usb1 (480M) + usb2 (10G, 3 puertos)
   usb1/1-8     Receiver Logitech (mouse)
   usb2         VACÍO  ← acá va el disco
```

## Procedimiento 1 — mover el disco (APAGADO, nunca en caliente)

1. Apagar la máquina del todo (es el disco raíz: no se replantea en caliente).
2. Cambiar el cable USB del enclosure del SSD a otro puerto físico del gabinete/panel
   trasero — buscamos uno que cuelgue del controlador `02:00.0`. En placas AM4 con
   chipset A520, los puertos del chipset suelen ser un cluster distinto del de los
   puertos "CPU"; no hay serigrafía confiable, así que se verifica por software.
3. Bootear y verificar:

   ```bash
   readlink -f /sys/block/sda
   # DEBE contener: 0000:02:00.0
   # Si sigue diciendo 0000:07:00.3 → apagar y probar otro puerto.
   ```

4. Confirmar velocidad y que el casco quedó solo en su bus:

   ```bash
   lsusb -t          # sda (JMicron/uas) bajo el root hub de usb2; casco en usb3/usb4
   cat /sys/bus/usb/devices/*/speed
   ```

## Procedimiento 2 — matar el autosuspend de disco y casco

El default del kernel (`usbcore.autosuspend=2`) suspende dispositivos "idle"; el hub que
lleva el disco raíz estaba en `auto`. Regla udev preparada en
`scripts/71-usb-no-autosuspend.rules` de este repo:

```bash
sudo cp scripts/71-usb-no-autosuspend.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb
# Verificar (todo lo listado debe decir "on"):
for d in /sys/bus/usb/devices/*/power/control; do
  v=$(cat ${d%/power/control}/idVendor 2>/dev/null)
  case "$v" in 152d|2109|03f0|04b4|045e) echo "$d -> $(cat $d)";; esac
done
```

## Procedimiento 3 — logs legibles sin sudo

Durante el cuelgue no pudimos leer ni `dmesg` ni `journalctl -k` como usuario (grupos
faltantes + `dmesg_restrict=1`): los errores USB solo se vieron en consola y se perdieron.

```bash
sudo usermod -aG adm,systemd-journal brunduk
# cerrar sesión y volver a entrar (o reboot), luego verificar:
journalctl -k | head    # debe mostrar líneas del kernel
```

Opcional (más cómodo para diagnosticar, decisión tuya):

```bash
echo 'kernel.dmesg_restrict = 0' | sudo tee /etc/sysctl.d/10-dmesg.conf
sudo sysctl --system
```

## Procedimiento 4 — test de estrés (gate para seguir con el resto)

Reproduce la carga del día del cuelgue, ahora con los buses separados:

```bash
# Terminal 1: transcodificación NVENC sostenida escribiendo al disco raíz
ffmpeg -y -f lavfi -i testsrc2=size=3840x2160:rate=30 -t 600 \
       -c:v hevc_nvenc -preset p5 -b:v 40M /tmp/stress_$(date +%s).mp4

# Terminal 2: pipeline VR completo
./scripts/jack-in.sh 3dof
# + un rato de player 360 con video

# Terminal 3: vigilancia
journalctl -kf | grep -iE 'usb|xhci|reset|uas'
```

**Criterio de éxito:** 10 minutos sin resets de xhci/uas en el journal y sin caída del
companion device (03f0:0580 estable en `lsusb`). Recién entonces se avanza con las fases
siguientes (NVDEC, controllers, lab 90Hz).

## Nota sobre el enclosure

La falla del companion board del casco es **física** (pasa igual en Windows; cable/conector
sospechoso — ver `06-known-issues.md`). Separar los buses no la cura: solo evita que esa
falla arrastre al disco del sistema. A mediano plazo el fix de fondo es mover `/` a un
disco interno (el NVMe hoy es 100% NTFS/Windows).
