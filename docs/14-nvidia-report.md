# 14 — Reporte para NVIDIA (borrador listo para publicar)

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

## Título sugerido

```
HP Reverb G2 clamped to 6 bpc because its EDID leaves color depth undefined — root cause
found + two-line patch, but 90 Hz still fails to light the panel (nvkms-dpy.c)
```

---

## Cuerpo del reporte

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

## Adjuntos sugeridos

- `patches/nvidia/0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch`
- El EDID crudo del casco (`hmd.edid`, 384 bytes) de cualquiera de los `nv-report-*/`
- Opcional: el `nvidia-bug-report.gz` de un `nv-report-*/` — es grande (500+ KB comprimido),
  mejor ofrecerlo "si lo necesitan" en vez de adjuntarlo de una

## Qué NO incluí, a propósito

- Números de versión de driver fuera de la 595.71.05 (esa parte del rango 590–610 es de
  otros posteos, no nuestro)
- Cualquier afirmación sobre qué dijo el staff de NVIDIA textualmente — no lo verificamos
  nosotros mismos esta sesión
- El dato de AMD/`dimitriscr` quedó afuera del cuerpo principal por la misma razón: no lo
  leímos de primera mano. Si querés sumarlo como reforzador, verificalo primero y agregalo
  vos con tus palabras, no como cita nuestra.
