#!/usr/bin/env python3
"""Decodifica y parchea el EDID del Reverb G2 (o cualquier EDID 1.4 + extensiones).

    ./scripts/edid-tool.py decode nv-report-*/hmd.edid
    ./scripts/edid-tool.py set-bpc nv-report-*/hmd.edid 8 -o g2-edid-8bpc.bin
    ./scripts/edid-tool.py inject-mode nv-report-*/hmd.edid
    ./scripts/edid-tool.py inject-mode nv-report-*/hmd.edid -o test.bin CTRL:1 A:2 B:3
    ./scripts/edid-tool.py inject-did nv-report-*/hmd.edid -o test.bin B4K:1

`decode` saca un volcado anotado, pensado para pegar/adjuntar en un reporte: incluye la
derivación completa de los modelines desde los DTD del bloque base y desde los descriptores
Type I del bloque DisplayID, que es lo que se compara contra `drmModeGetConnector`.

`set-bpc` reescribe los bits 6-4 del byte 0x14 (Color Bit Depth) y corrige el checksum del
bloque base. Sirve para reproducir el bug del clamp a 6 bpc **sin parchear el driver**, si se
tiene una vía de override de EDID que NVIDIA respete (ver docs/13).

`inject-mode` escribe timings sintéticos en los slots de DTD libres del bloque base, para el
experimento del vblank de docs/16: desacoplar "90 Hz" de "vblank corto", que en los tres
modos nativos del G2 están perfectamente confundidos. Sin argumentos de asignación lista los
presets y qué hay en cada slot. Las asignaciones son `PRESET:SLOT` y se aplican todas de una
sola pasada, así no hace falta encadenar archivos.

`inject-did` es lo mismo que `inject-mode` pero sobre los descriptores Type I del bloque
DisplayID (4320x2160) en vez de los DTD del bloque base (2880x1440). Existe porque el
factorial corrido en `inject-mode` salió confundido con la resolución: 2880x1440 nunca
mostró nada a ningún refresh en este proyecto, así que un fallo ahí no distingue "vblank
corto" de "esta resolución no engancha". A 4320x2160 sí hay un caso confirmado que anda
(el descriptor #2, @60), así que el mismo factorial ahí no tiene ese confound. Las
asignaciones son `PRESET:DESCRIPTOR` (1 o 2, son sólo dos descriptores).

Sin dependencias: sólo stdlib.
"""

import sys

BPC_FIELD = {0: "undefined", 1: 6, 2: 8, 3: 10, 4: 12, 5: 14, 6: 16, 7: "reserved"}
BPC_TO_FIELD = {v: k for k, v in BPC_FIELD.items() if isinstance(v, int)}

# Presets del experimento del vblank (docs/16). El DTD del bloque base tiene el campo de
# horizontal active de 12 bits (máximo 4095 px), así que 4320x2160 NO entra acá — que es
# justamente por qué el G2 lleva esos dos modos en el bloque DisplayID. El experimento va
# entonces sobre 2880x1440, que además mantiene la resolución constante contra el modo
# nativo que falla.
#
#            vblank corto (158)      vblank largo (514)
#   60 Hz    A     285.72 MHz        CTRL  349.38 MHz
#   90 Hz    nativo: FALLA           B     524.06 MHz
#
# Las dos formas de blanking vertical que existen en los modos nativos del G2, aplicadas a
# 2880x1440. El horizontal (50/4/46) es idéntico en los tres modos nativos, así que se deja
# fijo: la única variable estructural del sink es el vertical.
_H = (2880, 50, 4, 46)
BLANKING = {
    # nombre: (vact, vfp, vsw, vbp) -> vblank
    "SHORT": (1440, 18, 2, 138),   # vblank 158, la forma de los modos que fallan
    "LONG": (1440, 14, 2, 498),    # vblank 514, la forma del único modo que anda
}

# Alias con nombre para el factorial 2x2 de docs/16.
MODE_PRESETS = {
    # control: 60 Hz con el blanking largo. Dice si un modo inyectado enciende el panel en
    # general. Sin esto, un fallo de A no distingue "vblank corto" de "cualquier inyectado
    # falla". Correr SIEMPRE éste primero.
    "CTRL": "LONG@60",
    # el test: 60 Hz con el blanking corto del modo de 90 que falla.
    "A": "SHORT@60",
    # el recíproco: 90 Hz con vblank largo. Si esto anda, 90 Hz no es el problema.
    "B": "LONG@90",
}


def resolve_preset(name):
    """Devuelve la tupla de 9 campos de un preset.

    Acepta los alias del factorial (CTRL, A, B) y la forma paramétrica
    `BLANKING@RATE`, por ejemplo `SHORT@72`, para el barrido de refresh: mantiene fija
    la forma del timing y mueve sólo el refresh, que es lo que el factorial no separa.
    """
    name = MODE_PRESETS.get(name, name)
    shape, _, rate_s = name.partition("@")
    if not rate_s or shape not in BLANKING:
        raise ValueError(f"preset '{name}' inválido; se espera uno de {sorted(MODE_PRESETS)} "
                         f"o BLANKING@RATE con BLANKING en {sorted(BLANKING)}")
    rate = int(rate_s)
    if not 24 <= rate <= 240:
        raise ValueError(f"refresh {rate} Hz fuera del rango razonable (24-240)")
    return _H + BLANKING[shape] + (rate,)


# Presets del mismo factorial pero a 4320x2160, sobre los descriptores Type I del bloque
# DisplayID (docs/16, "Si hace falta repetirlo a 4320x2160"). El horizontal (50/4/46) es
# igual que en el bloque base -- es el mismo sink, la misma forma. vfp/vsw reusan los
# valores reales de los dos descriptores nativos (16/2 en el que falla a 90, 14/2 en el que
# anda a 60); sólo cambia vbp para mover el vblank total.
_H4K = (4320, 50, 4, 46)
DID_PRESETS = {
    # igual forma que el descriptor #2 real (el único que anda), vblank 514.
    "CTRL4K": (2160, 14, 2, 498, 60),
    # igual forma que el descriptor #1 real (el que falla), pero a 60 Hz. vblank 116.
    "A4K": (2160, 16, 2, 98, 60),
    # 90 Hz con vblank largo, pero 514 a 4320 de ancho pasa 25.5 Gbps @24bpp -- pegado al
    # techo de HBR3 (25.92). 240 deja margen y sigue siendo mucho más que el 116 que falla.
    "B4K": (2160, 14, 2, 224, 90),
}


def resolve_did_preset(name):
    """Como resolve_preset() pero para los descriptores Type I de DisplayID (4320x2160).

    Acepta los alias del factorial (CTRL4K, A4K, B4K), la forma paramétrica
    `VBLANK@RATE` (por ejemplo `240@90`) para puntos intermedios de vblank/refresh, y
    `HBP:VBLANK@RATE` (por ejemplo `1236:514@60`) para además mover el horizontal back
    porch y así el pixel clock manteniendo fijo el resto -- ningún test anterior tocó el
    horizontal (siempre 50/4/46), así que no separaba "el pixel clock específico importa"
    de "el refresh/vblank importa" (docs/16, sección "esto rompe la hipótesis...").
    """
    if name in DID_PRESETS:
        vact, vfp, vsw, vbp, rate = DID_PRESETS[name]
        return _H4K + (vact, vfp, vsw, vbp, rate)
    hact, hfp, hsw, hbp_default = _H4K
    hbp_s, sep, tail = name.partition(":")
    if sep:
        hbp = int(hbp_s)
        vblank_s, _, rate_s = tail.partition("@")
    else:
        hbp = hbp_default
        vblank_s, _, rate_s = name.partition("@")
    if not rate_s or not vblank_s.isdigit():
        raise ValueError(f"preset '{name}' inválido; se espera uno de {sorted(DID_PRESETS)}, "
                         "VBLANK@RATE (ej. 240@90) o HBP:VBLANK@RATE (ej. 1236:514@60)")
    vblank, rate = int(vblank_s), int(rate_s)
    if not 24 <= rate <= 240:
        raise ValueError(f"refresh {rate} Hz fuera del rango razonable (24-240)")
    vfp, vsw = 14, 2
    vbp = vblank - vfp - vsw
    if vbp < 0:
        raise ValueError(f"vblank {vblank} muy chico (mínimo {vfp + vsw})")
    return (hact, hfp, hsw, hbp, 2160, vfp, vsw, vbp, rate)


def blocks(data):
    return [data[i:i + 128] for i in range(0, len(data), 128)]


def fix_checksum(block):
    b = bytearray(block)
    b[127] = (-sum(b[:127])) & 0xFF
    return bytes(b)


def hexdump(block, indent="  "):
    out = []
    for i in range(0, 128, 16):
        row = " ".join(f"{x:02x}" for x in block[i:i + 16])
        out.append(f"{indent}{i:02x}: {row}")
    return "\n".join(out)


def decode_dtd(d):
    """DTD de 18 bytes del bloque base EDID. Devuelve dict o None si no es un DTD."""
    pclk = (d[1] << 8 | d[0]) * 10_000
    if pclk == 0:
        return None
    hact = ((d[4] & 0xF0) << 4) | d[2]
    hblank = ((d[4] & 0x0F) << 8) | d[3]
    vact = ((d[7] & 0xF0) << 4) | d[5]
    vblank = ((d[7] & 0x0F) << 8) | d[6]
    hfp = ((d[11] & 0xC0) << 2) | d[8]
    hsw = ((d[11] & 0x30) << 4) | d[9]
    vfp = ((d[11] & 0x0C) << 2) | (d[10] >> 4)
    vsw = ((d[11] & 0x03) << 4) | (d[10] & 0x0F)
    return {
        "pclk": pclk,
        "hact": hact, "hfp": hfp, "hsw": hsw, "hbp": hblank - hfp - hsw,
        "vact": vact, "vfp": vfp, "vsw": vsw, "vbp": vblank - vfp - vsw,
        "htotal": hact + hblank, "vtotal": vact + vblank,
        "hsync_pos": bool(d[17] & 0x02), "vsync_pos": bool(d[17] & 0x04),
        "interlaced": bool(d[17] & 0x80),
    }


def encode_dtd(hact, hfp, hsw, hbp, vact, vfp, vsw, vbp, rate, h_mm=0, v_mm=0):
    """Inversa de decode_dtd(): arma los 18 bytes de un DTD del bloque base."""
    hblank, vblank = hfp + hsw + hbp, vfp + vsw + vbp
    pclk_hz = (hact + hblank) * (vact + vblank) * rate
    pclk = round(pclk_hz / 10_000)
    if not 1 <= pclk <= 0xFFFF:
        raise ValueError(f"pixel clock {pclk_hz / 1e6:.3f} MHz fuera del campo EDID "
                         "(máximo 655.35 MHz)")
    for name, val, bits in (("h active", hact, 12), ("h blanking", hblank, 12),
                            ("v active", vact, 12), ("v blanking", vblank, 12),
                            ("h front porch", hfp, 10), ("h sync width", hsw, 10),
                            ("v front porch", vfp, 6), ("v sync width", vsw, 6)):
        if not 0 <= val < (1 << bits):
            raise ValueError(f"{name} = {val} no entra en los {bits} bits del DTD")
    d = bytearray(18)
    d[0], d[1] = pclk & 0xFF, pclk >> 8
    d[2], d[3] = hact & 0xFF, hblank & 0xFF
    d[4] = ((hact >> 8) & 0x0F) << 4 | ((hblank >> 8) & 0x0F)
    d[5], d[6] = vact & 0xFF, vblank & 0xFF
    d[7] = ((vact >> 8) & 0x0F) << 4 | ((vblank >> 8) & 0x0F)
    d[8], d[9] = hfp & 0xFF, hsw & 0xFF
    d[10] = ((vfp & 0x0F) << 4) | (vsw & 0x0F)
    d[11] = (((hfp >> 8) & 0x03) << 6 | ((hsw >> 8) & 0x03) << 4
             | ((vfp >> 4) & 0x03) << 2 | ((vsw >> 4) & 0x03))
    d[12], d[13] = h_mm & 0xFF, v_mm & 0xFF
    d[14] = ((h_mm >> 8) & 0x0F) << 4 | ((v_mm >> 8) & 0x0F)
    d[17] = 0x1E  # digital separate sync, +vsync, +hsync
    return bytes(d)


def decode_did_type1(d):
    """Descriptor Type I Detailed Timing de DisplayID 1.x (20 bytes)."""
    pclk = ((d[2] << 16) | (d[1] << 8) | d[0]) + 1
    hact = (d[5] << 8 | d[4]) + 1
    hblank = (d[7] << 8 | d[6]) + 1
    hfp_raw = d[9] << 8 | d[8]
    hsw = (d[11] << 8 | d[10]) + 1
    vact = (d[13] << 8 | d[12]) + 1
    vblank = (d[15] << 8 | d[14]) + 1
    vfp_raw = d[17] << 8 | d[16]
    vsw = (d[19] << 8 | d[18]) + 1
    hfp = (hfp_raw & 0x7FFF) + 1
    vfp = (vfp_raw & 0x7FFF) + 1
    return {
        "pclk": pclk * 10_000,
        "hact": hact, "hfp": hfp, "hsw": hsw, "hbp": hblank - hfp - hsw,
        "vact": vact, "vfp": vfp, "vsw": vsw, "vbp": vblank - vfp - vsw,
        "htotal": hact + hblank, "vtotal": vact + vblank,
        "hsync_pos": bool(hfp_raw & 0x8000), "vsync_pos": bool(vfp_raw & 0x8000),
        "preferred": bool(d[3] & 0x80), "interlaced": bool(d[3] & 0x10),
    }


def encode_did_type1(hact, hfp, hsw, hbp, vact, vfp, vsw, vbp, rate,
                      preferred=False, interlaced=False, extra_flags=0,
                      hsync_pos=True, vsync_pos=True):
    """Inversa de decode_did_type1(): arma los 20 bytes de un descriptor Type I.

    `extra_flags` deja pasar bits de byte 3 que no se decodifican (hay al menos uno seteado
    en los dos descriptores reales del G2, sin identificar) para no pisarlos sin querer.
    """
    hblank, vblank = hfp + hsw + hbp, vfp + vsw + vbp
    pclk_hz = (hact + hblank) * (vact + vblank) * rate
    pclk = round(pclk_hz / 10_000) - 1
    if not 0 <= pclk < (1 << 24):
        raise ValueError(f"pixel clock {pclk_hz / 1e6:.3f} MHz fuera del campo DisplayID "
                         "(máximo 167772.15 MHz)")
    for name, val, bits in (("h active", hact, 16), ("h blanking", hblank, 16),
                            ("v active", vact, 16), ("v blanking", vblank, 16),
                            ("h front porch", hfp, 15), ("h sync width", hsw, 16),
                            ("v front porch", vfp, 15), ("v sync width", vsw, 16)):
        if not 1 <= val <= (1 << bits):
            raise ValueError(f"{name} = {val} no entra en los {bits} bits del descriptor")
    d = bytearray(20)
    d[0], d[1], d[2] = pclk & 0xFF, (pclk >> 8) & 0xFF, (pclk >> 16) & 0xFF
    d[3] = (0x80 if preferred else 0) | (0x10 if interlaced else 0) | (extra_flags & 0x6F)
    hact_f, hblank_f = hact - 1, hblank - 1
    d[4], d[5] = hact_f & 0xFF, (hact_f >> 8) & 0xFF
    d[6], d[7] = hblank_f & 0xFF, (hblank_f >> 8) & 0xFF
    hfp_raw = (hfp - 1) | (0x8000 if hsync_pos else 0)
    d[8], d[9] = hfp_raw & 0xFF, (hfp_raw >> 8) & 0xFF
    hsw_f = hsw - 1
    d[10], d[11] = hsw_f & 0xFF, (hsw_f >> 8) & 0xFF
    vact_f, vblank_f = vact - 1, vblank - 1
    d[12], d[13] = vact_f & 0xFF, (vact_f >> 8) & 0xFF
    d[14], d[15] = vblank_f & 0xFF, (vblank_f >> 8) & 0xFF
    vfp_raw = (vfp - 1) | (0x8000 if vsync_pos else 0)
    d[16], d[17] = vfp_raw & 0xFF, (vfp_raw >> 8) & 0xFF
    vsw_f = vsw - 1
    d[18], d[19] = vsw_f & 0xFF, (vsw_f >> 8) & 0xFF
    return bytes(d)


def fix_displayid_checksum(block):
    """Corrige el checksum interno de la sección DisplayID (no el del bloque EDID de 128
    bytes, que sigue siendo fix_checksum()). La sección arranca en offset 1 y mide
    5 + section_bytes (offset 2), último byte de ese tramo es el checksum."""
    b = bytearray(block)
    span_end = 1 + 5 + b[2]
    b[span_end - 1] = (-sum(b[1:span_end - 1])) & 0xFF
    return bytes(b)


def fmt_timing(t, label):
    rate = t["pclk"] / (t["htotal"] * t["vtotal"])
    pol = ("+" if t["hsync_pos"] else "-") + "H " + ("+" if t["vsync_pos"] else "-") + "V"
    return (
        f"  {label}\n"
        f"    pixel clock : {t['pclk'] / 1e6:.2f} MHz\n"
        f"    horizontal  : {t['hact']} active + {t['hfp']} front + {t['hsw']} sync + "
        f"{t['hbp']} back = {t['htotal']} total\n"
        f"    vertical    : {t['vact']} active + {t['vfp']} front + {t['vsw']} sync + "
        f"{t['vbp']} back = {t['vtotal']} total\n"
        f"    sync        : {pol}\n"
        f"    refresh     : {rate:.3f} Hz\n"
    )


def decode(data):
    out = []
    bl = blocks(data)
    out.append(f"EDID: {len(data)} bytes, {len(bl)} block(s)\n")

    for i, b in enumerate(bl):
        ok = "ok" if (sum(b) & 0xFF) == 0 else f"BAD (0x{sum(b) & 0xFF:02x})"
        out.append(f"--- block {i} (tag 0x{b[0]:02x}) checksum {ok}")
        out.append(hexdump(b))
        out.append("")

    base = bl[0]
    vid = base[0x14]
    out.append("Video Input Definition (byte 0x14) = "
               f"0x{vid:02x}")
    if vid & 0x80:
        depth = (vid >> 4) & 0x07
        out.append(f"  bit 7      : 1 = digital input")
        out.append(f"  bits 6-4   : {depth:03b} = color bit depth {BPC_FIELD[depth]}"
                   + ("   <-- nothing declared" if depth == 0 else ""))
        out.append(f"  bits 3-0   : {vid & 0x0F:04b} = digital interface")
    else:
        out.append("  bit 7      : 0 = analog input")
    out.append("")

    out.append("Base block detailed timing descriptors")
    for n, off in enumerate((0x36, 0x48, 0x5A, 0x6C)):
        t = decode_dtd(base[off:off + 18])
        if t:
            out.append(fmt_timing(t, f"DTD #{n} (offset 0x{off:02x})"))
    out.append("")

    for i, b in enumerate(bl[1:], start=1):
        if b[0] == 0x02:
            out.append(f"Block {i}: CTA-861, revision {b[1]}")
            f3 = b[3]
            out.append(f"  byte 3 = 0x{f3:02x}")
            out.append(f"    native DTD count      : {f3 & 0x0F}")
            out.append(f"    YCbCr 4:2:2 supported : {bool(f3 & 0x10)}")
            out.append(f"    YCbCr 4:4:4 supported : {bool(f3 & 0x20)}")
            out.append(f"    basic audio           : {bool(f3 & 0x40)}")
            out.append(f"    underscan             : {bool(f3 & 0x80)}")
            out.append("")
        elif b[0] == 0x70:
            ver, rev = b[1] >> 4, b[1] & 0x0F
            out.append(f"Block {i}: DisplayID extension, version byte 0x{b[1]:02x} "
                       f"= DisplayID {ver}.{rev}")
            path = ("DisplayID 2.x parser" if (b[1] & 0xF0) == 0x20
                    else "DisplayID 1.3 parser (nvt_edid.c gates 2.x on (pExt[1] & 0xF0) == 0x20)")
            out.append(f"  nvidia nvt path : {path}")
            out.append(f"  section bytes   : {b[2]}")
            out.append(f"  extension count : {b[4]}")
            pos = 5
            while pos + 3 <= 127 and b[pos] != 0x00:
                tag, drev, dlen = b[pos], b[pos + 1], b[pos + 2]
                out.append(f"  data block tag 0x{tag:02x}, revision {drev}, "
                           f"payload {dlen} bytes")
                payload = b[pos + 3:pos + 3 + dlen]
                if tag == 0x03:
                    kind = "Type VII" if (b[1] & 0xF0) == 0x20 else "Type I"
                    out.append(f"    = {kind} Detailed Timing, "
                               f"{dlen // 20} descriptor(s) of 20 bytes")
                    out.append("")
                    for n in range(dlen // 20):
                        t = decode_did_type1(payload[n * 20:(n + 1) * 20])
                        pref = " [preferred]" if t.get("preferred") else ""
                        out.append(fmt_timing(t, f"descriptor #{n + 1}{pref}"))
                pos += 3 + dlen
            out.append("")
    return "\n".join(out)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    cmd, path = sys.argv[1], sys.argv[2]
    data = open(path, "rb").read()
    if len(data) % 128:
        print(f"aviso: {len(data)} bytes no es múltiplo de 128", file=sys.stderr)

    if cmd == "decode":
        print(decode(data))
        return 0

    if cmd == "set-bpc":
        bpc = int(sys.argv[3])
        if bpc not in BPC_TO_FIELD:
            print(f"bpc debe ser uno de {sorted(BPC_TO_FIELD)}", file=sys.stderr)
            return 1
        out_path = None
        if "-o" in sys.argv:
            out_path = sys.argv[sys.argv.index("-o") + 1]
        b = bytearray(data)
        old = b[0x14]
        if not old & 0x80:
            print("el EDID no es digital; no hay campo de color bit depth", file=sys.stderr)
            return 1
        b[0x14] = (old & 0x8F) | (BPC_TO_FIELD[bpc] << 4)
        b[:128] = fix_checksum(bytes(b[:128]))
        print(f"byte 0x14: 0x{old:02x} -> 0x{b[0x14]:02x}  (color bit depth -> {bpc} bpc)")
        print(f"byte 0x7f: 0x{data[127]:02x} -> 0x{b[127]:02x}  (checksum del bloque base)")
        if out_path:
            open(out_path, "wb").write(bytes(b))
            print(f"escrito: {out_path}")
        else:
            print("(sin -o no se escribe nada)")
        return 0

    if cmd == "inject-mode":
        rest = sys.argv[3:]
        out_path = None
        if "-o" in rest:
            i = rest.index("-o")
            out_path = rest[i + 1]
            rest = rest[:i] + rest[i + 2:]

        slots = [(n, 0x36 + n * 18) for n in range(4)]
        print("slots de DTD del bloque base")
        for n, off in slots:
            t = decode_dtd(data[off:off + 18])
            if t:
                rate = t["pclk"] / (t["htotal"] * t["vtotal"])
                what = (f"timing {t['hact']}x{t['vact']}@{rate:.2f} "
                        f"{t['pclk'] / 1e6:.2f} MHz vblank={t['vtotal'] - t['vact']}")
            elif data[off:off + 3] == b"\x00\x00\x00":
                what = ("LIBRE (dummy)" if data[off + 3] == 0x10
                        else f"descriptor tag 0x{data[off + 3]:02x}")
            else:
                what = "desconocido"
            print(f"  slot {n} (offset 0x{off:02x}): {what}")
        print()

        def describe_preset(name):
            p = resolve_preset(name)
            ht, vt = p[0] + p[1] + p[2] + p[3], p[4] + p[5] + p[6] + p[7]
            pclk = ht * vt * p[8]
            return (f"{p[0]}x{p[4]}@{p[8]} vblank={vt - p[4]:3d} "
                    f"{pclk / 1e6:7.2f} MHz  {pclk * 24 / 1e9:5.2f} Gbps @24bpp")

        if not rest:
            print("alias del factorial 2x2 (docs/16)")
            for name, target in MODE_PRESETS.items():
                print(f"  {name:5s} = {target:9s} {describe_preset(name)}")
            print("\nforma paramétrica BLANKING@RATE, para el barrido de refresh")
            print(f"  BLANKING: {', '.join(sorted(BLANKING))}   "
                  f"(vblank {BLANKING['SHORT'][1] + BLANKING['SHORT'][2] + BLANKING['SHORT'][3]}"
                  f" y {BLANKING['LONG'][1] + BLANKING['LONG'][2] + BLANKING['LONG'][3]})")
            for r in (65, 70, 72, 75, 80, 85):
                print(f"  SHORT@{r:<3d}  {describe_preset(f'SHORT@{r}')}")
            print("\nel bloque base tiene 4 slots y el 0 lleva el modo nativo, así que")
            print("entran 3 por EDID: el barrido se hace bisectando, no de una sola vez.")
            print("\nasignaciones PRESET:SLOT, por ejemplo:")
            print("  ./scripts/edid-tool.py inject-mode hmd.edid -o test.bin CTRL:1 A:2 B:3")
            print("  ./scripts/edid-tool.py inject-mode hmd.edid -o sweep.bin \\")
            print("      SHORT@70:1 SHORT@75:2 SHORT@80:3")
            return 0

        b = bytearray(data)
        for spec in rest:
            if ":" not in spec:
                print(f"asignación inválida '{spec}', se espera PRESET:SLOT", file=sys.stderr)
                return 1
            name, _, slot_s = spec.rpartition(":")
            try:
                preset = resolve_preset(name)
            except ValueError as e:
                print(e, file=sys.stderr)
                return 1
            slot = int(slot_s)
            if not 0 <= slot <= 3:
                print(f"slot {slot} fuera de rango (0-3)", file=sys.stderr)
                return 1
            off = 0x36 + slot * 18
            old = decode_dtd(b[off:off + 18])
            h_mm = ((b[off + 14] >> 4) & 0x0F) << 8 | b[off + 12]
            v_mm = (b[off + 14] & 0x0F) << 8 | b[off + 13]
            if old:
                print(f"aviso: el slot {slot} tenía un timing y se reemplaza", file=sys.stderr)
            try:
                b[off:off + 18] = encode_dtd(*preset, h_mm=h_mm, v_mm=v_mm)
            except ValueError as e:
                print(f"preset {name}: {e}", file=sys.stderr)
                return 1
            t = decode_dtd(b[off:off + 18])
            want = preset
            got = (t["hact"], t["hfp"], t["hsw"], t["hbp"],
                   t["vact"], t["vfp"], t["vsw"], t["vbp"])
            if got != want[:8]:
                print(f"round-trip falló en {name}: {want[:8]} != {got}", file=sys.stderr)
                return 1
            print(fmt_timing(t, f"{name} -> slot {slot} (offset 0x{off:02x})"))

        b[:128] = fix_checksum(bytes(b[:128]))
        print(f"checksum del bloque base: 0x{data[127]:02x} -> 0x{b[127]:02x}")
        if (sum(b[:128]) & 0xFF) != 0:
            print("checksum del bloque base quedó mal", file=sys.stderr)
            return 1
        if bytes(b[128:]) != data[128:]:
            print("las extensiones cambiaron y no deberían", file=sys.stderr)
            return 1
        print("bloques de extensión intactos, checksums ok")

        if out_path:
            open(out_path, "wb").write(bytes(b))
            print(f"escrito: {out_path}  ({len(b)} bytes)")
        else:
            print("(sin -o no se escribe nada)")
        return 0

    if cmd == "inject-did":
        rest = sys.argv[3:]
        out_path = None
        if "-o" in rest:
            i = rest.index("-o")
            out_path = rest[i + 1]
            rest = rest[:i] + rest[i + 2:]

        bl = blocks(data)
        ext_idx = next((i for i, b in enumerate(bl) if i > 0 and b[0] == 0x70), None)
        if ext_idx is None:
            print("no encontré un bloque de extensión DisplayID (tag 0x70)", file=sys.stderr)
            return 1
        ext = bytearray(bl[ext_idx])

        pos, tag_pos = 5, None
        while pos + 3 <= 127 and ext[pos] != 0x00:
            tag, dlen = ext[pos], ext[pos + 2]
            if tag == 0x03:
                tag_pos = pos
                break
            pos += 3 + dlen
        if tag_pos is None:
            print("no encontré un data block Type I/VII (tag 0x03) en la extensión",
                  file=sys.stderr)
            return 1
        dlen = ext[tag_pos + 2]
        ndesc = dlen // 20
        payload_off = tag_pos + 3

        print(f"descriptores Type I en el bloque {ext_idx} (offset base 0x{payload_off:02x}, "
              f"{ndesc} de 20 bytes)")
        for n in range(ndesc):
            off = payload_off + n * 20
            t = decode_did_type1(ext[off:off + 20])
            rate = t["pclk"] / (t["htotal"] * t["vtotal"])
            print(f"  descriptor #{n + 1} (offset 0x{off:02x}): {t['hact']}x{t['vact']}@"
                  f"{rate:.2f} {t['pclk'] / 1e6:.2f} MHz vblank={t['vtotal'] - t['vact']}")
        print()

        def describe_did_preset(name):
            p = resolve_did_preset(name)
            ht, vt = p[0] + p[1] + p[2] + p[3], p[4] + p[5] + p[6] + p[7]
            pclk = ht * vt * p[8]
            return (f"{p[0]}x{p[4]}@{p[8]} vblank={vt - p[4]:3d} "
                    f"{pclk / 1e6:7.2f} MHz  {pclk * 24 / 1e9:5.2f} Gbps @24bpp")

        if not rest:
            print("alias del factorial a 4320x2160 (docs/16)")
            for name in DID_PRESETS:
                print(f"  {name:7s} {describe_did_preset(name)}")
            print("\nforma paramétrica VBLANK@RATE, para puntos intermedios, ej. 240@90")
            print(f"\nsólo hay {ndesc} descriptores en este EDID -- asignaciones PRESET:DESCRIPTOR")
            print("  ./scripts/edid-tool.py inject-did hmd.edid -o test.bin B4K:1")
            return 0

        for spec in rest:
            if ":" not in spec:
                print(f"asignación inválida '{spec}', se espera PRESET:DESCRIPTOR",
                      file=sys.stderr)
                return 1
            name, _, slot_s = spec.rpartition(":")
            try:
                preset = resolve_did_preset(name)
            except ValueError as e:
                print(e, file=sys.stderr)
                return 1
            slot = int(slot_s)
            if not 1 <= slot <= ndesc:
                print(f"descriptor {slot} fuera de rango (1-{ndesc})", file=sys.stderr)
                return 1
            off = payload_off + (slot - 1) * 20
            old = decode_did_type1(ext[off:off + 20])
            old_d3 = ext[off + 3]
            print(f"aviso: el descriptor {slot} tenía {old['hact']}x{old['vact']} "
                  f"vblank={old['vtotal'] - old['vact']} y se reemplaza", file=sys.stderr)
            try:
                ext[off:off + 20] = encode_did_type1(
                    *preset, preferred=bool(old_d3 & 0x80), interlaced=bool(old_d3 & 0x10),
                    extra_flags=old_d3, hsync_pos=old["hsync_pos"], vsync_pos=old["vsync_pos"])
            except ValueError as e:
                print(f"preset {name}: {e}", file=sys.stderr)
                return 1
            t = decode_did_type1(ext[off:off + 20])
            want = preset
            got = (t["hact"], t["hfp"], t["hsw"], t["hbp"],
                   t["vact"], t["vfp"], t["vsw"], t["vbp"])
            if got != want[:8]:
                print(f"round-trip falló en {name}: {want[:8]} != {got}", file=sys.stderr)
                return 1
            print(fmt_timing(t, f"{name} -> descriptor {slot} (offset 0x{off:02x})"))

        old_did_cs, old_blk_cs = ext[126], ext[127]
        ext = bytearray(fix_displayid_checksum(bytes(ext)))
        ext = bytearray(fix_checksum(bytes(ext)))
        print(f"checksum sección DisplayID (byte 0x7e): 0x{old_did_cs:02x} -> 0x{ext[126]:02x}")
        print(f"checksum bloque de extensión (byte 0x7f): 0x{old_blk_cs:02x} -> 0x{ext[127]:02x}")
        if (sum(ext) & 0xFF) != 0:
            print("checksum del bloque de extensión quedó mal", file=sys.stderr)
            return 1

        out = bytearray(data)
        out[ext_idx * 128:(ext_idx + 1) * 128] = ext
        untouched = bytes(out[:ext_idx * 128]) + bytes(out[(ext_idx + 1) * 128:])
        untouched_orig = bytes(data[:ext_idx * 128]) + bytes(data[(ext_idx + 1) * 128:])
        if untouched != untouched_orig:
            print("otros bloques cambiaron y no deberían", file=sys.stderr)
            return 1
        print("resto de los bloques intacto")

        if out_path:
            open(out_path, "wb").write(bytes(out))
            print(f"escrito: {out_path}  ({len(out)} bytes)")
        else:
            print("(sin -o no se escribe nada)")
        return 0

    print(f"comando desconocido: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
