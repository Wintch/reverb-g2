# Siguiente paso — pasar el disco raíz de USB a SATA

Estado al 2026-08-04, tarde.

## Qué hay que hacer

Sacar el **Crucial CT240BX500SSD1** del enclosure USB JMicron y enchufarlo a un
**puerto SATA de la placa**. Eso elimina la causa raíz del cuelgue total de la
máquina: hoy el disco raíz y el casco comparten el mismo controlador xHCI.

Procedimiento completo y verificaciones en `docs/00-hardware-usb.md`,
**Procedimiento 1**.

### Necesitás tener a mano

- Un **cable de datos SATA** (los mothers traen 1 o 2 en la caja) ← lo único que
  puede faltar y hay que comprar.
- Un conector **SATA de alimentación** libre en la fuente.
- Destornillador para abrir el enclosure JMicron.

### Los pasos, corto

1. Apagar del todo y desenchufar de la corriente.
2. Abrir el enclosure, sacar el SSD.
3. SSD → `SATA1` del mother + poder SATA de la fuente.
4. Fijarlo donde entre (bahía 2.5", o apoyado/atado — no tiene partes móviles).
5. Encender → **BIOS** → poner ese disco primero en el orden de arranque.
   El disco deja de ser "USB HDD" y pasa a ser SATA; no todos los BIOS reordenan solos.

## Por qué esto y no mover puertos USB

Ya se probó, dos veces, y **no hay solución por USB en esta máquina**:

- Mover el **SSD** de puerto (mañana): `4-3.1` → `4-4`. Mismo xHCI `07:00.3`.
- Mover el **casco** de puerto (tarde): `4-1` → `4-2`. Mismo xHCI `07:00.3`.

Sondeo con `scripts/find-port.sh` → mapa físico definitivo: **los 4 puertos USB3
del panel trasero son todos del CPU (`07:00.3`)**. Los 3 USB3 del chipset
(`02:00.0`/usb2) existen solo en headers internos y **el gabinete no tiene panel
frontal cableado**, así que son inalcanzables. Callejón sin salida.

En cambio el controlador SATA del chipset (`02:00.1`) tiene **6 puertos AHCI
libres, ninguno ocupado**, y el disco ya es SATA — está dentro de un puente USB
sin necesidad.

## El arranque no se rompe (verificado antes de tocar nada)

| chequeo | resultado |
|---|---|
| `/etc/fstab` | usa `UUID=` para `/` y swap → el cambio de nombre de dispositivo es irrelevante |
| initramfs | contiene `ahci`; `MODULES=most` |
| modo de arranque | **BIOS/legacy** (no existe `/sys/firmware/efi`), tabla `dos` |
| bootloader | MBR en el propio disco → viaja con el disco |

Único punto de intervención posible: el orden de arranque en el BIOS (paso 5).

## Al volver a bootear

```bash
~/Documents/linux_vr_base/reverb-g2-linux/scripts/check-usb-split.sh
```

Debe decir:

```
Disco raíz (sda): tran=sata  ctrl=0000:02:00.1
RESULTADO: OK — el disco raíz ya NO está en USB
```

Si dice OK → **test de estrés** (`docs/00-hardware-usb.md`, procedimiento 4).
Ese es el gate para retomar el resto del proyecto.

## Ya hecho de la Fase 0

- ✅ `71-usb-no-autosuspend.rules` instalada y aplicada (SSD, QHMD, sensores en
  `power/control=on`).
- ✅ `usermod -aG adm,systemd-journal brunduk` — activo, `journalctl -k` accesible.
- ❌ Separación del disco → **esto es lo que falta**, ahora por SATA.

## Después del gate, la cola pendiente

1. Verificación visual en el casco del player 360 con NVDEC (branch `g2-360-viewer`).
2. Test 10/10 de conexión de controllers (branch `g2-controllers`).
3. Lab dual-boot 90 Hz (manual cap. 04).

## Ojo aparte (no bloquea esto)

En el último chequeo el **`03f0:0580` (QHMD companion) no estaba enumerado** — solo
el hub y los sensores. Es el fallo físico conocido del cable (ver
`docs/06-known-issues.md`), no tiene que ver con el cambio de puerto. Tenerlo en
cuenta antes de cualquier prueba con el casco: si no aparece en `lsusb`, Monado va
a caer en Simulated HMD.
