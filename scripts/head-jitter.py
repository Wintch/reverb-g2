#!/usr/bin/env python3
"""Head jitter analyzer: static-window rotation/position jitter, raw vs delivered.

Usage: head-jitter.py <slam-csv-dir> [t_start_s t_end_s]
Reads tracking.csv (raw SLAM output) and filtering.csv (the pose the application
actually receives) from a SLAM_WRITE_CSVS session dir. Finds static windows on the
raw stream automatically, then reports, for each stream in those windows:
  - consecutive-step rotation (deg) and position (mm) quantiles
  - high-frequency residual vs a 1 s moving median (jitter separated from drift)
Optional t_start/t_end (seconds since first raw row) restricts analysis.

Born 2026-08-13 (T180). It found the delivered pose wandering 10-25 mm at rest over
a raw SLAM sitting at 0.3-0.9 mm -- the smoking gun for the VIO backlog fixed by
patches/basalt/0002 (frames aged 0.5-0.9 s in Basalt's input queue, so dead
reckoning integrated IMU noise over that whole horizon).

BLIND TO (docs/32 discipline):
  - Motion jitter and feel: it only measures windows it detects as static. The
    wearer's verdict during movement is a separate, human measurement.
  - filtering.csv interleaves every pose querent (compositor at ~90 Hz, the
    constellation tracker at past camera timestamps, implausible-clock queries).
    It keeps the strictly-monotonic in-session subsequence; treat the delivered
    row count as "queries kept", not "frames rendered".
  - filtering.csv is EMPTY when nothing queries poses (no client connected):
    launch hello_xr (sleep N | hello_xr ...) to have a querent, or you will get
    "missing data" on a perfectly healthy tracker.
"""
import sys, math, bisect

def load(path):
    rows = []
    with open(path) as f:
        for line in f:
            if line.startswith('#'):
                continue
            p = line.rstrip('\n').split(',')
            if len(p) != 8:
                continue
            try:
                rows.append((int(p[0]), float(p[1]), float(p[2]), float(p[3]),
                             float(p[4]), float(p[5]), float(p[6]), float(p[7])))
            except ValueError:
                continue
    return rows

def qang(a, b):
    d = abs(a[0]*b[0] + a[1]*b[1] + a[2]*b[2] + a[3]*b[3])
    if d > 1.0: d = 1.0
    return 2.0 * math.degrees(math.acos(d))

def pdist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)

def quantiles(v, qs=(0.5, 0.9, 0.99)):
    if not v: return None
    s = sorted(v)
    out = [s[min(len(s)-1, int(q*len(s)))] for q in qs]
    out.append(s[-1])
    return out  # p50 p90 p99 max

def fmt(label, v, unit):
    q = quantiles(v)
    if q is None: return f'  {label}: no data'
    return (f'  {label}: p50 {q[0]:.3f}  p90 {q[1]:.3f}  p99 {q[2]:.3f}  '
            f'max {q[3]:.3f} {unit}  (n={len(v)})')

def steps(rows):
    rs, ps = [], []
    for i in range(1, len(rows)):
        rs.append(qang(rows[i-1][4:8], rows[i][4:8]))
        ps.append(1000.0 * pdist(rows[i-1][1:4], rows[i][1:4]))
    return rs, ps

def residuals(rows, half_win_ns=500_000_000):
    """High-frequency residual vs a 1 s moving median (component-wise, then renorm quat)."""
    ts = [r[0] for r in rows]
    rrot, rpos = [], []
    for i, r in enumerate(rows):
        lo = bisect.bisect_left(ts, r[0] - half_win_ns)
        hi = bisect.bisect_right(ts, r[0] + half_win_ns)
        if hi - lo < 5:
            continue
        seg = rows[lo:hi]
        med = []
        for k in range(1, 8):
            vals = sorted(s[k] for s in seg)
            med.append(vals[len(vals)//2])
        q = med[3:7]
        n = math.sqrt(sum(x*x for x in q)) or 1.0
        q = [x/n for x in q]
        rrot.append(qang(q, r[4:8]))
        rpos.append(1000.0 * pdist(med[0:3], r[1:4]))
    return rrot, rpos

def main():
    d = sys.argv[1].rstrip('/')
    raw = load(d + '/tracking.csv')
    filt = load(d + '/filtering.csv')
    if not raw or not filt:
        print('missing data'); return
    t0 = raw[0][0]

    # filtering.csv interleaves compositor queries (~90 Hz, future display times)
    # with constellation-tracker queries (past camera times) and the odd implausible
    # timestamp. Keep the strictly-monotonic in-session stream with sane poses:
    # that is the sequence of poses the app actually consumed, in order.
    n_all = len(filt)
    lo_ts, hi_ts = raw[0][0] - 2_000_000_000, raw[-1][0] + 2_000_000_000
    clean, last = [], -1
    for r in filt:
        if r[0] <= last or r[0] < lo_ts or r[0] > hi_ts:
            continue
        if abs(r[1]) > 100 or abs(r[2]) > 100 or abs(r[3]) > 100:
            continue
        clean.append(r); last = r[0]
    print(f'delivered: kept {len(clean)}/{n_all} rows after monotonic/sane cleaning')
    filt = clean
    if len(sys.argv) >= 4:
        a = t0 + int(float(sys.argv[2]) * 1e9)
        b = t0 + int(float(sys.argv[3]) * 1e9)
        raw = [r for r in raw if a <= r[0] <= b]
        filt = [r for r in filt if a <= r[0] <= b]
    span_raw = (raw[-1][0] - raw[0][0]) / 1e9
    span_f = (filt[-1][0] - filt[0][0]) / 1e9
    print(f'raw: {len(raw)} rows / {span_raw:.0f} s = {len(raw)/max(span_raw,1e-9):.1f} Hz | '
          f'delivered: {len(filt)} rows / {span_f:.0f} s = {len(filt)/max(span_f,1e-9):.1f} Hz')

    # static windows on raw: 10 s windows, 5 s hop; static if rot range < 2.5 deg
    # and pos range < 80 mm within the window
    ts = [r[0] for r in raw]
    W, H = 10_000_000_000, 5_000_000_000
    static = []  # (start_ns, end_ns)
    t = raw[0][0]
    while t + W <= raw[-1][0]:
        lo = bisect.bisect_left(ts, t)
        hi = bisect.bisect_right(ts, t + W)
        seg = raw[lo:hi]
        if len(seg) >= 20:
            q0 = seg[len(seg)//2][4:8]
            p0 = seg[len(seg)//2][1:4]
            rr = max(qang(q0, s[4:8]) for s in seg)
            pr = max(1000.0 * pdist(p0, s[1:4]) for s in seg)
            if rr < 2.5 and pr < 80.0:
                if static and t <= static[-1][1]:
                    static[-1] = (static[-1][0], t + W)
                else:
                    static.append((t, t + W))
        t += H
    tot = sum((b - a) for a, b in static) / 1e9
    print(f'static stretches (raw): {len(static)}, total {tot:.0f} s')
    for a, b in static:
        print(f'  [{(a - t0)/1e9:7.1f} .. {(b - t0)/1e9:7.1f}] s  ({(b-a)/1e9:.0f} s)')

    def in_static(rows):
        out = []
        for a, b in static:
            lo = bisect.bisect_left([r[0] for r in rows], a)
            hi = bisect.bisect_right([r[0] for r in rows], b)
            out.append(rows[lo:hi])
        return out

    for name, rows in (('RAW (tracking.csv)', raw), ('DELIVERED (filtering.csv)', filt)):
        segs = in_static(rows)
        allr, allp, hr, hp = [], [], [], []
        for seg in segs:
            if len(seg) < 20: continue
            r, p = steps(seg); allr += r; allp += p
            r, p = residuals(seg); hr += r; hp += p
        print(f'-- {name}, static windows only --')
        print(fmt('rot step  ', allr, 'deg'))
        print(fmt('pos step  ', allp, 'mm'))
        print(fmt('rot resid ', hr, 'deg'))
        print(fmt('pos resid ', hp, 'mm'))

    # whole-session step stats for continuity with T162's in-game numbers
    for name, rows in (('RAW', raw), ('DELIVERED', filt)):
        r, p = steps(rows)
        print(f'-- {name}, whole span --')
        print(fmt('rot step', r, 'deg'))
        print(fmt('pos step', p, 'mm'))

if __name__ == '__main__':
    main()
