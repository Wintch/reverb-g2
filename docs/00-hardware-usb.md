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

## Descartado: mover cosas de puerto USB (medido 2026-08-04, tarde)

Se probó y **no hay solución por USB en esta máquina**. Dos intentos, ambos fallidos:

- **Mover el SSD de puerto** (2026-08-04, mañana): pasó de `4-3.1` a `4-4` — otro conector
  físico, mismo xHCI `07:00.3`.
- **Mover el casco de puerto** (2026-08-04, tarde): pasó de `4-1` a `4-2` — otra vez el
  mismo `07:00.3`.

Sondeando con `scripts/find-port.sh` se confirmó el mapa físico definitivo:

| controlador | bus | puertos | dónde están físicamente |
|---|---|---|---|
| `07:00.3` (Matisse, CPU) | usb3 (480M) / usb4 (10G) | 4 + 4 | **los 4 USB3 azules del panel trasero** |
| `02:00.0` (chipset A520) | usb1 (480M) | 9 | los 2 USB2 traseros (ahí el receiver Logitech en `1-8`) + headers |
| `02:00.0` (chipset A520) | usb2 (10G) | 3 | **solo headers internos — el gabinete no tiene panel frontal cableado** |

El panel trasero tiene 6 puertos: 2 USB2 + 4 USB3. Los 4 USB3 son **todos** del CPU
(coincide con los 4 puertos de `usb4`). Los 3 puertos USB3 del chipset — los únicos que
servirían — existen únicamente en headers internos que este gabinete no expone.

**Conclusión: el barajado de puertos USB es un callejón sin salida.** Ir directo al
Procedimiento 1.

## Procedimiento 1 — mover el disco raíz a SATA (APAGADO)

El `sda` es un **Crucial CT240BX500SSD1**, o sea un **SSD SATA de 2.5" metido en un
enclosure USB JMicron JMS578**. La placa tiene el controlador SATA del chipset
(`02:00.1`, AMD 500 Series) con **6 puertos AHCI (`ata1`..`ata6`), todos vacíos**.
Sacarlo del enclosure y enchufarlo a SATA resuelve el problema de raíz:

- el casco queda solo en `07:00.3`, sin nada que compartir → desaparece la causa del cuelgue;
- se sale del techo del JMS578 (~430 MB/s) a SATA III (~550 MB/s);
- y lo más importante, el filesystem raíz deja de colgar de un bus que se resetea solo.

### Verificado de antemano — el arranque NO se rompe

| chequeo | resultado |
|---|---|
| `/etc/fstab` | usa `UUID=` para `/` y para swap → el cambio de nombre de dispositivo es irrelevante |
| initramfs | contiene `ahci`; `MODULES=most` en `initramfs.conf` |
| modo de arranque | **BIOS/legacy** (no existe `/sys/firmware/efi`), tabla de particiones `dos` |
| bootloader | MBR en el propio disco → viaja con el disco |
| puertos SATA | 6 libres |

### Pasos

1. Apagar del todo y desenchufar de la corriente (es el disco raíz: nunca en caliente).
2. Abrir el enclosure JMicron y sacar el SSD.
3. Conectarlo a `SATA1` del mother + un conector **SATA de alimentación** de la fuente.
4. Fijarlo donde se pueda (bahía de 2.5", o apoyado/atado — es SSD, sin partes móviles).
5. Encender, **entrar al BIOS y poner ese disco primero en el orden de arranque**. Es el
   único paso que puede requerir intervención: el disco deja de ser "USB HDD" y pasa a ser
   SATA, y no todos los BIOS reordenan solos.

**Lo único que puede faltar físicamente:** un **cable de datos SATA** (los mothers traen
1 o 2 en la caja) y un conector SATA de poder libre en la fuente.

### Verificación al volver

```bash
./scripts/check-usb-split.sh
# Debe dar OK: el SSD ya no aparece en USB en absoluto.
lsblk -o NAME,SIZE,TRAN,MODEL   # sda debe decir TRAN=sata, no usb
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
falla arrastre al disco del sistema. El Procedimiento 1 (pasar `/` a SATA) es exactamente
ese fix de fondo — el NVMe sigue siendo 100% NTFS/Windows y no se toca.

Una vez movido el SSD a SATA, el enclosure JMS578 queda libre y es perfectamente usable
para otra cosa (backups, discos externos), solo que nunca más para el filesystem raíz.
