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

## Rollback

- Nada del sistema principal se tocó: boot menu del BIOS → disco viejo → todo como antes.
- Dentro del lab: `sudo dkms remove nvidia/595.71.05 --all`, borrar las líneas `PATCH[]`
  de dkms.conf, `sudo dkms install nvidia/595.71.05` → driver 595 stock.

## Si el 90Hz anda estable

Recién ahí se planifica el "setup ideal" (decisión ya tomada con el usuario): Debian,
dos usuarios dedicados — `vr` (sesión X11, jack-in al login) y `edit` (Resolve, cap. 05) —
en una instalación definitiva. No antes: el criterio de corte es "el casco a la par de
Windows o mejor".
