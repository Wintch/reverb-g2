#!/usr/bin/env python3
"""
Analiza y diffea capturas HID del companion del Reverb G2 (03f0:0580).

Objetivo: encontrar qué comando manda Windows para poner el panel a 90Hz y Monado no.
Medido en Linux el 2026-08-04: Monado manda EXACTAMENTE lo mismo a 60Hz (el panel
enciende) y a 90Hz (no enciende) — ver cap. 04. Falta el lado de Windows.

Lee dos formatos, para que el diff Linux <-> Windows sea homogéneo:

  usbmon (Linux)    scripts/capture-hid.sh produce esto directamente.
  tsv    (Windows)  exportado con tshark desde el .pcapng de USBPcap; el comando exacto
                    (con TODOS los campos que hacen falta) está en docs/07.

Lo que importa de verdad son las transferencias de control de clase HID:

  SET_REPORT  bmRequestType=0x21 bRequest=0x09   host -> casco   (los comandos)
  GET_REPORT  bmRequestType=0xa1 bRequest=0x01   casco -> host

y en las dos, wValue = (tipo << 8) | report_id, con tipo 1=Input 2=Output 3=Feature.

El resto del tráfico del bus (enumeración, descriptores de string, hubs, audio) se
descarta: el companion se detecta solo, por su descriptor de dispositivo.

Uso:
  ./analyze-hid.py resumen  ~/vr/hid-mode2.txt
  ./analyze-hid.py diff     ~/vr/hid-mode2.txt ~/vr/hid-mode1.txt
  ./analyze-hid.py diff     ~/vr/hid-mode1.txt windows-90hz.tsv
"""

import argparse
import re
import sys
from collections import Counter

VID, PID = 0x03F0, 0x0580

# Reportes que Monado manda hoy (wmr_hmd.c). Lo que NO esté acá es candidato a ser
# el comando que nos falta.
KNOWN = {
    0x50: "loop (activacion)",
    0x09: "data_1 (activacion)",
    0x08: "data_2 (activacion)",
    0x06: "data_3 (activacion)",
    0x04: "screen on/off",
    0x02: "proximidad/IPD (telemetria)",
}
RTYPE = {1: "Input", 2: "Output", 3: "Feature"}

# ffff8c00587106c0 2027666441 S Co:3:079:0 s 21 09 0350 0000 0040 64 = 50010000 ...
USBMON_RE = re.compile(
    r"^\S+\s+(\d+)\s+([SCE])\s+([CZIB])([io]):(\d+):(\d+):(\d+)\s+(.*)$"
)
SETUP_RE = re.compile(
    r"^s\s+([0-9a-f]{2})\s+([0-9a-f]{2})\s+([0-9a-f]{4})\s+([0-9a-f]{4})\s+([0-9a-f]{4})"
)


class Xfer:
    """Una transferencia de control de clase HID, normalizada."""

    def __init__(self, t, req_type, request, wvalue, data):
        self.t = t
        self.req_type = req_type
        self.request = request
        self.report_type = (wvalue >> 8) & 0xFF
        self.report_id = wvalue & 0xFF
        self.data = data

    @property
    def kind(self):
        if self.req_type == 0x21 and self.request == 0x09:
            return "SET_REPORT"
        if self.req_type == 0xA1 and self.request == 0x01:
            return "GET_REPORT"
        return f"otro(bmRequestType=0x{self.req_type:02x},bRequest=0x{self.request:02x})"

    def signature(self):
        # Los timestamps y el padding de ceros se ignoran: importa QUE se mando.
        return (self.kind, self.report_type, self.report_id, self.data[:16].rstrip("0"))


def find_companion(path):
    """Busca el device address del companion por su descriptor de dispositivo.

    El descriptor trae idVendor/idProduct en little endian en los bytes 8..11, que en
    el volcado hex de usbmon caen como 'f0038005'. El device address cambia en cada
    re-enumeración (y el G2 se re-enumera todo el tiempo, cap. 06), así que hardcodearlo
    no sirve.
    """
    want = f"{VID & 0xFF:02x}{VID >> 8:02x}{PID & 0xFF:02x}{PID >> 8:02x}"
    found = set()
    with open(path, errors="replace") as fh:
        for line in fh:
            if want not in line.replace(" ", "").lower():
                continue
            m = USBMON_RE.match(line.strip())
            if m and m.group(6) != "000":
                found.add(int(m.group(6)))
    return found


def parse_usbmon(path, device=None):
    if device is None:
        cands = find_companion(path)
        if len(cands) == 1:
            device = cands.pop()
        elif len(cands) > 1:
            # Se re-enumeró durante la captura: nos quedamos con el que realmente
            # recibió comandos, no con el primero que aparezca.
            device = pick_active(path, cands)
        # Si no aparece ningún descriptor, caemos a "cualquier device con HID de clase".

    out = []
    with open(path, errors="replace") as fh:
        for line in fh:
            m = USBMON_RE.match(line.strip())
            if not m:
                continue
            ts, event, ttype, direction, bus, dev, ep, rest = m.groups()
            if ttype != "C":  # sólo transferencias de control
                continue
            if device is not None and int(dev) != device:
                continue
            sm = SETUP_RE.match(rest)
            if not sm:
                continue  # es el callback; el setup viaja en el submit
            req_type, request, wvalue, _widx, _wlen = sm.groups()
            data = ""
            if "=" in rest:
                data = "".join(rest.split("=", 1)[1].split()).lower()
            x = Xfer(int(ts), int(req_type, 16), int(request, 16), int(wvalue, 16), data)
            if x.kind.startswith("otro"):
                continue  # descriptores, SET_ADDRESS, etc.
            out.append(x)
    return out, device


def pick_active(path, cands):
    counts = Counter()
    with open(path, errors="replace") as fh:
        for line in fh:
            m = USBMON_RE.match(line.strip())
            if m and int(m.group(6)) in cands and SETUP_RE.match(m.group(8)):
                counts[int(m.group(6))] += 1
    return counts.most_common(1)[0][0] if counts else sorted(cands)[0]


def parse_tsv(path, device=None):
    """TSV de tshark. Columnas, en este orden (ver docs/07):
    time_relative, device_address, bmRequestType, bRequest, wValue, capdata
    """
    out = []
    with open(path, errors="replace") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) < 5:
                continue
            try:
                t = int(float(p[0]) * 1_000_000)
                dev = int(p[1]) if p[1].strip() else None
                req_type = int(p[2], 0) if p[2].strip() else 0
                request = int(p[3], 0) if p[3].strip() else 0
                wvalue = int(p[4], 0) if p[4].strip() else 0
            except ValueError:
                continue  # fila de encabezado o campo vacío
            if device is not None and dev != device:
                continue
            data = p[5].replace(":", "").replace(" ", "").lower() if len(p) > 5 else ""
            x = Xfer(t, req_type, request, wvalue, data)
            if x.kind.startswith("otro"):
                continue
            out.append(x)
    return out, device


def load(path, fmt, device=None):
    if fmt == "auto":
        fmt = "tsv" if path.endswith((".tsv", ".csv")) else "usbmon"
    dev = int(device) if device else None
    return (parse_usbmon if fmt == "usbmon" else parse_tsv)(path, dev)


def fmt_sig(sig, count=None):
    kind, rtype, rid, data = sig
    arrow = "->" if kind == "SET_REPORT" else "<-"
    note = KNOWN.get(rid, "")
    note = f"  [{note}]" if note else "  [DESCONOCIDO]"
    c = f"  x{count}" if count and count > 1 else ""
    t = RTYPE.get(rtype, f"tipo{rtype}")
    return f"  {kind:10s} {arrow} {t:7s} report 0x{rid:02x}  data={data or '(vacio)'}{c}{note}"


def cmd_resumen(args):
    recs, dev = load(args.file, args.format, args.device)
    print(f"{args.file}")
    print(f"companion detectado: device {dev if dev is not None else '(sin filtrar)'}")
    if not recs:
        print("\nSin transferencias HID de clase. Si el companion se re-enumeró en pleno\n"
              "arranque, la captura puede no servir: fijate que haya un SET_REPORT 0x50.",
              file=sys.stderr)
        return 1
    print(f"{len(recs)} transferencias HID de clase\n")
    counts = Counter(r.signature() for r in recs)
    seen = []
    for r in recs:
        if r.signature() not in seen:
            seen.append(r.signature())
    for s in seen:
        print(fmt_sig(s, counts[s]))
    sets = sum(1 for r in recs if r.kind == "SET_REPORT")
    print(f"\nSET_REPORT (host->casco): {sets}   GET_REPORT: {len(recs) - sets}")
    return 0


def cmd_diff(args):
    a, da = load(args.file_a, args.format_a, args.device_a)
    b, db = load(args.file_b, args.format_b, args.device_b)
    print(f"A = {args.file_a}  (device {da}, {len(a)} transferencias HID)")
    print(f"B = {args.file_b}  (device {db}, {len(b)} transferencias HID)\n")
    if not a or not b:
        print("Alguna de las dos capturas no tiene trafico HID utilizable.", file=sys.stderr)
        return 1

    sa, sb = Counter(x.signature() for x in a), Counter(x.signature() for x in b)

    print("=" * 72)
    print("EN B PERO NO EN A  <-- si B es 90Hz y A es 60Hz, ACA esta la respuesta")
    print("=" * 72)
    only_b = [s for s in sb if s not in sa]
    print("\n".join(fmt_sig(s, sb[s]) for s in only_b) if only_b
          else "  (nada: B no manda ningun comando que A no mande)")

    print("\n" + "=" * 72)
    print("EN A PERO NO EN B")
    print("=" * 72)
    only_a = [s for s in sa if s not in sb]
    print("\n".join(fmt_sig(s, sa[s]) for s in only_a) if only_a else "  (nada)")

    print("\n" + "=" * 72)
    print("MISMO COMANDO, DISTINTA CANTIDAD")
    print("=" * 72)
    diffs = [s for s in sa if s in sb and sa[s] != sb[s]]
    print("\n".join(f"{fmt_sig(s)}   A x{sa[s]}  B x{sb[s]}" for s in diffs)
          if diffs else "  (nada)")

    ia = {x.report_id for x in a if x.kind == "SET_REPORT"}
    ib = {x.report_id for x in b if x.kind == "SET_REPORT"}
    print("\nReport IDs enviados al casco (SET_REPORT):")
    print(f"  A: {sorted('0x%02x' % i for i in ia)}")
    print(f"  B: {sorted('0x%02x' % i for i in ib)}")
    if ib - ia:
        print(f"  >>> SOLO EN B: {sorted('0x%02x' % i for i in ib - ia)}")
    elif not only_b:
        print("  >>> Las dos capturas mandan lo mismo.")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resumen", help="lista los comandos HID de una captura")
    r.add_argument("file")
    r.add_argument("--format", choices=["auto", "usbmon", "tsv"], default="auto")
    r.add_argument("--device", help="forzar device address (normalmente se detecta solo)")
    r.set_defaults(func=cmd_resumen)

    d = sub.add_parser("diff", help="compara dos capturas")
    d.add_argument("file_a")
    d.add_argument("file_b")
    d.add_argument("--format-a", choices=["auto", "usbmon", "tsv"], default="auto")
    d.add_argument("--format-b", choices=["auto", "usbmon", "tsv"], default="auto")
    d.add_argument("--device-a")
    d.add_argument("--device-b")
    d.set_defaults(func=cmd_diff)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
