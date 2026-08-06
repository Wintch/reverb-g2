# 19 — Seguimiento para el hilo del bug 5923212 (60Hz-only en NVIDIA)

Hilo: https://forums.developer.nvidia.com/t/reverb-g2-unable-to-drive-more-than-60hz-mode-on-nvidia/337744

Estado al 2026-08-05: NVIDIA (`abchauhan`) confirmó reproducción y abrió el bug interno
**5923212** el 2026-03-20, preguntando si alguna versión vieja del driver andaba. Sin
respuesta de NVIDIA desde entonces. Último post de la comunidad: `MiaPerec`, 2026-07-19,
mismo síntoma en 610.43.02.

**Lo que este seguimiento suma que el hilo no tiene todavía:**

1. El chip puente identificado por nombre (`ANX7530`, leído del string de versión del
   firmware del propio casco) y su datasheet, que declara el techo como **"4K x 2K x 60Hz"**
   explícitamente — no es sólo una cuenta de ancho de banda.
2. Un factorial completo que separa refresh, vblank y pixel clock como variables
   independientes, con verificación física en cada celda (no sólo "la API dice éxito").
3. El dato de que el HID del propio casco confirma, byte a byte, que el timing pedido llega
   perfecto al link incluso en los casos que fallan — descarta "el modo nunca llegó" como
   explicación.

Está en inglés porque es para el foro. Copialo tal cual o editalo antes de postear — **no
lo posteo yo**, no tengo tus credenciales del foro y postear ahí es una acción pública que
te corresponde a vos decidir cuándo y cómo.

---

## Borrador del post

**Summary:** Ran a full 2×2×N factorial isolating refresh rate, vertical blanking, and
pixel clock as independent variables on real hardware (physical verification each time,
headset worn, not just API success). Result: none of resolution, refresh rate, vblank
duration, or total DisplayPort bandwidth alone explain the failure. The only pixel clock
that has ever produced an image, across every combination tried, is **exactly ~709.15 MHz**
— which is also the bridge chip's own native 4320x2160@60 timing. That, plus the bridge
chip's datasheet, points at a hardware/firmware ceiling rather than a pure EDID/mode-timing
problem.

**Setup:** RTX 3060 Ti, 595.71.05-open, patched with the 3-patch Project-VR stack plus a
4th patch fixing a separate 6bpc-clamp bug in this same EDID (undeclared color depth —
[NVIDIA/open-gpu-kernel-modules#1275](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275),
unrelated to this bug but worth ruling out first if anyone else hits it). Modes injected via
`nvidia_modeset.config_file` EDID override, so htotal/vtotal/refresh are controlled
precisely per attempt. Verified two ways every time: (a) physically, headset worn, backlight
on/off and color vs. logo; (b) the headset's own HID status report
(`DEVICE_STATUS`, 33 bytes), which echoes back the negotiated htotal/vtotal/refresh/bpc —
confirms the requested timing actually reached the panel, independent of whether it lit up.

**Bridge chip:** `ANX7530` (Analogix DisplayPort-to-dual-MIPI, VR-targeted), identified from
a firmware version string on the device (`ANX7530:x.x`). Its product brief
(AA-004263-PB-7) states: "DisplayPort Receiver Input Bandwidth supports up to 4K x 2K x
60Hz" as an explicit spec line, and lists HBR2.5 (6.75 Gbps/lane) as its DisplayPort link
ceiling — not HBR3. Both numbers are far above anything any of our attempted 90Hz modes
needed, so neither the chip's raw link rate nor total pixel throughput explains the
failures below.

**Results** (all at 4320x2160 unless noted; vblank time = vblank_lines / ((v_active +
vblank_lines) × refresh)):

| label | resolution | refresh | vblank (lines) | pixel clock | vblank time | result |
|---|---|---|---|---|---|---|
| native, working | 4320x2160 | 60.00 Hz | 514 | 709.15 MHz | 3.204 ms | **works** |
| CTRL4K (cloned copy of the working mode, different descriptor slot) | 4320x2160 | 60.00 Hz | 514 | 709.14 MHz | 3.204 ms | **works** |
| A4K | 4320x2160 | 60.00 Hz | 116 | 603.60 MHz | 0.849 ms | fails |
| B4K | 4320x2160 | 90.00 Hz | 240 | 954.72 MHz | 1.111 ms | fails |
| 90long (same vblank *line count* as the working mode, at 90Hz) | 4320x2160 | 90.00 Hz | 514 | 1063.72 MHz | 2.136 ms | fails |
| bisect1 (60Hz, short vblank, no bandwidth pressure) | 4320x2160 | 60.00 Hz | 340 | 663.00 MHz | 2.267 ms | fails |
| 80hz (more vblank *time* than the working mode, comfortable bandwidth margin) | 4320x2160 | 80.00 Hz | 775 | 1037.82 MHz | 3.301 ms | fails |
| native, previously reported | 2880x1440 | 90.00 Hz | — | 428.58 MHz | — | fails (lower total bandwidth than the working mode) |

Every row that isn't ≈709 MHz fails, regardless of whether it has more bandwidth headroom,
more vblank lines, or more vblank *time* than the one working mode. `80hz` is the clearest
single data point: strictly more vertical blanking time than the working 60Hz mode, well
inside the bridge's own bandwidth spec, and it still doesn't light up.

**What this rules out, with this methodology:**
- Total DisplayPort bandwidth (`80hz` needs less than the chip's declared HBR2.5 ceiling
  and still fails; `2880x1440@90`, reported earlier in this thread, needs *less* bandwidth
  than the working mode and also fails).
- Vertical blanking duration, whether measured in lines or in time (`80hz` has more than
  the working mode; `A4K`/`bisect1` have less; both buckets fail identically).
- The EDID/mode-injection mechanism itself not reaching the panel — the headset's own HID
  status confirms exact timing delivery in every failing case tested.

**Open question for anyone with lower-level visibility (DPCD/MSA capture, or the Windows
driver's internal handling of this panel):** is there a known reason the ANX7530's PLL (or
its `MCU` block, per the datasheet's block diagram) would only lock to specific discrete
pixel clocks rather than an arbitrary continuous range? If so, is ~709 MHz special-cased
somewhere in NVIDIA's Windows driver for this device (a quirk/allowlist), which the Linux
595-open path doesn't carry over?

Happy to run more targeted captures if anyone with visibility into the internal bug can
point at what to look for specifically.

**Update (2026-08-05, evening): live Windows capture — no special pixel clock, no extra USB
command**

With direct access to a Windows machine driving the same headset, I read the *active* timing
with CRU (Custom Resolution Utility) while 90 Hz was working: `2880x1440 @ 89.999 Hz
(428.58 MHz)`, `htotal=2980 vtotal=1598`. This is exactly the base-block DTD from the EDID,
unmodified — same pixel clock, same totals. Windows isn't using any special or out-of-band
timing for this mode: it's exactly what the EDID itself publishes.

This reframes the open question above (is there a "special" pixel clock cached somewhere in
the Windows driver for this device?): there isn't, at least not in the sense of a magic value
that differs from the EDID. Windows drives the 60 Hz mode (709.15 MHz, DisplayID descriptor
#2) and the 90 Hz mode (428.58 MHz, base-block DTD) both "as-is," straight from the EDID.
What separates the two isn't the pixel clock itself — it's specifically crossing the
refresh-rate threshold, consistent with the factorial results above.

I also captured, over USB (Wireshark + USBPcap), the exact moment of a live refresh-rate
change on Windows (60→90 Hz and 90→60 Hz, without disconnecting the headset). No additional
HID command appears during the transition — only the usual status report (`DEVICE_STATUS`,
33 bytes) updating refresh/htotal/vtotal, identical in shape to what's already seen in steady
state. This rules out a hidden, Windows-specific USB activation sequence as well.

At this point, from the Windows user-tooling side (Wireshark/USBPcap, CRU, HWiNFO64, GPU-Z,
NVIDIA's own control panel) there's nothing left to check: no special EDID, no hidden USB
command, no visible DSC (the Reverb G2 doesn't even show up as a selectable display in the
NVIDIA panel or in Windows Settings while in direct/HMD mode). What's still invisible from
here is exactly the open question above: what happens during DisplayPort link training
(DPCD/AUX), or inside the closed GSP firmware — no user-space tool reaches either of those on
any OS.

---

## Chequeo local (2026-08-05, sin reboot): bits de stereo/3D en el EDID — nada

El datasheet del ANX7530 lista "Horizontal left/right line splitting" y "3D stereo modes"
como features del receptor DisplayPort — hipótesis: quizás Windows activa un modo de
stream dividido (un stream liviano por ojo, en vez de uno combinado de 4320 de ancho) vía
algún bit de stereo en el EDID que nuestros clones no están preservando.

Se decodificó a mano el `byte 17` del único DTD del bloque base y el `byte 3` de los dos
descriptores DisplayID Type I nativos:

- Bloque base (2880x1440@90, nativo, falla): byte17=`0x1e`, bits de stereo (0 y 6-5) todos
  en 0 — sin stereo declarado.
- DisplayID descriptor #1 (4320x2160@90, nativo, falla): byte3=`0x88` — `preferred=1`,
  bits de stereo (6-5) en `00`, resto idéntico al #2 salvo ese bit.
- DisplayID descriptor #2 (4320x2160@60, nativo, ANDA): byte3=`0x08` — `preferred=0`,
  mismos bits de stereo en `00`.

**Ningún descriptor nativo declara stereo, y el único bit que distingue al que anda del que
falla es `preferred`.** Si el split dual-stream existe, no se activa por un flag visible en
el EDID — que ya venimos preservando sin tocar en todos los clones. Esto no descarta la
hipótesis del dual-stream, pero si es real, el mecanismo que la dispara vive fuera del EDID
(DPCD, AUX, o un comando propietario), consistente con todo lo demás que este documento ya
señala como "por debajo del EDID".

## Búsqueda del driver original de Windows Mixed Reality (2026-08-05): no es lo que hace falta

Se buscó el driver/runtime original de Microsoft (previo a la remoción de WMR) para ver si
tenía la lógica de panel que Oasis no tiene. Resultado: los candidatos encontrados
(`microsoft.com/.../id=56265`, el zip de archive.org) son el driver de **sensores/IMU**
(`HololensSensors`, tracking), no el pipeline de video — no mencionan el ANX7530, DisplayPort
ni 90 Hz. El *Feature-on-Demand* del shell holográfico (`Microsoft-Windows-Holographic-
Desktop-FOD-Package`, ~1.5 GB) sí está listado en el mismo archive.org, sin inspeccionar
todavía.

**Pero conseguirlo probablemente no cierra nada de esto igual.** El propio `driver_oasis.dll`
— el driver que efectivamente logra 90 Hz en Windows, ya desensamblado en el cap. 09 — **no
toca timing de video en absoluto**: sólo habla HID/USB para tracking y manda `Display
Enable`. Si el único componente verificado que logra 90 Hz no negocia el modo de video, esa
negociación corre entera por el **driver NVIDIA de Windows estándar**, no por ningún
componente de Microsoft o HP. Ni el FOD holográfico ni el portal original van a explicar el
mecanismo real — el misterio vive adentro del driver NVIDIA de Windows, que no tenemos forma
de inspeccionar sin ingeniería inversa de ese binario o una captura DPCD/AUX real durante la
transición 60→90 en una máquina Windows con el hardware físico (caro, y ya estaba anotado
como tal en el historial del proyecto).

Dato adicional encontrado: hay reportes de "black screen at 90Hz" con el Portal original de
Microsoft mismo, en AMD y en NVIDIA — el 90 Hz del G2 parece frágil incluso en la plataforma
de referencia, no un problema exclusivo de este lab o de Linux.

## Update (2026-08-05, noche): capturas reales en Windows — sin pixel clock especial, sin comando USB extra

Con acceso real a una máquina Windows con el mismo casco, se leyó el timing ACTIVO con CRU
(Custom Resolution Utility) mientras el 90Hz andaba: `2880x1440 @ 89.999 Hz (428.58 MHz)`,
`htotal=2980 vtotal=1598`. **Es exactamente el DTD del bloque base del EDID, sin modificar un
bit** — mismo pixel clock, mismos totales. Windows no usa ningún timing especial ni fuera de
banda para este modo: es el que el propio EDID publica.

Esto cambia el marco de la pregunta abierta más arriba (¿hay un pixel clock "especial"
cacheado en el driver de Windows?): no lo hay, al menos no en el sentido de un valor mágico
distinto del EDID. Windows usa igual de "sin trucos" el modo de 60Hz (709.15 MHz,
DisplayID descriptor #2) y el de 90Hz (428.58 MHz, DTD del bloque base) — los dos, EDID puro.
Lo que separa a uno de otro no es el pixel clock en sí, es específicamente cruzar el umbral
de refresh, consistente con lo que ya decía el factorial de este mismo hilo.

También se capturó por USB (Wireshark + USBPcap) el momento exacto de un cambio de refresh
EN VIVO en Windows (60→90Hz y 90→60Hz, sin desconectar el casco). **No aparece ningún comando
HID adicional en la transición** — sólo el reporte de estado de siempre (`DEVICE_STATUS`,
33 bytes) actualizando refresh/htotal/vtotal, idéntico en forma al que ya se ve en régimen
estable. Esto descarta también una secuencia de activación oculta por USB específica de
Windows.

Con esto, del lado de las herramientas de usuario en Windows (Wireshark/USBPcap, CRU,
HWiNFO64, GPU-Z, el propio panel de NVIDIA) no queda nada más para mirar: ni EDID especial,
ni comando USB oculto, ni DSC visible (el Reverb G2 ni siquiera aparece como display
seleccionable en el panel de NVIDIA ni en Configuración de Windows, al estar en modo
directo/HMD). Lo que sigue siendo invisible desde acá es exactamente lo que se preguntaba
arriba: qué pasa en el link training de DisplayPort (DPCD/AUX) o adentro del firmware GSP
cerrado — ninguna herramienta de usuario llega ahí en ningún SO.
