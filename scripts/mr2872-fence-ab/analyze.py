import re,sys,statistics as st
f=sys.argv[1]; lat=[]; drop=0; fell=0; tbl=[]
cur=None
for l in open(f,errors="replace"):
    m=re.search(r"Delivered frame ([\d.]+)ms (early|late)",l)
    if m: lat.append(float(m.group(1))*(1 if m.group(2)=="late" else -1)); continue
    if "Dropping old missed frame" in l: drop+=1
    if "Fake pacer fell behind" in l: fell+=1
    if "Compositor frame timing" in l: cur=[]; tbl.append(cur); continue
    if cur is not None:
        m=re.match(r"\s+(\w+)\s+([\d.]+)ms\s+([\d.]+)ms\s+([\d.]+)ms",l)
        if m: cur.append((m.group(1),)+tuple(float(x) for x in m.groups()[1:]))
n=len(lat); s=sorted(lat); q=lambda p:s[min(n-1,int(p*n))]
print(f"frames={n} median={st.median(lat):.2f} mean={st.mean(lat):.2f} p95={q(.95):.2f} p99={q(.99):.2f} p999={q(.999):.2f} max={s[-1]:.2f}  (ms, +late/-early)")
print(f"late>0.5ms: {sum(x>.5 for x in lat)/n*100:.1f}%  >1ms: {sum(x>1 for x in lat)/n*100:.1f}%  >2ms: {sum(x>2 for x in lat)/n*100:.2f}%  >5ms: {sum(x>5 for x in lat)/n*100:.2f}%")
print(f"stdev={st.pstdev(lat):.2f}  dropped_missed={drop}  fake_pacer_fell_behind={fell}")
import collections
agg=collections.defaultdict(list)
for t in tbl[1:]:  # skip first (startup)
    for r in t: agg[r[0]].append(r[1:])
for k,v in agg.items(): print(f"  {k:12s} median(avg of tables)={st.mean(x[0] for x in v):.2f}  mean={st.mean(x[1] for x in v):.2f}  worst(max)={max(x[2] for x in v):.2f}")
