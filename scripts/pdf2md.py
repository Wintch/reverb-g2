#!/usr/bin/env python3
"""Convierte un PDF a markdown y saca sus imagenes. Sin dependencias.

Hecho para los expedientes de la FCC: son PDFs escaneados, o sea imagenes sin capa de
texto. Extraer "el texto" no alcanza — hay que sacar las IMAGENES para poder mirarlas.

  ./pdf2md.py archivo.pdf [directorio-de-salida]

Produce:
  <salida>/<nombre>.md        texto extraido (vacio si es puro escaneo) + inventario
  <salida>/<nombre>-NNN.jpg   cada imagen embebida, en orden

Formatos de imagen que saca directo: DCTDecode (JPEG) y JPXDecode (JPEG2000), porque el
stream ya ES el archivo. Los CCITTFax y los bitmaps crudos se reportan pero no se
convierten: para eso haria falta un decodificador, y los escaneos de la FCC suelen ser JPEG.
"""
import os
import re
import sys
import zlib

TEXT_OPS = re.compile(rb"\((?:[^()\\]|\\.)*\)\s*Tj|\[(?:[^\[\]\\]|\\.)*\]\s*TJ")
STR_IN = re.compile(rb"\((?:[^()\\]|\\.)*\)")


def png_encode(w, h, channels, raw):
    """Arma un PNG a mano desde pixeles crudos. Sin PIL: el sistema no la tiene."""
    import struct
    color = {1: 0, 3: 2, 4: 6}.get(channels)
    if color is None:
        return None
    stride = w * channels
    if len(raw) < stride * h:
        return None
    # PNG exige un byte de filtro por fila (0 = sin filtro)
    body = b"".join(b"\x00" + raw[y * stride:(y + 1) * stride] for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, color, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(body, 6))
            + chunk(b"IEND", b""))


def img_geometry(d):
    """Saca ancho, alto, bits y canales del diccionario del XObject."""
    def num(key):
        m = re.search(rb"/" + key + rb"\s+(\d+)", d)
        return int(m.group(1)) if m else None
    w, h = num(b"Width"), num(b"Height")
    bpc = num(b"BitsPerComponent") or 8
    if b"/DeviceRGB" in d:
        ch = 3
    elif b"/DeviceCMYK" in d:
        ch = 4
    elif b"/DeviceGray" in d or b"/CalGray" in d:
        ch = 1
    else:
        ch = None
    return w, h, bpc, ch


def unescape(s):
    s = s[1:-1]
    s = s.replace(rb"\(", b"(").replace(rb"\)", b")").replace(rb"\\", b"\\")
    s = re.sub(rb"\\[0-7]{1,3}", lambda m: bytes([int(m.group(0)[1:], 8) & 0xFF]), s)
    return s


def objects(data):
    """Devuelve (dict_crudo, contenido_del_stream) por cada objeto con stream."""
    out = []
    for m in re.finditer(rb"stream\r?\n", data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        head = data[max(0, m.start() - 2000):m.start()]
        i = head.rfind(b"<<")
        d = head[i:] if i >= 0 else head
        out.append((d, data[start:end].rstrip(b"\r\n")))
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(outdir, exist_ok=True)
    name = os.path.splitext(os.path.basename(path))[0]
    data = open(path, "rb").read()
    print(f"  {path}: {len(data)/1024/1024:.1f} MB")

    texts, images, otros = [], [], []
    for d, raw in objects(data):
        if b"/DCTDecode" in d:
            images.append(("jpg", raw))
        elif b"/JPXDecode" in d:
            images.append(("jp2", raw))
        elif b"/FlateDecode" in d:
            try:
                dec = zlib.decompress(raw)
            except zlib.error:
                continue
            if b"/Image" in d or b"/Subtype /Image" in d:
                # Imagen cruda comprimida con Flate: la reconstruimos como PNG a mano.
                w, h, bpc, ch = img_geometry(d)
                png = png_encode(w, h, ch, dec) if (w and h and ch and bpc == 8) else None
                if png:
                    images.append(("png", png))
                else:
                    otros.append((f"flate-raw {w}x{h} bpc={bpc} ch={ch}", len(dec), d[:180]))
                continue
            chunks = []
            for t in TEXT_OPS.finditer(dec):
                for s in STR_IN.finditer(t.group(0)):
                    chunks.append(unescape(s.group(0)).decode("latin-1"))
            if chunks:
                texts.append("".join(chunks))
        elif b"/CCITTFaxDecode" in d:
            otros.append(("ccittfax", len(raw), d[:180]))

    for i, (ext, raw) in enumerate(images, 1):
        p = os.path.join(outdir, f"{name}-{i:03d}.{ext}")
        open(p, "wb").write(raw)
        print(f"    imagen -> {p}  ({len(raw)/1024:.0f} KB)")

    md = [f"# {name}", "", f"Origen: `{path}`", ""]
    if texts:
        md += ["## Texto extraido", ""] + texts + [""]
    else:
        md += ["## Texto extraido", "",
               "**(ninguno: el PDF no tiene capa de texto, es un escaneo)**", ""]
    md += ["## Inventario", "",
           f"- imagenes extraidas: **{len(images)}**",
           f"- objetos de imagen no convertidos: {len(otros)}", ""]
    for kind, size, head in otros[:10]:
        md.append(f"  - `{kind}` {size} bytes — `{head.decode('latin-1', 'replace')[:120]}`")
    if not texts and not images:
        md += ["", "> No salio nada. Puede ser un PDF con xref comprimido (object streams).",
               "> En ese caso conviene abrirlo con un visor y sacar captura de pantalla."]

    mdp = os.path.join(outdir, f"{name}.md")
    open(mdp, "w").write("\n".join(md))
    print(f"    markdown -> {mdp}")
    print(f"    resumen: {len(texts)} bloques de texto, {len(images)} imagenes, "
          f"{len(otros)} objetos sin convertir")


main()
