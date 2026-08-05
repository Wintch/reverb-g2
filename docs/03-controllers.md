# 03 — Controllers WMR del G2: estado real, fixes y roadmap

## Cómo hablan los controllers

Los controllers del G2 NO hablan Bluetooth con la PC: están apareados de fábrica con el
radio interno del casco, y sus paquetes viajan **tunelizados por el mismo stream HID** que
lleva el IMU del casco, los timestamps de cámara y el status (`wmr_hmd_controller.c`).
Consecuencia clave: durante la lectura de firmware/calibración de un controller, todo lo
demás comparte el canal — y ahí vivía la fragilidad.

No hay que apareanar nada en Linux. Encenderlos y listo (y con nuestros parches, ya no
importa si se encienden después de arrancar monado-service — ver abajo).

## Qué estaba roto (upstream, verificado leyendo el código el 2026-08-04)

**Conexión:**
- Un solo timeout de 250ms por comando de firmware, sin ningún retry en ningún nivel.
  Un reply perdido (frecuentísimo en un canal compartido) = controller NULL **toda la sesión**.
- El pedido de status de controllers se mandaba UNA vez al arrancar. Controller apagado en
  ese instante = invisible para siempre.
- Espera SIN timeout del primer status: un reply perdido colgaba el arranque entero
  (upstream lo tenía marcado con @todo).
- Sleep incondicional de 10ms por chunk hacía durar segundos la lectura de calibración —
  agrandando la ventana de fallo.
- En el transporte BT directo (otros cascos WMR): un error de lectura transitorio mataba
  el thread para siempre con el dispositivo aún registrado (controller mudo).

**Inputs (bugs de driver, ni siquiera de transporte):**
- Stick sin clamp en el extremo negativo (-1.0005, viola OpenXR) y sin deadzone → drift.
- El click de grip recibía el valor analógico: cualquier presión leve = click.
- **Háptica muerta por partida doble**: nombre de output que los bindings no referencian
  + `set_output` jamás implementado.
- Timestamps de input siempre 0 (rompe `lastChangeTime` de OpenXR).
- Typos: labels x/y cruzados en el GUI de debug, loop `inputs[0]` en vez de `inputs[i]`.

## Qué arreglamos (patches/monado/0001-0008; renumerados 2026-08-05 al partirlos en 4 MRs para upstream, ver docs/18)

| Patch | Qué hace |
|---|---|
| 0003 | Inputs: clamp+deadzone de sticks, squeeze_click correcto, nombre háptico, timestamps, typos |
| 0004 | Retry 3x con backoff en lecturas de firmware + pacing 10ms→1ms + fix de leak |
| 0005 | Re-request de status cada 5s mientras falte un controller + espera de arranque acotada (3s) |
| 0006 | Thread BT directo tolera errores transitorios (se rinde tras 10 seguidos) |

Efecto neto esperado: los controllers conectan siempre (aunque un fw-read falle, se
reintenta; aunque estén apagados al arrancar, aparecen al encenderlos), los sticks quedan
centrados sin drift, y el grip se comporta.

## Cómo verificar

```bash
./jack-in.sh 3dof     # controllers encendidos antes O después, ya no importa
grep -E "left:|right:" ~/Documents/linux_vr_base/jack-in.log
# debe decir: left: HP Reverb G2 Left Controller / right: HP Reverb G2 Right Controller

# GUI de debug con paneles por controller (sticks en vivo, batería, IMU):
XRT_DEBUG_GUI=1 en el servicio; ver panel "WMR HMD" y los de cada controller.
```

Test de estrés de conexión: 10 ciclos de arranque del servicio con controllers encendidos
→ deben conectar 10/10 (antes: ~50%). Sticks quietos deben leer exactamente (0,0).

## Lo que sigue faltando (con el porqué)

1. **Vibración**: el output ya resuelve, pero el comando de wire para el motor no está
   documentado en ningún lado del árbol de Monado y no vamos a inventar bytes contra un
   firmware. Fuentes posibles: capturas USB en Windows (usbpcap) o el árbol de thaytan.
2. **Tracking posicional (6DoF)**: el driver WMR es orientation-only por código
   (`position_tracking = false`, posición hardcodeada). PERO la infraestructura de
   **constellation tracking** (tracking óptico por LEDs) ya existe upstream, se compila en
   nuestro build (`libconstellation.a`), la cámara del casco ya separa los frames de
   controller (frametype 0x2 — hoy mueren en un debug sink), y la geometría de LEDs ya se
   parsea de la calibración del propio controller y se descarta. Falta cablearlo: modelo de
   oclusión del ring, mosaico de cámara móvil, y alineación temporal cámara/IMU. Hay dos
   drivers de referencia en el árbol (rift, pssense) y un fork que lo tiene andando para
   WMR (thaytan `dev-constellation-controller-tracking`, base del trabajo de Project-VR).
   Es EL gran paso siguiente después del 90Hz.
3. El refactor de fondo del fw-read (state machine en el dispatch en vez de robar el
   stream) — upstream ya lo pide en un @todo; nuestros retries lo hacen innecesario en la
   práctica, pero es la solución elegante para proponer en un MR.
