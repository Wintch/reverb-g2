import glob,os,fcntl,select,time,sys
def dev():
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try: ue=open(d+"/device/uevent").read()
        except OSError: continue
        if "045E:00000659" in ue.upper(): return "/dev/"+os.path.basename(d)
def HIDIOCSFEATURE(l): return (3<<30)|(ord('H')<<8)|0x06|(l<<16)
fd=os.open(dev(),os.O_RDWR)
# unblock the BT debug log (report 0x05/0x19 narrates the pairing state machine).
# Try the known debug-enable: report 0x05, subtype 0x19 handling differs; also try 0x03 log on.
def feat(payload):
    b=bytes(payload)+bytes(64-len(payload))
    try: fcntl.ioctl(fd,HIDIOCSFEATURE(len(b)),b,True); return True
    except OSError as e: return False
# fire PAIR right (16 05 01) via control SET_REPORT
print("fire PAIR 16 05 01 via HIDIOCSFEATURE:", feat([0x16,0x05,0x01]))
# now READ everything for 25s, decode report 0x05 ASCII (the BT state machine)
print("listening 25s for the BT debug log (report 0x05) and status (0x17)...")
t0=time.time()
while time.time()-t0<25:
    r,_,_=select.select([fd],[],[],0.5)
    if not r: continue
    try: b=os.read(fd,64)
    except OSError:
        print("  [fd died -- reopening]"); 
        try: os.close(fd)
        except: pass
        time.sleep(0.5)
        nd=dev()
        if nd: fd=os.open(nd,os.O_RDWR)
        continue
    if not b: continue
    if b[0]==0x05 and len(b)>6:
        txt=bytes(x for x in b[6:] if 32<=x<127).decode('ascii','replace')
        if txt.strip(): print(f"  t+{time.time()-t0:4.1f}s  BT-LOG: {txt}")
    elif b[0]==0x17 and len(b)>=3:
        nm={0:'left',1:'right'}.get(b[1],b[1]); st={0:'UNPAIRED',1:'offline',2:'ONLINE'}.get(b[2],b[2])
        if b[1]==1: print(f"  t+{time.time()-t0:4.1f}s  STATUS right={st}")
os.close(fd)
