# 16 — El experimento del vblank: ¿es el refresh, o la forma del timing?

Preparado 2026-08-05 desde el sistema principal, con el SSD del lab montado. **El EDID de
prueba ya está generado y verificado**: `experiments/vblank/`. Falta correrlo con el casco
puesto — y falta además resolver **cómo cargarlo**: la sección "El EDID ya está armado" más
abajo lo deja como paso 0, sin vía confirmada todavía.

---

## PREFLIGHT — correr esto antes que nada

Este experimento **sólo vale en el lab**, con el 595-open parcheado. Ya nos pasó una vez de
empezar a medir en el sistema principal, que tiene el `nvidia-current` 550.163.01 de Debian
**sin** el parche del bpc: ahí el clamp a 6 bpc está activo y cualquier resultado sale
confundido con el bug que justamente sacamos del medio.

```bash
# 1. driver correcto
grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' /proc/driver/nvidia/version | head -1
#    tiene que decir 595.71.05   (si dice 550.x estás en el sistema equivocado, rebooteá)

# 2. modulos abiertos, no los propietarios
modinfo nvidia 2>/dev/null | grep -i license
#    tiene que incluir "Dual MIT/GPL"

# 3. el parche del bpc esta adentro del modulo
./scripts/verify-bpc.sh

# 4. el casco enumera completo (los cinco)
lsusb | grep -E '04b4:6506|0bda:4c15|03f0:0580|04b4:6504|045e:0659' | wc -l
#    tiene que dar 5; si falta 03f0:0580 es el puerto USB, no Monado (docs/00)

# 5. y el bpc real en el cable
dmesg | grep 'Notify Attach Begin' | tail -1
#    tiene que decir 24 bpp, no 18
```

Si cualquiera de los cinco falla, **parar**. Medir con el driver equivocado no da un
resultado malo: da un resultado que parece bueno y apunta al lado que no es.

---

## De dónde venimos

El clamp a 6 bpc está cerrado (ver `docs/13`, `docs/14`):

- **PR abierto en NVIDIA:** https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275
- **Hilo del foro:** post 379240, revisión 6
- Con el parche el casco reporta `08` en el byte 18 y su status HID de 33 bytes queda
  idéntico byte a byte al de Windows

Y sin embargo **los dos modos de 90 Hz siguen sin mostrar imagen**: el panel enciende y
parpadea en blanco. El de 60 Hz anda.

---

## La hipótesis

En los tres modos que el EDID del G2 ofrece, el blanking **horizontal** es idéntico
(50/4/46). La única variable estructural es el **vertical**:

| modo | vblank | resultado |
|---|---|---|
| 4320x2160@60 | **514 líneas** | anda |
| 4320x2160@90 | 116 líneas | falla |
| 2880x1440@90 | 158 líneas | falla |

Es decir: **"90 Hz" y "vblank corto" están perfectamente confundidos**. Nunca se observó
un vblank corto a 60 Hz, ni uno largo a 90 Hz. Con estos tres modos es imposible saber
cuál de las dos variables rompe el panel.

El experimento inyecta los dos modos que faltan y completa el factorial.

---

## Diseño

|  | vblank corto (158) | vblank largo (514) |
|---|---|---|
| **60 Hz** | **A** — 285.72 MHz | **CTRL** — 349.38 MHz |
| **90 Hz** | nativo slot 0: **falla** | **B** — 524.06 MHz |

Los tres inyectados quedan muy por debajo de los 709.15 MHz del modo que ya funciona
(6.86 / 8.39 / 12.58 Gbps a 24 bpp), así que ninguno introduce presión de ancho de banda.

**Por qué 2880x1440 y no 4320x2160:** el DTD del bloque base tiene el campo de horizontal
active de **12 bits — máximo 4095 px**. 4320 no entra. Por eso el propio G2 pone
2880x1440 en el bloque base y sus dos modos de 4320 en el bloque DisplayID, cuyos
descriptores Type I usan campos de 16 bits. Usar 2880x1440 además mantiene la resolución
constante contra el modo nativo que falla, que es una comparación más limpia.

**`CTRL` no es opcional y va primero.** Sin él, si A falla no se puede distinguir "el
vblank corto rompe el panel" de "cualquier modo inyectado rompe". Es la línea de base.

---

## El EDID ya está armado

`experiments/vblank/g2-vblank-test.edid` — 384 bytes, partiendo de
`experiments/vblank/hmd.edid`. Los tres modos entran en los slots de DTD que
estaban libres, así que **queda un solo EDID con todo el factorial**: se corre la
experiencia entera en una sesión, sin re-overridear entre test y test.

```
bloque base   slot 0  2880x1440@90  428.58 MHz  vblank 158   nativo, FALLA
              slot 1  2880x1440@60  349.38 MHz  vblank 514   CTRL
              slot 2  2880x1440@60  285.72 MHz  vblank 158   TEST A
              slot 3  2880x1440@90  524.06 MHz  vblank 514   TEST B
DisplayID     desc 1  4320x2160@90  905.40 MHz  vblank 116   nativo, FALLA  (intacto)
              desc 2  4320x2160@60  709.15 MHz  vblank 514   nativo, ANDA   (intacto)
```

Verificado: round-trip de codificación en los tres, checksum del bloque base correcto,
y los dos bloques de extensión sin tocar byte a byte.

Para regenerarlo o variarlo:

```bash
./scripts/edid-tool.py inject-mode experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-test.edid CTRL:1 A:2 B:3

# sin asignaciones lista los presets y qué hay en cada slot
./scripts/edid-tool.py inject-mode experiments/vblank/hmd.edid
```

**PENDIENTE, y es el paso 0 real de este experimento — no hay una vía de carga confirmada
todavía.** El bug de 6 bpc se cerró con un parche al *driver* (parche 0004), no con un
override de EDID: nunca hizo falta lograr que NVIDIA leyera un EDID falso. `docs/13`
lista tres candidatos, ninguno probado:

1. `/sys/kernel/debug/dri/*/DP-1/edid_override` (debugfs) — el más barato de probar primero.
   Duda abierta: no se sabe si NVKMS lee el EDID por el helper genérico de DRM (lo vería) o
   por su canal AUX propio (no lo vería). Escribir el archivo **no dispara hotplug**: hay que
   desconectar/reconectar el conector después.
2. `nvidia_modeset.config_file` — mecanismo propio de NVKMS, parámetro compilado y presente,
   pero la sintaxis del nombre de dpy no está documentada. Se descubre con
   `nvidia_modeset.debug=1` y leyendo dmesg como root durante un modeset real.
3. Parchear el EDID que reporta el propio casco (bytes reales sobre el cable), si hay algún
   punto de inyección entre el puente Analogix y el host — sin explorar.

Probar en ese orden. Si ninguno funciona, el experimento no es concluyente por esta vía y
hay que replantear cómo inyectar el modo (la fila "CTRL falla" de la tabla de más abajo
cubre justo ese caso, aunque ahí la causa real sería la vía de carga, no la hipótesis).

**Opción 1 — descartada (2026-08-05), con evidencia:** se escribió
`g2-vblank-test.edid` en `/sys/kernel/debug/dri/*/DP-1/edid_override` (los tres alias del
mismo conector: `0000:05:00.0`, `0`, `128`) y se cicló `force` (`off` → `on`, un segundo de
por medio) para forzar el re-probe. Resultado: `/sys/class/drm/card0-DP-1/edid` quedó
**byte-idéntico** (`cmp` exit 0, mismo md5) a `hmd.edid` **sin modificar** — no al EDID que
se acababa de escribir. Conclusión: el driver NVIDIA no pasa por el helper genérico de DRM
(`drm_get_edid`/`connector->edid_override`) para poblar el EDID de este conector; lo lee por
su propio canal (RM/AUX), que ignora el override. Responde la duda abierta que tenía esta
opción: **no lo ve**. No reintentar esta vía tal cual — pasar directo a la opción 2.

---

## Cómo correrlo

Orden: **CTRL → B → A**. Si B anda, ya está la respuesta y A es sólo confirmación.

### La verificación es física

La API miente: reporta modeset exitoso y 90.0 fps con el panel apagado. **Hay que ponerse
el casco y mirar.** Para cada modo, anotar:

- ¿enciende el panel? (backlight)
- ¿muestra contenido con color, o blanco/parpadeo?
- `dmesg`, línea `Notify Attach Begin`: pclk, raster, bpp — confirmar que dice `24 bpp`
- byte 18 del status report HID (`scripts/decode-status.sh`)

---

## Cómo leer el resultado

| CTRL | B | A | conclusión |
|---|---|---|---|
| falla | — | — | los modos inyectados no encienden este panel. **No concluyente**: falla el override o la vía de inyección, no la hipótesis. Replantear antes de seguir |
| anda | **anda** | — | **90 Hz no es el problema; el vblank corto sí.** El mejor resultado posible: le da a NVIDIA una variable concreta en vez de "miren el GSP" |
| anda | falla | anda | es el refresh, 90 Hz específicamente. Descarta el vblank y cierra esta línea |
| anda | falla | falla | ni el vblank ni el refresh por separado — apunta al pixel clock o a la combinación |

Cualquiera de las tres filas concluyentes es material para un reply al hilo 379240.

---

## Corrido (2026-08-05): CTRL falla — y con evidencia de por qué no es el override

**Vía de carga confirmada primero.** `nvidia_modeset.config_file` con la clave corregida
`override.[0000:05:00.0].DP-0` (el nombre interno de NVKMS es 0-based; ver `NEXT-STEP.md`
para la cadena de código completa) cargó al reboot: `dmesg` dijo `Successfully read
.../nvkms-override-candidates.conf` sin warning, `/sys/class/drm/card0-DP-1/edid` quedó
byte-idéntico (md5 `749a63f7...`) a `g2-vblank-test.edid`, y `drmprops` confirmó
`connector 130 ... modes=6` — subió de 3 a 6, exactamente los 4 slots del bloque base más
los 2 descriptores DisplayID sin tocar. La vía 2 queda **confirmada de punta a punta**, no
sólo a nivel del atributo sysfs sino hasta el conteo de modos que ve DRM.

**Orden de índice, confirmado por precisión de refresh (Vulkan vs `edid-tool.py decode`):**
`hmd-vk native <idx>` enumera **en el mismo orden que los slots del EDID** — primero el
bloque base (0-3), después DisplayID (4-5):

| idx Vulkan | refresh reportado | corresponde a |
|---|---|---|
| 0 | 89.999 Hz | nativo 2880x1440@90, slot 0, ya sabido FALLA |
| 1 | 60.001 Hz | **CTRL** |
| 2 | 59.999 Hz | **A** |
| 3 | 90.000 Hz | **B** |
| 4 | 90.001 Hz | nativo 4320x2160@90, ya sabido FALLA |
| 5 | 60.000 Hz | nativo 4320x2160@60, ya sabido ANDA |

**Resultado físico, con el casco puesto, PREFLIGHT completo (595.71.05, Dual MIT/GPL, parche
0004 presente, los 5 USB, `Notify Attach Begin` en 24 bpp):**

| modo | HID (`DEVICE_STATUS`, segundo mensaje) | físico |
|---|---|---|
| **CTRL** (idx1) | htotal=2980 vtotal=1954 refresh=60 bpc=8 — **exacto al diseño** | logo HP, nada |
| **B** (idx3) | htotal=2980 vtotal=1954 refresh=90 bpc=8 — **exacto al diseño** | logo HP, nada |
| **A** (idx2) | htotal=2980 vtotal=1598 refresh=60 bpc=8 — **exacto al diseño** | logo HP, nada |

Es la fila **"CTRL falla"** de la tabla de arriba — pero con un dato que la tabla no
anticipaba: el casco reporta por HID el timing **byte a byte idéntico** al que se inyectó
en cada uno de los tres casos (`scripts/decode-status.sh` ya había establecido que byte 5 =
refresh decimal y bytes 19-22 = htotal/vtotal little-endian). Eso **descarta** la mitad de
la ambigüedad de esa fila: no es que "el override no llegó" — llegó, hasta el link físico,
con el bpc correcto (byte 18 = 08 en los tres). Lo que falla es la vía de inyección en sí
(**"la vía de inyección"**, la otra mitad de la ambigüedad que la fila sí previó), no que el
casco nunca haya visto el modo pedido.

**Y hay un candidato concreto para esa vía, que la tabla no tenía como variable: la
resolución.** Los tres modos inyectados son **2880x1440** — y ésa es la resolución del
único otro modo nativo que existe a esa anchura, `2880x1440@90` (slot 0), que **ya fallaba
antes de este experimento** (T002, sesión anterior: "hp prendido, pantalla apagada"). O sea
que 2880x1440 **nunca mostró nada, a ningún refresh, en toda la historia del proyecto**: ni
nativo a 90 Hz, ni inyectado a 60 con vblank largo (CTRL, la forma exacta del modo que sí
anda), ni inyectado a 60 con vblank corto (A), ni inyectado a 90 con vblank largo (B). El
único modo que alguna vez mostró video es 4320x2160@60 (T001). Con sólo estos datos, **la
resolución explica el 100% de los resultados sin necesitar el refresh ni el vblank**: quizás
el firmware del panel (o el puente Analogix) sólo acepta los anchos de banda / resoluciones
para los que fue calibrado, y 2880x1440 simplemente no es uno de ellos — independiente de
qué tan correcto sea el timing eléctrico.

Esto no cierra el factorial, lo **replantea**: hay que repetirlo inyectando en los
descriptores DisplayID Type I (4320x2160), como ya preveía la sección "Si hace falta
repetirlo a 4320x2160" más abajo — ahí sí hay un caso confirmado que funciona a esa
resolución, así que cualquier resultado que salga de mover sólo el vblank/refresh en 4320
no va a tener este mismo confound.

**Anomalía sin explicar, anotada para no perderla:** en el segundo mensaje HID de **A**
(único de los tres), el byte 1 pasó de `00` a `01`. Según el comentario de Monado sobre el
G1 (citado en `panel-status.py`), ese bit en el segundo mensaje señala que el backlight
**visiblemente prendió**. En CTRL y B ese byte se quedó en `00` los dos. Pero el usuario
reportó "nada, apagado, solo logo hp" para A igual que para los otros dos — así que, o el
bit no es fiable como señal de contenido visible, o hubo algo transitorio en esa corrida
puntual. Queda abierto; no tomarlo como evidencia de que A funcionó parcialmente.

Testlogs T008/T009/T010 (`docs/pruebas.jsonl`) tienen los HID crudos completos.

---

## Segunda ronda (2026-08-05, noche): el mismo factorial, sobre 4320x2160

`scripts/edid-tool.py inject-did` ya está escrito y probado (round-trip por el decoder
completo, checksums de la sección DisplayID y del bloque de extensión verificados, resto de
los bloques intacto). Escribe sobre los descriptores Type I del bloque DisplayID en vez del
bloque base, así que esta vez el factorial corre a 4320x2160 — la única resolución con un
caso confirmado que anda — y no tiene el confound de resolución de la ronda anterior.

```bash
./scripts/edid-tool.py inject-did experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-4k-ctrl.edid CTRL4K:1
./scripts/edid-tool.py inject-did experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-4k-b.edid B4K:1
./scripts/edid-tool.py inject-did experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-4k-a.edid A4K:1
```

Los tres reemplazan el **descriptor #1** (el que ya fallaba a 90 Hz) y dejan el
**descriptor #2** (@60, vblank 514, el que anda) intacto como control físico en cada EDID.

| preset | timing | pclk | Gbps @24bpp |
|---|---|---|---|
| `CTRL4K` | 4320x2160@60 vblank 514 (igual forma que el descriptor #2 real) | 709.14 MHz | 17.02 |
| `A4K` | 4320x2160@60 vblank 116 (igual forma que el descriptor #1 real, pero a 60Hz) | 603.60 MHz | 14.49 |
| `B4K` | 4320x2160@90 vblank 240 | 954.72 MHz | 22.91 |

**Por qué `B4K` usa vblank 240 y no 514, a diferencia del factorial anterior:** a 4320 de
ancho, vblank 514 a 90 Hz pasa **25.53 Gbps @24bpp** — pegado al techo de HBR3 (25.92), sin
margen. 240 sigue siendo muy superior al 116 que falla (más del doble) y deja margen real
de ancho de banda, así que sigue discriminando la hipótesis sin arriesgar un segundo
confound (ancho de banda esta vez, no resolución).

**Cada EDID nuevo necesita su propio reboot.** Se confirmó por fuente
(`nvkms-dpy-override.c: DpyOverrideReadEdid`) que NVKMS copia el contenido del archivo a un
buffer en memoria una sola vez, al parsear `config_file` durante la carga del módulo — no
lo vuelve a leer del disco después. Sobreescribir el archivo sin reiniciar no tiene efecto.
`experiments/vblank/nvkms-override-candidates.conf` ya apunta al primero (`CTRL4K`); para
pasar al siguiente hay que editar esa línea y reiniciar de nuevo.

**Orden: CTRL4K → B4K → A4K**, mismo criterio que la ronda anterior. Después de cada reboot:
PREFLIGHT completo (arriba) y `hmd-vk list` para confirmar el índice real antes de
presentar — con `CTRL4K` cerca de 60 Hz igual que el descriptor #2, van a aparecer dos
modos casi idénticos y hay que fijarse en cuál mueve la refresca exacta (`hmd-vk list` la
imprime con 3 decimales, como ya se hizo en la ronda anterior) o directamente correr los
dos y comparar contra el HID.

**Lectura del resultado:** si `CTRL4K` (clonar el modo que anda a la otra posición) también
falla, la explicación ya no puede ser "vblank" ni "resolución" — sería algo posicional
(cuál descriptor, o el bit `preferred`) y hay que replantear otra vez. Si `CTRL4K` anda,
seguir con `B4K`: si anda, es la respuesta (90 Hz no es el problema, el vblank corto sí). Si
`B4K` falla y `A4K` anda, es el refresh específicamente. Si los dos fallan, ninguno de los
dos por separado — apunta al pixel clock o a la combinación.

### `CTRL4K` corrido (2026-08-05, noche): anda — el descriptor #1 no es la causa

Override cargado y verificado con `scripts/verify-override.sh` (nuevo: junta en un solo
script todo lo que necesita root — `dmesg`, forzar `detect()`, comparar md5 del EDID activo
— para no pedir la contraseña de sudo comando por comando). `dmesg` limpio,
`Successfully read...`, md5 del EDID activo (`993031c3...`) idéntico al archivo.

`hmd-vk list` mostró 3 modos (no 6: esta ronda usa el `hmd.edid` base sin tocar + sólo los 2
descriptores DisplayID, uno de ellos modificado): `[0] 2880x1440@89.999` (nativo, bloque
base, ya sabido FALLA), `[1] 4320x2160@60.000` y `[2] 4320x2160@60.000` — **idénticos a 3
decimales**, esperado porque `CTRL4K` fue diseñado para clonar la forma exacta del
descriptor #2. Se presentó `[1]` (el descriptor #1 modificado, antes ocupado por el
4320x2160@90 que siempre falló) por orden de enumeración (bloque base primero, después
DisplayID en orden — confirmado en la ronda anterior).

**Resultado físico: colores alternando (azul, blanco, verde) — el panel prendió con
contenido real.** Paleta distinta a la esperada (naranja/azul/verde), pero inequívocamente
lejos del logo de HP o negro que dan los modos que fallan. HID (`panel-status.py`)
corroboró: byte 5 = `0x3c` (60 decimal, exacto), y el segundo mensaje `DEVICE_STATUS` pasó
byte 1 de `00` a `01` — la señal de "backlight visiblemente prendido" del comentario de
Monado sobre el G1 — coincidiendo esta vez con una confirmación física real (a diferencia
de la anomalía sin explicar de `A` en la ronda anterior, donde ese mismo bit se prendió sin
video visible). Log completo y testlog T012 en `docs/pruebas.jsonl`.

**Conclusión: la posición del descriptor #1 no es la causa.** Clonar un timing sano ahí
funciona igual que en su posición original. Eso deja en pie la hipótesis del vblank —
sigue `B4K` (90 Hz, vblank corto, mismo descriptor #1) como el test que de verdad decide.

### `B4K` corrido (2026-08-05, noche): FALLA — 90Hz + vblank corto, en la posición ya probada sana

Mismo procedimiento: `verify-override.sh` confirmó carga (dmesg limpio, md5 activo
`506f366f...` idéntico al archivo), PREFLIGHT completo incluyendo `Notify Attach Begin`
(`pclk 954720000 raster 4420x2400 24 bpp` — exacto al diseño de `B4K`: vtotal 2400 = 2160 +
vblank 240). `hmd-vk list` mostró `[1]` en `90.000 Hz` como esperado.

**Resultado físico: nada, sólo el logo de HP.** Igual que todos los 90Hz nativos previos.
HID (T013) capturó sólo 2 mensajes `DEVICE_STATUS`, los dos con byte 5 = `0x3c` (60
decimal) — **no `0x5a` (90)** — y byte 1 en `00` las dos veces (sin la señal de backlight
prendido). A diferencia del factorial de la ronda anterior (`docs/pruebas.jsonl` T008-T010),
donde el casco sí reportaba por HID el refresh de 90 exacto pese a fallar visualmente, acá
el companion nunca llegó a reportar 90 — se quedó en el último estado conocido (60, de
`CTRL4K`) y después "se fue" (re-enumeró) sin más mensajes. Diferencia real entre las dos
rondas, anotada tal cual sin explicación todavía: puede ser timing de arranque de
`panel-status.py` respecto del modeset, o que acá el link nunca entrena lo suficiente para
que el companion se entere del cambio — no alcanza con lo medido para decidir cuál.

**Sigue `A4K`** (60 Hz, vblank corto — mismo descriptor, mismo pixel clock más bajo, sin el
salto a 90Hz) para separar si la causa es el refresh en sí o el vblank/pixel-clock.

### `A4K` corrido (2026-08-05, noche): FALLA — y esto cierra el factorial

`verify-override.sh` confirmó carga (md5 `e1f99097...` idéntico), PREFLIGHT completo,
`Notify Attach Begin`: `pclk 603600000 raster 4420x2276 24 bpp` — exacto al diseño (vtotal
2160+116). **Resultado físico: pantalla apagada, sólo logo HP.** HID (T014) confirmó
refresh=`0x3c` (60, exacto) y htotal/vtotal (`4420`/`8e4`=2276, bytes 19-22) exactos al
diseño — el timing llegó perfecto otra vez — pero el bit de backlight-prendido (byte 1 del
segundo mensaje, el mismo que sí se prendió en `CTRL4K`/T012) se quedó en `00` en los dos
mensajes. Igual que `B4K`: el link nunca llega a encender el panel.

**Conclusión del factorial 2x2 completo:**

| | vblank largo (514) | vblank corto (116/240) |
|---|---|---|
| **60 Hz** | `CTRL4K` — **ANDA** | `A4K` — **FALLA** |
| **90 Hz** | (no probado a 4320; ver abajo) | `B4K` — **FALLA** |

**No es el refresh. Es el vblank corto.** `CTRL4K` y `A4K` son los dos a 60 Hz — uno anda y
el otro no, y la única diferencia es el vblank (514 vs 116). Eso también cierra en seco la
explicación de ancho de banda: `A4K` corre a 603.6 MHz, muy por debajo del techo HBR3
(25.92 Gbps), y aun así falla igual que `B4K` a 954.72 MHz. No importa cuánto margen de
bandwidth haya — lo que rompe el enganche es la duración corta del blanking vertical en sí,
no los bits por segundo que hacen falta para sostenerlo.

**Esto cambia el objetivo del proyecto.** El límite no es "90 Hz": es un vblank mínimo, en
algún punto entre 116/240 (fallan) y 514 (anda). Si ese mínimo es compatible con 90 Hz
dentro del ancho de banda de HBR3, **90 Hz es alcanzable** con el vblank correcto — el
candidato más directo es exactamente la combinación que se había descartado por margen
justo de bandwidth: 4320x2160@90 con vblank 514 (25.53 Gbps de 25.92 — 1.5% de margen). Si
ANDA, se acabó el lab. Si falla, hace falta bisectar el vblank mínimo entre 240 y 514 (el
"segundo experimento" de más abajo, pero corrido a 4320 con `inject-did` en vez de al
bloque base) para encontrar el punto de corte real y desde ahí buscar un refresh que entre.

Testlog T014 completo en `docs/pruebas.jsonl`.

### `90long` corrido (2026-08-05, noche): FALLA — y esto acota el problema a microsegundos

`verify-override.sh` confirmó carga (md5 `82483a9f...`), PREFLIGHT completo, `Notify Attach
Begin`: `pclk 1063720000 raster 4420x2674 24 bpp` — exacto al diseño (vtotal 2160+514, el
mismo vblank que anda a 60 Hz, ahora a 90). **Resultado físico: sólo logo HP, negro.**

Novedad respecto de `B4K`: el HID (T015) esta vez **sí** actualizó — refresh `0x5a` (90,
exacto) y htotal/vtotal (`4420`/`0a72`=2674) exactos al diseño, byte 1 de backlight en `00`
las dos veces. O sea que el modo sí llegó completo hasta el link, con el mismo vblank
(en líneas) que funciona perfecto a 60 Hz — y aun así no engancha. Descarta que el fallo de
`B4K` fuera "el HID nunca se enteró"; a 90 Hz, ni con vblank correcto en líneas alcanza.

**Los cuatro resultados ordenan limpio por tiempo de blanking vertical, no por líneas:**

| modo | vblank (líneas) | refresh | vblank (ms) = vblank/((vact+vblank)·rate) | resultado |
|---|---|---|---|---|
| `A4K` | 116 | 60 Hz | 0.849 ms | FALLA |
| `B4K` | 240 | 90 Hz | 1.111 ms | FALLA |
| `90long` | 514 | 90 Hz | 2.136 ms | FALLA |
| `CTRL4K` | 514 | 60 Hz | **3.204 ms** | **ANDA** |

Notar que `90long` y `CTRL4K` tienen el **mismo número de líneas** de vblank (514) y aun así
uno falla y el otro anda — la única diferencia es el refresh, que cambia cuánto *tiempo*
real dura ese blanking (a mayor refresh, cada línea dura menos). Eso descarta "cantidad de
líneas" como la variable relevante y apunta a una duración mínima en microsegundos que el
panel/puente Analogix necesita durante el vblank para lo que sea que hace ahí (quizás
reentrenar, quizás procesar el frame anterior) — hipótesis, no confirmada todavía.

**Por qué esto es un problema para 90 Hz específicamente:** el techo de HBR3 (25.92 Gbps
@24bpp) limita el pixel clock a ~1080 MHz. A 90 Hz con `htotal=4420`, eso pone un vblank
máximo de **~555 líneas ≈ 2.27 ms** — por debajo de los 3.204 ms que ya sabemos que
funcionan. Si el umbral real de tiempo necesario está más cerca de 3.2 ms que de 2.27 ms,
**90 Hz podría no ser alcanzable dentro de HBR3 con ningún vblank**, sin importar cuánto se
estire — el ancho de banda se agota antes de llegar al tiempo mínimo.

**Antes de gastar otro reboot cerca del límite de banda a 90 Hz, conviene acotar el umbral
real a 60 Hz**, donde no hay presión de bandwidth y se puede probar cualquier vblank.
Candidato siguiente: `vblank=340` líneas a 60 Hz da exactamente 2.27 ms — el mismo tiempo
que sería el máximo posible a 90 Hz dentro de HBR3.

```bash
./scripts/edid-tool.py inject-did experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-4k-bisect1.edid 340@60:1
```

663.00 MHz, vtotal 2500 — 15.91 Gbps, muy lejos de cualquier límite. **Si esto FALLA, 90 Hz
queda descartado dentro de HBR3** (no hay vblank que a la vez entre en el ancho de banda y
llegue al tiempo mínimo). **Si ANDA**, sigue bisectando hacia arriba entre 340 y 514 líneas
(a 60 Hz, sin presión de banda) para acotar el umbral real, y recién con eso evaluar si cabe
a 90 Hz o si hace falta buscar un refresh intermedio (72/75/80 Hz) que sí entre.

Testlog T015 completo en `docs/pruebas.jsonl`.

### `bisect1` corrido (2026-08-05, noche): FALLA — 90 Hz queda descartado dentro de HBR3

`verify-override.sh` confirmó carga (md5 `001af82f...`), `Notify Attach Begin`: `pclk
663000000 raster 4420x2500 24 bpp` — exacto (vtotal 2160+340). **Resultado físico: sólo
logo HP.** HID (T016) confirmó timing exacto (60Hz, htotal/vtotal 4420/2500) entregado
perfecto, backlight nunca se prendió.

**vblank=340 a 60 Hz da 2.27 ms — el mismo tiempo que sería el máximo posible a 90 Hz
dentro de HBR3 — y falla.** Eso confirma que el umbral real de tiempo está por encima de
2.27 ms, y como el techo de ancho de banda a 90 Hz no permite superar ese valor bajo
ninguna combinación de vblank, **90 Hz queda descartado como alcanzable dentro de este
enlace DisplayPort HBR3**, sin importar qué vblank se use.

**Decisión con el usuario: ir directo a un refresh intermedio con margen real, en vez de
seguir bisectando el umbral exacto a 60 Hz.** A 80 Hz el techo de banda permite hasta 3.66
ms (contra los 3.204 ms que ya sabemos que andan a 60 Hz) — mucho más margen que a 90 Hz.
Candidato: `vblank=775` a 80 Hz → 1037.82 MHz, 3.301 ms, 24.91 de 25.92 Gbps (~4% de margen,
no pegado al límite como los intentos anteriores a 90 Hz).

```bash
./scripts/edid-tool.py inject-did experiments/vblank/hmd.edid \
    -o experiments/vblank/g2-vblank-4k-80hz.edid 775@80:1
```

**Esto redefine el objetivo del proyecto.** `CLAUDE.md` afirma que "la única cura" para el
parpadeo es llegar a 90 Hz — pero esa afirmación nunca se puso a prueba a un refresh
intermedio, era una suposición basada en cómo WMR anuncia sus modos nativos (sólo 60/90 en
el EDID), no una medición. Si 80 Hz (o el refresh más alto que entre en HBR3 con vblank
suficiente) reduce o elimina el parpadeo perceptible, cambia el criterio de éxito del lab.
Si no lo reduce, hay que revisar si el parpadeo es específico de la frecuencia del strobe
del backlight a 90 Hz y no simplemente "más alto es mejor".

Testlog T016 completo en `docs/pruebas.jsonl`.

### `80hz` corrido (2026-08-05, noche): FALLA — refuta la hipótesis del umbral de tiempo

`verify-override.sh` confirmó carga, `Notify Attach Begin`: `pclk 1037820000 raster
4420x2935 24 bpp` — exacto al diseño (vtotal 2160+775). **Resultado físico: sin imagen,
sólo logo.** HID (T017) confirmó refresh `0x50` (80, exacto) y htotal/vtotal
(`4420`/`0b77`=2935) exactos.

**Esto rompe la hipótesis de "umbral de tiempo de blanking".** `80hz` tiene **3.301 ms** de
blanking vertical — *más* que los 3.204 ms de `CTRL4K`, que sí anda. Si el tiempo de
blanking fuera la variable relevante, `80hz` debería haber andado. No andó. La hipótesis
armada a partir de los primeros cuatro puntos (que ordenaban perfecto por tiempo) queda
refutada por el quinto. Anotado explícitamente para no repetir el error: **no se vuelve a
usar esta hipótesis como si estuviera confirmada.**

**Patrón que sí sobrevive a los seis puntos, y es más simple:** el único modo que alguna vez
mostró video, en toda la historia del proyecto, tiene **pixel clock ≈ 709.15 MHz** (el
descriptor #2 nativo, y `CTRL4K`, su clon). Todos los demás — nativos y sintéticos —
tienen un pixel clock distinto, y todos fallaron:

| modo | pixel clock | resultado |
|---|---|---|
| nativo 2880x1440@90 (T002) | 428.58 MHz | FALLA |
| nativo 4320x2160@90 (T003/T007) | 905.40 MHz | FALLA |
| `A4K` | 603.60 MHz | FALLA |
| `B4K` | 954.72 MHz | FALLA |
| `90long` | 1063.72 MHz | FALLA |
| `bisect1` | 663.00 MHz | FALLA |
| `80hz` | 1037.82 MHz | FALLA |
| **nativo 4320x2160@60** | **709.15 MHz** | **ANDA** |
| **`CTRL4K`** | **709.14 MHz** | **ANDA** |

Esto también reinterpreta un resultado de la ronda anterior que había quedado sin explicar
del todo: `CTRL` (T008, primera ronda, 2880x1440@60 con vblank largo) había fallado y se
atribuyó al confound de resolución (2880x1440 "nunca mostró nada"). Con este patrón, hay una
explicación alternativa que encaja igual de bien: 2880x1440@60 tiene un pixel clock de
~397 MHz — tampoco 709.15 MHz — así que el mismo mecanismo lo explica sin necesitar invocar
la resolución en absoluto.

**Hipótesis nueva, sin confirmar: el puente Analogix (o el panel mismo) sólo engancha a un
pixel clock específico (~709 MHz), independiente de resolución, refresh o vblank.** Si es
así, no hay combinación de EDID que alcance 90 Hz (ni ningún otro refresh) sobre este link:
el límite no es de timing sino del PLL del puente, y la vía HID de Windows para llegar a 90
Hz tendría que estar reprogramando ese reloj por otro canal (DPCD/AUX, no la vía EDID/modo
que este experimento puede tocar).

**Test que separa esta hipótesis de "sólo 60 Hz enclava" (sin tocar el refresh):** armar un
modo a 60 Hz con vblank generoso (conocido bueno, ~514 líneas) pero con un pixel clock
distinto de 709 MHz — cambiando el *horizontal* blanking en vez del vertical (algo que
ningún test hasta ahora tocó: todos usaron el mismo horizontal 50/4/46). Si eso también
falla, el pixel clock específico es la variable, no el refresh. Si anda, el pixel clock no
importa y el patrón de la tabla es coincidencia (los seis fallos también comparten refresh
≠ 60, así que no se puede separar todavía con los datos que hay).

Testlog T017 completo en `docs/pruebas.jsonl`.

---

## Segundo experimento: el barrido de refresh

El factorial dice *si* el vblank importa. No dice *dónde* está el límite en el eje del
refresh. Para eso se mantiene la forma del timing fija y se mueve sólo el refresh:

```bash
./scripts/edid-tool.py inject-mode experiments/vblank/hmd.edid \
    -o experiments/vblank/sweep-70-75-80.edid  SHORT@70:1 SHORT@75:2 SHORT@80:3
```

`SHORT` es el blanking de los modos que fallan (vblank 158), `LONG` el del que anda
(vblank 514). La forma paramétrica es `BLANKING@RATE` y acepta cualquier refresh entre
24 y 240.

**El bloque base tiene 4 slots y el 0 lleva el modo nativo, así que entran 3 por EDID.**
Por eso el barrido se hace **bisectando**, no de una sola pasada:

| ronda | modos | qué contesta |
|---|---|---|
| 1 | `SHORT@70` `SHORT@75` `SHORT@80` | ¿hay umbral, y en qué tercio cae? |
| 2 | tres valores alrededor del cambio | lo acota a ±1-2 Hz |

Referencia de pixel clocks con `SHORT` (todos muy por debajo de los 709 MHz del modo que
anda, así que ninguno mete presión de ancho de banda):

```
SHORT@65  309.53 MHz     SHORT@75  357.15 MHz
SHORT@70  333.34 MHz     SHORT@80  380.96 MHz
SHORT@72  342.87 MHz     SHORT@85  404.77 MHz
```

Cómo se lee: si el panel anda hasta cierto refresh y falla a partir de ahí **con la forma
de timing constante**, hay un umbral duro y es un dato mucho más accionable que "90 Hz
falla". Si en cambio falla a cualquier refresh distinto de 60 con `SHORT`, no es un umbral
sino la forma del timing — y refuerza lo que diga el factorial.

Correr esto **después** del factorial: si `B` (90 Hz con vblank largo) anda, el eje del
refresh ya quedó descartado y el barrido pierde sentido.

---

## Si hace falta repetirlo a 4320x2160

`edid-tool.py` ya **decodifica** los descriptores Type I de DisplayID (`decode_did_type1`),
pero todavía no los escribe. El encoder se escribió y se validó contra este EDID real: el
decoder reproduce exactamente `905.400 MHz` con vblank 116 y `709.150 MHz` con vblank 514,
así que el layout está confirmado empíricamente y agregar un `inject-did` es directo.

Layout del Type I (20 bytes, todos los campos menos las polaridades guardan `valor - 1`):

```
0-2   pixel clock / 10 kHz, 24 bits LSB primero
3     flags: bit7 preferred, bit4 interlaced
4-5   horizontal active        6-7    horizontal blanking
8-9   horizontal front porch, bit15 = polaridad hsync
10-11 horizontal sync width
12-13 vertical active          14-15  vertical blanking
16-17 vertical front porch, bit15 = polaridad vsync
18-19 vertical sync width
```

Hay que corregir **dos** checksums: el de la sección DisplayID (último byte de la sección,
que arranca en `blk+1` y mide `5 + section_size`) y el del bloque de extensión EDID
(`blk+127`).

Presets sugeridos, todos dentro de HBR3 (25.92 Gbps):

| preset | timing | pclk | Gbps @24bpp |
|---|---|---|---|
| `CTRL4K` | 4320x2160@60 vblank 514 | 709.15 MHz | 17.02 |
| `A4K` | 4320x2160@60 vblank 116 | 603.60 MHz | 14.49 |
| `B4K` | 4320x2160@90 vblank 240 | 954.72 MHz | 22.91 |

Con sólo dos descriptores en el bloque, conviene reemplazar el **desc 1** (el @90 que ya
falla) y dejar el desc 2 (@60) intacto como control.

---

## Correcciones ya aplicadas — no reintroducir

El reporte publicado tuvo errores que se corrigieron sobre la marcha. Si se redacta algo
nuevo para el foro o el PR:

- La extensión del G2 es **DisplayID 1.2** (byte de versión `0x12`), con dos descriptores
  **Type I**. NO es DisplayID 2.0 ni Type VII. *(verificado contra los bytes reales)*
- `input.u.digital.bpc` se asigna en **tres** lugares del árbol, no dos: `nvt_edid.c:932`,
  `nvt_edidext_displayid20.c:314`, y `nvkms-dpy.c:2257` — este último dentro de
  `CreateParsedEdidFromNVT_TIMING()`, que nunca corre para un sink con EDID real.
- Números de línea en el tag 595.71.05: clamp DP en `nvkms-dpy.c:3456`, dispatch DisplayID
  en `nvt_edid.c:1101`. En `main` (610.57.04) son 3468 y 1101.
- DSC se descarta **por aritmética**, no por ausencia de strings en `dmesg`: el modo que
  anda son 17.0 Gbps sin comprimir y el que falla 10.3, así que DSC no puede ser requerido
  para el que falla.
- El `.patch.txt` adjunto en el foro es **viejo**: dice "DisplayID 2.0" y trae el header de
  hunk mal contado. Hay uno regenerado en `patches/nvidia/`.

## Verificado contra los bytes reales del EDID

Todo esto se chequeó contra `experiments/vblank/hmd.edid`, y coincide con lo que
afirma el post del foro:

```
byte 0x14 = 0x80          digital, color bit depth = 000 (undefined)
checksum base block 0xE8  suma del bloque = 0
ManufID 0x220E            = HPN
CTA byte 3 = 0x00         sin YCbCr 4:4:4 ni 4:2:2
DisplayID: 70 12 79 00 00 03   version 1.2, tag 0x03, 40 bytes = 2 descriptores Type I
g2-edid-8bpc-repro.bin    difiere en exactamente 2 bytes: 0x14 y 0x7F, checksum válido
```
