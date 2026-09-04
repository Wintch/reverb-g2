#!/usr/bin/env python3
# parse-metrics.py -- objective reprojection meter for Monado, from XRT_METRICS_FILE.
#
# WHY: frame-pacing.sh only counts "Frame late by" (the app missing its deadline) and is BLIND to
# reprojection -- the compositor presenting a REUSED app frame because no fresh one arrived. That is
# the real "micro-stutter" signal, and it can be nonzero while every easy counter reads 0
# (measured 2026-09-04 on Aircar; see docs/96 section 14). This reads Monado's own per-frame metrics
# instead of guessing from feel.
#
# ENABLE (at monado launch, so it is in the service env):
#   XRT_METRICS_FILE=/path/to/metrics.bin XRT_METRICS_EARLY_FLUSH=true  <launch monado>
# EARLY_FLUSH makes the file readable live (fflush per record, negligible overhead); without it the
# file only completes when monado exits.
#
# USE:
#   ./parse-metrics.py metrics.bin [start_byte_offset]
# The file appends for the whole session; pass a byte offset (the file size captured just before the
# window of interest) to score only that window -- e.g. capture `stat -c%s metrics.bin`, fly 30 s,
# then parse from that offset.
#
# METHOD: the file is a nanopb stream of length-prefixed monado_metrics_Record messages. Record is a
# oneof; tags: 1=version 2=session_frame 3=used 4=system_frame 5=system_gpu_info 6=system_present_info.
# A `used` record maps one compositor frame (system_frame_id, tag 3) to the app frame it showed
# (session_frame_id, tag 2). Presents that reuse a session_frame_id are reprojections:
#   reprojections = total presents - unique app-frames shown.
# session_frame carries `discarded` (tag 14): an app frame dropped because a newer one arrived
# (app faster than the display) -- the opposite of a reprojection.
import sys

def rv(b, i):
    s = 0; r = 0
    while True:
        x = b[i]; i += 1; r |= (x & 0x7f) << s
        if not (x & 0x80): return r, i
        s += 7

def fields(msg):
    # yield (field_no, wire_type, value_or_bytes)
    i = 0; n = len(msg)
    while i < n:
        key, i = rv(msg, i); f = key >> 3; wt = key & 7
        if wt == 0: v, i = rv(msg, i); yield f, 0, v
        elif wt == 2: l, i = rv(msg, i); yield f, 2, msg[i:i + l]; i += l
        elif wt == 1: yield f, 1, msg[i:i + 8]; i += 8
        elif wt == 5: yield f, 5, msg[i:i + 4]; i += 4
        else: return

_off = int(sys.argv[2]) if len(sys.argv) > 2 else 0
data = open(sys.argv[1], "rb").read()[_off:]
i = 0; n = len(data)
hist = {}; used = []; sframes = []; presents = 0; recs = 0
while i < n:
    try:
        rl, i = rv(data, i)
    except IndexError:
        break
    if rl <= 0 or i + rl > n:
        break
    rec = data[i:i + rl]; i += rl; recs += 1
    for f, wt, val in fields(rec):
        if wt != 2:
            continue
        hist[f] = hist.get(f, 0) + 1
        if f == 3:  # used
            sfid = sysid = None
            for ff, w, v in fields(val):
                if ff == 2 and w == 0: sfid = v
                elif ff == 3 and w == 0: sysid = v
            used.append((sysid, sfid))
        elif f == 2:  # session_frame (app frame)
            fid = None; disc = 0
            for ff, w, v in fields(val):
                if ff == 2 and w == 0: fid = v
                elif ff == 14 and w == 0: disc = v
            sframes.append((fid, disc))
        elif f == 6:  # system_present_info (a present)
            presents += 1
        break  # Record is a oneof: one field per record

NAME = {1: "version", 2: "session_frame", 3: "used", 4: "system_frame",
        5: "system_gpu_info", 6: "system_present_info"}
print("records:", recs)
print("by type:", {NAME.get(k, k): v for k, v in sorted(hist.items())})
if used:
    tot = len(used); uniq = len(set(sf for _, sf in used if sf is not None))
    print(f"USED: {tot} presents, {uniq} unique app-frames -> reprojections={tot - uniq} "
          f"({100 * (tot - uniq) / tot:.1f}%)")
if sframes:
    shown = sum(1 for _, d in sframes if not d); disc = sum(1 for _, d in sframes if d)
    print(f"SESSION_FRAME: {len(sframes)} app-frames (shown={shown}, discarded={disc})")
if presents:
    print(f"SYSTEM_PRESENT_INFO: {presents} presents")
    if sframes:
        shown = sum(1 for _, d in sframes if not d)
        print(f"  -> reprojections (presents - app_shown) = {presents - shown} "
              f"({100 * (presents - shown) / presents:.1f}% of {presents})")
