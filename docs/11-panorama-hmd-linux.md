# 11 — Panorama: ¿es sólo NVIDIA? ¿es sólo el G2?

Barrido del 2026-08-04. La pregunta era si el fallo de 90Hz es específico de NVIDIA, del
Reverb G2, o de algo más grande. La respuesta cambia a quién le escribimos.

## Lo que más reordena: NVIDIA tiene TRES firmas de falla distintas

No es un bug aislado nuestro. En Linux, con NVIDIA, aparecen tres fallos distintos según el
panel — cada uno con su número de bug interno, los tres abiertos:

| headset | síntoma | bug NVIDIA |
|---|---|---|
| **WMR / Reverb G1 y G2** | **panel negro / logo de HP, no engancha** | **5923212** |
| Bigscreen Beyond | corrupción DSC, "fuzzy static" | 4834531 |
| Valve Index / Vive / Vive Pro | modeset ocurre, pero judder y latencia | 5372097 |

Y la misma familia aparece **sin VR de por medio**: un hilo de feb-2026 reporta el problema
en un monitor de escritorio común (LG C5 OLED) a 144Hz con VRR.

**Lectura:** el problema de fondo parece ser "NVIDIA + Linux + refresh alto" en general, y el
G2 simplemente lo expone de la forma más severa — pantalla completamente apagada en vez de
artefactos o judder. Eso convierte a nuestro caso en **el mejor repro de la familia**, no en
una queja de nicho.

## ¿Es sólo NVIDIA? No se sabe, y hay que decirlo así

**No hay un solo reporte humano, con verificación física, de un Reverb G2 a 90Hz en Linux con
NINGUNA GPU** — ni NVIDIA, ni AMD, ni Intel.

- La wiki de LVRA dice que Intel Arc / i915 anda "OK" con el G2, pero **no especifica Hz**.
  Puede ser 60, igual que nosotros.
- De AMD con el G2: **zona ciega total**. Nadie reportó que ande ni que falle.

Eso es *ausencia de evidencia*, no evidencia a favor de AMD/Intel. Cuando escribamos, la
frase correcta es "nadie lo reportó", nunca "en AMD anda".

**Pero sí hay evidencia indirecta sólida de que amdgpu no prohíbe refresh alto en
direct-mode:** el Valve Index llega limpio a 90 y 120Hz en AMD (RX 7900 XTX), y el Bigscreen
Beyond llega a 90Hz en AMD con parches de kernel comunitarios. Ninguno es WMR — el G2 tiene su
secuencia de activación propia que esos no tienen — así que no cierra la pregunta. Pero deja
claro que el stack de Linux **puede** hacer refresh alto en direct mode.

Por eso el test con una AMD prestada sigue siendo el experimento más valioso disponible.

## El precedente Oculus / DK2: más débil de lo que esperábamos

El **DK2 sí llegaba a sus 75Hz nativos en Linux** (reportes humanos consistentes de 2015).
Pero es estructuralmente distinto al G2 en tres ejes, y por eso no sirve como precedente:

1. Modo **extendido de X11**, no direct-mode ni DRM lease.
2. Panel sin secuencia de activación tipo WMR — cualquier GPU que le tire el modeline lo trata
   como un monitor más.
3. NVIDIA propietario ~340–352.x sobre Kepler/Maxwell: **una generación entera antes** del bug
   que perseguimos (Turing/Ampere/Blackwell).

Además esas fuentes describen el setup como "funciona", sin verificación física rigurosa.

**CV1 (90Hz) y Rift S (80Hz)** —los dos con arquitectura de activación más parecida a WMR—
no tienen ningún reporte limpio de refresh nativo verificado, **ni tampoco de que fallen**.
Silencio en ambos sentidos. El soporte Linux de toda la familia post-DK2 es 100% comunitario:
Oculus pausó su SDK de Linux en mayo de 2015 y nunca lo retomó.

**Conclusión honesta: la familia Oculus no aporta precedente de que NVIDIA+Linux logre refresh
alto en un HMD con activación no trivial.**

## Panorama de HMDs en Linux hoy

| HMD | refresh máx. confirmado | GPU | software |
|---|---|---|---|
| Reverb G1/G2 (WMR) | 60Hz limpio; **90Hz falla** | NVIDIA Turing/Ampere/Blackwell | Monado |
| Reverb G1/G2 (WMR) | "OK", **Hz sin especificar** | Intel i915 | Monado |
| Reverb G1/G2 (WMR) | **sin dato** | AMD | — |
| Valve Index / Vive / Vive Pro | **90 y 120Hz limpio** (144 falla, también en Windows) | AMD RX 7900 XTX | SteamVR-Linux |
| Valve Index / Vive / Vive Pro | modeset ocurre, pero judder | NVIDIA | Monado / SteamVR |
| Bigscreen Beyond | 90Hz limpio (con parche de kernel) | AMD | Monado |
| Bigscreen Beyond | corrupción DSC | NVIDIA | Monado |
| Oculus DK2 | 75Hz limpio (X11 extendido, driver de 2015) | NVIDIA Kepler/Maxwell | — |
| Oculus CV1 / Rift S | sin confirmación en ningún sentido | — | OpenHMD / Monado |
| Pimax P2 (4K/5K/8K) | sin dato de Hz; hay que parchear el EDID a mano | NVIDIA | Monado |
| Somnium VR1 | no soportado | — | — |

**El único caso limpio de refresh alto en un HMD bajo Linux es con AMD.**

## Dónde publicar, en orden

1. **Hilo de NVIDIA 337744** — `forums.developer.nvidia.com/t/337744`. Tiene staff activo
   (bug 5923212 confirmado) y **una pregunta suya sin responder**: si hay alguna versión de
   driver anterior donde no pasara. **Responder ahí, no abrir hilo nuevo.** No hay plantilla
   oficial; la convención es prefijar `[Bug Report]` y estructurar en secciones.
   Ojo: nosotros probamos **solamente 595.71.05**. El rango 590–610 sale del hilo, no de
   nuestras mediciones — no atribuírnoslo.
2. **Monado** — `gitlab.freedesktop.org/monado/monado`. **Hay que revisar A MANO** si ya existe
   un issue de "pantalla negra a 90Hz" antes de abrir uno: gitlab.freedesktop.org está detrás
   de Anubis (anti-bot) y el barrido no pudo leerlo. Es el único proyecto activo al que sumarse:
   Project-VR es un diario personal sin comunidad, `wumbo_mr` está archivado, y OpenHMD sólo
   tiene issues de detección/firmware para el G2.
3. **LVRA / Linux VR Adventures** — wiki + Matrix `#linux-vr-adventures:matrix.org` + Discord.
   Es el público correcto: converge gente de Monado, SteamVR-Linux y hardware WMR/Vive/Index.
   Su wiki hoy documenta el límite ("60Hz-only on Nvidia") **sin causa técnica** — ahí es donde
   nuestra medición de ancho de banda y la verificación física llenan un hueco real.

**Y un aporte propio que no tiene precedente publicado:** la metodología de verificación
física. Nadie documentó que Vulkan/OpenXR reporta éxito y 90 fps sobre un panel negro, ni el
protocolo para evitar ese falso positivo. Vale publicarlo en cualquiera de los tres destinos.

## Lo que no se pudo averiguar

- **gitlab.freedesktop.org está detrás de Anubis**: bloqueados los trackers de Monado, AMD
  (`drm/amd`) e Intel (`drm/i915`, `drm/xe`). Lo poco de Monado que se leyó vino por un proxy
  indirecto — confianza media, no alta.
- Si ya existe un issue de Monado de "G2 pantalla negra a 90Hz". **Sin confirmar ni descartar.**
- Si Intel i915 llega a 90Hz con el G2 o sólo a 60.
- Si el Bigscreen Beyond anda hoy limpio en NVIDIA 580+-open (el wiki dice "requiere", sin
  reporte humano posterior).
- Si el Rift S llega a sus 80Hz nativos verificados.
