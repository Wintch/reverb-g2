#!/usr/bin/env python3
"""controller-pair-v2: pair a G2 motion controller to the HEADSET's own radio, and LISTEN to
everything the headset says while we do it.  Python 3 stdlib only.  MIT-compatible: the protocol
below is reimplemented from OUR OWN captures (docs/03-controllers.md T238-T244), not copied from
any third-party code.

WHY A V2.  controller-pair.py sent the right bytes (`16 05 <hand>` as a Feature SET_REPORT, byte
for byte what Windows sends) but on Linux the radio never started an inquiry.  What it never did
was READ the replies: report 0x03 (firmware log) and report 0x16 (BT-control replies) were
ignored, and the Windows host's setup traffic before the PAIR was never replayed.  This tool
adds a reader thread that decodes and timestamps EVERY input report, plus an optional replay of
the Windows host preamble, so the next attempt produces evidence either way.

THE REFERENCE (Windows capture pairing3.pcapng, LEFT controller, one clean attempt):
    t=141.3244  Feature  16 09 00        CMD_STATUS left
    t=141.3247  input    16 09 00 00 10 00 00 00 7d 92 ...   (reply, flag 0 = complete)
    ... ~47 s idle, camera/IMU bulk stream running ...
    t=188.3308  Feature  16 05 00        PAIR left   (wValue 0x0316, wIndex 2, wLength 64)
    t=188.3318  report 0x03  "Received pair request MC: 0"            (+1.0 ms)
    t=188.3318  report 0x03  "MC:0, New pairingStatus: 1"
    t=188.3337  report 0x05  COMMAND_SET_VISIBILITY / SET_PAIRING_MODE / "Set the pairing allowed
                             to 1" / COMMAND_INQUIRY / "inquiry started"        (-188.3395)
    t=188.3414  report 0x03  "CmdStatus Success"
    t=189.5137  report 0x05  "Found by address: Motion Controller - Left"       (+1.18 s)
`--selftest` re-derives all of that from the capture with tshark, no headset needed.

REPORT FORMATS DECODED HERE (offsets verified against pairing3.pcapng unless marked):
  0x03  firmware log, 509 bytes: id | "Dlo+" | 8 records of 63 bytes. Record = u32 device tick |
        u16 seq | u8 level | 56 bytes ASCII, NUL padded.  (The magic appears only once per packet:
        scripts/fwlog.py's magic scan only ever saw the FIRST record of each packet.)
  0x05  BT radio debug log, 256 bytes: id | 0x19 | u16 tag | u16 text length | ASCII text.
  0x16  BT-control reply: id | cmd | hand | ...; for cmd 0x09 byte 3 is the status flag
        (0 complete, 1 pending, 2 failed, 3 in progress, 4/5 paired, 6 unpaired).
        cmd 0x08 reply layout (MAC, VID/PID) is NOT in our captures; offsets are provisional.
  0x17  controller status, 7 bytes: id | hand | state (0 unpaired, 1 paired/offline, 2 online)
        | u16 VID | u16 PID.   Streamed passively by the headset.

MODES (exactly one):
  --single-pair L|R   send exactly ONE Feature `16 05 <0|1>` and listen.  DESTRUCTIVE to the
                      current bond of that hand; refuses without
                      --i-understand-this-erases-the-current-bond.
  --status L|R        query `16 08` and `16 04` only, listen a few seconds.
  --listen            passive: send nothing, decode and log everything.
  --selftest PCAP     offline: decode the Windows capture with tshark and check the facts above.

SAFETY, by construction: the send layer refuses every `0x16` subcommand except 04/05/08/09 --
UNPAIR (`16 06`) and the unexplained `16 07` cannot be sent even by editing the call sites
without also editing the allow-list.  PAIR can only be sent through one function that demands
the confirmation flag.  A PAIR is never retried.  Even queries are control SET_REPORTs; the radio
has been seen to re-enumerate around them (docs/03 T238), so do not run this while Monado or
anything else holds the headset's hidraw (a warning is printed if monado-service is running).
"""
import argparse
import collections
import fcntl
import glob
import json
import os
import re
import select
import subprocess
import sys
import threading
import time

HOLOLENS_SENSORS = (0x045E, 0x0659)
RADIO_INTERFACE = 2                  # the HID interface that carries BT control (wIndex 2)

RID_FWLOG = 0x03
RID_BTLOG = 0x05
RID_BT_CONTROL = 0x16
RID_CTRL_STATUS = 0x17
RID_OUT_CONTROL = 0x02               # Output reports Windows sends: 02 0b/06/04/08/07 (docs/03)

BT_ONLINE_STATUS = 0x04
BT_PAIR = 0x05
BT_PAIRING_STATUS = 0x08
BT_CMD_STATUS = 0x09
# 16 06 (UNPAIR) and 16 07 (unexplained) are deliberately absent.
ALLOWED_BT_CMDS = (BT_ONLINE_STATUS, BT_PAIR, BT_PAIRING_STATUS, BT_CMD_STATUS)

FWLOG_MAGIC = b"Dlo+"
FWLOG_RECORD = 63                    # u32 tick, u16 seq, u8 level, 56 text bytes

CMD_FLAGS = {0: "complete", 1: "pending", 2: "failed", 3: "in progress",
             4: "paired", 5: "paired", 6: "unpaired"}
CTRL_STATES = {0: "UNPAIRED", 1: "paired/offline", 2: "paired/online"}
HAND_NAMES = {0: "left", 1: "right"}
HAND_IDS = {"l": 0, "left": 0, "r": 1, "right": 1}

CONFIRM_FLAG = "--i-understand-this-erases-the-current-bond"


# --------------------------------------------------------------------------------------------
# Decoders (pure functions, shared by the live reader and --selftest)
# --------------------------------------------------------------------------------------------

def _u16(b, o):
    return int.from_bytes(b[o:o + 2], "little")


def _u32(b, o):
    return int.from_bytes(b[o:o + 4], "little")


def _ascii(raw):
    """ASCII text up to the first NUL, trimmed."""
    end = raw.find(b"\x00")
    if end >= 0:
        raw = raw[:end]
    return raw.decode("ascii", "replace").strip()


def parse_fwlog(buf):
    """Report 0x03 -> list of dicts {tick, seq, level, text}.

    pairing3.pcapng shows the real layout: the magic is present ONCE, right after the report id,
    followed by fixed 63-byte records (509 = 1 + 4 + 8 * 63).  If a packet does not have that
    shape, fall back to scanning for the magic per entry like the old fwlog.py did."""
    out = []
    if len(buf) >= 12 and buf[1:5] == FWLOG_MAGIC:
        pos = 5
        while pos + 7 <= len(buf):
            rec = buf[pos:pos + FWLOG_RECORD]
            text = _ascii(rec[7:])
            if text:
                out.append({"tick": _u32(rec, 0), "seq": _u16(rec, 4), "level": rec[6], "text": text})
            pos += FWLOG_RECORD
        if out:
            return out
    for m in re.finditer(re.escape(FWLOG_MAGIC), buf):
        p = m.end()
        if p + 7 > len(buf):
            continue
        text = _ascii(buf[p + 7:])
        if text:
            out.append({"tick": _u32(buf, p), "seq": _u16(buf, p + 4), "level": buf[p + 6], "text": text})
    return out


def decode_report(buf):
    """Decode one input report (first byte = report id) into a dict.  Never raises."""
    ev = {"rid": buf[0] if buf else -1, "len": len(buf), "kind": "other"}
    if not buf:
        ev["kind"] = "empty"
        return ev
    rid = buf[0]
    if rid == RID_FWLOG:
        ev["kind"] = "fwlog"
        ev["entries"] = parse_fwlog(buf)
    elif rid == RID_BTLOG and len(buf) >= 6 and buf[1] == 0x19:
        n = _u16(buf, 4)
        ev["kind"] = "btlog"
        ev["tag"] = _u16(buf, 2)
        ev["text_len"] = n
        ev["truncated"] = n > len(buf) - 6
        ev["text"] = _ascii(buf[6:6 + n])
    elif rid == RID_BT_CONTROL and len(buf) >= 3:
        ev["kind"] = "bt_ctrl"
        ev["cmd"] = buf[1]
        ev["hand"] = buf[2]
        if buf[1] == BT_CMD_STATUS and len(buf) >= 4:
            ev["flag"] = buf[3]
            ev["flag_name"] = CMD_FLAGS.get(buf[3], "unknown")
            ev["rest"] = buf[4:16].hex()
        elif buf[1] == BT_PAIRING_STATUS and len(buf) >= 15:
            # Provisional layout (not present in our captures): MAC at 3..8, VID at 11, PID at 13.
            ev["mac"] = ":".join("%02x" % x for x in buf[3:9])
            ev["vid"] = _u16(buf, 11)
            ev["pid"] = _u16(buf, 13)
        else:
            ev["rest"] = buf[3:16].hex()
    elif rid == RID_CTRL_STATUS and len(buf) >= 3:
        ev["kind"] = "ctrl_status"
        ev["hand"] = buf[1]
        ev["state"] = buf[2]
        ev["state_name"] = CTRL_STATES.get(buf[2], "0x%02x" % buf[2])
        if len(buf) >= 7:
            ev["vid"] = _u16(buf, 3)
            ev["pid"] = _u16(buf, 5)
    return ev


def hand_name(h):
    return HAND_NAMES.get(h, "hand%s" % h)


def describe(ev, full_hex=False, raw=b""):
    """Human console lines for a decoded report (no timestamp prefix)."""
    k = ev["kind"]
    if k == "fwlog":
        return ["0x03 fw   seq=%-5d lvl=%d tick=%-8d %s" % (e["seq"], e["level"], e["tick"], e["text"])
                for e in ev["entries"]] or ["0x03 fw   (no text entries)"]
    if k == "btlog":
        return ["0x05 bt   tag=%-4d %s%s" % (ev["tag"], ev["text"], "  [truncated]" if ev["truncated"] else "")]
    if k == "bt_ctrl":
        who = hand_name(ev["hand"])
        if "flag" in ev:
            return ["0x16 ctl  cmd=0x%02x (CMD_STATUS) %s: flag=%d (%s) rest=%s"
                    % (ev["cmd"], who, ev["flag"], ev["flag_name"], ev["rest"])]
        if "mac" in ev:
            return ["0x16 ctl  cmd=0x%02x (PAIRING_STATUS) %s: mac=%s vid=0x%04x pid=0x%04x [provisional layout]"
                    % (ev["cmd"], who, ev["mac"], ev["vid"], ev["pid"])]
        return ["0x16 ctl  cmd=0x%02x %s: %s" % (ev["cmd"], who, ev.get("rest", ""))]
    if k == "ctrl_status":
        extra = " vid=0x%04x pid=0x%04x" % (ev["vid"], ev["pid"]) if "vid" in ev else ""
        return ["0x17 stat %s = %s%s" % (hand_name(ev["hand"]), ev["state_name"], extra)]
    data = raw if full_hex else raw[:32]
    return ["0x%02x other len=%d %s%s" % (ev["rid"], ev["len"], data.hex(" "),
                                          "" if full_hex or len(raw) <= 32 else " ...")]


# --------------------------------------------------------------------------------------------
# Device discovery and the radio handle
# --------------------------------------------------------------------------------------------

def hidraw_candidates():
    """All hidraw nodes of 045e:0659 as [(devnode, interface_number_or_None)]."""
    out = []
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            ue = open(os.path.join(d, "device", "uevent")).read()
        except OSError:
            continue
        for line in ue.splitlines():
            if not line.startswith("HID_ID="):
                continue
            _, vid, pid = line.split(":")
            if (int(vid, 16), int(pid, 16)) != HOLOLENS_SENSORS:
                continue
            iface = None
            for comp in os.path.realpath(os.path.join(d, "device")).split("/"):
                m = re.match(r"^[\d.-]+:\d+\.(\d+)$", comp)
                if m:
                    iface = int(m.group(1))
            out.append(("/dev/" + os.path.basename(d), iface))
    return out


def find_radio_dev():
    """Prefer the node on USB interface 2.  If none reports interface 2, accept a single
    candidate ONLY when its interface number could not be determined (the assumption
    controller-pair.py makes); a node known to sit on another interface, or several candidates,
    are refused rather than guessed."""
    cands = hidraw_candidates()
    for dev, iface in cands:
        if iface == RADIO_INTERFACE:
            return dev
    if len(cands) == 1 and cands[0][1] is None:     # interface unknown: cannot rule it out
        return cands[0][0]
    return None


def _HIDIOCSFEATURE(length):
    return (3 << 30) | (ord("H") << 8) | 0x06 | (length << 16)


class Radio:
    """hidraw handle of the headset radio interface. Thread-safe; survives re-enumeration."""

    def __init__(self, path, log):
        self.path = path
        self.log = log
        self.lock = threading.Lock()
        self.fd = None
        self._open()

    def _open(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)

    def reopen(self, wait=9.0):
        """The radio can re-enumerate (hidraw node moves).  Re-find by VID/PID and swap the fd."""
        t_end = time.monotonic() + wait
        while time.monotonic() < t_end:
            dev = find_radio_dev()
            if dev:
                try:
                    nfd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
                except OSError:
                    nfd = None
                if nfd is not None:
                    with self.lock:
                        old, self.fd, self.path = self.fd, nfd, dev
                    try:
                        os.close(old)
                    except OSError:
                        pass
                    self.log.event("reopened", path=dev)
                    return True
            time.sleep(0.3)
        return False

    def close(self):
        with self.lock:
            fd, self.fd = self.fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    @staticmethod
    def _guard(payload, pair_ok=False):
        """Refuse anything dangerous BEFORE it reaches the wire.  Applies to the dry-run radio too.
        A PAIR (16 05) additionally needs pair_ok=True, which only send_pair() ever passes."""
        if payload and payload[0] == RID_BT_CONTROL:
            if len(payload) < 2 or payload[1] not in ALLOWED_BT_CMDS:
                raise RuntimeError("refusing to send 16 %s: not on the allow-list (UNPAIR and 16 07 are never sent)"
                                   % ("%02x" % payload[1] if len(payload) > 1 else "??"))
            if payload[1] == BT_PAIR and not pair_ok:
                raise RuntimeError("refusing 16 05 (PAIR) outside send_pair()")
        if len(payload) > 64:
            raise RuntimeError("payload longer than 64 bytes")

    def send_feature(self, payload, pair_ok=False):
        """Control SET_REPORT, ReportType Feature (wValue 0x03xx), padded to 64 bytes.
        HIDIOCSFEATURE's length argument is the whole buffer INCLUDING the report id byte, which
        is what ends up in wLength (64 in the Windows capture)."""
        self._guard(payload, pair_ok)
        buf = bytes(payload) + bytes(64 - len(payload))
        try:
            with self.lock:
                fcntl.ioctl(self.fd, _HIDIOCSFEATURE(len(buf)), buf, True)
            return True, ""
        except (OSError, TypeError) as e:
            return False, str(e)

    def send_output(self, payload):
        """Output report; interface 2 has no interrupt-OUT, so write() goes out as a control
        SET_REPORT with wValue 0x02xx -- what Windows does for the 02 xx reports (docs/03 T240).
        Only report id 0x02 is ever sent this way (Windows sends 0x16 as Feature, never Output)."""
        if not payload or payload[0] != RID_OUT_CONTROL or len(payload) > 64:
            raise RuntimeError("send_output only sends Output report 0x02")
        buf = bytes(payload) + bytes(64 - len(payload))
        try:
            with self.lock:
                n = os.write(self.fd, buf)
            if n != len(buf):
                return False, "short write %d/%d" % (n, len(buf))
            return True, ""
        except (OSError, TypeError) as e:
            return False, str(e)


class DryRadio:
    """Same interface, sends nothing."""

    path = "(dry-run)"

    def send_feature(self, payload, pair_ok=False):
        Radio._guard(payload, pair_ok)
        return True, ""

    def send_output(self, payload):
        if not payload or payload[0] != RID_OUT_CONTROL:
            raise RuntimeError("send_output only sends Output report 0x02")
        return True, ""

    def close(self):
        pass


# --------------------------------------------------------------------------------------------
# Logging: JSONL + console, one clock (monotonic ms since start)
# --------------------------------------------------------------------------------------------

class Log:
    def __init__(self, path, full_hex=False):
        self.t0 = time.monotonic()
        self.lock = threading.Lock()
        self.fh = open(path, "w", buffering=1) if path else None
        self.full_hex = full_hex
        self.last_status = {}
        self.other_counts = collections.Counter()
        self.other_last_print = {}
        self.seen = []                 # decoded NON-stream rx events (for the end-of-run summary)
        self.total_rx = 0              # every input report, including the 0x01 sensor stream

    def ms(self):
        return (time.monotonic() - self.t0) * 1000.0

    def _write(self, rec):
        """One JSON object per line.  Never raises: a full disk or a closed file must not kill the
        reader thread in the middle of a PAIR, so on failure logging to file is switched off."""
        if self.fh:
            try:
                self.fh.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")
            except (OSError, ValueError) as e:
                print("WARNING: JSONL logging disabled: %s" % e, file=sys.stderr)
                self.fh = None

    def _say(self, t_ms, text):
        print("[%9.1f ms] %s" % (t_ms, text), flush=True)

    def event(self, name, **kw):
        t = self.ms()
        with self.lock:
            rec = dict(kw)
            rec.update(t_ms=round(t, 3), dir="evt", event=name)     # reserved keys always win
            self._write(rec)
            self._say(t, "--   %s %s" % (name, " ".join("%s=%s" % kv for kv in kw.items())))

    def tx(self, label, payload, ok=True, err="", t_send=None):
        """t_send = clock reading taken just BEFORE the send.  The control transfer is synchronous,
        so stamping after it returns could place the TX later than the reports the headset
        emitted 1 ms after it.  t_done_ms is when the send returned.  JSONL lines are written in
        completion order; sort by t_ms to get wire order."""
        t_done = self.ms()
        t = t_done if t_send is None else t_send
        with self.lock:
            self._write({"t_ms": round(t, 3), "t_done_ms": round(t_done, 3), "dir": "tx",
                         "label": label, "ok": ok, "err": err, "hex": bytes(payload).hex()})
            if not label.startswith("quiet:"):
                self._say(t, "TX   %-34s %s%s" % (label, bytes(payload[:4]).hex(" "),
                                                  "" if ok else "  FAILED: " + err))

    def rx(self, raw):
        t = self.ms()
        ev = decode_report(raw)
        rec = {"t_ms": round(t, 3), "dir": "rx", "rid": ev["rid"], "len": ev["len"], "kind": ev["kind"]}
        rec.update({k: v for k, v in ev.items() if k not in rec})
        keep = raw if (self.full_hex or ev["kind"] != "other") else raw[:24]
        rec["hex"] = keep.hex()
        with self.lock:
            self.total_rx += 1
            if ev["kind"] != "other":
                self.seen.append(ev)
            self._write(rec)
            k = ev["kind"]
            if k == "ctrl_status":
                key = ev["hand"]
                sig = (ev["state"], ev.get("vid"), ev.get("pid"))
                if self.last_status.get(key) == sig:
                    return
                self.last_status[key] = sig
            elif k == "other":
                rid = ev["rid"]
                self.other_counts[rid] += 1
                n = self.other_counts[rid]
                if n > 3 and t - self.other_last_print.get(rid, -1e9) < 5000:
                    return                      # high-rate stream: first 3, then one line per 5 s
                self.other_last_print[rid] = t
                if n > 3:
                    self._say(t, "     (report 0x%02x: %d so far, last len=%d)" % (rid, n, ev["len"]))
                    return
            for line in describe(ev, self.full_hex, raw):
                self._say(t, "RX   " + line)

    def close(self):
        if self.fh:
            self.fh.close()


def reader_loop(radio, log, stop):
    """Read every input report until `stop`; survive re-enumeration."""
    while not stop.is_set():
        fd = radio.fd
        if fd is None:
            break
        try:
            r, _, _ = select.select([fd], [], [], 0.2)
            if not r:
                continue
            raw = os.read(fd, 4096)
        except (OSError, ValueError, TypeError) as e:
            if stop.is_set():
                break
            log.event("read-error", err=str(e))
            if not radio.reopen():
                log.event("reader-gave-up")
                break
            continue
        if raw:
            try:
                log.rx(raw)
            except Exception as e:          # a decode/log bug must never stop the reader
                log.event("rx-handler-error", err=repr(e), hex=raw[:16].hex())


# --------------------------------------------------------------------------------------------
# Live modes
# --------------------------------------------------------------------------------------------

def warn_if_monado_running():
    for p in glob.glob("/proc/[0-9]*/comm"):
        try:
            name = open(p).read().strip()
        except OSError:
            continue
        if name in ("monado-service", "hello_xr", "vrserver"):
            print("WARNING: %s (pid %s) is running; it may hold or fight over the headset hidraw. "
                  "Stop it first." % (name, p.split("/")[2]), file=sys.stderr)


def tx_feature(radio, log, label, payload, pair_ok=False):
    t_send = log.ms()                   # stamped BEFORE the (synchronous) control transfer
    ok, err = radio.send_feature(payload, pair_ok)
    log.tx(label, payload, ok, err, t_send)
    return ok


def tx_output(radio, log, label, payload):
    t_send = log.ms()
    ok, err = radio.send_output(payload)
    log.tx(label, payload, ok, err, t_send)
    return ok


def send_pair(radio, log, hand, confirmed):
    """THE only place a PAIR (16 05) is built.  Sent exactly once, never retried."""
    if not confirmed:
        raise RuntimeError("PAIR requires %s" % CONFIRM_FLAG)
    if hand not in HAND_NAMES:
        raise RuntimeError("PAIR hand must be 0 or 1")
    return tx_feature(radio, log, "PAIR 16 05 %02x (%s)" % (hand, hand_name(hand)),
                      [RID_BT_CONTROL, BT_PAIR, hand], pair_ok=True)


PREAMBLE_GAP_S = 6.4        # Windows: 02 07 at 134.036, next 02 0b at 134.363 and 140.837 (~6.5 s quiet)


def preamble_plan(burst):
    """The host setup Windows sends before the PAIR in pairing3.pcapng, in the order seen, as
    ("out", sub) = Output 02 <sub>, ("poll", n) = n x Output 02 08, ("gap", seconds).  Run-length
    compressed, the capture (host Output reports, t=133.18-141.26) reads:
        0b 04 | 08x417 | 06 | 08x4 | 0b 0b 04 | 08x417 | 06 | 08x4 | 07 | 0b | (gap) | 0b 04 |
        08x417 | 06 | 08x4 | 07          then Feature 16 09 <hand> at 141.32
    i.e. three identical groups of (about burst/3) 02 08 polls around one 02 06.  --selftest
    compares this plan against the capture.  The sixth 02 0b of the capture is at t=214.9, after
    the PAIR, so it is not part of the preamble."""
    per_group = max(5, burst // 3)
    group = [("poll", per_group - 4), ("out", 0x06), ("poll", 4)]
    return ([("out", 0x0B), ("out", 0x04)] + group +
            [("out", 0x0B), ("out", 0x0B), ("out", 0x04)] + group + [("out", 0x07)] +
            [("out", 0x0B), ("gap", PREAMBLE_GAP_S), ("out", 0x0B), ("out", 0x04)] + group +
            [("out", 0x07)])


def plan_signature(steps):
    """Run-length compressed Output-report order of a plan: ['0b', '04', '08', '06', ...]
    (poll bursts collapse to '08'; gaps are dropped)."""
    sig = []
    for kind, arg in steps:
        tok = "08" if kind == "poll" else "%02x" % arg if kind == "out" else None
        if tok and (not sig or sig[-1] != tok):
            sig.append(tok)
    return sig


def windows_preamble(radio, log, wait, burst, sleep, hand, gap=PREAMBLE_GAP_S):
    """Replay the Windows host setup (see preamble_plan) and then Feature 16 09 <hand>.
    Aborts (returns False) if sends keep failing, so a dead link never leads to a blind PAIR."""
    fails = 0

    def out(sub, label=None):
        nonlocal fails
        if not tx_output(radio, log, label or "quiet:02 %02x" % sub, [RID_OUT_CONTROL, sub]):
            fails += 1
        return fails < 4

    steps = preamble_plan(burst)
    log.event("preamble-start", steps=len(steps), polls=sum(a for k, a in steps if k == "poll"))
    for kind, arg in steps:
        if kind == "poll":
            log.event("preamble-02-08-burst", count=arg)
            ok = True
            for _ in range(arg):
                ok = out(0x08)
                if not ok:
                    break
                sleep(0.001)
        elif kind == "gap":
            log.event("preamble-gap", seconds=gap)
            sleep(gap)
            ok = True
        else:
            ok = out(arg, "Output 02 %02x" % arg)
            sleep(0.005)
        if not ok:
            log.event("preamble-aborted", reason="too many failed sends; PAIR will NOT be sent")
            return False
    # Windows sent 16 09 about 63 ms after the last 02 07.
    if not tx_feature(radio, log, "Feature 16 09 %02x (CMD_STATUS)" % hand, [RID_BT_CONTROL, BT_CMD_STATUS, hand]):
        log.event("preamble-aborted", reason="16 09 failed; PAIR will NOT be sent")
        return False
    if isinstance(radio, DryRadio):
        log.event("preamble-wait-skipped", seconds=wait, note="dry run")
        return True
    log.event("preamble-wait", seconds=wait)
    t_end = time.monotonic() + wait
    while time.monotonic() < t_end:
        time.sleep(min(10.0, max(0.0, t_end - time.monotonic())))
        left = t_end - time.monotonic()
        if left > 0.5:
            log.event("preamble-waiting", seconds_left=round(left))
    return True


def summarize(log):
    """Which of the reference markers did the headset produce?"""
    texts = []
    for ev in log.seen:
        if ev["kind"] == "fwlog":
            texts += [e["text"] for e in ev["entries"]]
        elif ev["kind"] == "btlog":
            texts.append(ev["text"])
    marks = [("fw 'Received pair request'", "Received pair request"),
             ("fw 'New pairingStatus'", "New pairingStatus"),
             ("bt COMMAND_SET_VISIBILITY", "COMMAND_SET_VISIBILITY"),
             ("bt COMMAND_SET_PAIRING_MODE", "SET_PAIRING_MODE"),
             ("bt COMMAND_INQUIRY", "COMMAND_INQUIRY"),
             ("bt 'inquiry started'", "inquiry started"),
             ("fw 'CmdStatus Success'", "CmdStatus Success"),
             ("bt 'Found by address'", "Found by address")]
    print("\n== summary: %d input reports (%d decoded non-stream), reference markers seen =="
          % (log.total_rx, len(log.seen)))
    for label, needle in marks:
        print("  %-30s %s" % (label, "YES" if any(needle in t for t in texts) else "no"))
    flags = [(ev["hand"], ev["flag"], ev["flag_name"]) for ev in log.seen if ev["kind"] == "bt_ctrl" and "flag" in ev]
    for h, f, n in flags:
        print("  16 09 reply: %s flag=%d (%s)" % (hand_name(h), f, n))
    st = {h: s for h, s in ((e["hand"], e["state_name"]) for e in log.seen if e["kind"] == "ctrl_status")}
    for h in sorted(st):
        print("  last 0x17 status: %s = %s" % (hand_name(h), st[h]))


def run_live(args, hand):
    default_secs = {"single_pair": 40.0, "status": 4.0, "listen": 40.0}
    mode = ("single_pair" if args.single_pair is not None else
            "status" if args.status is not None else "listen")
    secs = args.seconds if args.seconds is not None else default_secs[mode]
    log_path = None if args.no_log else (args.log or time.strftime("controller-pair-v2-%Y%m%d-%H%M%S.jsonl"))
    sleep = (lambda s: None) if args.dry_run else time.sleep

    dev = None
    if not args.dry_run:
        dev = args.device or find_radio_dev()
        if args.device and args.device not in [d for d, _ in hidraw_candidates()]:
            sys.exit("--device %s is not a hidraw node of 045e:0659 (candidates: %s); refusing to send "
                     "HID ioctls to anything else." % (args.device, hidraw_candidates() or "none"))
        if not dev:
            cands = hidraw_candidates()
            sys.exit("cannot pick the headset radio hidraw (045e:0659, interface 2). candidates: %s. "
                     "Use --device /dev/hidrawN." % (cands or "none"))
        warn_if_monado_running()
    log = Log(log_path, args.full_hex)       # opened only once we know there is something to log
    if args.dry_run:
        radio = DryRadio()
        print("DRY RUN: nothing is opened or sent; listen windows and waits are skipped.")
    else:
        try:
            radio = Radio(dev, log)
        except OSError as e:
            log.close()
            if log_path and os.path.exists(log_path):
                os.unlink(log_path)              # do not leave an empty log behind
            if isinstance(e, PermissionError):
                sys.exit("no permission for %s -- need group plugdev (see scripts/70-wmr-reverb.rules)" % dev)
            sys.exit("cannot open %s: %s" % (dev, e))
    print("device: %s   mode: %s   listen: %.0f s   log: %s" % (radio.path, mode, secs, log_path or "(none)"))

    stop = threading.Event()
    th = None
    rc = 0
    if not args.dry_run:
        # The reader is started BEFORE anything is sent.  The hidraw queue also buffers reports from
        # the moment the fd was opened, but only 64 of them, and the 0x01 stream alone is ~250/s.
        th = threading.Thread(target=reader_loop, args=(radio, log, stop), daemon=True)
        th.start()
    try:
        if mode == "listen":
            print("passive listen, sending nothing.")
            sleep(secs)
        elif mode == "status":
            print("status query for the %s controller: 16 08 then 16 04 (no PAIR, no UNPAIR)." % hand_name(hand))
            tx_feature(radio, log, "Feature 16 08 %02x (PAIRING_STATUS)" % hand, [RID_BT_CONTROL, BT_PAIRING_STATUS, hand])
            sleep(0.5)
            tx_feature(radio, log, "Feature 16 04 %02x (ONLINE_STATUS)" % hand, [RID_BT_CONTROL, BT_ONLINE_STATUS, hand])
            sleep(secs)
        else:
            print("*** PAIR %s controller: this ERASES its current bond on the headset radio. ***" % hand_name(hand))
            if args.windows_preamble:
                if not windows_preamble(radio, log, args.preamble_wait, args.preamble_burst, sleep, hand,
                                        args.preamble_gap):
                    rc = 3
            if rc == 0:
                print("controller must be in discovery NOW (slow-pulse LEDs) -- sending ONE PAIR.")
                t_pair = time.monotonic()
                if not send_pair(radio, log, hand, args.confirmed or args.dry_run):
                    log.event("pair-send-failed", note="not retried")
                if args.dry_run:
                    if args.poll_status:
                        tx_feature(radio, log, "Feature 16 09 %02x (CMD_STATUS, once at PAIR+20 s)" % hand,
                                   [RID_BT_CONTROL, BT_CMD_STATUS, hand])
                else:
                    polled = False
                    while time.monotonic() - t_pair < secs:
                        time.sleep(0.2)
                        if args.poll_status and not polled and time.monotonic() - t_pair >= 20.0:
                            polled = True
                            tx_feature(radio, log, "Feature 16 09 %02x (CMD_STATUS, once)" % hand,
                                       [RID_BT_CONTROL, BT_CMD_STATUS, hand])
    finally:
        stop.set()
        if th:
            th.join(timeout=2)
        radio.close()
    summarize(log)
    log.close()
    if log_path:
        print("JSONL log: %s" % log_path)
    return rc


# --------------------------------------------------------------------------------------------
# --selftest: decode the Windows capture with tshark
# --------------------------------------------------------------------------------------------

def tshark(pcap, display_filter, fields):
    # (no `-c`: tshark counts packets READ, not packets matching -Y, so it would stop too early)
    cmd = ["tshark", "-r", pcap, "-Y", display_filter, "-T", "fields", "-E", "separator=/t"]
    for f in fields:
        cmd += ["-e", f]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 and not p.stdout:
        sys.exit("tshark failed: %s" % p.stderr.strip()[:300])
    rows = []
    for line in p.stdout.splitlines():
        cols = line.split("\t")
        cols += [""] * (len(fields) - len(cols))
        rows.append(cols)
    return rows


def selftest(pcap, window):
    """USBPcap structure used (verified on pairing3.pcapng, tshark 4.4):
       host->device control: usb.bmRequestType==0x21 (class, interface), HID SET_REPORT; the report
         bytes live in usb.data_fragment; usbhid.setup.wValue/wIndex/wLength give the setup stage.
       device->host interrupt-IN: usb.src == "<bus>.<dev>.4" (endpoint 0x84, interface 2); the report
         bytes (first byte = report id) are in usbhid.data -- NOT usb.capdata."""
    if not os.path.exists(pcap):
        sys.exit("capture not found: %s" % pcap)
    rows = tshark(pcap, 'usb.bmRequestType==0x21 && usb.data_fragment[0:2]==16:05',
                  ["frame.number", "frame.time_relative", "usb.bus_id", "usb.device_address",
                   "usbhid.setup.wValue", "usbhid.setup.wIndex", "usbhid.setup.wLength", "usb.data_fragment"])
    if not rows:
        sys.exit("no Feature 16 05 (PAIR) found in %s" % pcap)
    if len(rows) > 1:
        print("note: %d PAIR frames in the capture, using the first" % len(rows))
    fno, t_pair, bus, dev, wval, widx, wlen, frag = rows[0]
    fno, t_pair = int(fno), float(t_pair)
    src = "%s.%s.4" % (bus, dev)
    t_from, t_to = window if window else (t_pair - 48.0, t_pair + 2.5)
    detail_from = t_pair - 0.05
    print("selftest: %s" % pcap)
    print("PAIR frame %d t=%.4f bus=%s dev=%s wValue=%s wIndex=%s wLength=%s payload=%s"
          % (fno, t_pair, bus, dev, wval, widx, wlen, bytes.fromhex(frag)[:4].hex(" ")))
    print("analysing t=%.3f .. %.3f, device->host source %s (ep 0x84)\n" % (t_from, t_to, src))

    flt = ('frame.time_relative>=%f && frame.time_relative<=%f && ('
           '(usb.src=="%s" && usbhid.data) || '
           '(usb.bmRequestType==0x21 && usb.device_address==%s && usb.data_fragment))' % (t_from, t_to, src, dev))
    rows = tshark(pcap, flt, ["frame.number", "frame.time_relative", "usb.src", "usbhid.data",
                              "usb.data_fragment", "usbhid.setup.wValue", "usbhid.setup.wIndex",
                              "usbhid.setup.wLength"])
    unpair_seen = False
    facts = {}                       # name -> (t, frame)
    out_counts = collections.Counter()
    in_counts = collections.Counter()
    last_status = {}
    cmdstatus_times = []
    bad_setups = []                  # host reports whose setup stage is not what we send

    def note(name, t, f):
        facts.setdefault(name, (t, f))

    for fno_s, t_s, src_s, data, frag, wv, wi, wl in rows:
        t, f = float(t_s), int(fno_s)
        if frag and not data:                                   # host -> device control
            raw = bytes.fromhex(frag)
            key = raw[:2].hex()
            # 0x16 goes out as Feature (wValue 0x03xx), 0x02 as Output (0x02xx); always interface 2, 64 bytes.
            want_wv = "0x%02x%02x" % (3 if raw[0] == RID_BT_CONTROL else 2, raw[0])
            if (wv, wi, wl, len(raw)) != (want_wv, "2", "64", 64) and raw[0] in (RID_BT_CONTROL, RID_OUT_CONTROL):
                bad_setups.append((f, key, wv, wi, wl, len(raw)))
            if raw[0] == RID_BT_CONTROL:
                print("[%9.4f] TX   frame %-6d Feature wValue=%s wIndex=%s wLength=%s: %s"
                      % (t, f, wv, wi, wl, raw[:6].hex(" ")))
                if raw[1] in (0x06, 0x07):
                    unpair_seen = True
                if raw[1] == BT_PAIR:
                    note("pair_tx", t, f)
                    facts["pair_setup"] = (wv, wi, wl)
                if raw[1] == BT_CMD_STATUS:
                    note("cmd_status_tx", t, f)
            else:
                out_counts[key] += 1
            continue
        raw = bytes.fromhex(data)
        ev = decode_report(raw)
        in_counts[ev["rid"]] += 1
        show = t >= detail_from or ev["kind"] == "bt_ctrl"
        if ev["kind"] == "ctrl_status":
            sig = (ev["state"], ev.get("vid"), ev.get("pid"))
            if last_status.get(ev["hand"]) == sig:
                show = False
            last_status[ev["hand"]] = sig
            show = show and t >= detail_from
        if ev["kind"] == "other":
            show = False
        if show:
            for line in describe(ev, False, raw):
                print("[%9.4f] RX   frame %-6d %s" % (t, f, line))
        if ev["kind"] == "fwlog":
            for e in ev["entries"]:
                if t < detail_from:
                    continue
                if e["text"].startswith("Received pair request MC: 0"):
                    note("fw_pair_req", t, f)
                elif e["text"].startswith("MC:0, New pairingStatus: 1"):
                    note("fw_status1", t, f)
                elif "CmdStatus Success" in e["text"] and t >= detail_from:
                    cmdstatus_times.append(t)       # several per PAIR; the facts cite the last one
        elif ev["kind"] == "btlog":
            for name, needle in (("bt_visibility", "COMMAND_SET_VISIBILITY"),
                                 ("bt_pairmode", "SET_PAIRING_MODE"),
                                 ("bt_allowed", "Set the pairing allowed to 1"),
                                 ("bt_inquiry", "COMMAND_INQUIRY"),
                                 ("bt_started", "inquiry started"),
                                 ("bt_found", "Found by address: Motion Controller - Left")):
                if needle in ev["text"] and t >= detail_from:
                    note(name, t, f)
        elif ev["kind"] == "bt_ctrl" and ev["cmd"] == BT_CMD_STATUS and "flag" in ev:
            if t < t_pair:
                note("reply_09", t, f)
                facts["reply_09_flag"] = ev["flag"]

    print("\nhost Output reports in window (counts): %s"
          % ", ".join("%s x%d" % (k, v) for k, v in sorted(out_counts.items())))
    print("device->host reports in window by id (counts): %s"
          % ", ".join("0x%02x x%d" % (k, v) for k, v in sorted(in_counts.items())))

    def rel(name):
        return facts[name][0] - facts["pair_tx"][0] if name in facts and "pair_tx" in facts else None

    checks = []

    def check(label, ok, detail=""):
        checks.append(ok)
        print("  [%s] %s %s" % ("PASS" if ok else "FAIL", label, detail))

    print("\nchecks against the known facts:")
    check("PAIR Feature 16 05 00, frame 53970, t=188.3308",
          "pair_tx" in facts and facts["pair_tx"][1] == 53970 and abs(facts["pair_tx"][0] - 188.3308) < 5e-4,
          "(frame %s t=%s)" % (facts.get("pair_tx", ("?", "?"))[1], facts.get("pair_tx", ("?", "?"))[0]))
    ps = facts.get("pair_setup", ("?", "?", "?"))
    check("PAIR setup wValue 0x0316, wIndex 2, wLength 64",
          ps[0] == "0x0316" and ps[1] == "2" and ps[2] == "64", "(%s, %s, %s)" % ps)
    r = rel("fw_pair_req")
    check("0x03 'Received pair request MC: 0' about 1 ms after PAIR", r is not None and 0 <= r < 0.005,
          "(+%.1f ms)" % (r * 1000) if r is not None else "(missing)")
    r = rel("fw_status1")
    check("0x03 'MC:0, New pairingStatus: 1'", r is not None and 0 <= r < 0.005,
          "(+%.1f ms)" % (r * 1000) if r is not None else "(missing)")
    for name, label in (("bt_visibility", "0x05 COMMAND_SET_VISIBILITY"), ("bt_pairmode", "0x05 SET_PAIRING_MODE"),
                        ("bt_allowed", "0x05 'Set the pairing allowed to 1'"), ("bt_inquiry", "0x05 COMMAND_INQUIRY"),
                        ("bt_started", "0x05 'inquiry started'")):
        r = rel(name)
        check(label + " within 10 ms of PAIR", r is not None and 0 <= r < 0.010,
              "(+%.1f ms)" % (r * 1000) if r is not None else "(missing)")
    near = [t for t in cmdstatus_times if abs(t - 188.3414) < 5e-4]
    check("0x03 'CmdStatus Success' at ~188.3414 (%d such entries after the PAIR, at %s)"
          % (len(cmdstatus_times), ", ".join("%.4f" % t for t in sorted(set(cmdstatus_times)))),
          bool(near), "(match)" if near else "(missing)")
    check("0x05 'Found by address: Motion Controller - Left' at ~189.5137",
          "bt_found" in facts and abs(facts["bt_found"][0] - 189.5137) < 5e-4,
          "(t=%.4f)" % facts["bt_found"][0] if "bt_found" in facts else "(missing)")
    check("0x16 reply to 16 09 00 at ~141.3247 has flag 0 (complete)",
          "reply_09" in facts and abs(facts["reply_09"][0] - 141.3247) < 5e-4 and facts.get("reply_09_flag") == 0,
          "(t=%.4f flag=%s)" % (facts["reply_09"][0], facts.get("reply_09_flag")) if "reply_09" in facts else "(missing)")
    check("every host 0x16 report is Feature (wValue 0x0316, wIndex 2, wLength 64) and every 0x02 report is "
          "Output (0x0202, 2, 64) in the window", not bad_setups,
          "(%d deviations %s)" % (len(bad_setups), bad_setups[:3]) if bad_setups else "")
    check("no host 16 06 (UNPAIR) / 16 07 anywhere in the window",
          not any(k in ("1606", "1607") for k in out_counts) and not unpair_seen, "")

    # The preamble the script replays must match the capture's host Output order before the first 16 09.
    if "cmd_status_tx" in facts:
        prow = tshark(pcap, 'usb.bmRequestType==0x21 && usb.device_address==%s && usb.data_fragment[0:1]==02 '
                            '&& frame.time_relative<%f' % (dev, facts["cmd_status_tx"][0]),
                      ["frame.number", "usb.data_fragment"])
        subs = [bytes.fromhex(r[1])[1] for r in prow if r[1]]
        cap_sig = []
        for b in subs:
            tok = "%02x" % b
            if not cap_sig or cap_sig[-1] != tok:
                cap_sig.append(tok)
        plan = preamble_plan(len(
            [b for b in subs if b == 0x08]))
        plan_sig = plan_signature(plan)
        polls = sum(a for k, a in plan if k == "poll")
        check("preamble_plan() order matches the capture's host Output order before the first 16 09 "
              "(%d reports)" % len(subs), cap_sig == plan_sig,
              "" if cap_sig == plan_sig else "\n    capture %s\n    plan    %s" % (cap_sig, plan_sig))
        check("plan 02 08 count equals the capture's (%d)" % subs.count(0x08), polls == subs.count(0x08),
              "(plan %d)" % polls)
        check("plan 02 0b/04/06/07 counts match the capture before the PAIR",
              all(sum(1 for k, a in plan if k == "out" and a == b) == subs.count(b) for b in (0x0B, 0x04, 0x06, 0x07)),
              "(capture 0b=%d 04=%d 06=%d 07=%d)" % tuple(subs.count(b) for b in (0x0B, 0x04, 0x06, 0x07)))
    print("\nSELFTEST %s: %d/%d checks passed" % ("OK" if all(checks) else "FAILED", sum(checks), len(checks)))
    return 0 if all(checks) else 1


# --------------------------------------------------------------------------------------------

def parse_hand(s):
    try:
        return HAND_IDS[s.lower()]
    except KeyError:
        raise argparse.ArgumentTypeError("hand must be L or R (left/right)")


def main():
    ap = argparse.ArgumentParser(
        description="Pair a G2 controller to the HEADSET radio and decode everything the headset "
                    "reports (0x03 firmware log, 0x05 BT radio log, 0x16 replies, 0x17 status). "
                    "Read the module docstring (head of this file) for the reference timeline.",
        epilog="Never sends UNPAIR (16 06). PAIR erases the current bond of that hand and needs "
               + CONFIRM_FLAG + ". Examples:\n"
               "  controller-pair-v2.py --listen --seconds 60\n"
               "  controller-pair-v2.py --status R\n"
               "  controller-pair-v2.py --single-pair L --windows-preamble --poll-status " + CONFIRM_FLAG + "\n"
               "  controller-pair-v2.py --selftest /mnt/nvme/debug_vr/pairing3.pcapng",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--single-pair", type=parse_hand, metavar="L|R",
                   help="send exactly one Feature `16 05 <0|1>` (64 bytes, zero padded), then listen. "
                        "DESTRUCTIVE: requires " + CONFIRM_FLAG)
    g.add_argument("--status", type=parse_hand, metavar="L|R",
                   help="send only `16 08` (pairing state) and `16 04` (online state) for that hand, then listen")
    g.add_argument("--listen", action="store_true", help="passive: send nothing, decode and log all input reports")
    g.add_argument("--selftest", metavar="PCAP",
                   help="offline: decode the Windows capture (pairing3.pcapng) with tshark and check the known "
                        "facts. No device needed.")
    ap.add_argument("--selftest-window", type=float, nargs=2, metavar=("T0", "T1"),
                    help="capture-relative seconds to analyse (default: 48 s before the PAIR to 2.5 s after)")
    ap.add_argument("--device", metavar="/dev/hidrawN",
                    help="override device discovery (default: hidraw of 045e:0659 on USB interface 2)")
    ap.add_argument("--seconds", type=float, default=None,
                    help="how long to listen (default 40 for --single-pair/--listen, 4 for --status; "
                         "for --single-pair it counts from the PAIR)")
    ap.add_argument("--windows-preamble", action="store_true",
                    help="with --single-pair: first replay the Windows host setup (Output 02 0b/06/04, a short "
                         "02 08 burst, 02 07 IMU on, Feature 16 09 <hand>), then wait --preamble-wait before the PAIR")
    ap.add_argument("--preamble-wait", type=float, default=45.0,
                    help="seconds to idle between the preamble and the PAIR (Windows: ~47 s; default 45)")
    ap.add_argument("--preamble-gap", type=float, default=PREAMBLE_GAP_S,
                    help="seconds of quiet inside the preamble (Windows: ~6.4 s between the first 02 07 and the "
                         "last 02 0b/04 group; default %.1f)" % PREAMBLE_GAP_S)
    ap.add_argument("--preamble-burst", type=int, default=120,
                    help="total number of Output `02 08` polls in the preamble, ~1 ms apart (Windows: 1263; default 120)")
    ap.add_argument("--poll-status", action="store_true",
                    help="with --single-pair: send Feature `16 09 <hand>` once at PAIR+20 s")
    ap.add_argument(CONFIRM_FLAG, dest="confirmed", action="store_true",
                    help="required for --single-pair: acknowledges the PAIR erases the hand's current bond")
    ap.add_argument("--log", metavar="FILE", help="JSONL log path (default controller-pair-v2-<time>.jsonl in the cwd)")
    ap.add_argument("--no-log", action="store_true", help="do not write a JSONL log")
    ap.add_argument("--full-hex", action="store_true",
                    help="log/print full hex for unknown reports (default: first 24 bytes in the JSONL)")
    ap.add_argument("--dry-run", action="store_true",
                    help="open nothing, send nothing: print the exact sequence that would be sent")
    args = ap.parse_args()

    if args.selftest:
        return selftest(args.selftest, args.selftest_window)
    if args.windows_preamble and args.single_pair is None:
        ap.error("--windows-preamble only makes sense with --single-pair")
    if args.poll_status and args.single_pair is None:
        ap.error("--poll-status only makes sense with --single-pair")
    hand = args.single_pair if args.single_pair is not None else args.status
    if args.single_pair is not None:
        print("PAIR target: %s controller (hand id %d)." % (hand_name(hand), hand))
        if not args.confirmed:
            if args.dry_run:
                print("(dry run: the %s gate is not enforced because nothing is sent)" % CONFIRM_FLAG)
            else:
                sys.exit("refusing to PAIR: this erases the %s controller's CURRENT bond on the headset "
                         "radio. Re-run with %s if that is what you want." % (hand_name(hand), CONFIRM_FLAG))
    return run_live(args, hand if hand is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
