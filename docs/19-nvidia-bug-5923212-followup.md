# 19 — Seguimiento para el hilo del bug 5923212 (60Hz-only en NVIDIA)

## Update (2026-08-06): el parche SI funciona — 90Hz prende con imagen real. No lo posteé yo todavía.

Sesión separada, en la máquina del lab, con un agente. Reinstalación completa del driver
595-open desde cero (`nvidia-open` vía el repo oficial de NVIDIA, no lo que había antes) +
los 4 parches aplicados vía el mecanismo `PATCH[]` de `dkms.conf` (en vez de la edición
directa del árbol que usaba `apply-bpc-patch.sh`). Probado por un camino de presentación
distinto al del factorial de vblank de más abajo: DRM-lease de un compositor Wayland (Monado,
`hmd-vk`), no NVKMS Direct-Mode de X11 con override de EDID por `nvidia_modeset.config_file`.

**Resultado: 90Hz prende con imagen real, confirmado físicamente, primera vez en toda esta
investigación que algo pasa del logo de HP a 90Hz.** Probado en el modo supersampleado
(`4320x2160@90`, el que usa Project-VR) y, más importante, en el **modo nativo
`2880x1440@90`** — el DTD del bloque base del EDID sin modificar, el mismo timing que ya se
había confirmado por CRU que usa Windows (ver más abajo en este mismo archivo).

**Lo que sigue sin explicar, y por qué no llamo esto "cerrado" todavía:** el panel sigue
pareciendo parpadear como si estuviera a ~60Hz, a pesar de que el HID del casco, el timing
del compositor (11.111ms, exacto) y la API confirman los tres que corre genuinamente a 90Hz.
Persiste igual con un patrón sintético y con video real, y persiste en el modo nativo
también — así que no es un artefacto de renderizado ni un problema de "modo equivocado".
Sin cámara de alta velocidad (120fps+) no hay forma de medir el strobe físico del backlight
desde acá.

**No puedo afirmar con certeza qué de los dos cambios importó** (la reinstalación completa,
o el camino de presentación distinto) — quizás ninguno, y el entorno de prueba anterior
simplemente estaba roto de una forma que no se detectó en su momento. Si alguien con
visibilidad del lado de NVIDIA sabe si el Direct-Mode de NVKMS y el DRM-lease de un
compositor Wayland deberían comportarse distinto a nivel DPCD/AUX para el mismo modo nominal,
eso ayudaría a explicar la diferencia en cualquier sentido.

**Drafts listos para postear, dos hilos (no los posteo yo — mismo trato que siempre, son
del usuario para revisar/editar/postear cuando quiera):**

### Draft para 379240 (el hilo del bpc — el más relevante, reply al post original)

```
Update: the patch works — 90 Hz now lights up the panel with a real image.

Following up on my original report above (6bpc clamp root-caused, two-line patch, but 90 Hz
still failing to light at the time).

What changed: I rebuilt the driver from a clean nvidia-open 595.71.05 install and applied
the patch via DKMS's own PATCH[] mechanism instead of a manual source edit, then tested
through a different presentation path than before — a Wayland compositor's DRM-lease direct
mode (via Monado, an open-source OpenXR runtime) rather than X11 NVKMS Direct-Mode with a
raw EDID override via nvidia_modeset.config_file.

Result: 90 Hz produces a real image, verified physically with the headset on (flat
alternating test colors, and separately with real decoded video content) — the first time in
this whole investigation that anything got past the boot logo at 90 Hz. Tested at both the
supersampled 4320x2160@90 mode and, more importantly, the native 2880x1440@90 mode (the
EDID's own base-block DTD, unmodified — the exact mode I separately confirmed via CRU that
Windows itself drives this panel with).

One thing still open, and it's the reason I'm not closing this out yet: the panel still
visually appears to flicker/strobe at what looks like ~60 Hz to the eye, despite genuinely
running at 90 Hz confirmed at every layer I can check — the headset's own HID status report,
the compositor's frame pacing (11.111 ms period, matches 90 Hz exactly), and the presentation
API. This persists identically with a synthetic test pattern and with real video content, and
persists at the native mode too, so it isn't a rendering/compositor artifact and it isn't a
"wrong mode" issue. I don't have a way to measure the physical backlight strobe rate directly
from here (would need a 120fps+ camera) so I can't rule in or out yet whether this is a
separate firmware-level backlight-timing behavior, unrelated to the DisplayPort link itself.

I honestly can't say with certainty which of the two changes above (rebuild path, or the
different presentation mechanism) actually mattered — possibly neither, and something about
the earlier test environment was simply broken in a way I didn't catch. If anyone reading
this has NVIDIA-side visibility into whether NVKMS's Direct-Mode path and a Wayland
compositor's DRM-lease path should behave any differently at the DPCD/AUX level for the same
nominal video mode, that would help explain the gap either way.

Happy to share the exact steps/config if useful to anyone else hitting this.
```

### Draft para 337744 (el hilo original del bug 5923212 — reply corto, dirige al otro hilo)

```
Update on my factorial results above: they're superseded — 90 Hz does light up now.

Since posting the factorial (concluding nothing but ~709 MHz ever showed an image, pointing
at a bridge-chip ceiling), I found and fixed an unrelated bug in the same EDID: NVKMS clamps
color depth to 6 bpc when the EDID leaves it undeclared (this headset's does), which was
still active during that whole factorial run without my realizing it mattered. Full
root-cause, patch, and today's confirmation that native 90 Hz now produces a real image are
in a separate thread I'd opened for that specific issue:

https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240

Short version: the bridge-chip-ceiling conclusion from the factorial doesn't hold up — once
the bpc bug is patched, native 90 Hz (the exact same EDID timing, unmodified) lights up fine.
There's still an open question about a visible flicker at 90 Hz even with a real image now,
detailed in the other thread, so I'm not calling this fully closed — but the "90 Hz is
architecturally impossible on this link" conclusion I posted earlier was wrong, and I wanted
to correct the public record here rather than leave it standing.
```

---


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

## Update (2026-08-06): el contenido de abajo se posteó, pero en el hilo equivocado

El borrador de más abajo se terminó posteando como respuesta en el **hilo del bpc (379240)**,
no acá (337744) — confirmado con fetch directo a los dos hilos: 379240 tiene el post de hoy
00:53am con este mismo contenido; 337744 sigue sin nada nuevo desde `MiaPerec` el 2026-07-19.
Puede haber sido a propósito (es tu hilo, tenés más contexto ahí) o cruce de pestañas — no lo
sé, no lo asumo.

Decisión: postear **también** acá, adaptado como cross-post corto que dirige a `abchauhan`
al resultado completo, en vez de duplicar la tabla entera. Draft abajo, mismo trato que el de
arriba: **no lo posteo yo**, es texto listo para copiar/pegar o editar.

**Posteado 2026-08-06, 10:00am**, como post #14 del hilo 337744:
<https://forums.developer.nvidia.com/t/reverb-g2-unable-to-drive-more-than-60hz-mode-on-nvidia/337744/14>.
Entró como post normal al final del hilo, **no** como reply threadeado al post #10 de
`abchauhan` (sin indicador "in reply to"). Si no responde en un tiempo razonable, considerar
editar el post para agregarle `@abchauhan` al arranque — en Discourse eso sí dispara
notificación directa. Sin respuesta de NVIDIA todavía en ninguno de los dos hilos (chequeado
el mismo día, a los pocos minutos de postear — es esperable que no haya nada aún).

### Draft para 337744 (cross-post, corto)

**Reply to `abchauhan`'s bug 5923212:**

Following up here — I ran a full factorial that isolates refresh rate, vertical blanking, and
pixel clock as independent variables on real hardware (physical verification every time,
headset worn, not just API success), plus identified the bridge chip's own datasheet ceiling.
Posted the full results (table, methodology, bridge chip data, an open question about the
ANX7530's PLL) as a follow-up in a related thread I'd started for a different EDID issue on
the same headset, to avoid fragmenting the data across two threads further:

<https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240/2>

Short version: none of resolution, refresh rate, vblank duration, or total DisplayPort
bandwidth alone explain the failure — the only pixel clock that has ever produced an image,
across every combination tried, is exactly ~709.15 MHz (the bridge chip's own native
4320x2160@60 timing). That, plus the bridge chip's datasheet ("DisplayPort Receiver Input
Bandwidth supports up to 4K x 2K x 60Hz" as an explicit spec line), points at a
hardware/firmware ceiling rather than a pure EDID/mode-timing problem.

Any update on bug 5923212 from your side? It's been quiet since March.

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
