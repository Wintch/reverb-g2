#!/usr/bin/env python3
"""Ubica strings en un PE y busca quien los referencia en el desensamblado de objdump.

objdump imprime los lea rip-relativos ya resueltos, con la VA destino en el operando,
asi que alcanza con matchear la VA en texto. Sin capstone ni pefile.
"""
import re, subprocess, sys

DLL, ASM = sys.argv[1], sys.argv[2]
NEEDLES = sys.argv[3:]

# secciones: (fileoff, vma, size) leidas de objdump -h
secs = []
for line in subprocess.run(["objdump","-h",DLL],capture_output=True,text=True).stdout.splitlines():
    m = re.match(r"\s*\d+\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+[0-9a-f]+\s+([0-9a-f]+)", line)
    if m:
        secs.append((m.group(1), int(m.group(4),16), int(m.group(2),16), int(m.group(3),16)))

def off2va(off):
    for name, fo, size, vma in secs:
        if fo <= off < fo + size:
            return vma + (off - fo)
    return None

# strings con offset de archivo
out = subprocess.run(["strings","-t","x","-n","4",DLL],capture_output=True,text=True).stdout
hits = {}
for line in out.splitlines():
    off_s, _, text = line.strip().partition(" ")
    text = text.strip()
    for n in NEEDLES:
        if n.lower() in text.lower():
            va = off2va(int(off_s,16))
            if va: hits[va] = text

if not hits:
    print("  (ningun string matcheo)"); sys.exit(0)

asm = open(ASM, errors="replace").read().splitlines()
# indice: linea -> funcion contenedora
func, funcs = "?", []
for i,l in enumerate(asm):
    m = re.match(r"^([0-9a-f]+) <(.+)>:", l)
    if m: func = m.group(2)
    funcs.append(func)

for va, text in sorted(hits.items()):
    pat = f"{va:x}"
    refs = [(i,asm[i]) for i,l in enumerate(asm) if pat in l and ("lea" in l or "mov" in l)]
    print(f"\n=== 0x{va:x}  {text!r}")
    if not refs: print("   (sin xrefs directas)")
    for i,l in refs[:6]:
        print(f"   {funcs[i]:<30} | {l.strip()}")
