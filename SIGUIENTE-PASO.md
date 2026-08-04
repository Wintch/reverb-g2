# Siguiente paso — Lab 90Hz (SSD aparte)

Estado al 2026-08-04, tarde. Pausa para conectar el SSD del lab.

## Decisión de prioridad (del usuario, hoy)

**El objetivo inmediato es eliminar el parpadeo, no sumar fps de video.** El parpadeo es el
strobe del backlight de baja persistencia del G2 a 60Hz — es inherente al modo 60Hz y solo
se va llegando a 90Hz. Por lo tanto: **lab 90Hz primero** (manual cap. 04, el plan completo
ya está escrito ahí).

Dato nuevo que reordenó todo: **en Windows 11 el casco anduvo horas a 90Hz sin problemas**
(solo el audio fue siempre problemático, también en Windows). Eso:

- **Mata la teoría de la fuente.** Si faltara corriente, Windows fallaría igual. No comprar
  fuente, no ir a la casa de electrónica.
- Confirma que el 90Hz es 100% bug del driver NVIDIA Linux (5923212) — que es exactamente
  lo que ataca el lab con el 595-open parcheado (Project-VR).
- Reclasifica las caídas del hub USB2 bajo carga (companion `03f0:0580` + audio se caen con
  el panel prendido, vuelven solos ~5s después de bajar Monado — reproducido 2 veces hoy)
  como **probable problema de software Linux**, no eléctrico. Sospechoso: cómo maneja el
  driver WMR de Monado los reportes HID/keepalive vs. como lo hace Windows. Investigar
  DESPUÉS del lab.

## Procedimiento al reconectar el SSD

1. Conectar el SSD libre a un puerto SATA del **controlador del chipset** (no compartir el
   xHCI del casco; ver cap. 00). Verificar con `lsblk -o NAME,SIZE,TRAN,MODEL`.
2. Seguir **cap. 04 paso a paso** — ya tiene: netinst Debian 13, repo apt de NVIDIA para
   debian13 con el 595.71.05 exacto, los parches Project-VR, y la validación.
3. Advertencia del cap. 04 que vale repetir: instalar con el disco principal desconectado
   idealmente, o elegir con MUCHO cuidado el destino del GRUB (= el SSD del lab).
4. La validación del 90Hz es **física**: el API reporta éxito y 90.0 fps aun con el panel
   negro. Solo vale mirar adentro del casco.

## Estado del player (branch `g2-360-viewer`, commits cf4cd29 + d6ee9ec)

Hoy fue un día enorme acá. Todo verificado en el casco salvo donde se indica:

- **VR180 3D confirmado por el usuario** ("el efecto es muy bueno en 3d!") — primera
  reproducción estereoscópica del rig. `photo360/vr180_berlin_8k60.mp4` (7680x4096@60,
  side-by-side, AV1).
- **8K60 estéreo a tasa completa**: decode 59-61 fps, upload 60.0 fps, 0 starves, 6.3 ms
  de render thread. La cadena entera: NVDEC escribe directo al staging de Vulkan (cero
  memcpy en el hilo de render), fix del decoder AV1 (ffmpeg elige libdav1d por defecto,
  que NO tiene hwaccel — había que pedir el decoder `av1` explícito), y ring de 8 buffers
  (con 5, el jitter de keyframes vaciaba la cola = stutter).
- **Proyecciones**: 360 / VR180 / plano, mono / SBS / over-under. Detección: metadata del
  contenedor → nombre de archivo → aspect ratio; overrides `HELLO_XR_PROJECTION` y
  `HELLO_XR_STEREO`. Banner de modo en la terminal antes de dibujar.
- **Playlist**: `HELLO_XR_VIDEO360=directorio/` reproduce todo en orden, con recreación
  completa de recursos entre pistas (probado 2 vueltas con cambios 4K↔8K).
- **Teclas** (espacio pausa, `[`/`]` velocidad 0.125x–4x, `1` normal, `n` siguiente, `q`
  salir): implementadas y compiladas, **falta probarlas interactivamente** — necesitan
  `./play360.sh` desde una terminal real (no piped). Si la terminal queda muda tras un
  corte: `stty sane`.
- **`play360.sh`** (en `linux_vr_base/` y `scripts/`): wrapper con todo. `-t` segundos,
  `-s` foto, `-p`/`-e` overrides, `-f` arco del 180, `-q` sin stats.
- **`get360.sh`**: YouTube esconde los streams VR reales detrás del cliente `android_vr`
  (mismo URL: 3136x1764 mono plano vs 7680x4096 estéreo). El script ya lo usa por defecto,
  con fallback a cookies para age-restricted (mutuamente excluyentes). En el listado `-l`,
  `2160s60` = estéreo, `2160p60` = plano.

### Pendientes del player (en orden)

1. Probar las teclas en vivo (5 min).
2. Interop CUDA↔Vulkan: NVDEC decodifica EN la VRAM y hoy bajamos/subimos 47MB por PCIe
   por frame igual. Importar la superficie directo como imagen Vulkan haría el 8K casi
   gratis. Es trabajo grande; hoy no hace falta (ya estamos a tasa completa).
3. Audio del video (el player es mudo — ffmpeg ya está en la cadena, falta el camino
   decode→PipeWire y A/V sync).

## Cola después del lab 90Hz

1. Caídas USB bajo carga: instrumentar el keepalive HID del driver WMR de Monado.
2. Audio del casco en uso real (probado OK 1 vez, pero es la parte que también en Windows
   fue siempre frágil — bajas expectativas, culpa del hardware/firmware del G2).
3. Test 10/10 de controllers (branch `g2-controllers`).
4. SLAM/Basalt divergente (6DoF).
