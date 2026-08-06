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

## Vinculación / pairing (investigado 2026-08-06)

Origen: los controllers tienen un botón chico oculto dentro del compartimento de pilas.
Apretado, los desvincula del casco. La pregunta era si hace falta una herramienta en Linux
para volver a vincularlos, y qué protocolo habla.

**Conclusión, con evidencia (no es una hipótesis):**

- El estado de vinculación se consulta con un comando HID normal al mismo dispositivo
  Hololens Sensors (045e:0659) que ya usa Monado — no hay Bluetooth de por medio en ningún
  lado (ni del host: este equipo no tiene hardware BT, `systemctl is-active bluetooth` →
  inactive, y no importa). Protocolo leído directo de `wmr_hmd.c`/`wmr_protocol.h` de
  Monado: reporte `0x16` con subtipo `0x17` (`WMR_MS_HOLOLENS_MSG_CONTROLLER_STATUS`) pide
  estado; la respuesta llega como reporte `0x17`, un paquete por controller, con
  `UNPAIRED` / `OFFLINE` / `ONLINE` (más VID/PID si está vinculado).
- **No existe ningún comando de "vincular" propietario que mandar por USB.** Se examinó
  `unlock_wmr.exe` (la "Procedure to unlock headset and controllers for Oasis" que
  referencia la wiki de Oasis, ver abajo) con el mismo método binutils de
  `docs/09-oasis-driver-re.md`: su único call site de `HidD_SetFeature`/`HidP_SetUsageValue`
  manda exactamente el mismo comando "Display Enable" (Usage Page 0x03 / Usage 0x21) que ya
  manda Monado — nada nuevo. El resto de sus imports relevantes son `SetupDiGetClassDevsW` /
  `CM_Get_Device_Interface_ListW` (enumeración de dispositivos PnP) con un loop de polling
  de ~6s (`Timeout pairing %s motion controller` si no aparece a tiempo) — es una UI que
  espera a que el controller aparezca, no algo que dispara la vinculación.
- **El handshake de vinculación pasa enteramente por el radio interno del casco**,
  disparado por el botón físico del controller: mantenerlo apretado hasta que el LED
  empiece a pulsar lento entra en modo descubrimiento, y el casco lo resuelve en firmware,
  sin que el host mande nada especial. Procedimiento documentado en la wiki de Oasis
  (`Pairing-Motion-Controllers`): encender el controller (Windows button), abrir el
  compartimento de pilas, mantener el botón chico hasta el pulso lento.

**Consecuencia práctica:** no hace falta escribir un "linkeador" — el procedimiento es
puramente físico y no depende del SO. Lo único que faltaba del lado Linux era poder
*verificar* el estado antes/después, que es lo que hace el chequeador de abajo. Si se
prueba el botón oculto alguna vez, correr el chequeador antes y después debería mostrar el
cambio `UNPAIRED → OFFLINE/ONLINE` sin que haga falta ningún otro software.

### Chequeador de vinculación

```bash
./scripts/controller-pair-check.py [segundos]   # default 6s
```

Manda el pedido de estado (reporte `0x16`/subtipo `0x17`) directo al Hololens Sensors y
decodifica la respuesta por controller. Funciona con o sin `monado-service` corriendo (el
hidraw se puede abrir más de una vez en paralelo). Probado 2026-08-06 con ambos joysticks
apagados: reportó correctamente `vinculado, offline` con el VID:PID real del controller
(045e:066a) para izquierda y derecha — confirma que el protocolo leído es el correcto.

Fuente de la investigación: `docs/09-oasis-driver-re.md` (mismo método de disassembly,
aplicado a `unlock_wmr.exe` en vez de a `driver_oasis.dll`/`HololensSensors.dll`).
