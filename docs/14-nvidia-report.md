# 14 — Reporte para NVIDIA

> ## ⚠️ CUÁL DE LOS DOS CUERPOS USAR
>
> Este archivo tiene **dos** versiones completas del reporte. No confundirlas:
>
> | sección | qué es | usar |
> |---|---|---|
> | "Cuerpo del reporte" (abajo) | la versión original, con el error del DisplayID (decía 2.0 / Type VII; es 1.2 / Type I). Ya reemplazada en el hilo | ❌ no — queda sólo como registro |
> | **"CUERPO CORREGIDO v2"** (después de `# PUBLICADO`) | **el nuevo.** Error corregido + Summary arriba de todo + secciones renombradas | ✅ **este** |
>
> **Estado del hilo al 2026-08-05:** post vivo y público, con la corrección del DisplayID
> ya aplicada, **los tres adjuntos subidos**, y 0 respuestas. Falta: pegar la v2 (Summary +
> renombres) y abrir el issue en GitHub.
>
> **OK, validado el 2026-08-05:** el cuerpo corregido menciona los parches de Project-VR
> (los tres, uno por uno) en la sección *"What we ruled out"* → bullet **"Community
> open-kernel patches for this headset"**. Lo que **no** hace es nombrar el repo; ver
> "Sobre nombrar a Project-VR" al final de esa sección para el porqué y para la variante
> con el nombre puesto, por si preferís esa.
>
> Adjuntos ya armados en `forum-attachments/`. Triage del feedback en `docs/15`.

## Cuerpo publicado el 2026-08-05 (con el error del DisplayID) — histórico

**Verificado por el usuario (2026-08-05):**
- El hilo y el bug `5923212` están confirmados — el usuario abrió el hilo y el número es
  correcto. Se puede citar tal cual.
- **El dato de AMD (issue #332 de Monado, `dimitriscr`) se decidió NO incluir.** No se
  verificó de primera mano, y aunque fuera cierto no ayuda al reporte: decirle a NVIDIA
  "funciona con la competencia" no aporta nada a que sus ingenieros entiendan la causa. El
  reporte ya es sólido sin eso — tiene código citado con línea exacta, un parche que
  funciona, y verificación física con protocolo. Por eso ese dato ya estaba fuera del cuerpo
  principal; queda confirmado que se mantiene así.
- Todo lo demás en este reporte (patch, mediciones, bytes, logs) es nuestro, medido en este
  rig, y se cita con confianza.

Lo que sigue está en inglés porque es para el foro de NVIDIA. Copialo tal cual, o editalo.

---

### Título sugerido

```
HP Reverb G2 clamped to 6 bpc because its EDID leaves color depth undefined — root cause
found + two-line patch, but 90 Hz still fails to light the panel (nvkms-dpy.c)
```

---

### Cuerpo del reporte

```markdown
Hi, replying with a specific root-cause finding for the "no more than 60Hz" issue on this
headset (I believe this is the same one tracked as bug 5923212 in this thread — please
correct me if I'm conflating two different bugs).

**Environment**
- GPU: RTX 3060 Ti (GA104, Ampere)
- Driver: 595.71.05, open kernel modules (nvidia-kernel-open-dkms)
- OS: Debian 13 (trixie), kernel 6.12.100+deb13-amd64
- Tested on both X11 NVIDIA Direct-Mode and Wayland (GNOME 48.7 / mutter) via DRM lease —
  identical failure on both, so this isn't specific to one display path.
- I have only tested 595.71.05 myself; earlier reports of 590.x–610.x being affected are
  from other posters in this thread, not from my own testing.

**Symptom**
The G2's EDID advertises three modes: 4320x2160@60 (works), 4320x2160@90 and
2880x1440@90 (both fail). At either 90 Hz mode the panel shows only the static HP boot logo
— no video ever reaches the panel — while Vulkan/DRM report a fully successful modeset and
90.0 fps presented. The API-level success is misleading; this was only caught by physically
looking inside the headset. `nvidia-modeset`'s own attach log looks identical (success, no
errors) for both the working 60 Hz mode and the failing 90 Hz modes.

**Root cause**

The G2's EDID is 1.4 and leaves the "Color Bit Depth" field of the Video Input Definition
byte (offset 0x14, bits 6-4) at `000` = "undefined" (byte value `0x80`). Its DisplayID 2.0
extension carries only a Type VII timing block, no Display Parameters block, so nothing
overrides this.

`src/common/modeset/timing/nvt_edid.c` parses the undefined case into
`input.u.digital.bpc = 0`:

    default :
        pInfo->input.u.digital.bpc = 0;
        break;

`src/nvidia-modeset/src/nvkms-dpy.c`, in `nvDpyGetOutputColorFormatInfo()`, DP branch, then
does:

    } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
        colorFormatsInfo.rgb444.maxBpc = NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_6;
        colorFormatsInfo.yuv444.maxBpc = NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_UNKNOWN;

`0 < 8` is true, so an EDID that simply didn't declare a depth gets clamped to 6 bpc
(18bpp) for every mode, confirmed in `dmesg`:

    nvidia-modeset: DPCONN> Notify Attach Begin (Head 0, pclk 428580000 raster 2980 x 1598  18 bpp)

Note the DSI branch of this *same* function already treats an unrecognized/unknown bpc as
8, not 6:

    default:
        nvAssert(!"Unsupported bpc for DSI");
        // fall through
    case 8:
        colorFormatsInfo.rgb444.maxBpc = NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_8;

so DP and DSI disagree on how to handle the exact same "undefined" input, in the same
source file.

**Independent confirmation via the headset itself**

The G2's companion device reports its own panel state over HID (report 0x05, 33 bytes) —
byte 18 of that report reflects the bpc actually in use. Capturing this on Linux (6 on the
DP-side per above) and on Windows (610.74, same GPU) at the identical mode
(4320x2160@90):

    Windows (works):  05 01 01 01 01 5a 00 00 00 09 38 1e 04 00 77 77 00 00 08 44 11 e4 08 ...
    Linux (fails):    05 00 01 01 00 5a 00 00 00 09 38 14 04 00 77 77 00 00 06 44 11 e4 08 ...
                                                              ^^                  ^^
Byte 18: `06` on Linux vs `08` on Windows, with the same GPU. Windows is driving this sink
at 8 bpc; our open-kernel Linux driver is driving it at 6.

**The patch**

    --- a/src/nvidia-modeset/src/nvkms-dpy.c
    +++ b/src/nvidia-modeset/src/nvkms-dpy.c
    @@ -3453,7 +3453,8 @@
                         colorFormatsInfo.rgb444.maxBpc =
                             NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_10;
                         colorFormatsInfo.yuv444.maxBpc =
                             NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_10;
    -                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
    +                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc != 0 &&
    +                           pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
                         colorFormatsInfo.rgb444.maxBpc =
                             NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_6;
                         colorFormatsInfo.yuv444.maxBpc =

Treats 0 ("not declared") the same way the DSI branch already does, and falls through to
the 8bpc default instead of clamping to 6.

**Verified effect of the patch**

- `dmesg` now shows `24 bpp` instead of `18 bpp` for every mode.
- The headset's own status byte 18 goes from `06` to `08`, matching Windows exactly.
- In fact, with the patch applied, the headset's full 33-byte status report for
  4320x2160@90 becomes **byte-for-byte identical** to the working Windows capture at the
  same mode.

**But this does not fix the 90 Hz modes**

With the patch applied and 8bpc confirmed on the wire, physical verification (someone
wearing the headset, not API state) at the two 90 Hz modes shows:

- 4320x2160@90 (905.4 MHz pixel clock): panel lights up and flickers, but shows plain white,
  no color content.
- 2880x1440@90 (428.6 MHz pixel clock — well under half the bandwidth of the mode above,
  and even under the 60Hz mode's 709.15 MHz): **identical white flicker**, no color.

Both 90 Hz modes fail identically despite a >2x difference in pixel clock, which rules out
DP or MIPI-side bandwidth as the differentiator. 4320x2160@60 continues to display correctly
with the same patch applied (so the patch does not regress the working mode).

This is real forward progress — pre-patch, both 90 Hz modes showed nothing but a static
boot logo, no backlight/panel activity at all. Post-patch, the panel activates but doesn't
render correct pixel content, specifically and only at 90 Hz.

**What we ruled out for the remaining 90 Hz failure**

- DSC / YCbCr / color-space switching: zero hits for these terms in `dmesg` with
  `nvidia_modeset.debug=1` across all three modes.
- Timing/porches: the full modeline nvkms programs (front/back porch, sync polarity) via
  `drmModeGetConnector` is internally consistent across all three modes — no anomaly found
  at this level.
- `NVreg_ResmanDebugLevel`: default is already `~0` (all bits); we suspect these debug
  prints are compiled out of release builds, same as `nvidia_modeset.debug` which is capped
  at 7 fixed lines regardless of value.
- GSP-RM firmware logs: this GPU (GA104) uses GSP firmware
  (`/lib/firmware/nvidia/595.71.05/gsp_ga10x.bin`), so a lot of the interesting logic likely
  runs there, not in the open kernel modules. We set `NVreg_EnableGpuFirmwareLogs=1`
  expecting more detail, but the driver reports it needs `gsp_log_ga10x.bin`, which is not
  present. We downloaded your official 595.71.05 `.run` installer in full and confirmed by
  MD5 that its `gsp_ga10x.bin` is byte-identical to the one already installed — the
  logging-capable firmware variant does not appear to be publicly distributed for this
  consumer GPU. We have no way to see what the GSP does during the 90 Hz negotiation.

**Ask**

Would appreciate if someone with access to the closed GSP-RM source could look at what
differs at 90 Hz specifically (independent of bandwidth, since both native 90 Hz modes fail
identically) now that the bpc is correctly negotiated. Happy to test additional patches or
provide more diagnostics — I have physical access to the hardware and a working automated
test harness (custom minimal Vulkan display client, bypassing Monado/SteamVR entirely) that
reproduces this on demand.

Patch attached: `0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-depth.patch`
```

---

### Adjuntos sugeridos

- `patches/nvidia/0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch`
- El EDID crudo del casco (`hmd.edid`, 384 bytes) de cualquiera de los `nv-report-*/`
- Opcional: el `nvidia-bug-report.gz` de un `nv-report-*/` — es grande (500+ KB comprimido),
  mejor ofrecerlo "si lo necesitan" en vez de adjuntarlo de una

### Qué NO incluí, a propósito

- Números de versión de driver fuera de la 595.71.05 (esa parte del rango 590–610 es de
  otros posteos, no nuestro)
- Cualquier afirmación sobre qué dijo el staff de NVIDIA textualmente — no lo verificamos
  nosotros mismos esta sesión
- El dato de AMD/`dimitriscr` quedó afuera del cuerpo principal por la misma razón: no lo
  leímos de primera mano. Si querés sumarlo como reforzador, verificalo primero y agregalo
  vos con tus palabras, no como cita nuestra.

---

# PUBLICADO el 2026-08-05

<https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240>

---

## CUERPO CORREGIDO v2 — la edición final del post (2026-08-05)

**Historia hasta acá.** El post se publicó con un error (decía DisplayID 2.0 / Type VII; es
1.2 / Type I). Se editó con la corrección, Akismet lo retuvo unos minutos, y un moderador lo
liberó. **Ahora está vivo, público, y con 0 respuestas** — o sea que todavía se lo puede dejar
en su mejor versión sin que nadie haya leído una versión peor.

**Esta v2 agrega, sobre lo ya publicado:**

1. Un bloque **Summary** arriba de todo que separa los dos hallazgos: el bug confirmado con
   parche de dos líneas (que **no** es específico del casco) y el fallo de 90 Hz sin resolver.
   Un ingeniero que abre el hilo tiene que saber en diez segundos que hay algo accionable y
   barato adentro; antes había que leer medio reporte para descubrirlo.
2. Se sacó el *"Hi, replying with..."* del arranque: esto es un tema nuevo, no una respuesta,
   y arrancar con "replying" confundía. La referencia al bug 5923212 quedó, al final del
   Summary.
3. `**Root cause**` → `**Finding 1 — the 6 bpc clamp: root cause**`, y `**But this does not
   fix the 90 Hz modes**` → `**Finding 2 — the 90 Hz failure, which this patch does not
   fix**`. Escanear el post ahora te da la estructura sola.
4. Se declara explícitamente el protocolo de verificación física y que falló **nueve veces
   sobre nueve, en dos vías de display que casi no comparten código**. Es el dato que separa
   este reporte de los demás del foro, y estaba enterrado.

**Que ésta sea la ÚLTIMA edición.** Cada edición reencola en Akismet, y editar repetido es
justo el patrón que el filtro puntúa. Todo junto, de una: pegar el cuerpo y subir los tres
adjuntos en la misma acción.

**Adjuntos** (armados en `forum-attachments/`):

| archivo | qué es |
|---|---|
| `g2-edid.zip` | EDID crudo (384 B), el EDID de repro con 8 bpc, el decode anotado, y un README |
| `nvidia-bug-report.log.gz` | 545 KB, capturado con el parche puesto |
| `0004-nvkms-no-6bpc-clamp.patch.txt` | el parche (`.txt` porque el foro no acepta `.patch`) |

Los `.bin` van dentro del `.zip` porque Discourse rechaza esa extensión suelta.

**Lo último del cuerpo es un link al issue de GitHub, que todavía no existe.** Dos opciones:
abrir el issue primero y pegar la URL antes de editar (mejor: una sola edición), o borrar esa
línea ahora y dejar la URL después en una respuesta.

Cuerpo completo, listo para pegar sobre el original:

````markdown
**Summary**

Two findings on the HP Reverb G2 (EDID ManufID 0x220E) with the 595.71.05 open kernel
modules. They are independent, and the first one is not specific to this headset:

1. **A confirmed bug with a two-line fix.** `nvkms-dpy.c` treats "the EDID did not declare a
   color depth" as "the sink wants 6 bpc" and drives the DisplayPort link at 18 bpp. The DSI
   branch of the *same function* already treats that same input as 8 bpc. This applies to
   **any** DisplayPort sink that leaves EDID Color Bit Depth undefined — on an ordinary
   monitor it would show up as banding, easy to misattribute. Confirmed in `dmesg`, and
   independently by the sink itself reporting the bpc back to the host.
2. **A failure that the patch does *not* fix.** Both of this headset's 90 Hz modes still fail
   to display correctly while its 60 Hz mode works. I have ruled out link bandwidth, DSC,
   color space, mode derivation, the display path, and the HID activation sequence — what is
   left appears to sit below the open kernel modules.

Everything about the 90 Hz behaviour below was verified by physically looking inside the
headset, because the API layer reports a successful modeset and a happy 90.0 fps with the
panel completely dark. It has failed on every attempt, nine runs, across two display paths
that share almost no driver code.

I believe this is the same underlying problem as the "60 Hz only on Reverb G2" reports
tracked as bug 5923212 — please correct me if I'm conflating two different bugs.

**Environment**
- GPU: RTX 3060 Ti (GA104, Ampere)
- Driver: 595.71.05, open kernel modules (nvidia-kernel-open-dkms)
- OS: Debian 13 (trixie), kernel 6.12.100+deb13-amd64
- Tested on both X11 NVIDIA Direct-Mode and Wayland (GNOME 48.7 / mutter) via DRM lease —
  identical failure on both, so this isn't specific to one display path.
- I have only tested 595.71.05 myself; reports of 590.x–610.x being affected come from other
  posters in the earlier thread, not from my own testing.

**Symptom**
The G2's EDID advertises three modes: 4320x2160@60 (works), 4320x2160@90 and
2880x1440@90 (both fail). At either 90 Hz mode the panel shows only the static HP boot logo
— no video ever reaches the panel — while Vulkan/DRM report a fully successful modeset and
90.0 fps presented. `nvidia-modeset`'s own attach log looks identical (success, no errors)
for both the working 60 Hz mode and the failing 90 Hz modes.

**Finding 1 — the 6 bpc clamp: root cause**

The G2's EDID is 1.4 and leaves the "Color Bit Depth" field of the Video Input Definition
byte (offset 0x14, bits 6-4) at `000` = "undefined" (byte value `0x80`).

`src/common/modeset/timing/nvt_edid.c` parses the undefined case into
`input.u.digital.bpc = 0`:

    default :
        pInfo->input.u.digital.bpc = 0;
        break;

`src/nvidia-modeset/src/nvkms-dpy.c`, in `nvDpyGetOutputColorFormatInfo()`, DP branch, then
does:

    } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
        colorFormatsInfo.rgb444.maxBpc = NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_6;
        colorFormatsInfo.yuv444.maxBpc = NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_UNKNOWN;

`0 < 8` is true, so an EDID that simply didn't declare a depth gets clamped to 6 bpc
(18bpp) for every mode, confirmed in `dmesg`:

    nvidia-modeset: DPCONN> Notify Attach Begin (Head 0, pclk 428580000 raster 2980 x 1598  18 bpp)

Note the DSI branch of this *same* function already treats an unrecognized/unknown bpc as
8, not 6:

    default:
        nvAssert(!"Unsupported bpc for DSI");
        // fall through
    case 8:
        colorFormatsInfo.rgb444.maxBpc = NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_8;

so DP and DSI disagree on how to handle the exact same "undefined" input, in the same
source file.

**Nothing else in this EDID can override the 0, and that generalizes**

`input.u.digital.bpc` is assigned in exactly two places in the whole tree: the base-block
switch quoted above, and `nvt_edidext_displayid20.c:314`, which reads the Display Parameters
block of a DisplayID **2.x** extension. Which of the two DisplayID parsers runs is decided in
`nvt_edid.c` purely by the version byte:

    case NVT_EDID_EXTENSION_DISPLAYID:
        if ((pExt[1] & 0xF0) == 0x20) // displayID2.x as EDID extension
            getDisplayId20EDIDExtInfo(...);
        else                          // displayID13 as EDID extension
            getDisplayIdEDIDExtInfo(...);

This headset's DisplayID extension block starts `70 12 79 00 00 03 ...`, i.e. version byte
`0x12` = DisplayID 1.2, so `0x12 & 0xF0 == 0x10` and it takes the DisplayID 1.3 path — which
never writes `digital.bpc` at all. (Its single data block, tag `0x03` / 40 bytes, is two
20-byte Type I Detailed Timing descriptors.)

So this isn't really a quirk of one headset's EDID. **For any DisplayPort sink whose
DisplayID extension is 1.x — or that has no DisplayID extension — the only override site is
unreachable by construction, so leaving Color Bit Depth undefined in the base block means an
unconditional 6 bpc clamp.** On an ordinary monitor that would show up as banding, which is
easy to misattribute. Here it happens to break a headset.

**Independent confirmation via the headset itself**

The G2's companion device reports its own panel state over HID (report 0x05, 33 bytes) —
byte 18 of that report reflects the bpc actually in use. Capturing this on Linux (6 on the
DP-side per above) and on Windows (610.74, same GPU) at the identical mode
(4320x2160@90):

    Windows (works):  05 01 01 01 01 5a 00 00 00 09 38 1e 04 00 77 77 00 00 08 44 11 e4 08 ...
    Linux (fails):    05 00 01 01 00 5a 00 00 00 09 38 14 04 00 77 77 00 00 06 44 11 e4 08 ...
                                                              ^^                  ^^
Byte 18: `06` on Linux vs `08` on Windows, with the same GPU. Windows is driving this sink
at 8 bpc; our open-kernel Linux driver is driving it at 6.

**The patch**

    --- a/src/nvidia-modeset/src/nvkms-dpy.c
    +++ b/src/nvidia-modeset/src/nvkms-dpy.c
    @@ -3453,7 +3453,8 @@
                         colorFormatsInfo.rgb444.maxBpc =
                             NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_10;
                         colorFormatsInfo.yuv444.maxBpc =
                             NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_10;
    -                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
    +                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc != 0 &&
    +                           pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
                         colorFormatsInfo.rgb444.maxBpc =
                             NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_6;
                         colorFormatsInfo.yuv444.maxBpc =

Treats 0 ("not declared") the same way the DSI branch already does, and falls through to
the 8bpc default instead of clamping to 6.

**Verified effect of the patch**

- `dmesg` now shows `24 bpp` instead of `18 bpp` for every mode.
- The headset's own status byte 18 goes from `06` to `08`, matching Windows exactly.
- In fact, with the patch applied, the headset's full 33-byte status report for
  4320x2160@90 becomes **byte-for-byte identical** to the working Windows capture at the
  same mode.

**If you want to reproduce the clamp without building a driver**

Attached (`g2-edid.zip`) is the raw EDID plus a copy with exactly two bytes changed: base
byte `0x14` from `0x80` to `0xA0` (Color Bit Depth undefined → 8 bpc) and the base block
checksum from `0xE8` to `0xC8`. Feeding that as an EDID override produces the same 24bpp
result as the source patch, which makes the bpc half of this testable on any sink you can
override.

**Finding 2 — the 90 Hz failure, which this patch does *not* fix**

With the patch applied and 8bpc confirmed on the wire, physical verification (someone
wearing the headset, not API state) at the two 90 Hz modes shows:

- 4320x2160@90 (905.4 MHz pixel clock): panel lights up and flickers, but shows plain white,
  no color content.
- 2880x1440@90 (428.6 MHz pixel clock — well under half the bandwidth of the mode above,
  and even under the 60Hz mode's 709.15 MHz): **identical white flicker**, no color.

Both 90 Hz modes fail identically despite a >2x difference in pixel clock, which rules out
DP or MIPI-side bandwidth as the differentiator. 4320x2160@60 continues to display correctly
with the same patch applied (so the patch does not regress the working mode).

This is real forward progress — pre-patch, both 90 Hz modes showed nothing but a static
boot logo, no backlight/panel activity at all. Post-patch, the panel activates but doesn't
render correct pixel content, specifically and only at 90 Hz.

**What we ruled out for the remaining 90 Hz failure**

- **Color space**: ruled out from the EDID itself, not just from logs. The CTA-861 extension
  has byte 3 = `0x00` — this sink advertises no YCbCr 4:4:4 and no YCbCr 4:2:2 at all, so the
  link is necessarily RGB in all three modes and there is no color-space variable that could
  differ between the working mode and the failing ones.
- **DSC**: zero hits for DSC/compression terms in `dmesg` with `nvidia_modeset.debug=1`
  across all three modes.
- **Mode derivation / timings**: I decoded all three timings by hand out of the raw EDID and
  compared them against what `drmModeGetConnector` reports the driver programming:

      source                       pclk       H act/fp/sync/bp    V act/fp/sync/bp     rate
      DisplayID desc #1 (pref)  905.40 MHz  4320 / 50 / 4 / 46  2160 / 16 / 2 /  98  90.00
      DisplayID desc #2         709.15 MHz  4320 / 50 / 4 / 46  2160 / 14 / 2 / 498  60.00
      base block DTD            428.58 MHz  2880 / 50 / 4 / 46  1440 / 18 / 2 / 138  90.00

  All three with positive H and V sync polarity, all three matching what the driver programs
  bit for bit (and matching the `raster 2980 x 1598 / pclk 428580000` in the attach log). The
  driver is programming precisely the timings the sink asks for; there is no second root
  cause hiding in mode derivation. Full annotated decode is in the attached zip.
- **Community open-kernel patches for this headset**: in addition to my bpc patch, this
  system has three others applied against 595.71.05 — VESA DisplayID/DSC VSDB
  spec-correctness fixes, DRM-lease enablement for VR HMDs, and a `forceMaxLinkConfig` WAR
  keyed on EDID ManufID 0x220E in `dp_wardatabase.cpp`. With all four applied on GA104, both
  90 Hz modes still fail physically. Mentioning it so nobody re-tests that combination:
  nothing found so far at the open kernel module level lights this panel at 90 Hz.
- `NVreg_ResmanDebugLevel`: default is already `~0` (all bits); we suspect these debug
  prints are compiled out of release builds, same as `nvidia_modeset.debug` which is capped
  at 7 fixed lines regardless of value.
- GSP-RM firmware logs: this GPU (GA104) uses GSP firmware
  (`/lib/firmware/nvidia/595.71.05/gsp_ga10x.bin`), so a lot of the interesting logic likely
  runs there, not in the open kernel modules. We set `NVreg_EnableGpuFirmwareLogs=1`
  expecting more detail, but the driver reports it needs `gsp_log_ga10x.bin`, which is not
  present. We downloaded your official 595.71.05 `.run` installer in full and confirmed by
  MD5 that its `gsp_ga10x.bin` is byte-identical to the one already installed — the
  logging-capable firmware variant does not appear to be publicly distributed for this
  consumer GPU. We have no way to see what the GSP does during the 90 Hz negotiation.

**Ask**

Would appreciate if someone with access to the closed GSP-RM source could look at what
differs at 90 Hz specifically (independent of bandwidth, since both native 90 Hz modes fail
identically) now that the bpc is correctly negotiated. Happy to test additional patches or
provide more diagnostics — I have physical access to the hardware and a working automated
test harness (custom minimal Vulkan display client, bypassing Monado/SteamVR entirely) that
reproduces this on demand.

**Attached**

- `0004-nvkms-no-6bpc-clamp.patch.txt` — the two-line patch above
- `g2-edid.zip` — raw 384-byte EDID, the 8bpc override copy, and a full annotated decode
- `nvidia-bug-report.log.gz` — captured with the patch applied

The bpc part of this is also filed as an issue against the open kernel modules:
PEGAR_URL_DEL_ISSUE_ACA
````

### Sobre nombrar a Project-VR en el cuerpo corregido

Los tres parches **sí están mencionados**, en el bullet *"Community open-kernel patches for
this headset"*, descritos uno por uno y con el archivo exacto (`dp_wardatabase.cpp`, ManufID
`0x220E`). Lo que se omitió a propósito es el **nombre del repo**, por una razón concreta:

`docs/06` deja registrado que **Project-VR no es un caso positivo verificado** — su evidencia
de "90 Hz andando" es una sesión Vulkan/OpenXR exitosa con sus logs, exactamente la clase de
evidencia que este proyecto demostró nueve veces que convive con el panel muerto. Nombrarlo en
un reporte a NVIDIA le mete a alguien de ingeniería la idea de que *hay* un caso funcionando en
Linux, que es justamente lo que no podemos sostener. Descrito por contenido, el dato que sí
aportamos —"estos tres cambios no encienden el panel a 90 Hz en GA104"— queda intacto y sin
importar un claim ajeno.

**Si preferís nombrarlo igual** (es defendible: le da a NVIDIA los parches en una URL y da
crédito al autor), reemplazá la primera oración de ese bullet por:

```markdown
- **Community open-kernel patches for this headset**: in addition to my bpc patch, this
  system has three patches from https://github.com/AshishKumar4/Project-VR applied against
  595.71.05 — VESA DisplayID/DSC VSDB spec-correctness fixes, DRM-lease enablement for VR
  HMDs, and a `forceMaxLinkConfig` WAR keyed on EDID ManufID 0x220E in `dp_wardatabase.cpp`.
  That repo reports 90 Hz working on an RTX 4080, but I could not confirm that result: its
  evidence is a successful Vulkan/OpenXR session and logs, and on this hardware a completely
  dark panel also produces a successful session at a happy 90.0 fps. With all four patches
  applied on GA104, both 90 Hz modes still fail physically.
```

Esa variante es honesta y probablemente la mejor de las dos: nombra la fuente, da la URL, y
al mismo tiempo aclara por qué no cuenta como caso positivo. Queda a tu criterio.

## Issue para `NVIDIA/open-gpu-kernel-modules` (listo para pegar)

Mismo hallazgo, recortado a lo que es puramente un bug de código: sin el 90 Hz, sin el casco,
sin nada que dependa de creerle a nuestra verificación física. Linkea el hilo del foro para el
contexto largo.

**Título:**

```
nvkms-dpy.c: DP sinks that leave EDID Color Bit Depth undefined are clamped to 6 bpc
```

**Cuerpo:**

```markdown
### Summary

`nvDpyGetOutputColorFormatInfo()` treats "the sink did not declare a color depth" as "the sink
wants 6 bpc", and clamps the DisplayPort link to 18 bpp. The DSI branch of the same function
already treats the unknown case as 8 bpc, so the two branches disagree on identical input.

### Details

For an EDID 1.4 digital sink, `nvt_edid.c` parses the Video Input Definition byte (offset
0x14, bits 6-4) and maps the "undefined" encoding (`000`) to zero:

```c
    default :
        pInfo->input.u.digital.bpc = 0;
        break;
```

`src/nvidia-modeset/src/nvkms-dpy.c`, DisplayPort branch:

```c
    } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
        colorFormatsInfo.rgb444.maxBpc = NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_6;
        colorFormatsInfo.yuv444.maxBpc = NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_UNKNOWN;
```

`0 < 8` is true, so the sink is driven at 6 bpc. Since `ChooseColorBpc()` returns `max` when
nothing is explicitly requested, this applies to every mode on such a sink.

Compare the DSI branch a few lines above, which handles the same "we don't know" case the
other way:

```c
    default:
        nvAssert(!"Unsupported bpc for DSI");
        // fall through
    case 8:
        colorFormatsInfo.rgb444.maxBpc = NV_KMS_DPY_ATTRIBUTE_CURRENT_COLOR_BPC_8;
```

`input.u.digital.bpc` is assigned in exactly two places in the tree — the base-block switch
above, and `nvt_edidext_displayid20.c:314` (DisplayID 2.x Display Parameters block). The
second one is gated on the DisplayID version in `nvt_edid.c`:

```c
    if ((pExt[1] & 0xF0) == 0x20) // displayID2.x as EDID extension
        getDisplayId20EDIDExtInfo(...);
    else                          // displayID13 as EDID extension
        getDisplayIdEDIDExtInfo(...);
```

The DisplayID 1.3 parser never writes `digital.bpc`. So for any sink with a DisplayID 1.x
extension (or no DisplayID extension) that leaves base-block Color Bit Depth undefined, the
6 bpc clamp is unconditional.

### Reproduced on

- RTX 3060 Ti (GA104), driver 595.71.05, open kernel modules, Debian 13, kernel 6.12.100
- Sink: HP Reverb G2 — EDID base byte 0x14 = `0x80` (digital, Color Bit Depth = undefined),
  DisplayID extension version byte `0x12`

Before:

```
nvidia-modeset: DPCONN> Notify Attach Begin (Head 0, pclk 428580000 raster 2980 x 1598  18 bpp)
```

After the patch below: `24 bpp`. The sink independently confirms the change — it reports the
bpc in use over its own status channel, and that field goes from `06` to `08`, matching what
the same GPU negotiates under Windows.

### Suggested fix

```diff
-                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
+                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc != 0 &&
+                           pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
```

This makes the DP branch fall through to the existing 8 bpc default for undeclared depth,
matching what the DSI branch already does.

### Context

Longer write-up, including a separate unresolved 90 Hz issue on this same sink that this
patch does **not** fix, in the developer forum thread:
<https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240>
```
