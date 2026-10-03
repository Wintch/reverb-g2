#!/usr/bin/env python3
"""Per-second hidraw report counts + device tick delta: shake 20 s, still 100 s. Log ~/bt-3phase.log"""
import glob, os, select, subprocess, time, collections
ENV = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}")
def say(t): subprocess.run(["espeak-ng","-v","es",t],env=ENV,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def find(side):
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try: u=open(h+"/device/uevent").read()
        except OSError: continue
        if "HID_ID=0005:0000045E:0000066A" in u and f"Motion controller - {side}" in u: return "/dev/"+os.path.basename(h)
fds={s:os.open(p,os.O_RDONLY|os.O_NONBLOCK) for s in ("Left","Right") if (p:=find(s))}
cnt={s:collections.Counter() for s in fds}; tick={s:{} for s in fds}
t0=time.time(); say("Agita los dos joys durante veinte segundos. Ya"); t0=time.time(); said=False
while time.time()-t0<120:
    el=time.time()-t0
    if el>=20 and not said: said=True; say("Quietos. Déjalos sin tocar")
    r,_,_=select.select(list(fds.values()),[],[],0.2)
    for s,fd in fds.items():
        if fd in r:
            try:
                while True:
                    d=os.read(fd,128)
                    if d and d[0]==1 and len(d)>=33:
                        sec=int(time.time()-t0); cnt[s][sec]+=1
                        tick[s].setdefault(sec,[]).append(int.from_bytes(d[29:33],"little"))
            except BlockingIOError: pass
with open(os.path.expanduser("~/bt-3phase.log"),"w") as f:
    for s in fds:
        for sec in range(0,120):
            t=tick[s].get(sec,[]); dts=[(b-a)/10000 for a,b in zip(t,t[1:])]
            f.write(f"{s} t={sec:3d}s n={cnt[s][sec]:3d} dev_dt_ms_med={sorted(dts)[len(dts)//2] if dts else 0:.1f}\n")
    f.write("done\n")
say("Prueba terminada")
