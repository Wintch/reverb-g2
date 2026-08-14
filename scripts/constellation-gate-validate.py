#!/usr/bin/env python3
"""Validate the gravity gate: published-position scatter per hand on a static capture.

Usage: constellation-gate-validate.py <capture-slice.log>
Compares against T179's pre-gate numbers (32 mm median / 126 mm p90 on the clean
cluster, plus a 193/321 mm mixed cluster). Born 2026-08-13 (T181), reads monado
0047's INFO telemetry. Blind to: hand attribution is adjacent-line pairing; only
every 15th solve is logged; a pure-yaw ghost shows a CLEAN gravity mismatch here —
the scatter/steps columns are what expose it.
"""
import re, math, sys

def qconj(q): x,y,z,w=q; return (-x,-y,-z,w)
def qmul(a,b):
    ax,ay,az,aw=a; bx,by,bz,bw=b
    return (aw*bx+ax*bw+ay*bz-az*by, aw*by-ax*bz+ay*bw+az*bx,
            aw*bz+ax*by-ay*bx+az*bw, aw*bw-ax*bx-ay*by-az*bz)
def qnorm(q):
    n=math.sqrt(sum(c*c for c in q)) or 1.0
    q=tuple(c/n for c in q)
    return tuple(-c for c in q) if q[3]<0 else q
def rot(q,v):
    p=(v[0],v[1],v[2],0.0)
    return qmul(qmul(q,p),qconj(q))[:3]
def vang(a,b):
    d=sum(x*y for x,y in zip(a,b))
    return math.degrees(math.acos(max(-1,min(1,d))))

grav_re=re.compile(r'\[HP Reverb G2 (Left|Right) Controller\].*q_solve=\((-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)\) q_imu=\((-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)\)')
samp_re=re.compile(r'constellation sample #\d+: pos=\((-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\) matched_blobs=(\d+) visible_leds=(\d+) reproj_err_px=([\d.]+)')
drop_re=re.compile(r'gravity gate: dropped wrong-lobe sample, ([\d.]+) deg .* (\d+) dropped so far')

recs=[]; pend=None; gap=0; drops=[]
for l in open(sys.argv[1],errors='replace'):
    m=drop_re.search(l)
    if m: drops.append((float(m.group(1)),int(m.group(2))))
    m=grav_re.search(l)
    if m:
        g=m.groups()
        pend=dict(hand=g[0].lower(), qs=qnorm(tuple(float(x) for x in g[1:5])),
                  qi=qnorm(tuple(float(x) for x in g[5:9]))); gap=0; continue
    if pend:
        gap+=1
        m=samp_re.search(l)
        if m:
            x,y,z,b,vl,e=m.groups()
            pend.update(pos=(float(x),float(y),float(z)),blobs=int(b),err=float(e))
            recs.append(pend); pend=None
        elif gap>6: pend=None

print(f'{len(recs)} accepted samples paired; {len(drops)} gate-drop log lines in window')
if drops:
    print(f'  drop mismatch values seen: {sorted(set(round(d[0]) for d in drops))} deg')
    print(f'  drop counters seen: {min(d[1] for d in drops)} .. {max(d[1] for d in drops)}')

down=(0.0,-1.0,0.0); RX180=(1.0,0.0,0.0,0.0)
def med(v): s=sorted(v); return s[len(s)//2] if s else float('nan')
def q90(v): s=sorted(v); return s[int(0.9*len(s))] if s else float('nan')

for hand in ('left','right'):
    H=[r for r in recs if r['hand']==hand]
    if not H:
        print(f'== {hand}: no samples =='); continue
    c=tuple(med([r['pos'][i] for r in H]) for i in range(3))
    dist=[1000*math.sqrt(sum((r['pos'][i]-c[i])**2 for i in range(3))) for r in H]
    steps=[1000*math.sqrt(sum((H[i]['pos'][j]-H[i-1]['pos'][j])**2 for j in range(3)))
           for i in range(1,len(H))]
    mism=[vang(rot(qconj(r['qs']),down), rot(RX180,rot(qconj(r['qi']),down))) for r in H]
    dist_s=sorted(dist); steps_s=sorted(steps)
    print(f'== {hand}: n={len(H)}  center=({c[0]:+.3f},{c[1]:+.3f},{c[2]:+.3f}) ==')
    print(f'   scatter from center: p50 {med(dist):6.1f}  p90 {q90(dist):6.1f}  max {dist_s[-1]:6.1f} mm')
    if steps:
        print(f'   consecutive steps  : p50 {med(steps):6.1f}  p90 {q90(steps):6.1f}  max {steps_s[-1]:6.1f} mm')
    print(f'   rx180 gravity mism : p50 {med(mism):6.1f}  p90 {q90(mism):6.1f}  max {max(mism):6.1f} deg')
    print(f'   reproj err med {med([r["err"] for r in H]):.2f} px  blobs med {med([r["blobs"] for r in H])}')
