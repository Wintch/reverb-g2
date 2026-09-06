#!/usr/bin/env python3
"""Logs a wall-clock timestamp every time a button is pressed on /dev/input/js0
(the Xbox 360 pad), for correlating with jack-in-wayland.log's PRESENCE-DIAG lines.
Ignores axis events, releases, and the synthetic init-sync events js devices send
on open (type & 0x80). Appends to ~/vr/joy-markers.log, one line per press:
  <ISO timestamp> BUTTON <number>
"""
import struct
import datetime
import sys

DEV = "/dev/input/js0"
LOG = "/home/iam/vr/joy-markers.log"
EVENT_FORMAT = "IhBB"  # time(u32), value(i16), type(u8), number(u8)
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

JS_EVENT_BUTTON = 0x01
JS_EVENT_INIT = 0x80

with open(DEV, "rb") as dev, open(LOG, "a", buffering=1) as log:
    print(f"listening on {DEV}, logging to {LOG}", flush=True)
    while True:
        data = dev.read(EVENT_SIZE)
        if len(data) < EVENT_SIZE:
            break
        _time, value, ev_type, number = struct.unpack(EVENT_FORMAT, data)
        is_init = bool(ev_type & JS_EVENT_INIT)
        real_type = ev_type & ~JS_EVENT_INIT
        if is_init or real_type != JS_EVENT_BUTTON or value != 1:
            continue
        now = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"{now} BUTTON {number}"
        print(line, flush=True)
        log.write(line + "\n")
