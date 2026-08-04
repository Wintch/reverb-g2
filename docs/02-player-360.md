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
./jack-in.sh 3dof     # 3dof = orientación sola, lo ideal para 360

# 2. Foto:
sleep 120 | HELLO_XR_PHOTO360=/ruta/foto_equirect.jpg \
  XR_RUNTIME_JSON=~/Documents/linux_vr_base/monado/build/openxr_monado-dev.json \
  ./build/src/tests/hello_xr/hello_xr --graphics Vulkan2

# 3. Video (gana sobre PHOTO360 si están las dos):
sleep 300 | HELLO_XR_VIDEO360=/ruta/video360.mp4 \
  XR_RUNTIME_JSON=... ./build/src/tests/hello_xr/hello_xr --graphics Vulkan2
```

El `sleep N |` no es decorativo: hello_xr trata EOF de stdin como "tecla presionada, salir".

## Variables de entorno

| Variable | Efecto |
|---|---|
| `HELLO_XR_PHOTO360=/ruta.jpg` | foto equirectangular (JPG/PNG, 2:1) |
| `HELLO_XR_VIDEO360=/ruta.mp4` | video equirectangular; H.264/HEVC/AV1 |
| `HELLO_XR_VIDEO_HW=0` | fuerza decode por software (default: NVDEC con fallback automático) |
| `HELLO_XR_VIDEO_STATS=1` | log de frames subidos/s + costo de memcpy y GPU |
| `HELLO_XR_POSE_STATS=1` | fps + delta de rotación entre frames (diagnóstico de tracking) |
| `HELLO_XR_FIXED_POSE=1` | ignora tracking (pose identidad) — diagnóstico |

## Cómo funciona el video (v2, NVDEC)

```
archivo → libavformat → NVDEC (CUDA hwaccel, sin CUDA toolkit)
        → NV12 en RAM (ring de 3 frames, thread de decode)
        → staging buffer (12MB/frame a 4K, era 32MB en RGBA)
        → texturas Y (R8) + CbCr (R8G8)
        → pass GPU YUV→RGB (shader yuv_frag.glsl, matriz 601/709 + rango según stream)
        → nivel 0 del skybox (sRGB) → mip chain (cap 6 niveles) → sampler del skybox
```

Decisiones clave y por qué:

- **swscale eliminado.** Medido: convertir YUV→RGBA en CPU costaba más que el decode
  entero (16.7s wall vs 4.3s para 900 frames 4K). La conversión ahora es un draw en GPU.
- **NVDEC vía hwaccel CUDA de ffmpeg**, no Vulkan Video. Ambos existen en el driver 550,
  pero el path Vulkan-video de NVIDIA tiene regresiones conocidas por versión de driver
  (colgadas de decode en la serie 575) y vamos a cambiar de driver para el 90Hz — cuvid
  es el camino robusto. Medido en test360.mp4: **1.7s de CPU vs 36.1s software** (900
  frames, incluye la bajada VRAM→RAM). El interop zero-copy (AVVulkanDeviceContext)
  queda como optimización futura documentada; a 4K30 el round-trip cuesta ~720MB/s de
  PCIe, irrelevante.
- **Fix de color**: la textura ahora es sRGB (antes UNORM: doble encoding, imagen lavada).
  El pass de video escribe R'G'B' por una vista UNORM del mismo image (MUTABLE_FORMAT)
  para que el gamma se codifique exactamente una vez.
- **10-bit (P010/yuv420p10)**: se baja a 8-bit en el decode thread. HDR real queda fuera
  de alcance para un skybox.

## Verificación

Con el casco puesto y `HELLO_XR_VIDEO_STATS=1`:
- "frames/s uploaded" debe igualar el fps del archivo (30 para test360.mp4).
- El log debe decir `decode: NVDEC requested` y no haber warnings de fallback.
- `htop`: el proceso hello_xr debe quedar bajo ~1 core con video 4K (antes: ~8 cores).
- Visual: sin banda en la costura trasera, colores no lavados, sin shimmer en detalle fino.

## Pendiente / roadmap

- Test 8K (los archivos de prueba 8K se truncaron en el cuelgue del 2026-08-04 — re-bajar).
- Zero-copy NVDEC→Vulkan (AVVulkanDeviceContext) si alguna vez hace falta más headroom.
- Audio del video (hoy se reproduce mudo; el audio del casco además está bloqueado por
  hardware — ver 06-known-issues.md).
