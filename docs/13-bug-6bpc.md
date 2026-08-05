# 13 — El bug: NVIDIA clava el G2 en 6 bits por color

**Encontrado el 2026-08-05, leyendo el código fuente del driver.** Es una línea.

---

## El resumen

El EDID del Reverb G2 **no declara su profundidad de color**. El driver NVIDIA de Linux
interpreta ese "no declarado" como **6 bits por componente** y maneja el enlace a 18 bpp en
todos los modos. Windows, con la misma GPU, usa 8. A 60 Hz el panel tolera los 6 bits; a 90 Hz
no enciende.

---

## La cadena causal, verificada eslabón por eslabón

| # | eslabón | evidencia |
|---|---|---|
| 1 | El EDID del casco deja la profundidad sin declarar | byte `0x14` = `0x80`: digital, bits 6-4 = `000` = *undefined*, EDID 1.4 |
| 2 | El parser lo convierte en `bpc = 0` | `nvt_edid.c:932`, rama `default:` |
| 3 | Nada lo sobreescribe | el DisplayID 2.0 del casco sólo trae un bloque Type VII (tag `0x03`); **no tiene Display Parameters (`0x21`)**, que es lo único que reasignaría `digital.bpc` (`nvt_edidext_displayid20.c:314`) |
| 4 | **`bpc < 8` clava el máximo en 6** | `nvkms-dpy.c:3456` |
| 5 | Al no pedirse nada, se usa el máximo | `ChooseColorBpc()` devuelve `max` si `requested == UNKNOWN` |
| 6 | El enlace corre a 18 bpp | `nvidia-modeset: DPCONN> Notify Attach Begin (Head 0, pclk 428580000 raster 2980 x 1598  18 bpp)` |
| 7 | **El casco lo confirma** | byte 18 de su `DEVICE_STATUS` = `06` en Linux, `08` en Windows |
| 8 | A 90 Hz el panel no enciende | verificación física, nueve corridas |

## El código

`src/nvidia-modeset/src/nvkms-dpy.c`, en `nvDpyGetOutputColorFormatInfo()`, rama de
DisplayPort:

```c
if (pDpyEvo->parsedEdid.info.input.u.digital.bpc >= 10) {
    colorFormatsInfo.rgb444.maxBpc = ..._BPC_10;
    colorFormatsInfo.yuv444.maxBpc = ..._BPC_10;
} else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {   // <-- 0 cae acá
    colorFormatsInfo.rgb444.maxBpc = ..._BPC_6;
    colorFormatsInfo.yuv444.maxBpc = ..._BPC_UNKNOWN;
} else {
    colorFormatsInfo.rgb444.maxBpc = ..._BPC_8;
    colorFormatsInfo.yuv444.maxBpc = ..._BPC_8;
}
```

**"Undefined" significa que el sink no la declaró, no que quiera 6.**

Y hay una inconsistencia dentro de la misma función: unas líneas más arriba, la rama de **DSI**
trata el caso desconocido como **8**:

```c
default:
    nvAssert(!"Unsupported bpc for DSI");
    // fall through
case 8:
    colorFormatsInfo.rgb444.maxBpc = ..._BPC_8;
```

DisplayPort y DSI hacen cosas distintas con la misma entrada.

## El parche

`patches/nvidia/0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch`:

```c
-                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
+                } else if (pDpyEvo->parsedEdid.info.input.u.digital.bpc != 0 &&
+                           pDpyEvo->parsedEdid.info.input.u.digital.bpc < 8) {
```

Se aplica y reconstruye con `sudo ./scripts/apply-bpc-patch.sh` (y `--revert` lo saca).
**Requiere reiniciar.**

## Cómo se verifica que funcionó

Dos señales, y conviene mirar las dos:

1. **El byte 18 del `DEVICE_STATUS` tiene que pasar de `06` a `08`.** Es medición del lado
   del casco, no del driver, así que no depende de que le creamos a NVIDIA.
   `./scripts/panel-status.py 40` en paralelo con `hmd-vk`.
2. **Verificación física a 90 Hz.** Como siempre: sólo vale lo que se ve adentro del casco.

Si el byte 18 pasa a `08` y el panel **sigue** sin encender a 90 Hz, entonces el bpc era un bug
real pero no *el* bug — y habría que seguir con el byte 11, que es la otra diferencia contra
Windows (`0x14`=20 en Linux contra `0x1e`=30 en Windows a 90 Hz).

## Por qué importa más allá del G2

Esto **no es específico del Reverb G2**. Afecta a cualquier sink DisplayPort con EDID 1.4 que
deje la profundidad de color sin declarar: el driver lo maneja a 6 bpc en Linux y a 8 en
Windows. En un monitor común el síntoma sería *banding* y colores pobres, fácil de atribuir a
otra cosa. En este casco el síntoma es que el panel no enciende a 90 Hz.

Vale la pena mirar si explica alguno de los otros dos bugs de HMD que NVIDIA tiene abiertos
(Bigscreen Beyond con corrupción DSC, bug 4834531; Index/Vive con judder, bug 5372097).

## Estado

- [x] Cadena causal verificada en el código y contra tres mediciones independientes
- [x] Parche escrito
- [ ] **Parche compilado y probado** ← acá estamos
- [ ] Si funciona: reportar a NVIDIA en el hilo 337744 (bug 5923212) con el parche
- [ ] Si funciona: proponerlo también a Monado y a la wiki de LVRA
