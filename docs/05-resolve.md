# 05 — DaVinci Resolve en el lab (makeresolvedeb)

Ruta probada por el usuario: [makeresolvedeb](https://www.danieltufvesson.com/makeresolvedeb),
que convierte el instalador oficial de Blackmagic en un .deb limpio para Debian.

## Instalación

```bash
# 1. Bajar el .run/.zip oficial de Resolve (Linux) desde blackmagicdesign.com/support
# 2. Bajar el script makeresolvedeb de danieltufvesson.com/makeresolvedeb
# 3. Generar e instalar el deb (ejemplo con la versión free):
unzip DaVinci_Resolve_*_Linux.zip
./makeresolvedeb_*.sh DaVinci_Resolve_*_Linux.run
sudo dpkg -i davinci-resolve_*_amd64.deb
```

Requisito GPU: con el stack de NVIDIA del lab (repo debian13, `nvidia-open` +
`nvidia-driver-cuda`) Resolve encuentra CUDA sin pasos extra. Si falta,
`sudo apt install nvidia-driver-cuda`.

## La limitación que hay que saber (versión free en Linux)

**Resolve free en Linux NO decodifica H.264/HEVC ni AAC** (Studio sí). El material de
cámara/teléfono típico entra mudo o no entra. Workflow estándar: transcodificar a DNxHR
antes de editar — y para eso ya tenemos NVDEC/NVENC en esta máquina:

```bash
# H.264/HEVC -> DNxHR HQ + PCM (rápido: decode NVDEC, ~sin CPU)
ffmpeg -hwaccel cuda -i entrada.mp4 \
       -c:v dnxhd -profile:v dnxhr_hq -pix_fmt yuv422p \
       -c:a pcm_s16le salida.mov
```

DNxHR HQ 4K ≈ 700 GB/hora — pensar el destino (el NVMe NTFS es visible desde Linux para
lectura; para trabajar en serio conviene una partición nativa, se decide en el setup ideal).

## Nota de contexto

Resolve ya fue validado andando en el sistema principal (sesión de research de agosto
2026). El lab lo re-valida sobre el driver 595 parcheado — si Resolve muestra artefactos o
inestabilidad ahí, es dato importante ANTES de migrar el sistema principal al driver nuevo.
En el setup ideal, Resolve vive en el usuario `edit`, sin nada de VR corriendo al lado.
