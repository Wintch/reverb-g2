# Contexto para el agente del lab de 90Hz

Estás en una instalación **nueva y limpia** de Debian 13, en un SSD dedicado, cuyo único
propósito es probar si el HP Reverb G2 puede correr a **90 Hz** con el driver NVIDIA
595-open parcheado. Este repo es todo el conocimiento acumulado del proyecto. Leelo antes
de proponer nada: hay varias cosas que ya se probaron y descartaron con medición.

## El objetivo, en una línea

**Que el panel del casco deje de parpadear.** El parpadeo es el strobe del backlight de
baja persistencia del G2 a 60 Hz, y es inherente al modo 60 Hz. La única cura es llegar a
90 Hz. No es un objetivo de rendimiento: el usuario dijo explícitamente que los fps del
video son secundarios frente al parpadeo.

## Por dónde empezar

1. `docs/04-lab-90hz.md` — el plan completo del lab, paso por paso. Es tu guion.
2. `scripts/bootstrap-lab.sh` — automatiza los pasos 1 a 4 de ese documento.
3. `docs/06-known-issues.md` — lo que NO hay que volver a perseguir.

Orden real:
```bash
./scripts/bootstrap-lab.sh deps
./scripts/bootstrap-lab.sh nvidia      # y REINICIAR
./scripts/bootstrap-lab.sh sources
./scripts/bootstrap-lab.sh build
# baseline SIN parches: confirmar que 90Hz TODAVÍA falla (paso 3 del cap. 04)
sudo ./scripts/bootstrap-lab.sh patch-nv    # y REINICIAR
# y ahí sí, el test de 90Hz
```

**No te saltees el baseline sin parches.** Es lo que separa "el driver 595 por sí solo
cambió algo" de "los parches lo arreglaron", y es la única forma de saber qué reportar.

### Dónde quedó todo (2026-08-05, 05:15) — el parche del bpc anda a medias

**El bug del bpc era real y el parche funciona exactamente como predijo el código: el byte 18
del casco pasó de 06 a 08.** Pero eso NO resolvió el 90Hz. Verificación física:

- `4320x2160@90` y `2880x1440@90` (dos anchos de banda que difieren 2x): los DOS ahora
  muestran **parpadeo blanco, sin color** — antes era logo estático sin actividad. Progreso
  real, pero no la solución.
- `4320x2160@60` (control, con el mismo parche): sigue con colores normales.
- Como los dos modos de 90Hz fallan igual pese a tener anchos de banda muy distintos, **no es
  un límite de ancho de banda MIPI**.

**El hallazgo más importante: el estado que reporta el casco ahora es BYTE-IDÉNTICO al de
Windows** (los 33 bytes del `DEVICE_STATUS`, incluido el byte 11 que quedaba pendiente — se
corrigió solo con el bpc). O sea que se agotó lo que este canal de medición puede decirnos: el
casco le dice al host lo mismo que le dice a Windows, y el resultado visual es distinto. La
diferencia que falta no es visible desde este ángulo — hay que buscarla en los logs de NVIDIA
(¿DSC en silencio? ¿color space RGB vs YCbCr? ¿timing fino que htotal/vtotal no capturan?).

Todo el detalle y el próximo paso concreto (recorrer `collect-nv.sh` con el parche puesto):
**`docs/13-bug-6bpc.md`**.

#### Lo anterior (2026-08-04, 20:45)

**Se probó la segunda vía de display entera — Wayland + DRM lease en GNOME/mutter — y el
90Hz falla idéntico. Ocho fallos ya. La causa casi no puede estar en NVIDIA.**

El lease **funciona**: mutter 48.7 de Debian 13, sin parches, ofrece el conector del casco
(`connector 130 DP-1 (HPN)`), Monado lo arrienda y toma `4320x2160@90.00`. Eso descarta el
hilo del foro de NVIDIA sobre DRM lease: **el culpable de ese bloqueo era KWin**, que anuncia
el device pero ofrece cero conectores. Y sin embargo, con el lease otorgado y el modo de 90
tomado, el panel sigue muerto con el logo de HP. El control a 60Hz por la **misma** vía dio
imagen perfecta. Tabla y logs en `docs/04-lab-90hz.md`, "GNOME/mutter ejecutado".

Cambiamos X11 Direct-Mode por Wayland DRM lease — dos mecanismos que casi no comparten código
del lado del driver — y el síntoma no se movió. Sumado a que el 595-open parcheado falló igual
que el sin parchear, del lado de la vía de display ya no queda casi nada.

Para chequear el lease sin levantar Monado: `scripts/check-lease.sh`.

**Y se cerraron las dos hipótesis que quedaban, las dos por evidencia:**

- **NO falta un comando HID de modo.** Se desensambló el driver Oasis de HP (el que corre el
  G2 a 90Hz en Windows hablándole al casco directo). Su único comando de panel es *Display
  Enable* — HID Usage Page `0x03`, Usage `0x21` — que es exactamente el `{0x04,0x01}` que
  Monado ya manda. **No existe comando de refresh rate.** Método, falsos positivos y strings
  del firmware en `docs/09-oasis-driver-re.md`. `docs/07` queda archivado: no hace falta
  bootear Windows.
- **NO es DSC.** Del EDID del casco: `2880x1440@90` pide **10.29 Gbps**, menos de la mitad que
  el `4320x2160@60` que anda perfecto (17.02), contra 25.92 Gbps de enlace. Ese modo no puede
  necesitar compresión y falla igual. Cuarta teoría de ancho de banda que cae medida.

**Lo único que comparten los dos modos que fallan es el 90 Hz.** No es bandwidth, no es
compresión, no es un comando faltante, no es la vía de display, no es contención de heads,
no es la fuente ni el cable.

**El test más barato que discrimina y que NO está corrido:** `2880x1440@90` (modo 0) por
Wayland DRM lease — `./scripts/jack-in-wayland.sh 0`. Sólo se probó en X11.

#### Lo anterior (2026-08-04, 19:10): los parches del 595-open NO arreglan el 90Hz

Reboot hecho, módulo parcheado confirmado en memoria, test corrido con verificación física
en seis casos (tabla completa en `docs/04-lab-90hz.md`, "Paso 5 ejecutado"). Los dos modos de
90Hz siguen dejando el panel apagado con el logo de HP, idéntico al baseline sin parches. El
control a 60Hz se corrió *después* de los fallos y dio imagen perfecta, así que el setup
estaba sano y el resultado es limpio.

También se probó y **se descartó** una hipótesis nueva del usuario: contención de heads /
dominios de reloj de la GPU (él ya había tenido que apagar paneles de 60Hz para llegar a
144Hz en X11). Se probó con un solo monitor y con **cero** — el casco como único display del
sistema — y sigue apagado. No es eso. Para repetirlo sin quedarse sin pantalla está
`scripts/solo-hmd-test.sh`, que restaura el escritorio desde un `trap EXIT`.

~~**La línea viva ahora es otra**: puede que al casco nunca se le pida cambiar a 90Hz
(`wmr_hmd.c:767` manda lo mismo a 60 y a 90). Falta la captura HID de Windows.~~

> **DESCARTADO el mismo día, dos veces** (ver arriba y `docs/09-oasis-driver-re.md`). Se deja
> tachado en vez de borrado porque este párrafo, al quedar sin actualizar unas horas, hizo que
> se resucitara la hipótesis y se la citara como "la única que explica los resultados".
> **Al cerrar una línea, actualizar esta sección en el mismo commit.**

Pendientes que necesitan sudo (prioridad RT para Monado, zram, audio, deps de basalt) siguen
sin hacer; ninguno bloqueaba el test.

## La regla más importante de todo el proyecto

**La verificación del 90 Hz es FÍSICA. Hay que mirar adentro del casco.**

La API de Vulkan/OpenXR reporta éxito y unos felices 90.0 fps **con el panel completamente
negro**. El fallo es invisible por encima del driver. Cualquier conclusión basada en logs,
en `xrandr`, o en el framerate reportado es inválida. Pedile al usuario que se ponga el
casco y te diga qué ve — es el único instrumento que sirve.

Esto vale para todo el proyecto, no sólo para el 90 Hz: la foto 360, el video, el estéreo
VR180, todo se validó con el usuario mirando. Si no lo vio un humano, no está verificado.

## Estado del hardware y lo que ya está descartado

**El casco funciona end-to-end en Linux.** Tracking 3DoF impecable, panel a 60 Hz, audio,
y un player propio de 360/VR180 que reproduce 8K estéreo a 60 fps. Nada de eso es el
problema.

Cosas que **ya se investigaron y hay que dejar quietas** (detalle en `docs/06-known-issues.md`):

- **El cable / el puerto USB.** Era un puerto USB-A malo, ya resuelto. Si falta el
  companion `03f0:0580`, revisá el puerto, no debuguees Monado.
- **La fuente de alimentación del G2.** Se sospechó y se **descartó**: el mismo casco corre
  90 Hz horas en Windows 11 sin una caída. No es eléctrico.
- **Las cámaras de tracking.** Se midió: apagarlas no cambia nada (`WMR_CAMERAS=0`).
- **El ancho de banda de DisplayPort.** Medido: el modo 60 Hz que funciona tiene pixel
  clock MÁS alto que el modo 90 Hz nativo que falla. No es bandwidth: es el refresh rate.
- **Los puertos DP de la GPU.** Test cruzado con un monitor: ambos sanos.

**Lo que sí queda abierto** (pero DESPUÉS del 90 Hz, no ahora): con el panel encendido, el
hub USB2 interno del casco se resetea cada tanto y se lleva al companion y al audio. Vuelve
solo a los ~5 s de matar `monado-service`. Sospechoso actual: cómo maneja el driver WMR de
Monado los reportes HID de keepalive comparado con Windows. Es una molestia, no un bloqueo.

## Trampas concretas que te van a morder

- **El player muestra NEGRO si no encuentra su contenido por defecto.** `LoadPhotoTexture()`
  hace `THROW` cuando el archivo no abre, y eso mata la sesión XR: el compositor queda
  presentando en negro y todo el resto del log dice "éxito". El default apunta a
  `~/Documents/linux_vr_base/photo360/venice_sunset.jpg`, que sólo existe en el sistema
  principal. Pasale `HELLO_XR_PHOTO360=` a algo que exista (en el lab hay una equirect de
  prueba en `~/vr/media/test-equirect.jpg`). Antes de culpar al modo de video, verificá en
  el log de Monado que haya `BEGIN_SESSION` **sin** `END_SESSION` inmediato.
- **El player sale solo si le das `< /dev/null`.** `hello_xr` v3 lee las teclas de transporte
  de stdin y trata `EOF` como "fin de corrida temporizada": lanzado con stdin cerrado muere en
  menos de un segundo, con **exit 0 y sin una sola línea de error**. En el log de Monado se ve
  `client_connected`, swapchains creados y destruidos, y `client_disconnected`, sin ningún
  `BEGIN_SESSION` de la app — parece un fallo del compositor y no lo es. Usá `sleep N |
  hello_xr ...`. Ojo que **monado-service** necesita lo contrario (`XRT_NO_STDIN=1`, si no
  muere con `epoll_ctl(stdin) failed`): al servicio se le saca stdin, al player se le da vivo.
- **Para Wayland hay que elegir bien la sesión en SDDM:** aparecen **dos** entradas llamadas
  sólo "GNOME", una Wayland y otra X11. Elegí "GNOME on Wayland". Y KWin no sirve para el
  lease. `scripts/check-lease.sh` lo verifica en dos segundos antes de perder tiempo.
- **`jack-in.sh` ya no hardcodea las salidas de video** (arreglado 2026-08-04): saca una
  foto del layout real con `xrandr` antes de tocar los CRTC y la restaura después, ciclando
  la rotación y usando `kscreen-doctor` en KDE. Tampoco hardcodea rutas: detecta
  `~/Documents/linux_vr_base` o `~/vr`, y acepta `VR_BASE=` y `HMD_OUTPUT=`.
- **`play360.sh` tenía la misma ruta hardcodeada** (arreglado 2026-08-04): apuntaba a
  `~/Documents/linux_vr_base` y en el lab moría con "falta compilar hello_xr". Ya autodetecta
  igual que `jack-in.sh`. Si tocás uno, sincronizá `scripts/` con la copia de `~/vr/`.
- **`XRT_COMPOSITOR_DESIRED_MODE` del entorno**: hasta el 2026-08-04 `jack-in.sh` lo pisaba
  con 60Hz, así que el test de 90Hz del cap. 04 corría en silencio a 60 y reportaba éxito.
  Ya respeta el valor externo — pero **verificá siempre en el log** qué modo agarró:
  `grep "found display mode" ~/vr/jack-in.log`.
- **El usuario se enoja, con razón, cuando le rompés el monitor vertical.** Pasó varias
  veces. Cada vez que Monado toma `DP-0` en direct-mode, el driver NVIDIA reprograma los
  CRTC y pierde la rotación del monitor portrait — y `xrandr` sigue *reportando* "right"
  mientras el panel muestra landscape. El arreglo que funciona es ciclar la rotación
  (`none` → `right`), y en KDE conviene hacerlo con `kscreen-doctor`, no con `xrandr`.
- **Secuencia de arranque de Monado**: el panel sólo enciende cuando Monado manda la
  activación WMR, pero Monado sólo puede tomar el display si X no lo está usando. Por eso
  `jack-in.sh` arranca el servicio, lo mata con `kill -9` (un `SIGTERM` mandaría el
  screen-off y volveríamos al principio), libera `DP-0`, y recién ahí arranca de verdad.
  `WMR_DISPLAY_INIT_SLEEP_SECONDS=2` es load-bearing: con el default de 4 s el panel ya se
  apagó cuando Monado lo busca, y el servicio se duerme para siempre.
- **Borrá `/run/user/1000/monado_comp_ipc` antes de CADA arranque.** `SIGKILL` no lo limpia.
- **`pgrep -f` se matchea a sí mismo** en entornos donde el shell lleva el patrón en su
  cmdline. Usá `pgrep -f "monado[-]service"`. Un PID que cambia en cada chequeo es la señal.
- **`pkill` está bloqueado** en el entorno de Claude Code (exit 144, aborta la cadena).
  Usá `kill` sobre PIDs de `pgrep`.
- **El parche 90Hz de Monado de Project-VR** (`nominal_frame_interval_ns = 1e9/90`) **ya
  está aplicado** en el árbol del lab desde el 2026-08-04. Se aplicó *antes* del baseline a
  propósito, para que el único cambio entre la medición sin parches y la de después sea el
  driver NVIDIA. `bootstrap-lab.sh` no lo trae: si rehacés `sources` desde cero, bajalo de
  `patches/consolidated/monado/0001-*.patch` del repo de Project-VR (aplica limpio).

## Qué hay en este repo

```
docs/00-hardware-usb.md     topología USB, el split SuperSpeed/USB2, procedimientos
docs/01-bringup-monado.md   build y arranque del runtime
docs/02-player-360.md       el player 360/VR180 (v3): proyecciones, pipeline, medición
docs/03-controllers.md      estado de los controllers (3DoF, límite del driver upstream)
docs/04-lab-90hz.md         >>> TU GUION <<<
docs/05-resolve.md          DaVinci Resolve (otro objetivo del rig, no toca esto)
docs/06-known-issues.md     lo descartado, con evidencia
docs/07-captura-hid-windows.md  ARCHIVADO: el comando de modo no existe (ver cap. 09)
docs/08-passthrough-y-limites.md  idea de passthrough + límites por marcas (no empezado)
docs/09-oasis-driver-re.md  qué le manda Windows al panel, leído del driver de HP
docs/10-recursos.md         índice de fuentes: driver de HP, FCC, chips, parque instalado
docs/11-panorama-hmd-linux.md  ¿es sólo NVIDIA? otros cascos, DK2, y dónde publicar
docs/12-protocolo-g2.md     >>> REFERENCIA DEL PROTOCOLO <<< todo lo que sabemos del casco
docs/13-bug-6bpc.md         >>> EL BUG <<< NVIDIA clava el G2 en 6 bits por color
windows-kit/                paquete de captura para Windows (se empaqueta en windows-kit.7z)
patches/nvidia/             los 3 parches de Project-VR para el 595-open
patches/monado/             7 parches nuestros (companion, controllers, WMR_CAMERAS)
patches/hello_xr-player/    3 parches: el player 360/VR180 completo
scripts/bootstrap-lab.sh    instalación automatizada del lab
scripts/jack-in.sh          levanta el pipeline VR (AJUSTAR las salidas de video)
scripts/play360.sh          reproduce 360/VR180/plano en el casco
scripts/get360.sh           baja video VR de YouTube (necesita el cliente android_vr)
scripts/solo-hmd-test.sh    test con el casco como ÚNICO display (restaura con trap EXIT)
scripts/check-lease.sh      ¿el compositor Wayland ofrece el conector del casco? (sin Monado)
scripts/xref.py             xrefs de strings en binarios PE, sólo con binutils
scripts/jack-in-wayland.sh  levanta el pipeline VR por DRM lease (Wayland; necesita GNOME)
scripts/drmprops.c          lee non-desktop/modos del conector directo del kernel
scripts/capture-hid.sh      captura el HID del companion por modo (usbmon, necesita root)
scripts/analyze-hid.py      diffea capturas HID: usbmon (Linux) y TSV de tshark (Windows)
```

Los árboles de código no vienen en el bundle: `bootstrap-lab.sh` los clona de upstream en
los SHA exactos contra los que los parches fueron generados, y aplica los parches. Así el
bundle pesa kilobytes y se ve exactamente qué es nuestro.

## Cómo trabaja este usuario

- Habla español. Contestale en español.
- Es técnico y quiere el porqué, no sólo el qué. Las mediciones le importan más que las
  opiniones — si vas a afirmar algo, medilo.
- **Corregí el rumbo cuando la evidencia lo contradiga.** En este proyecto ya hubo tres
  conclusiones dadas por buenas que resultaron falsas (el cable, la fuente, el audio
  "bloqueado por hardware"). Cada una costó semanas. Si algo no cierra, decilo.
- No declares nada verificado sin que él lo haya visto. Ya pasó que se dio por bueno un
  render que nunca se había mirado.

## Si el 90 Hz funciona

Registrar en `docs/04-lab-90hz.md`: qué modo anduvo (`XRT_COMPOSITOR_DESIRED_MODE`),
estabilidad a 15+ minutos, y re-correr el smoke test de video del cap. 02 (el path
NVDEC/cuvid debería andar igual en 595, pero hay que verificarlo explícitamente).

Recién ahí se planifica la instalación definitiva. El criterio de corte acordado con el
usuario es **"el casco a la par de Windows o mejor"**.
