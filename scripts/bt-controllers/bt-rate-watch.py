import glob,os,select,time,collections,sys
fds={}
for h in glob.glob("/sys/class/hidraw/hidraw*"):
    u=open(h+"/device/uevent").read()
    if "0000045E:0000066A" in u: fds[("L" if "Left" in u else "R")]=os.open("/dev/"+os.path.basename(h),os.O_RDONLY|os.O_NONBLOCK)
c=collections.defaultdict(collections.Counter);t0=time.time()
while time.time()-t0<float(sys.argv[1]):
    r,_,_=select.select(list(fds.values()),[],[],0.2)
    for s,fd in fds.items():
        if fd in r:
            try:
                while True:
                    if os.read(fd,128)[:1]==b"\x01": c[s][int(time.time()-t0)]+=1
            except BlockingIOError: pass
with open(os.path.expanduser("~/bt-rate-watch.log"),"w") as f:
    for s in c:
        for k in range(int(sys.argv[1])): f.write(f"{s} {k} {c[s][k]}\n")
    f.write("done\n")
