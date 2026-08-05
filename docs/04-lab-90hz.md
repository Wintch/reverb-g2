# 04 — Lab 90Hz: Debian en SSD aparte + driver 595-open parcheado

## Por qué así

El G2 no pasa de 60Hz en NVIDIA/Linux por bugs del driver (NVIDIA bug 5923212: parser
DisplayID que tira el modo nativo, tablas DSC 1.1 fuera de spec — el handshake de
compresión del modo 90Hz falla — y parsing del VSDB de Microsoft). Medido acá: NO es ancho
de banda (el modo 60Hz que anda tiene pixel clock MÁS alto que el 90Hz nativo que falla).
NVIDIA no lo arregló en ninguna versión hasta la 610.x (jul 2026).
[Project-VR](https://github.com/AshishKumar4/Project-VR) lo arregla parcheando los **open
kernel modules**; probado por su autor solo en RTX 4080. Análisis nuestro: los parches son
genéricos (el path Ampere `nvkms-evo3.c` está cubierto) y la 3060 Ti (GA104) está
soportada por los open modules — debería andar, pero es exactamente lo que el lab prueba.

**Por qué un sistema aparte:** reemplaza el stack gráfico completo. Si sale mal, el
sistema principal ni se entera — rollback = elegir el otro disco en el boot menu.

**Decisiones tomadas:**
- **Debian 13 estable (trixie)** también en el lab. NVIDIA publica un repo apt para
  debian13 con **exactamente 595.71.05**, la versión que Project-VR parchea — cero rebase.
  (El 550-open empaquetado por Debian ni compila en kernel 6.12.100; descartado.)
  Testing/sid rompería el rebuild DKMS con cada kernel nuevo — no para un experimento.
- **Sesión X11**, no Wayland: todo nuestro pipeline Monado usa el direct-mode NVIDIA vía
  X11/XRandR. El path Wayland necesita el parche 0002 completo + parche de Monado 0008 +
  compositor con soporte (Project-VR lo validó en GNOME/mutter parcheado; en KDE no está
  probado). Wayland queda como camino futuro.
- Esta máquina bootea **BIOS/legacy → no hay Secure Boot ni MOK**. Un paso menos.

## Paso 1 — Install base (SSD libre)

1. Conectar el SSD libre (a un puerto del controlador del chipset, ver cap. 00).
2. Debian 13 netinst → instalar en ese disco, **KDE o XFCE**, con el disco principal
   DESCONECTADO idealmente (evita que el instalador toque el GRUB del sistema bueno).
   Si no, elegir con cuidado el destino del bootloader = el SSD del lab.
3. Primer boot, básicos:

```bash
sudo apt install -y build-essential dkms linux-headers-amd64 git curl \
    cmake ninja-build meson pkg-config glslang-tools \
    libvulkan-dev vulkan-tools vulkan-validationlayers \
    libeigen3-dev libusb-1.0-0-dev libudev-dev libhidapi-dev \
    libgl-dev libglx-dev libglvnd-dev libxcb-randr0-dev libx11-xcb-dev \
    libavcodec-dev libavformat-dev libavutil-dev libswscale-dev ffmpeg
# udev del casco:
sudo cp scripts/70-wmr-reverb.rules scripts/71-usb-no-autosuspend.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo usermod -aG plugdev,adm,systemd-journal $USER
```

## Paso 2 — Driver NVIDIA 595.71.05 (repo oficial debian13)

**NO instalar el nvidia-driver de Debian en el lab.** Los stacks son excluyentes.

```bash
# Keyring + repo de NVIDIA para Debian 13:
curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/cuda-keyring_1.1-1_all.deb -o /tmp/cuda-keyring.deb
sudo dpkg -i /tmp/cuda-keyring.deb
sudo apt update

# Pin a la versión exacta que Project-VR parchea, e instalar el stack open:
sudo apt install -y nvidia-driver-pinning-595.71.05
sudo apt install -y nvidia-open
# (el paquete DKMS de NVIDIA se llama nvidia-kernel-open-dkms — OJO, Debian tiene otro
#  casi homónimo, nvidia-open-kernel-dkms 550: no mezclar)
sudo reboot
```

## Paso 3 — Baseline SIN parches (control del experimento)

Compilar Monado + Basalt en el lab (cap. 01), correr `jack-in.sh`, y confirmar que 90Hz
**sigue fallando igual** (modos 0 y 1 = panel negro con el logo, modo 2 = 60Hz anda).
Esto separa "el driver 595 cambió algo" de "los parches lo arreglaron".

## Paso 4 — Aplicar los parches vía DKMS

Los parches se enganchan al árbol DKMS que el paquete deja en `/usr/src/nvidia-595.71.05/`,
usando el mecanismo `PATCH[]` de dkms.conf — así se re-aplican solos con cada kernel:

```bash
cd /usr/src/nvidia-595.71.05
sudo mkdir -p patches
sudo cp ~/reverb-g2-linux/patches/nvidia/000*.patch patches/

# Registrar los parches en dkms.conf (agregar al final):
sudo tee -a dkms.conf >/dev/null <<'EOF'
PATCH[0]="0001-nvkms-VESA-DisplayID-DSC-VSDB-spec-correctness-fixes.patch"
PATCH[1]="0002-nvkms-nvidia-drm-enable-Wayland-DRM-lease-of-VR-HMDs.patch"
PATCH[2]="0003-dp-force-maximum-link-config-for-the-HP-Reverb-G2-ED.patch"
EOF

# Verificar que aplican en seco ANTES de rebuilder:
for p in patches/000*.patch; do sudo patch -p1 --dry-run < "$p" || echo "FALLO: $p"; done

# Rebuild + reinstall del módulo:
sudo dkms remove nvidia/595.71.05 --all
sudo dkms install nvidia/595.71.05
sudo reboot
```

Nota: `dkms` aplica `PATCH[]` sobre una copia al momento del build — el árbol fuente queda
limpio, y un upgrade de kernel re-aplica todo automáticamente. Si un futuro
`apt upgrade` trae 595.91.07, los parches aplican igual (verificado contra ese árbol);
en 610.x hay que dropear los dos hunks de `flatnessDetThresh` del 0001 (NVIDIA ya lo
arregló ahí) — el resto sigue haciendo falta.

## Paso 5 — Monado con el fix de 90Hz

Al Monado del lab aplicarle nuestros parches (`patches/monado/`) **más** el 0001 de
Project-VR (`nominal_frame_interval_ns = 1e9/90` en `wmr_hmd.c` — sin esto el bridge de
SteamVR calcula 1/0 y cae a 60Hz con judder; aplica limpio sobre main):

```bash
curl -fsSL https://raw.githubusercontent.com/AshishKumar4/Project-VR/main/patches/consolidated/monado/0001-drivers-wmr-Set-90-Hz-nominal-frame-interval-on-WMR-.patch | git -C monado am
```

(El nombre exacto del archivo puede variar — listar `patches/consolidated/monado/` del repo.)

## Paso 6 — El test

```bash
./jack-in.sh 3dof     # pero con XRT_COMPOSITOR_DESIRED_MODE=0  (2880x1440@90 nativo)
# y si falla, probar =1 (4320x2160@90)
```

**Mirar el panel físicamente.** La API reporta éxito y 90fps aunque el panel esté negro —
la única verificación válida es el ojo. Resultado esperado con parches: imagen a 90Hz y
adiós flicker de backlight-strobe de 60Hz.

Registrar en este capítulo: modo que funcionó, estabilidad (15+ min), temperatura/clocks
(`nvidia-smi -q -d SUPPORTED_CLOCKS` — NO copiar los lock-clocks de Project-VR, son de Ada),
y re-correr el smoke test de video del cap. 02 (el path NVDEC/cuvid debería andar igual en
595; verificarlo explícitamente).

### Resultado del baseline — 2026-08-04, lab (Debian 13, KDE/X11, 595.71.05-open SIN parches)

Verificado **físicamente**, casco puesto, con `hello_xr` mostrando una equirect de prueba
(`ffmpeg -f lavfi -i testsrc2=size=4096x2048`, en `~/vr/media/test-equirect.jpg`):

| `XRT_COMPOSITOR_DESIRED_MODE` | modo que reporta el compositor | qué se ve adentro del casco |
|---|---|---|
| 2 | 4320x2160@60.00 | imagen correcta + el strobe de 60Hz de siempre |
| 0 | 2880x1440@90.00 | **panel apagado, sólo el logo de HP** |
| 1 | 4320x2160@90.00 | **panel apagado, sólo el logo de HP** |

**Conclusión: el 595-open por sí solo NO arregla el 90Hz.** El fallo es idéntico al del 550
en el sistema principal, así que cualquier cosa que ande después del paso 4 es atribuible a
los parches y no a la versión del driver. Control del experimento cumplido.

Detalles que conviene tener a mano:

- La numeración de modos **no cambió** entre el 550 y el 595 (se sospechó y se descartó):
  el log en `XRT_COMPOSITOR_LOG=debug` confirma `Found 3 modes` y el mapeo 0=2880x1440@90,
  1=4320x2160@90, 2=4320x2160@60.
- En los dos modos de 90Hz la API reporta éxito completo: `BEGIN_SESSION` sin cierre,
  frame interval de 89.999/90.001 Hz, ambos procesos con memoria en la GPU. Nada arriba del
  driver delata el fallo. Es la regla del proyecto en estado puro.
- Para leer la tabla de modos hace falta `XRT_COMPOSITOR_LOG=debug`: `print_modes()` usa
  `COMP_PRINT_MODE`, que no sale en el nivel por defecto.

### Paso 4 ejecutado — 2026-08-04 18:26

`bootstrap-lab.sh patch-nv` corrió limpio: los tres parches pasaron el dry-run, dkms los
aplicó sobre su copia, compiló, firmó e instaló los cinco módulos. Verificado después:

- `dkms.conf` tiene las tres líneas `PATCH[0..2]` → un upgrade de kernel los re-aplica solo.
- `/usr/src/nvidia-595.71.05/` queda **sin parchear** (dkms trabaja sobre una copia).
- Módulos nuevos en `/lib/modules/6.12.100+deb13-amd64/updates/dkms/`.
- La firma MOK es irrelevante acá: la máquina bootea BIOS/legacy, sin Secure Boot.

**Pendiente: reiniciar.** Hasta el reboot sigue corriendo el módulo viejo sin parches.

### Cómo retomar después del reboot

```bash
# 1. Confirmar que el módulo cargado es el parcheado (fecha de build, no versión:
#    la versión sigue siendo 595.71.05 en ambos casos)
modinfo nvidia-modeset | grep -E "^filename|^version"
ls -l /lib/modules/$(uname -r)/updates/dkms/nvidia-modeset.ko.xz

# 2. Casco enchufado: los CINCO tienen que estar (ver cap. 00)
lsusb | grep -E "03f0:0580|045e:0659|04b4:650[46]|0bda:4c15"

# 3. El test. MODE=0 primero (2880x1440@90 nativo)
cd ~/vr && XRT_COMPOSITOR_LOG=debug XRT_COMPOSITOR_DESIRED_MODE=0 ./jack-in.sh 3dof
grep -E "found display mode|frame interval" ~/vr/jack-in.log   # confirmar que agarró @90

# 4. Contenido para ver algo (el default del player apunta al sistema principal):
sleep 600 | XR_RUNTIME_JSON=$HOME/vr/monado/build/openxr_monado-dev.json \
  IPC_IGNORE_VERSION=1 VK_LOADER_LAYERS_DISABLE='*' \
  HELLO_XR_PHOTO360=$HOME/vr/media/test-equirect.jpg \
  ./OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr --graphics Vulkan2

# 5. MIRAR ADENTRO DEL CASCO. Si falla el modo 0, probar MODE=1.
```

Si anda: dejarlo 15+ min, después el smoke test de video del cap. 02 (NVDEC/cuvid en 595),
y recién ahí planificar la instalación definitiva.

### Paso 5 ejecutado — el test CON parches: FALLA (2026-08-04, 18:38–18:55)

Reboot hecho, módulo parcheado confirmado cargado (`.ko` del build de las 18:26, dkms
`installed`), los cinco USB presentes. Verificación **física** en los seis casos, el usuario
mirando adentro del casco:

| Modo | Resolución@Hz | Displays de escritorio activos | Resultado |
|---|---|---|---|
| 2 | 4320x2160@60 | 3 | **imagen correcta** (control) |
| 0 | 2880x1440@90 | 3 | panel apagado, logo de HP |
| 1 | 4320x2160@90 | 3 | panel apagado, logo de HP |
| 0 | 2880x1440@90 | 1 (sólo DP-3) | panel apagado, logo de HP |
| 0 | 2880x1440@90 | **0 (casco único display)** | panel apagado, logo de HP |

**Conclusión: los tres parches de Project-VR para el 595-open NO arreglan el 90Hz acá.**
El comportamiento es idéntico al baseline sin parches y al del 550 en el sistema principal.

El control a 60Hz se corrió *después* de los fallos, con los parches puestos, y dio imagen
perfecta: el setup está sano y el resultado es limpio. No es "negro en todo".

### Descartado en el mismo test: contención de displays (hipótesis del usuario)

Hipótesis razonable y nunca antes probada: en X11 el usuario ya había tenido que apagar sus
paneles de 60Hz para que su monitor llegara a 144Hz, y `jack-in.sh` deja los tres monitores
encendidos cuando Monado toma `DP-0`. Con el casco son 4 heads en una 3060 Ti — justo el
límite. **Es una teoría distinta de la del ancho de banda del cable DP** (ya descartada en
el cap. 06): ésta es sobre el display engine de la GPU, no sobre el enlace.

Se probó y **se descarta**, en dos escalones: con un solo monitor y con **cero**. Con el
casco como único display del sistema el panel sigue apagado. No es contención de heads ni
de dominios de reloj.

Los pixel clocks medidos, que además matan la variante "presupuesto de bandwidth agregado":

| Display | Modo | Pixel clock |
|---|---|---|
| Casco mode 2 (**anda**) | 4320x2160@60 | 709.150 MHz |
| Casco mode 0 (falla) | 2880x1440@90 | **428.580 MHz** |
| Casco mode 1 (falla) | 4320x2160@90 | 905.400 MHz |

El mode 0 falla consumiendo **menos** clock que el mode 2 que funciona, con los mismos
heads encendidos. Si fuera presupuesto de ancho de banda, el mode 0 tendría que andar.

Para repetir el test sin quedarse sin pantalla: `scripts/solo-hmd-test.sh` apaga todo el
escritorio, corre el test y **restaura el layout desde un `trap EXIT`** (incluido el ciclo
de rotación de `DP-3` con `kscreen-doctor`). Sobrevive a que el script falle.

### Hipótesis viva: a nadie le está diciendo al casco que vaya a 90Hz

Hallazgo de código, no medición todavía. En `src/xrt/drivers/wmr/wmr_hmd.c`:

- `wmr_hmd_activate_reverb()` (línea ~767) manda **siempre la misma secuencia HID** —
  `0x50`×4, `0x09`, `0x08`, `0x06`, y `wmr_hmd_screen_enable_reverb()`. No hay ni una rama
  que dependa del refresh rate. La activación de 60Hz y la de 90Hz son idénticas.
- El "parche 90Hz de Monado" (línea ~1992) sólo hace
  `nominal_frame_interval_ns = 1e9/90.0`. Su propio comentario lo explica: existe para que
  el bridge de SteamVR no calcule `1/0` y se caiga a 60. Es un valor **reportado hacia
  arriba** para el pacing. **No toca el panel.**

O sea: se le pide al conector DisplayPort un modo de 90Hz, pero el panel del G2 nunca
recibe una orden de reconfigurarse. Eso es consistente con los seis resultados de arriba —
incluido el porqué los parches de NVIDIA no movieron nada: **el problema puede no estar en
NVIDIA.**

Falta confirmar que el G2 realmente exija un comando propietario para 90Hz en vez de
negociarlo por modeset. Camino natural: capturar el tráfico HID del casco en Windows 11
(donde el 90Hz anda horas) y diferenciarlo contra lo que manda Monado.

### Medido: Monado manda lo mismo a 60 y a 90 Hz (2026-08-04, 19:10)

Ya no es sólo lectura de código. Captura con `usbmon` del companion durante el arranque de
Monado, un archivo por modo (`scripts/capture-hid.sh`), analizado con
`scripts/analyze-hid.py`. Toda la conversación HID de clase con el casco, completa:

| Transferencia | modo 2 — 60Hz (**panel enciende**) | modo 1 — 90Hz (**panel apagado**) |
|---|---|---|
| `SET_REPORT` Feature `0x50` = `5001` | ×4 | ×4 |
| `GET_REPORT` Feature `0x50` | ×4 | ×4 |
| `GET_REPORT` Feature `0x09` | ×1 | ×1 |
| `GET_REPORT` Feature `0x08` | ×1 | ×1 |
| `GET_REPORT` Feature `0x06` | ×1 | ×1 |
| `SET_REPORT` Feature `0x04` = `0401` (screen ON) | ×2 | ×2 |

13 transferencias en cada caso. El diff da **cero** diferencias. Al casco se le manda
exactamente lo mismo cuando el panel enciende y cuando no. Esto es la línea base contra la
cual comparar Windows (cap. 07).

Dos cosas para no tropezar al repetirlo:

- **La captura del modo 0 no sirvió** y hay que rehacerla: el companion se re-enumeró en
  pleno arranque (apareció recién como device 085) y Monado nunca completó la secuencia con
  él — el archivo no tiene un solo `SET_REPORT 0x50`. Es el reset del hub USB2 del cap. 06.
  No invalida nada: el modo 1 también es 90Hz y quedó limpio. **Criterio de captura válida:
  tiene que haber un `SET_REPORT` Feature `0x50`.**
- **El device address del companion cambia en cada corrida** (79, 91, 85...). Hardcodearlo
  no sirve; `analyze-hid.py` lo detecta por el descriptor `f0038005` (`03f0:0580` en little
  endian) y, si hay varios, se queda con el que realmente recibió comandos.

Y una trampa que costó dos corridas: **el bus 3 está lleno de tráfico que parece HID y no lo
es** — descriptores de string en UTF-16 que se leen como reportes con payloads plausibles.
Hay que filtrar por transferencias de control de clase (`bmRequestType` 0x21/0xa1 con
`bRequest` 0x09/0x01) o el análisis da puro ruido con cara de señal.

### GIRO: el 90Hz en NVIDIA SÍ funciona — Project-VR lo tiene andando (2026-08-04, 19:30)

Búsqueda en las fuentes, después de cerrar el lab. Cambia el plan entero.

[Project-VR](https://github.com/AshishKumar4/Project-VR) —el repo de donde salieron nuestros
tres parches— **reporta el G2 corriendo a `4320x2160 @ 90 Hz` en una RTX 4080 con el mismo
`nvidia-driver-595-open` y los mismos parches.** No es un problema abierto: es un problema
resuelto que a nosotros no nos anduvo.

Y ahora se sabe **por qué** el 60 anda y el 90 no: **el modo de 90Hz usa DSC (Display Stream
Compression)**. El parche 0001 arregla las tablas de rate-control DSC 1.1 y el parsing de
DisplayID 2.0 — textualmente, *"needed for the 90 Hz handshake to succeed"*.

Eso explica de una por qué **todos** los razonamientos por ancho de banda fallaron: el
nuestro del display engine, el del usuario sobre los paneles, y la teoría de los 2 lanes que
circula en el [hilo de NVIDIA](https://forums.developer.nvidia.com/t/reverb-g2-unable-to-drive-more-than-60hz-mode-on-nvidia/337744).
Con DSC el pixel clock crudo no es el limitante — lo que importa es si el handshake de
compresión se completa. Anotarlo: fue el tercer descarte de una teoría de bandwidth.

Estado del bug upstream: NVIDIA confirma el **5923212**, lo reproduce, sigue en investigación,
y el último reporte del hilo (**19 de julio de 2026**) dice que persiste en **610.43.02**.
Esperar upstream no es plan.

**Muere la hipótesis del comando HID** de la sección anterior: Project-VR llega a 90Hz con
parches al driver de video, sin ningún comando propietario. La secuencia HID idéntica que
medimos es correcta y suficiente. `docs/07` (captura en Windows) queda como material
archivado — **no hace falta bootear Windows.**

#### Las dos diferencias con el setup que funciona

1. **Ampere vs Ada.** Ellos validaron en RTX 4080 (AD103); acá hay una 3060 Ti (GA104). El
   README de `patches/nvidia/` afirma que el path `nvkms-evo3.c` de Ampere está cubierto,
   pero eso es lectura de código y el resultado empírico dice que no.
2. **X11 direct-mode vs Wayland DRM lease.** Nuestro log dice `Selected NVIDIA Direct-Mode
   backend!` con `VK_EXT_acquire_xlib_display`. Project-VR corre **Wayland con DRM lease**, y
   el parche 0002 se llama literalmente `enable-Wayland-DRM-lease-of-VR-HMDs`. El README
   sostiene que esa maquinaria es código muerto en X11 — otra afirmación sin verificar.

La segunda es gratis de probar y es la única variable de setup que se puede cambiar sin
comprar hardware. Va primero.

### Probar Wayland + DRM lease

```bash
# 1. Cerrar sesion y elegir "Plasma" (NO "Plasma (X11)") en SDDM.
# 2. Reanudar el agente si hace falta:  claude --continue
# 3. El HMD NO tiene que aparecer en Configuracion > Pantallas. Si aparece, KWin lo tomo
#    como monitor y el parche 0002 (marcarlo non-desktop) no esta haciendo efecto.
cd ~/vr && ./jack-in-wayland.sh 1     # 1 = 4320x2160@90, el modo de Project-VR
```

`jack-in-wayland.sh` es mucho más simple que `jack-in.sh`: con DRM lease no hay que pelearle
el display a X, así que **no toca ningún monitor del escritorio** — no hay liberación de
`DP-0`, ni ciclado de CRTC, ni el problema de la rotación del portrait.

**Lo que hay que mirar en la salida** (el script lo imprime solo): el backend elegido. Si
sigue diciendo `Selected NVIDIA Direct-Mode backend!`, el DRM lease no se usó y el test no
vale. Tiene que aparecer el path de Wayland/lease.

Y después, como siempre: **mirar adentro del casco.** La API va a reportar 90.0 fps felices
con el panel negro.

### Wayland ejecutado: bloqueado en KWin, pero con tres descartes medidos (2026-08-04, 20:05)

No llegó a haber test de 90Hz: el path de DRM lease no se pudo levantar. Pero el camino dejó
cosas verificadas que valen más que el intento.

**1. El parche 0002 FUNCIONA. Medido, no deducido.** El conector del casco está marcado
`non-desktop=1` y KWin lo deja afuera del escritorio (lista sólo los 3 monitores). Leído del
kernel con `scripts/drmprops.c`:

```
connector 130  type=10  CONNECTED  modes=3
    non-desktop  = 1
    mode: 4320x2160@90
    mode: 2880x1440@90
    mode: 4320x2160@60
```

Con lo cual: **el lado del driver NVIDIA está haciendo su parte.** Los tres modos están
expuestos, el HMD está marcado como arrendable. Lo que falta está más arriba.

**2. Monado estaba compilado SIN Wayland, y nada lo delataba.** El síntoma en runtime era
`Could not find target factory with identifier 'direct_wayland'`. Causa raíz: faltaba
**`libdrm-dev`**, y la lógica de CMake de Monado es

```cmake
option_with_deps(XRT_HAVE_WAYLAND ... DEPENDS WAYLAND_FOUND WAYLAND_SCANNER_FOUND
                 WAYLAND_PROTOCOLS_FOUND LIBDRM_FOUND)
```

o sea que sin libdrm se cae Wayland **entero**, y con él `XRT_HAVE_WAYLAND_DIRECT`. CMake no
avisa: deja las opciones en OFF y compila igual. `bootstrap-lab.sh` traía `libwayland-dev` y
`wayland-protocols` pero no `libdrm-dev` — ya corregido, con el comentario de por qué.
Reconfigurado y recompilado: `WAYLAND: ON`, `WAYLAND_DIRECT: ON`.

**3. Con todo eso resuelto, KWin no ofrece el conector.** Monado ve el device pero cero
conectores:

```
INFO [_drm_lease_device_drm_fd] Available DRM lease device: /dev/dri/card0
INFO [comp_window_direct_wayland_init] Found no connectors available for direct mode
```

Ese síntoma exacto está reportado en el [foro de NVIDIA](https://forums.developer.nvidia.com/t/nvidia-proprietary-non-open-modules-completely-unable-to-acquire-a-drm-lease-on-any-display-server-all-known-nvidia-drivers-any-hardware/341244)
como fallo de DRM lease con drivers NVIDIA, sin resolver al 16-nov-2025. El hilo es sobre los
módulos cerrados, pero hay un reporte con módulos **open** en RTX 4080. Plasma 6.3.6 todavía
no tiene el toggle de "VR Mode / Display Leasing" (está en un MR draft de KWin).

**Trampa para el que siga:** `XRT_COMPOSITOR_FORCE_VK_DISPLAY` **no es una alternativa
inocente.** Enumera todos los displays del sistema y con índice `0` agarró el monitor LG del
usuario, no el casco (`Will use display: LG Electronics LG ULTRAGEAR (HDMI-0)`), y segfalleó.
Si se prueba, hay que identificar primero el índice del HMD.

#### Lo que Project-VR realmente necesita (y sube el costo de replicarlo)

Releyendo su README con foco en el runtime: **no es sólo "GNOME en vez de KDE".** Usan
GNOME 50 / mutter 50.1 **con parches propios a Mutter**, SteamVR como runtime, su fork de
WMR cargado dentro de `vrserver`, y su propio orquestador (`g2-studio` / `infra/g2ctl`).

El matiz que deja la puerta abierta: sus parches a Mutter son para que *"el escritorio no se
cuelgue durante/después de VR"* (ciclo de vida del lease, freezes de input/render) — **no**
para que el lease funcione en primer lugar. Así que Mutter *sin* parchear debería igual
ofrecer el conector, y eso es lo que discrimina si el problema es KWin o es NVIDIA.

**Siguiente test, en orden de costo:** instalar GNOME y probar una sesión GNOME Wayland con
`jack-in-wayland.sh`. Si Mutter ofrece el conector, el problema era KWin y se sigue por ahí.
Si tampoco lo ofrece, el problema es NVIDIA + DRM lease, coincide con el hilo del foro, y hay
que decidir si vale replicar el stack entero de Project-VR o quedarse en 60Hz.

### GNOME/mutter ejecutado: el lease anda, el 90Hz sigue fallando (2026-08-04, 20:45)

El test discriminante del bloque anterior está corrido, y contesta las dos preguntas que
tenía pendientes — una a favor y otra en contra.

**1. El culpable del lease era KWin, no NVIDIA.** Con GNOME 48.7 / mutter 48.7 de Debian 13,
**sin ningún parche**, el conector del casco aparece ofrecido para arrendar. Leído con
`wayland-info` (`scripts/check-lease.sh`):

```
interface: 'wp_drm_lease_device_v1', version: 1, name: 35
	path: /dev/dri/card0
	connector:
		id: 130
		name: DP-1
		description: HPN
```

| | KWin 6.3.6 | mutter 48.7 |
|---|---|---|
| anuncia `wp_drm_lease_device_v1` | sí | sí |
| ofrece conectores | **cero** | **conector 130 `DP-1 (HPN)`** |
| lease otorgado | no | **sí** |

Y Monado lo toma sin pelear:

```
INFO  [_lease_connector_done] [/dev/dri/card0] connector DP-1 (HPN) id: 130
DEBUG [_lease_fd] Lease granted
DEBUG [compositor_try_window] Target backend wayland-direct initialized!
DEBUG [get_primary_display_mode] found display mode 4320x2160@90.00
```

Esto **descarta el hilo del foro de NVIDIA** para nuestro caso: el 595.71.05-open concede
leases perfectamente. El bug era del compositor. Los parches a mutter de Project-VR no hacen
falta para levantar el lease, tal como se había predicho.

**2. Y sin embargo el 90Hz falla exactamente igual.** Verificación física, el usuario con el
casco puesto:

| modo | vía | lease | modo tomado | qué se ve adentro |
|---|---|---|---|---|
| 1 | Wayland DRM lease | otorgado | `4320x2160@90.00` | **logo de HP, panel muerto** |
| 2 | Wayland DRM lease | otorgado | `4320x2160@60.00` | **imagen perfecta** |

El control a 60Hz se corrió *después* del fallo, por la misma vía y con el mismo lease, así
que el path está sano y el resultado es limpio. Con esto son **ocho** fallos de 90Hz.

**Lo que esto cierra.** Cambiamos la ruta de video entera — X11 NVIDIA Direct-Mode →
Wayland DRM lease, dos mecanismos que casi no comparten código del lado del driver — y el
fallo no se movió: mismo síntoma exacto, mismo logo de HP. Sumado a que el 595-open parcheado
falló igual que el sin parchear, ya casi no queda superficie del lado de NVIDIA donde la
causa pueda estar escondida.

**Lo que NO se sigue de esto.** Al escribir esta sección se dijo que la hipótesis del comando
HID quedaba "como la única que explica los ocho resultados", y se propuso la captura HID de
Windows como siguiente paso. **Era un error**: el bloque anterior (`GIRO`, 19:30) ya la había
descartado, y `CLAUDE.md` había quedado desactualizado dándola por viva. Peor: unas horas
después se leyó el driver de HP y se confirmó que **el comando de modo no existe**
(`docs/09-oasis-driver-re.md`). Se deja el error escrito porque es exactamente el tipo de
recaída que este proyecto ya pagó tres veces.

**El siguiente paso real está en la sección de abajo**, y no necesita bootear Windows.

#### Trampa que costó un ciclo de debug: el player sale con EOF en stdin

`hello_xr` v3 lee las teclas de transporte de stdin, y **`EOF` es su forma de terminar**
(`case EOF: // the pipe on stdin closed - this is how a timed run ends`). Lanzarlo con
`< /dev/null` lo mata en menos de un segundo, con **exit 0 y sin una línea de error**: en el
log de Monado se ve `client_connected`, los swapchains creados y destruidos, y
`client_disconnected`, sin ningún `BEGIN_SESSION` de la app. Parece un fallo del compositor y
no lo es. La forma correcta es la documentada: `sleep N | hello_xr ...`.

Ojo que esto choca con `XRT_NO_STDIN=1`, que sí hace falta para **monado-service** (sin él
muere con `epoll_ctl(stdin) failed`). Son dos procesos distintos: al servicio se le saca
stdin, al player hay que dárselo vivo.

### La teoría de DSC no sobrevive a la aritmética (2026-08-04, 21:30)

Muerta la hipótesis del HID por segunda vez (ver `docs/09-oasis-driver-re.md`), el sospechoso
que quedaba era DSC: si el panel sólo obedece al timing de video, el 90 Hz falla porque el
timing que le llega no es decodificable, y el parche 0001 de Project-VR dice tratar
justamente el *"90 Hz handshake"* de DSC 1.1.

Antes de perseguirlo, se sacaron los números reales del EDID del casco, leído del kernel
(`/sys/class/drm/card0-DP-1/edid`, 3 bloques: base + CEA + DisplayID 2.0):

| modo | pixel clock | totales | 24 bpp | 30 bpp | ¿anda? |
|---|---|---|---|---|---|
| 2880x1440@90 | 428.6 MHz | 2980x1598 | **10.29 Gbps** | 12.86 Gbps | **NO** |
| 4320x2160@60 | 709.1 MHz | 4420x2674 | 17.02 Gbps | 21.27 Gbps | **SÍ** |
| 4320x2160@90 | 905.4 MHz | 4420x2276 | 21.73 Gbps | 27.16 Gbps | **NO** |

Capacidad del enlace, 4 lanes HBR3 (8.1 Gbps/lane, 8b/10b → 80% útil): **25.92 Gbps**.

**El modo `2880x1440@90` pide 10.29 Gbps — menos de la MITAD que el `4320x2160@60` que
funciona perfecto.** No hay forma de que ese modo necesite compresión: entra tres veces en el
enlace. Y falla igual que el otro.

Sólo `4320x2160@90` a 30 bpp se pasa del enlace y necesitaría DSC de verdad. O sea que **DSC
podría explicar como mucho uno de los dos modos que fallan, y no explica el otro.**

Lo único que comparten los dos modos que fallan es el **90 Hz**. Es el mismo patrón que ya
apareció tres veces en este proyecto: toda teoría de ancho de banda se cae al medirla. Van
cuatro.

Ojo con el matiz de la nota vieja de `CLAUDE.md` ("el modo de 60 que anda tiene pixel clock
más alto que el de 90 que falla"): es cierto, pero comparaba `4320x2160@60` (709 MHz) contra
`2880x1440@90` (428 MHz). Contra `4320x2160@90` (905 MHz) no vale. La afirmación correcta es
la de la tabla.

**El test más barato que discrimina, y no está corrido:** `2880x1440@90` (modo 0) por la vía
de **Wayland DRM lease**. Sólo se probó en X11 direct-mode. Si por lease también falla, DSC
queda descartado como causa de ese modo y el sospechoso pasa a ser el refresh rate en sí —
algo del handshake o del bring-up del panel a 90 Hz, no del ancho de banda ni de la
compresión.

```bash
./scripts/jack-in-wayland.sh 0     # 2880x1440@90
# y verificacion FISICA, como siempre
```

### Pendientes que necesitan sudo (no bloquean el test de 90Hz)

1. **Prioridad RT para Monado.** El log tira `Could not raise priority for thread
   'VBlank Events'` y `'Multi Client Module'`. A 60Hz se toleraba; a 90Hz el pacing del
   vblank es lo último que querés que compita por CPU. Necesita re-login:
   `printf '@plugdev - rtprio 99\n@plugdev - nice -20\n@plugdev - memlock unlimited\n' | sudo tee /etc/security/limits.d/99-monado.conf`
2. **Audio del casco fuera del medio** mientras dure el lab: regla udev
   `72-wmr-audio-off.rules` con `ATTR{authorized}="0"` para `0bda:4c15`. No arregla el reset
   del hub (cap. 06), sólo saca el audio del ciclo de re-enumeración.
3. **zram** (16 GB de RAM, 12 hilos): `systemd-zram-generator`, `zram-size = ram / 2`, zstd,
   `swap-priority = 100`, `vm.swappiness=180`. Red de seguridad para los builds, no
   acelerador. No compilar los tres proyectos en paralelo: ninja ya satura los 12 hilos con
   uno solo, y el pico de RAM de basalt es el que puede disparar el OOM.
4. **Deps que le faltan a basalt**: `libbz2-dev liblz4-dev libssl-dev` (ROS arrastra más).
   No bloquea nada mientras se use `3dof`, que es el modo de todo el trabajo de 360/video.

## Rollback

- Nada del sistema principal se tocó: boot menu del BIOS → disco viejo → todo como antes.
- Dentro del lab: `sudo dkms remove nvidia/595.71.05 --all`, borrar las líneas `PATCH[]`
  de dkms.conf, `sudo dkms install nvidia/595.71.05` → driver 595 stock.

## Si el 90Hz anda estable

Recién ahí se planifica el "setup ideal" (decisión ya tomada con el usuario): Debian,
dos usuarios dedicados — `vr` (sesión X11, jack-in al login) y `edit` (Resolve, cap. 05) —
en una instalación definitiva. No antes: el criterio de corte es "el casco a la par de
Windows o mejor".
