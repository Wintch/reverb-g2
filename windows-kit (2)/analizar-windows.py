#!/usr/bin/env python3
"""Analiza la captura de Windows y la diffea contra lo medido en Linux.

Se corre DE VUELTA EN LINUX, sobre el .tsv que produce capturar.bat.

Busca los dos canales que descubrimos el 2026-08-04:

  0x05  DEVICE_STATUS  del companion 03f0:0580, 33 bytes.
        byte 5      refresh en decimal      (confirmado: 0x3c=60, 0x5a=90)
        bytes 19-20 htotal little-endian    (confirmado contra el EDID)
        bytes 21-22 vtotal little-endian    (confirmado contra el EDID)
        bytes 9,10,12,14,15,24-31           DESCONOCIDOS  <-- el objetivo

  0x03  LOG DE FIRMWARE del HoloLens Sensors 045e:0659, 509 bytes, ASCII.
        formato: magic "Dlo+" | 4B ts | 2B seq | 1B nivel | texto

  ./analizar-windows.py windows-90hz.tsv [windows-60hz.tsv]
"""
import re, sys

REF_LINUX = {
    "60Hz ANDA  (Linux)": "05 00 01 01 00 3c 00 00 00 05 2c 1e 02 00 77 00 00 00 06 44 11 72 0a 01 00 80 00 80 ff ff ff ff 02",
    "90Hz FALLA (Linux, 2880x1440)": "05 00 01 01 00 5a 00 00 00 0c 1a 14 02 00 77 00 00 00 06 a4 0b 3e 06 01 00 80 00 80 ff ff ff ff 02",
    "90Hz FALLA (Linux, 4320x2160)": "05 00 01 01 00 5a 00 00 00 09 38 14 04 00 77 77 00 00 06 44 11 e4 08 01 00 80 00 80 00 80 00 80 02",
}


def parse_tsv(path):
    """Devuelve (status, fwlog): listas de bytes de cada canal."""
    status, fwlog = [], []
    for line in open(path, errors="replace"):
        cols = line.rstrip("\n").split("\t")
        if not cols:
            continue
        data = cols[-1].strip()
        if not data:
            continue
        try:
            b = bytes.fromhex(data.replace(":", ""))
        except ValueError:
            continue
        if not b:
            continue
        if b[0] == 0x05 and len(b) >= 23:
            status.append(b)
        elif b[0] == 0x03 and len(b) > 64:
            fwlog.append(b)
    return status, fwlog


def show_status(b):
    ht = b[19] | (b[20] << 8)
    vt = b[21] | (b[22] << 8)
    return (f"refresh={b[5]:<4} htotal={ht:<6} vtotal={vt:<6} "
            f"b1={b[1]} b9={b[9]:02x} b10={b[10]:02x} b12={b[12]:02x} "
            f"b14={b[14]:02x} b15={b[15]:02x}")


def fw_entries(buf):
    out = []
    for m in re.finditer(re.escape(b"Dlo+"), buf):
        p = m.end()
        if p + 7 > len(buf):
            continue
        seq = int.from_bytes(buf[p + 4:p + 6], "little")
        body = buf[p + 7:]
        end = body.find(b"\x00")
        txt = (body[:end] if end >= 0 else body).decode("ascii", "replace").strip()
        if txt:
            out.append((seq, txt))
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for path in sys.argv[1:]:
        print(f"\n{'='*78}\n  {path}\n{'='*78}")
        status, fwlog = parse_tsv(path)
        print(f"  DEVICE_STATUS (0x05): {len(status)}   LOG DE FIRMWARE (0x03): {len(fwlog)}")

        if status:
            print("\n  --- estados de panel vistos en Windows ---")
            seen = set()
            for b in status:
                h = b.hex(" ")
                if h in seen:
                    continue
                seen.add(h)
                print(f"    {show_status(b)}")
                print(f"      {h}")

        if fwlog:
            print("\n  --- log de firmware ---")
            seen = set()
            for b in fwlog:
                for seq, txt in fw_entries(b):
                    if (seq, txt) in seen:
                        continue
                    seen.add((seq, txt))
                    mark = "!!" if re.search(r"error|fail|err", txt, re.I) else "  "
                    print(f"    {mark} seq={seq:<7} {txt}")

    print(f"\n{'='*78}\n  REFERENCIA: lo medido en Linux\n{'='*78}")
    for k, v in REF_LINUX.items():
        print(f"  {k}\n    {v}")
    print("""
  QUE MIRAR:
  Si Windows a 90Hz (con el panel ENCENDIDO) muestra bytes 9/10/12/14/15/24-31
  distintos a los del "90Hz FALLA (Linux)", esos bytes son la diferencia y ahi
  esta la causa. Si son identicos, el casco esta en el mismo estado en los dos
  sistemas y hay que buscar en otra capa.
""")


main()
