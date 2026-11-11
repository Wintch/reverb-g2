#!/usr/bin/env python3
"""Identify the constant LED-model-to-IMU rotation per hand from motion data.

Consecutive logged samples of one hand give the same physical rotation seen in two
body frames: dS = conj(qs_i)*qs_{i+1} (LED frame), dI = conj(qi_i)*qi_{i+1} (IMU
frame). Their rotation angles must agree (frame-independent); their axes differ by
the constant R we want: axis(dS) = R * axis(dI). Wahba/Davenport over all pairs.

Usage: constellation-frame-fit.py <wave-capture.log> <full-log-with-P_imu_me>

Born 2026-08-13 (T181). Needs a capture where the controllers ROTATE (user waving
them, ~90 s); the log lines come from monado 0047's INFO telemetry ("constellation
vs IMU [...] q_solve=... q_imu=..."). Static data is underdetermined (two unknown
fixed rotations plus per-session yaw) — this tool bypasses world frames entirely,
which is the point. Verdict on real G2 controllers: Rx180 on both hands, NOT the
factory accel.pose.
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
def axang(q):
    q=qnorm(q); w=min(1.0,q[3]); ang=2*math.degrees(math.acos(w))
    s=math.sqrt(max(1e-12,1-w*w))
    return (q[0]/s,q[1]/s,q[2]/s), ang
def vang(a,b):
    d=sum(x*y for x,y in zip(a,b))
    return math.degrees(math.acos(max(-1,min(1,d))))
def qang(a,b):
    d=min(1.0,abs(sum(x*y for x,y in zip(a,b))))
    return 2*math.degrees(math.acos(d))

grav_re=re.compile(r'\[HP Reverb G2 (Left|Right) Controller\].*q_solve=\((-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)\) q_imu=\((-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)\)')
pime_re=re.compile(r'P_imu_me \((left|right)\): quat=\((-?[\d.]+), (-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\)')

P={}
for l in open(sys.argv[2],errors='replace'):
    m=pime_re.search(l)
    if m: P[m.group(1)]=qnorm(tuple(float(x) for x in m.groups()[1:]))

seq={'left':[],'right':[]}
for l in open(sys.argv[1],errors='replace'):
    m=grav_re.search(l)
    if m:
        g=m.groups()
        seq[g[0].lower()].append((qnorm(tuple(float(x) for x in g[1:5])),
                                  qnorm(tuple(float(x) for x in g[5:9]))))

def davenport(pairs):
    """pairs: list of (v_ref, v_body) with model v_ref = R * v_body. Returns quat of R."""
    B=[[0.0]*3 for _ in range(3)]
    for vr,vb in pairs:
        for i in range(3):
            for j in range(3):
                B[i][j]+=vr[i]*vb[j]
    S=[[B[i][j]+B[j][i] for j in range(3)] for i in range(3)]
    trB=B[0][0]+B[1][1]+B[2][2]
    z=[B[1][2]-B[2][1], B[2][0]-B[0][2], B[0][1]-B[1][0]]
    K=[[S[0][0]-trB,S[0][1],S[0][2],z[0]],
       [S[1][0],S[1][1]-trB,S[1][2],z[1]],
       [S[2][0],S[2][1],S[2][2]-trB,z[2]],
       [z[0],z[1],z[2],trB]]
    # power iteration on K + shift to make dominant eigenvalue the max one
    shift=sum(abs(K[i][j]) for i in range(4) for j in range(4))
    for i in range(4): K[i][i]+=shift
    v=[1.0,0.0,0.0,0.5]
    for _ in range(500):
        nv=[sum(K[i][j]*v[j] for j in range(4)) for i in range(4)]
        n=math.sqrt(sum(c*c for c in nv)) or 1.0
        v=[c/n for c in nv]
    return qnorm((v[0],v[1],v[2],v[3]))

for hand in ('left','right'):
    s=seq[hand]
    print(f'\n==== {hand.upper()}: {len(s)} samples ====')
    pairs=[]; rej_ang=0; rej_agree=0
    for i in range(1,len(s)):
        dS=qmul(qconj(s[i-1][0]),s[i][0])
        dI=qmul(qconj(s[i-1][1]),s[i][1])
        aS,angS=axang(dS); aI,angI=axang(dI)
        if not (2.0<angS<40.0 and 2.0<angI<40.0): rej_ang+=1; continue
        if abs(angS-angI)>0.25*max(angS,angI): rej_agree+=1; continue
        pairs.append((aS,aI,angS,angI))
    print(f'usable pairs: {len(pairs)} (rejected: {rej_ang} angle-range, {rej_agree} angle-mismatch)')
    if len(pairs)<10:
        print('  not enough motion pairs'); continue
    # angle agreement stats (sanity: same physical rotation)
    dd=sorted(abs(p[2]-p[3]) for p in pairs)
    print(f'rotation-angle agreement |dS-dI|: p50 {dd[len(dd)//2]:.2f} deg  p90 {dd[int(.9*len(dd))]:.2f} deg')
    R=davenport([(p[0],p[1]) for p in pairs])
    ax,ang=axang(R)
    res=sorted(vang(p[0],rot(R,p[1])) for p in pairs)
    print(f'R (v_led = R * v_imu): quat=({R[0]:+.4f},{R[1]:+.4f},{R[2]:+.4f},{R[3]:+.4f})')
    print(f'   axis=({ax[0]:+.3f},{ax[1]:+.3f},{ax[2]:+.3f}) angle={ang:.1f} deg')
    print(f'   residuals: p50 {res[len(res)//2]:.1f}  p90 {res[int(.9*len(res))]:.1f}  max {res[-1]:.1f} deg')
    if hand in P:
        p=P[hand]
        print(f'   vs P_imu_me: {qang(R,p):.1f} deg | vs conj(P): {qang(R,qconj(p)):.1f} deg | angle(P)={axang(p)[1]:.1f}')
