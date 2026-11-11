#!/usr/bin/env python3
"""Locates strings in a PE and finds who references them in the objdump disassembly.

objdump prints rip-relative leas already resolved, with the target VA in the operand,
so it's enough to match the VA in text. No capstone or pefile.
"""
import re, subprocess, sys

DLL, ASM = sys.argv[1], sys.argv[2]
NEEDLES = sys.argv[3:]

# sections: (fileoff, vma, size) read from objdump -h
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

# strings with file offset
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
    print("  (no string matched)"); sys.exit(0)

asm = open(ASM, errors="replace").read().splitlines()
# index: line -> containing function
func, funcs = "?", []
for i,l in enumerate(asm):
    m = re.match(r"^([0-9a-f]+) <(.+)>:", l)
    if m: func = m.group(2)
    funcs.append(func)

for va, text in sorted(hits.items()):
    pat = f"{va:x}"
    refs = [(i,asm[i]) for i,l in enumerate(asm) if pat in l and ("lea" in l or "mov" in l)]
    print(f"\n=== 0x{va:x}  {text!r}")
    if not refs: print("   (no direct xrefs)")
    for i,l in refs[:6]:
        print(f"   {funcs[i]:<30} | {l.strip()}")
