# Siguiente paso — probar el handshake de activación WMR

Estado al 2026-08-04, noche.

## Lo que se resolvió hoy

**Fase 0 cerrada.** El disco raíz salió del enclosure USB y está en SATA
(`tran=sata`, controlador `0000:02:00.1`, AHCI 6 Gbps, cero errores ATA). El casco
quedó solo en su xHCI `07:00.3`. `scripts/check-usb-split.sh` da OK.

**El fallo "físico incurable" del casco era un puerto USB-A malo.** Ver
`docs/06-known-issues.md`, primera sección — está reescrita con la evidencia del
kernel (`error -71`, error 7-14 de WMR) y la lista de enumeración correcta.

**El audio del G2 anda.** Card ALSA `Generic USB Audio` (`0bda:4c15`), confirmado
audible. Probar siempre al 100% de volumen: el device reporta mal su escala de dB.

## Lo que falta

`DP-0` sigue `disconnected` — el panel no enciende. Los puertos DisplayPort de la
GPU están descartados (test cruzado con el monitor vertical: el monitor da link en
los dos, el casco en ninguno).

**Hipótesis a testear:** el casco nunca recibe el handshake de activación WMR, que
va por HID al companion `03f0:0580` y lo manda el runtime. Sin él el casco queda en
reposo — apaga el amplificador de audio a los ~20s (síntoma observado y medido) y no
enciende el panel. Nunca se pudo probar antes porque el companion no enumeraba.

### Procedimiento

1. **Volver los cables como estaban**: monitor vertical a su puerto DisplayPort
   original (vuelve a ser `DP-3`), casco a `DP-0`. Hoy se intercambiaron para
   diagnosticar y el swap ya dio su respuesta.
   Sin esto, `jack-in.sh` no funciona bien: tiene hardcodeado `DP-3` y configura las
   tres salidas en un solo comando `xrandr`, así que si una no existe falla entero.
2. Verificar que enumeren los cinco devices USB (lista en `docs/06-known-issues.md`).
3. `./jack-in.sh 3dof` y mirar si `DP-0` pasa a `connected`.

### Pendiente menor

Agregar el device de audio a `scripts/71-usb-no-autosuspend.rules` — la regla no lo
cubre porque `0bda:4c15` no existía cuando se escribió:

```
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="0bda", ATTR{idProduct}=="4c15", TEST=="power/control", ATTR{power/control}="on"
```

(Hoy ya figura en `control=on` por su cuenta, así que no es lo que causa el corte de
audio a los 20s — pero conviene fijarlo.)

## Cola después de esto

1. Test de estrés (`docs/00-hardware-usb.md`, procedimiento 4) — el gate original.
2. Verificación visual del player 360 con NVDEC (branch `g2-360-viewer`).
3. Test 10/10 de conexión de controllers (branch `g2-controllers`).
4. Lab dual-boot 90 Hz (manual cap. 04).
