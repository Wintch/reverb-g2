# 13 — El bug: NVIDIA clava el G2 en 6 bits por color

**Encontrado el 2026-08-05, leyendo el código fuente del driver.** Es una línea.

---

## El resumen

El EDID del Reverb G2 **no declara su profundidad de color**. El driver NVIDIA de Linux
interpreta ese "no declarado" como **6 bits por componente** y maneja el enlace a 18 bpp en
todos los modos. Windows, con la misma GPU, usa 8. A 60 Hz el panel tolera los 6 bits; a 90 Hz
no enciende.

---

## La cadena causal, verificada eslabón por eslabón

| # | eslabón | evidencia |
|---|---|---|
| 1 | El EDID del casco deja la profundidad sin declarar | byte `0x14` = `0x80`: digital, bits 6-4 = `000` = *undefined*, EDID 1.4 |
| 2 | El parser lo convierte en `bpc = 0` | `nvt_edid.c:932`, rama `default:` |
| 3 | Nada lo sobreescribe | la extensión del casco es **DisplayID 1.2** (byte de versión `0x12`), y `nvt_edid.c:1101` sólo llama al parser 2.x si `(pExt[1] & 0xF0) == 0x20`. En todo el árbol `digital.bpc` se escribe en dos lugares: `nvt_edid.c:914-932` y `nvt_edidext_displayid20.c:314` (Display Parameters de DisplayID **2.x**) — **el parser 1.3 no lo toca nunca** |
| 4 | **`bpc < 8` clava el máximo en 6** | `nvkms-dpy.c:3456` |
| 5 | Al no pedirse nada, se usa el máximo | `ChooseColorBpc()` devuelve `max` si `requested == UNKNOWN` |
| 6 | El enlace corre a 18 bpp | `nvidia-modeset: DPCONN> Notify Attach Begin (Head 0, pclk 428580000 raster 2980 x 1598  18 bpp)` |
| 7 | **El casco lo confirma** | byte 18 de su `DEVICE_STATUS` = `06` en Linux, `08` en Windows |
| 8 | A 90 Hz el panel no enciende | verificación física, nueve corridas |

## El código

`src/nvidia-modeset/src/nvkms-dpy.c`, en `nvDpyGetOutputColorFormatInfo()`, rama de
DisplayPort:

```c
if (pDpyEvo->parsedEdid.info.input.u.digital.bpc >= 10) {
    colorFormatsInfo.rgb444.maxBpc = ..._BPC_10;
    colorFormatsInfo.yuv444.maxBpc = ..._BPC_10;
} else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {   // <-- 0 cae acá
    colorFormatsInfo.rgb444.maxBpc = ..._BPC_6;
    colorFormatsInfo.yuv444.maxBpc = ..._BPC_UNKNOWN;
} else {
    colorFormatsInfo.rgb444.maxBpc = ..._BPC_8;
    colorFormatsInfo.yuv444.maxBpc = ..._BPC_8;
}
```

**"Undefined" significa que el sink no la declaró, no que quiera 6.**

Y hay una inconsistencia dentro de la misma función: unas líneas más arriba, la rama de **DSI**
trata el caso desconocido como **8**:

```c
default:
    nvAssert(!"Unsupported bpc for DSI");
    // fall through
case 8:
    colorFormatsInfo.rgb444.maxBpc = ..._BPC_8;
```

DisplayPort y DSI hacen cosas distintas con la misma entrada.

## El parche

`patches/nvidia/0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch`:

```c
-                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
+                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc != 0 &&
+                           pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
```

Se aplica y reconstruye con `sudo ./scripts/apply-bpc-patch.sh` (y `--revert` lo saca).
**Requiere reiniciar.**

## Terminología: "logo HP" no es señal, es solo "tiene corriente" (aclarado 2026-08-06)

A lo largo de este documento y de `docs/16-lab-vblank.md`, la frase "logo HP, negro" aparece
constantemente como resultado de fallo. **Aclaración importante, para que nadie la
malinterprete en el futuro:** el "logo HP" es un badge LED luminoso en el frente del casco,
físicamente separado de los paneles LCD internos — se prende solo con recibir corriente USB,
sin que ningún software del host haga nada. **No es una señal diagnóstica de nada** más que
"el casco tiene alimentación". Nunca hubo una imagen de arranque dibujada en el panel interno
mismo.

Lo único que importa, y lo único que varía entre intentos, es el estado del **panel interno**
(el que se ve mirando por el lente):

| Panel interno (mirando por el lente) | Qué significa |
|---|---|
| Negro | Backlight apagado. Esto es lo que "logo HP, negro" siempre quiso decir: badge externo prendido (trivial, ignorar) + panel apagado. |
| Blanco fijo / parpadeo, sin color | Backlight prendido, sin imagen real — el hallazgo original de este documento (finding #2). |
| Imagen real (colores, video) | Éxito. |

**Dato práctico nuevo:** esta unidad tiene un daño físico (golpe) que deja un punto de fuga
de luz visible mirando por el lente — es el único indicador a simple vista, sin cámara ni
HID, de si el backlight está prendido o no, incluso cuando el resto del panel se ve negro a
primera vista. Coordenadas de referencia (para cámara, no aplica a simple vista) en
`linuxlab-kit/NEXT-STEP.md`, sección del experimento de webcam.

## Cómo se verifica que funcionó

Dos señales, y conviene mirar las dos:

1. **El byte 18 del `DEVICE_STATUS` tiene que pasar de `06` a `08`.** Es medición del lado
   del casco, no del driver, así que no depende de que le creamos a NVIDIA.
   `./scripts/panel-status.py 40` en paralelo con `hmd-vk`.
2. **Verificación física a 90 Hz.** Como siempre: sólo vale lo que se ve adentro del casco.

Si el byte 18 pasa a `08` y el panel **sigue** sin encender a 90 Hz, entonces el bpc era un bug
real pero no *el* bug — y habría que seguir con el byte 11, que es la otra diferencia contra
Windows (`0x14`=20 en Linux contra `0x1e`=30 en Windows a 90 Hz).

### Corrección del 2026-08-05 (post-publicación): es DisplayID 1.2, no 2.0

El reporte publicado en el foro dice *"its DisplayID 2.0 extension carries only a Type VII
timing block"*. **Es incorrecto**, y el error viene de acá. El bloque 2 del EDID empieza con
`70 12 79 00 00 03 00 28`: el `0x12` es versión 1 revisión 2, o sea **DisplayID 1.2**, y el
bloque de datos tag `0x03` de 40 bytes son **dos descriptores Type I Detailed Timing** de 20
bytes (el tag `0x03` recién es Type VII en DisplayID 2.0 — de ahí la confusión).

La conclusión no cambia y el argumento queda **más fuerte**: no es que a este DisplayID le
falte el bloque de Display Parameters, es que para **cualquier** sink con extensión DisplayID
1.x el único sitio que podría reasignar `digital.bpc` es inalcanzable por construcción. El
clamp a 6 bpc es inevitable para todo sink DP que deje la profundidad sin declarar en el
bloque base y no traiga DisplayID 2.x con Display Parameters.

Corrección redactada para postear en el hilo: `docs/14`, "Reply #1".

### Los modelines derivados del EDID coinciden exactamente con lo que programa nvkms

Decodificado a mano el 2026-08-05, para descartar una segunda causa raíz en la derivación de
modos:

| fuente | pclk | H act/fp/sync/bp | V act/fp/sync/bp | refresh |
|---|---|---|---|---|
| DisplayID desc #1 (preferred) | 905.40 MHz | 4320 / 50 / 4 / 46 | 2160 / 16 / 2 / 98 | 90.00 Hz |
| DisplayID desc #2 | 709.15 MHz | 4320 / 50 / 4 / 46 | 2160 / 14 / 2 / 498 | 60.00 Hz |
| DTD del bloque base | 428.58 MHz | 2880 / 50 / 4 / 46 | 1440 / 18 / 2 / 138 | 90.00 Hz |

Los tres con polaridad `+H +V`, y los tres idénticos a lo que reporta `drmModeGetConnector` y
al raster del log (`raster 2980 x 1598`, `pclk 428580000`). **No hay segunda causa raíz acá.**

### El color space lo cierra el propio EDID

La extensión CTA-861 (bloque 1) tiene **byte 3 = `0x00`**: el casco no anuncia YCbCr 4:4:4 ni
4:2:2. El enlace es RGB obligatoriamente en los tres modos — no hay variable de color space
que pueda diferir entre el modo que anda y los que fallan. Esto es independiente de la
búsqueda en los logs de `nvidia_modeset`, que ya había dado cero.

## Por qué importa más allá del G2

Esto **no es específico del Reverb G2**. Afecta a cualquier sink DisplayPort con EDID 1.4 que
deje la profundidad de color sin declarar: el driver lo maneja a 6 bpc en Linux y a 8 en
Windows. En un monitor común el síntoma sería *banding* y colores pobres, fácil de atribuir a
otra cosa. En este casco el síntoma es que el panel no enciende a 90 Hz.

Vale la pena mirar si explica alguno de los otros dos bugs de HMD que NVIDIA tiene abiertos
(Bigscreen Beyond con corrupción DSC, bug 4834531; Index/Vive con judder, bug 5372097).

## El parche funciona a medias: destraba el panel, pero no restaura el color (2026-08-05)

Reiniciado con el parche compilado. Cuatro pruebas, verificación física en cada una.

### La confirmación esperada: el byte 18 pasó de 06 a 08

```
antes:  05 00 01 01 00 5a 00 00 00 09 38 14 04 00 77 77 00 00 06 44 11 e4 08 ...
ahora:  05 01 01 01 01 5a 00 00 00 09 38 1e 04 00 77 77 00 00 08 44 11 e4 08 ...
                                                              ^^
```

El parche hace exactamente lo que predijo la lectura del código.

### Lo que NO se esperaba

| prueba | modo | resultado físico |
|---|---|---|
| T004 | `4320x2160@90` | **parpadeo blanco**, sin color, más marcado que el strobe de 60Hz conocido |
| T005 | `4320x2160@60` (control) | colores visibles, parpadeo igual de marcado que T004 |
| T006 | `2880x1440@90` (90Hz de MENOR ancho de banda: 428 MHz) | **también todo blanco parpadeando** |

**T006 es el descarte importante.** Los dos modos de 90Hz fallan igual — uno con 428 MHz de
pixel clock y el otro con 905 MHz, una diferencia de más de 2x — así que **no es un límite de
ancho de banda MIPI**. Es algo del refresh de 90Hz en sí, independiente de la resolución.

### El hallazgo que más importa: el estado del casco ahora es BYTE-IDÉNTICO a Windows

Capturado durante T004 (panel encendido manualmente con `panel.py on` mientras `hmd-vk`
presentaba a 90Hz en `4320x2160`):

```
Windows (ANDA):            05 01 01 01 01 5a 00 00 00 09 38 1e 04 00 77 77 00 00 08 44 11 e4 08 01 00 80 00 80 00 80 00 80 02
Linux post-parche (BLANCO): 05 01 01 01 01 5a 00 00 00 09 38 1e 04 00 77 77 00 00 08 44 11 e4 08 01 00 80 00 80 00 80 00 80 02
```

**Son exactamente iguales, los 33 bytes.** Incluso el byte 11 —que habíamos anotado como la
otra diferencia pendiente contra Windows (`0x14` vs `0x1e`)— se corrigió solo: pasó de 20 a 30
en los dos modos de 90Hz apenas se arregló el bpc. No era una variable independiente; dependía
del bpc, no del refresh como se pensó en un principio.

**Conclusión: agotamos lo que el canal `DEVICE_STATUS` puede decirnos.** El casco le reporta al
host lo mismo que le reporta a Windows — mismo refresh, mismo timing, mismo bpc, mismo flag de
backlight — y el resultado visual es distinto. La diferencia que queda **no es visible desde
este ángulo**. Tiene que estar en algo del propio stream de video que este canal no captura:

- **DSC activándose en silencio.** Ahora que el bpc subió a 8, la cuenta de ancho de banda es
  más ajustada (10.08 Gbps por panel contra 12 Gbps del ANX7530), y NVIDIA podría estar
  invocando DSC para el modo pesado — pero eso no explica por qué el modo liviano (10.29 Gbps
  totales de enlace, con margen de sobra) también falla igual.
- **Un detalle de timing que `htotal`/`vtotal` no capturan**: front porch, back porch, o
  polaridad de sync. Los totales pueden coincidir y el reparto interno ser distinto.
- **El formato de color en el enlace** (RGB444 vs YCbCr444/422): `nvDpyGetOutputColorFormatInfo()`
  también decide el color space, no sólo el bpc, y ese código no se leyó todavía.

### Balance honesto

No es la solución completa, pero es progreso real y medible: el parche cruzó el obstáculo que
dejaba el panel **completamente muerto** (logo estático, cero actividad) y lo llevó a un estado
nuevo (parpadeo con contenido, aunque sin color). El bpc era un bug real — confirmado por el
código, por el log de NVIDIA, y por el propio casco — pero no es *el* bug completo.

## Próximo paso: leer los logs de NVIDIA con los tres modos, ya con el parche puesto

`scripts/collect-nv.sh` ya existe y hace exactamente esto: activa `nvidia_modeset debug=1`,
corre los tres modos (60 control primero, después los dos de 90) capturando `dmesg` en cada
uno, y junta el contexto completo. Ya se corrió una vez antes del parche; hay que repetirlo
ahora que el bpc cambió, para ver si aparece algo nuevo — sobre todo cualquier mención a DSC,
color space o formato que antes no estuviera.

```bash
sudo /home/iam/Documents/reverb-g2/scripts/collect-nv.sh
```

Tarda unos minutos (la mayor parte es `nvidia-bug-report.sh`). No hace falta que nadie mire el
casco para esto — es captura de logs del lado del driver.

## Se agotaron los diagnósticos accesibles sin más root (2026-08-05, 01:30)

`collect-nv.sh` corrido de nuevo, ya con el parche puesto, capturando los tres modos.
Confirmado otra vez: **24 bpp** en los tres (antes 18), coincidiendo con el byte 18 del casco.

Tres búsquedas, las tres en blanco:

1. **DSC / color space / YCbCr / compresión**: cero menciones en los tres logs de
   `nvidia-modeset`. Ese callejón está cerrado — no hay evidencia de que NVIDIA esté
   invocando DSC en silencio ni cambiando el color space entre modos.
2. **El log no da más información a este nivel de verbosidad.** Mismo patrón exacto
   (`Attach Begin` → `VIDEO` → `Attach End` → `Delayed HDCP` → `detach`) repetido para cada
   modo, sin una línea de más.
3. **El modeline completo que arma el driver** (no sólo htotal/vtotal, sino front/back porch
   y polaridad de sync, leído directo de `drmModeGetConnector`):

   ```
   4320x2160@90:  H front=50 sync=4 back=46   V front=16 sync=2 back=98    flags=0x5
   2880x1440@90:  H front=50 sync=4 back=46   V front=18 sync=2 back=138   flags=0x5
   4320x2160@60:  H front=50 sync=4 back=46   V front=14 sync=2 back=498   flags=0x5
   ```

   Mismo H blanking en los dos modos de 4320 (60 y 90). Misma polaridad de sync (`flags=0x5`
   = positiva H y V) en los tres. El V blanking escala razonablemente con el vtotal. **Nada
   anómalo a este nivel.**

### Dónde queda esto

Se agotó lo que se puede inspeccionar sin acciones más disruptivas. Lo que queda:

- **`NVreg_ResmanDebugLevel`** en el módulo core — mucho más verboso que `nvidia_modeset
  debug`, pero **obliga a descargar y recargar el módulo**, lo que tira la sesión gráfica.
  No es algo para hacer de paso; hay que planearlo (cerrar sesión, o hacerlo desde una
  consola de texto).
- **Reportar a NVIDIA con todo lo que ya tenemos.** Aunque el bug del bpc no resolvió el
  90Hz por sí solo, es un bug real, verificado en el código fuente, con un parche de dos
  líneas, y con evidencia de que el casco queda en un estado nuevo (parpadeo con contenido en
  vez de logo estático) — información que sus ingenieros, con acceso a las partes cerradas
  del driver (firmware GSP, RM), pueden usar para seguir de donde nosotros no podemos.

Este es un punto de corte razonable para la sesión: cuatro horas de pruebas físicas, un bug
real encontrado y confirmado, y dos callejones más cerrados con evidencia. Lo que sigue
requiere o mucho más tiempo de GPU debugging invasivo, o la colaboración de alguien con
acceso al código cerrado.

## Habilitando los logs del firmware GSP (2026-08-05, 01:45)

La GPU (RTX 3060 Ti = GA104) usa firmware **GSP** (`/lib/firmware/nvidia/595.71.05/gsp_ga10x.bin`):
buena parte de la lógica del resource manager — probablemente incluido el link training de
DisplayPort y la negociación del modo — corre en un microcontrolador **dentro de la GPU**, no
en el módulo de kernel abierto que leemos. Eso explica por qué `nvidia_modeset.debug` estaba
topeado en 7 líneas: no hay más para loguear del lado de Linux, la decisión pasa por otro lado.

Encontrado en `nv-reg.h`: **`NVreg_EnableGpuFirmwareLogs`** — hace que el propio firmware GSP
mande sus logs al host. Por default, en un build de release, está deshabilitado
(`gpu_mgr.c:1024`: la rama `ENABLE_ON_DEBUG` sólo se activa si el driver es un build
`DEBUG`/`DEVELOP`, que no es nuestro caso). Hay que forzarlo con `NVreg_EnableGpuFirmwareLogs=1`.

Se descartó `NVreg_ResmanDebugLevel` en el camino: su default ya es `~0` (todos los bits),
que es la misma pinta que tenía el `debug` de `nvidia_modeset` cuando resultó topeado — huele
a lo mismo, prints de host compilados afuera en un build de release.

`scripts/enable-gsp-logs.sh` escribe `/etc/modprobe.d/99-nvidia-gsp-logs.conf` con esa opción.
**Requiere reiniciar**: el parámetro es del módulo `nvidia` (core), que carga antes que
`nvidia-modeset` — no se puede activar en caliente como hicimos con el `debug` de modeset.

## El firmware de logging del GSP no existe en ningún lado accesible (2026-08-05, 01:50)

Reiniciado con `NVreg_EnableGpuFirmwareLogs=1` puesto y corrido `collect-nv.sh` de nuevo.
**El parámetro se activó correctamente**, pero el driver reporta:

```
nvidia 0000:05:00.0: firmware: failed to load nvidia/595.71.05/gsp_log_ga10x.bin (-2)
NVRM: RmFetchGspRmImages: Failed to load gsp_log_*.bin, no GSP-RM logs will be printed (non-fatal)
```

**Falta un archivo de firmware específico para logging**, distinto del que ya usa el driver en
producción (`gsp_ga10x.bin`). Se buscó en todos los lugares razonables:

- El paquete Debian `firmware-nvidia-gsp` (todas las versiones disponibles en el repo, de
  550.163.01 a 610.57.04): sólo trae `gsp_ga10x.bin` y `gsp_tu10x.bin`, nunca la variante
  `_log_`.
- **El instalador oficial de NVIDIA** (`NVIDIA-Linux-x86_64-595.71.05.run`, 403 MB, bajado
  completo y extraído con `--extract-only`): su `firmware/gsp_ga10x.bin` es **byte a byte
  idéntico** (mismo MD5) al que ya teníamos instalado. **NVIDIA no distribuye públicamente el
  firmware con logging para esta GPU de consumo.**

Con esto se agotó el último recurso de software disponible. La lógica que decide cómo
enganchar el panel a 90Hz corre en un microcontrolador dentro de la GPU, con un firmware
cerrado del que no existe versión pública que hable. **No hay forma de ver, desde Linux, qué
piensa el GSP mientras negocia el modo de 90Hz.**

## Estado

- [x] Cadena causal del bpc verificada en el código y contra tres mediciones independientes
- [x] Parche escrito, compilado e instalado
- [x] Verificado: el byte 18 pasa de 06 a 08 — el parche funciona como predijo el código
- [x] Verificado: el fallo NO es de ancho de banda (los dos modos de 90Hz fallan igual, con
      2x de diferencia en pixel clock)
- [x] Verificado: el estado del casco es ahora byte-idéntico al de Windows — se agotó lo que
      este canal puede decirnos
- [x] Descartado: DSC, color space, YCbCr — cero menciones en los logs con `nvidia_modeset
      debug=1`
- [x] Descartado: el modeline completo (porches, sync, polaridad) — consistente entre los
      tres modos, nada anómalo
- [x] Intentado y agotado: logs del firmware GSP (`NVreg_EnableGpuFirmwareLogs=1`) — falta el
      binario `gsp_log_ga10x.bin`, que **NVIDIA no distribuye públicamente** ni siquiera en su
      instalador oficial completo (verificado por MD5 contra el `.run` de 403 MB)
- [ ] **Se agotó lo accesible desde Linux. El siguiente paso es reportar a NVIDIA** — con el
      bug del bpc (real, confirmado, con parche de dos líneas) y con todo lo demás como
      contexto de diagnóstico ya hecho, para que alguien con acceso al firmware GSP cerrado
      siga desde ahí. Hilo: 337744 (bug 5923212).
- [ ] **No intentado: sniffear el canal AUX de DisplayPort** con un logic analyzer (tipo
      Saleae) en los pines AUX+/AUX-, para ver el DPCD real durante el link training — es la
      única capa que ningún método usado hasta ahora puede mostrar. El link principal (varios
      Gbps) no es sniffeable sin un analizador de protocolo DP dedicado (miles de dólares); el
      AUX corre a ~1MHz y es alcanzable con hardware genérico. Depende de tener el instrumento
      a mano — no vale la pena construir nada para esto sin eso resuelto primero.

### 2026-08-05 (noche): el canal USB queda cerrado también para la TRANSICIÓN, no sólo el estado

Con `windows-kit/` (ver `windows-kit/README.txt`) se capturó por primera vez el momento
exacto de un cambio de refresh EN VIVO en Windows (60→90 y 90→60, sin reconectar el casco),
algo que la comparación anterior de este documento no cubría (esa comparaba dos estados ya
asentados). Resultado: **en el momento de la transición no aparece ningún comando ni reporte
HID especial** — sólo el `DEVICE_STATUS` (0x05) de siempre, con el byte 5 (refresh) y
htotal/vtotal actualizados, y los heartbeats periódicos de 4 bytes (Report ID 0x01) que ya
estaban ahí antes y siguen igual después, sin relación con el modo. Con esto, el canal HID/USB
queda agotado también para la transición, no sólo para el estado estable — cierra del todo esa
vía de investigación.

De paso se resolvió el byte 6 del `DEVICE_STATUS`, que había quedado como la única diferencia
entre una captura de Linux parchado y una de Windows (ver `windows-kit/analyze-windows.py`):
se mantuvo en `0x0e` durante TODA una sesión de Windows de 90 segundos con dos cambios de
refresh en el medio, y en `0x00` en las capturas de Linux del mismo día. Como no cambia con el
refresh, es un valor de sesión/conexión (probablemente un contador de resets del propio
companion desde que arrancó), no algo específico del SO ni del modo — no hace falta seguir
persiguiéndolo.

También se confirmó por captura de pantalla que el Reverb G2 **no aparece como display
seleccionable** ni en "Configuración > Pantalla avanzada" de Windows ni en "Cambiar resolución"
del panel de NVIDIA — las dos sólo listan los monitores de escritorio. La vía de leer DSC desde
ahí queda cerrada por falta de acceso a la pantalla, no por un resultado negativo de esa
pantalla.

---

## Nota de reproducibilidad (importante)

La instalación de esta noche se hizo **editando el árbol fuente directamente**
(`/usr/src/nvidia-595.71.05/src/nvidia-modeset/src/nvkms-dpy.c`), no por el mecanismo
`PATCH[]` de DKMS. Se hizo así a propósito: los otros tres parches ya están aplicados en ese
árbol, y un `PATCH[]` nuevo se aplicaría sobre la copia limpia y chocaría.

Verificado que el cambio llegó al módulo:

| chequeo | resultado |
|---|---|
| el parche en el árbol fuente | sí, `nvkms-dpy.c:3456-3457` |
| `0001`/`0002`/`0003` tocan `nvkms-dpy.c` | **cero** coincidencias cada uno |
| fuente editada | `00:57:47` |
| módulo construido | `00:58:54` |

**Pero la edición directa es frágil**: si `apt` actualiza el paquete de NVIDIA, `/usr/src` se
reemplaza y el parche se pierde **en silencio**. Por eso `bootstrap-lab.sh` ya registra
`PATCH[3]` para instalaciones desde cero.

**Si alguna vez hay que reconciliar las dos vías** (árbol editado + `PATCH[3]` registrado), el
`PATCH[3]` va a fallar por "ya aplicado". El orden correcto es:
`sudo ./scripts/apply-bpc-patch.sh --revert` primero, y recién después dejar que DKMS lo
aplique por `PATCH[3]`.

## Si el parche no alcanza: otras vías para forzar el bpc

En orden de lo que más chance tiene, y todas por debajo de X11/Wayland:

1. **`nvidia_modeset.config_file`** — es el mecanismo propio de NVKMS para reemplazar el EDID
   que ve el parser, o sea el mismo subsistema donde vive la decisión de bpc. El parámetro
   **existe y está compilado** en el módulo (`/sys/module/nvidia_modeset/parameters/config_file`).
   El hueco: la sintaxis del nombre de dpy no está documentada públicamente ni aparece en el
   código abierto (se genera en la parte cerrada del RM). Habría que descubrirlo con
   `nvidia_modeset.debug=1` y mirar dmesg como root.

2. **EDID parcheado**, si se consigue una vía de override que NVIDIA respete. La receta es
   corta: byte `0x14` de `0x80` a `0xA0` (bits 6-4 de `000` a `010` = 8 bpc) y corregir el
   checksum del bloque base restándole `0x20` al byte `127`.

3. **`/sys/kernel/debug/dri/*/DP-1/edid_override`** — barato de probar pero con una duda de
   fondo: no está confirmado si la lógica cerrada de NVKMS lee el EDID por el helper genérico
   de DRM (que vería el override) o si lo saca del canal AUX por su cuenta. Un negativo acá no
   cierra nada. Además escribir el archivo **no dispara hotplug**: hay que desconectar y
   reconectar.

**Descartadas para nuestro setup:** `CustomEDID` de xorg.conf (sólo X11, y nosotros vamos por
Wayland/DRM lease), `drm.edid_firmware=` (nvidia-drm no lo respeta), `nvidia-settings` (no
existe el atributo), y la propiedad DRM `max bpc` (no está implementada en `nvidia-drm.ko`).
