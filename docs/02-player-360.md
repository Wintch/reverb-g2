# 02 — Player 360 (fotos y video con NVDEC)

El player es `hello_xr` (OpenXR-SDK-Source, branch local `g2-360-viewer`) modificado para
renderizar un skybox equirectangular. El parche completo vive en
`patches/hello_xr-player/`. Base: OpenXR SDK 1.1.62.

## Build

```bash
cd ~/Documents/linux_vr_base/OpenXR-SDK-Source
cmake -B build -GNinja -DBUILD_TESTS=ON -DBUILD_API_LAYERS=OFF -DBUILD_CONFORMANCE_TESTS=OFF
ninja -C build hello_xr
```

(`hello_xr` vive bajo `src/tests/`, por eso `BUILD_TESTS=ON`. Necesita `libavcodec-dev
libavformat-dev libavutil-dev libswscale-dev` para el path de video — si faltan, compila
igual pero solo con fotos.)

## Uso

```bash
# 1. Levantar el pipeline VR (ver 01-bringup-monado.md)
./jack-in.sh 3dof     # 3dof = orientación sola, lo ideal para 360/VR180

# 2. Todo pasa por el wrapper:
./play360.sh video.mp4                 # un archivo, en loop
./play360.sh photo360/                 # directorio = playlist, ordenada por nombre
./play360.sh -s foto_equirect.jpg      # foto
./play360.sh -t 60 video.mp4           # límite de tiempo
./play360.sh -p 180 -e sbs video.mp4   # forzar proyección/estéreo si la detección falla
```

Corrido desde una **terminal real** (no piped ni backgrounded), hay teclas de transporte:
`espacio` pausa, `[`/`]` velocidad (0.125x–4x), `1` normal, `n` siguiente, `q` salir.
Si un corte sucio deja la terminal muda: `stty sane`. En un pipe no hay teclas y el run
termina en el EOF de stdin, como siempre.

## Proyecciones y estéreo (v3)

El player entiende tres proyecciones — **360 equirect, VR180 half-equirect, plano**
(pantalla virtual) — cada una mono o estéreo **side-by-side / over-under**. El split de
ojo se aplica en el shader después del mapeo esférico, así que ambos ojos salen del mismo
frame decodificado (una sola subida por frame).

La detección importa porque los layouts son ambiguos por dimensiones: un 2:1 es 360 mono
**o** VR180 SBS, y equivocarse se ve "plausible pero raro", no roto. Orden de resolución:

1. Overrides: `HELLO_XR_PROJECTION` (360|180|flat) y `HELLO_XR_STEREO` (mono|sbs|tb)
2. Metadata del contenedor (boxes MP4 `sv3d`/`st3d` — las cámaras VR180 y YouTube las escriben)
3. Convenciones de nombre de archivo (vr180, sbs, _tb, 360…)
4. Aspect ratio como último recurso

Lo que decidió se imprime SIEMPRE antes de dibujar (con el casco puesto no hay otra forma
de saberlo):

```
  MODO: VR180 3D (side-by-side)
  Archivo: 7680x4096  ->  3840x4096 por ojo  |  59.94 fps  |  av1
```

**VR180 3D verificado en el casco 2026-08-04** ("el efecto es muy bueno en 3d").

### YouTube esconde los streams VR

Mismo URL, distinto contenido: el cliente normal recibe un render plano monoscópico
(3136x1764 en el ejemplo medido) y el cliente `android_vr` los streams reales
(7680x4096 estéreo "mesh"). `get360.sh` pide `android_vr` primero; en el listado `-l`,
`2160s60` = estéreo, `2160p60` = plano. Contra: `android_vr` no acepta cookies, así que
age-restricted ⇒ solo versión plana (fallback automático).

## Variables de entorno

| Variable | Efecto |
|---|---|
| `HELLO_XR_PHOTO360=/ruta.jpg` | foto equirectangular (JPG/PNG) |
| `HELLO_XR_VIDEO360=/ruta` | video O directorio (playlist); H.264/HEVC/AV1/VP9 |
| `HELLO_XR_PROJECTION=360\|180\|flat` | fuerza la proyección |
| `HELLO_XR_STEREO=mono\|sbs\|tb` | fuerza el empaquetado estéreo |
| `HELLO_XR_PANO_FOV=AxB` | arco del frame 180 en grados (default 180x180) |
| `HELLO_XR_SCREEN_FOV=N` | ancho aparente de la pantalla virtual en modo flat (default 70°) |
| `HELLO_XR_VIDEO_HW=0` | fuerza decode por software |
| `HELLO_XR_VIDEO_DIRECT=0` | desactiva NVDEC→staging directo (para A/B) |
| `HELLO_XR_VIDEO_STATS=1` | stats de decode y de upload por separado |
| `HELLO_XR_POSE_STATS=1` | fps + delta de rotación entre frames |
| `HELLO_XR_FIXED_POSE=1` | ignora tracking — diagnóstico |

## Cómo funciona el video (v3, zero-memcpy)

```
archivo → libavformat → NVDEC (decoder elegido a mano: ffmpeg default para AV1 es
        libdav1d, ¡que NO tiene hwaccel! — fix medido: 25→59 fps en 8K60)
        → av_hwframe_transfer_data DIRECTO al staging buffer mapeado de Vulkan
          (ring de 8 buffers; el hilo de render ya no copia NADA)
        → vkCmdCopyBufferToImage → texturas Y (R8) + CbCr (R8G8)
        → pass GPU YUV→RGB (matriz 601/709 + rango según stream)
        → nivel 0 del skybox (sRGB) → mip chain (cap 6) → shader del skybox
          (proyección + split de ojo por push constants)
```

Historia de la optimización (8K, medido):

| versión | upload | hilo de render |
|---|---|---|
| v2: decode→RAM propia, memcpy al staging | 19 fps | 14.5 ms |
| v3: NVDEC→staging directo | 30 fps (tope del archivo HEVC) | 8.2 ms |
| v3 + fix decoder AV1 (8K60) | ~48 fps | 6.5 ms |
| v3 + ring 5→8 buffers | **60.0 fps, 0 starves** | 6.3 ms |

El ring pasó de 5 a 8 porque el jitter del decode (keyframes) vaciaba un colchón de 3
frames: el renderer no encontraba frame nuevo en ~25% de los vsyncs aunque el decode
promediara 59 fps. +126 MB de RAM a 8K, nada a 4K.

Decisiones que siguen vigentes de v2: sin swscale (YUV→RGB en GPU), textura sRGB con
escritura por vista UNORM (MUTABLE_FORMAT, gamma exactamente una vez), 10-bit se baja a
8 en el thread de decode.

**Playlist**: cada pista destruye y recrea toda la cadena (staging, planos, pass de
conversión, skybox) porque la siguiente puede tener otra resolución/proyección. El hitch
entre pistas es un vkDeviceWaitIdle + realloc — solo ocurre entre videos.

## Verificación

Con el casco puesto y `HELLO_XR_VIDEO_STATS=1`:
- "video upload: X frames/s" debe igualar el fps del archivo, y "renderer starves" ≈ 0.
- "video decode:" debe decir `NVDEC direct-to-staging` (si dice `+ copy`, el transfer
  directo falló y se degradó solo — funcional pero más lento).
- El banner `MODO:` debe coincidir con lo que el contenido ES.
- Visual 360: sin banda en la costura trasera. VR180: negro detrás de los hombros, no
  imagen repetida. 3D: profundidad real (si se ve doble, el split de ojo está mal).

## Pendiente / roadmap

- Probar las teclas de transporte en vivo (implementadas 2026-08-04, sin test interactivo).
- Audio del video (mudo hoy; decode→PipeWire + A/V sync).
- Zero-copy real CUDA↔Vulkan (importar la superficie NVDEC como imagen Vulkan, cero PCIe).
  Hoy innecesario: ya estamos a tasa completa. Es LA optimización si 90Hz+8K pide más.
- Proyección "mesh" de YouTube: nuestro half-equirect es una aproximación; si se nota
  estiramiento en los bordes, ajustar con `HELLO_XR_PANO_FOV` o implementar el mesh real.
