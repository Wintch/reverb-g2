#!/usr/bin/env python3
"""ab-analyze.py -- summarise monado-service logs of the hare_ware constellation A/B (docs/135).

    python3 -I ab-analyze.py [--json] [--bucket 10] LOG [LOG ...]

Reads logs written by ab-run.sh (lines prefixed '@<epoch> ', .log or .log.gz) and, where present,
the sidecars ab-run.sh writes next to them (<base>.usb.log, <base>.kernel.log, <base>.meta).
Also accepts a plain, un-timestamped Monado log (e.g. docs/135's jack-in-hw-*.log.gz): the clock is
then derived from the controller timesync packets (device time, ~real time), which is approximate.

Every pattern below is a literal log string from the hw/nct-10a23daab tree (file:line in
ab-FINDINGS or the hand-over note). Needs the service run with
WMR_LOG=debug CONSTELLATION_TRACKER_LOG=debug (ab-run.sh does that).

Python 3 stdlib only; streams the file, so multi-hundred-MB logs are fine.
"""
import argparse
import gzip
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

PHASES = {0: "INIT", 1: "FIND_INITIAL_OFFSET", 2: "FIND_RIGHT_EDGE", 3: "FIND_LEFT_EDGE",
          4: "REFINE_BLINK_DURATION", 5: "MAINTAIN_OFFSET"}

# One cheap pre-filter so 600 MB logs are not regex-matched line by line.
KEY = re.compile(
    r"Found pose for device|Dropping (?:slow|fast) sample|timesync counter|Entering search phase|"
    r"Triggering resync|companion|reading thread|RECONNECTED|giving up|Hololens Sensors|"
    r"MONADO_MARKER|Using builder|found display mode|AB_TS_END|AB_TS_RESTART|Fast processing for device|"
    r"Adding controller device")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
RE_TS = re.compile(r"^@(\d+\.\d+) ")
RE_POSE = re.compile(r"Found pose for device (-?\d+)")
RE_DROP = re.compile(r"Dropping (slow|fast) sample (\d+) at ts (-?\d+)")
RE_TSYNC = re.compile(r"(Left|Right) controller timesync counter (\d+) led_intensity (\d+) "
                      r"time (\d+) offset (\d+) ramp_width (\d+)")
RE_PHASE = re.compile(r"Entering search phase: (\d+)")
RE_RESYNC = re.compile(r"Triggering resync due to not being visually seen for (\d+) frames")
RE_FAST = re.compile(r"Fast processing for device (-?\d+) succeeded")
RE_COMP_ERR = re.compile(r"Error reading from companion \(HMD control\) device(?: \((\d+) in a row\))?")
RE_RECON = re.compile(r"Companion device RECONNECTED on (\S+) after (\d+) ms dead")
RE_CTRL = re.compile(r"Adding controller device (\d+)")
RE_META = re.compile(r"^(start_epoch|ready_epoch|nudge_epoch|launcher_attempt|controllers_created|host_uptime_at_ready_s): (\S+)")

TWO64 = 1 << 64
TWO63 = 1 << 63


def open_text(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "rt", encoding="utf-8", errors="replace")


def fmt_t(t):
    return "   n/a" if t is None else "%+7.1fs" % t


def sidecar(path, suffix):
    base = re.sub(r"\.log(\.gz)?$", "", path)
    p = base + suffix
    return p if os.path.exists(p) else None


def label_of(path):
    m = re.match(r"ab-(.+)-\d{8}-\d{6}", os.path.basename(path))
    return m.group(1) if m else os.path.basename(path)


class Run:
    def __init__(self, path, bucket):
        self.path = path
        self.label = label_of(path)
        self.bucket = bucket
        self.lines = 0
        self.first_ts = None
        self.last_ts = None
        self.has_wall = False
        # raw event lists: (t_seconds_or_None_if_unknown, payload)
        self.poses = []          # (t, dev)
        self.drops = []          # (t, kind)
        self.tsync = []          # (t, hand, ctr, signed_us, led)
        self.phases = []         # (t, phase)
        self.resyncs = []        # (t, frames)
        self.fastok = []         # (t, dev)
        self.comp_err = []       # (t, n_in_row)
        self.comp_exit = []      # t   (HMD "Exiting reading thread.")
        self.bt_exit = []
        self.reconnects = []     # (t, dead_ms)
        self.holo_err = []
        self.giveup = []
        self.markers = []        # (t, text)
        self.builder = None
        self.ready_t = None
        self.derived_clock = False
        self._dev0 = None        # first timesync device time (us), derived-clock origin
        self._dev_last = None
        self.dur_wall = None
        self.ctrl_added = set()  # controller ids added before the display mode line (existed at builder return)
        self.ctrl_late = set()   # added later: not exposed to the app, not attached to the tracker
        self._mode_seen = False
        self.restarts = 0        # AB_TS_RESTART: launcher retry truncated the raw log
        self.meta_kv = {}        # ready_epoch / nudge_epoch / ... from the .meta sidecar
        self.ready_from_meta = False

    # ---- clock ----------------------------------------------------------------------------
    def now(self, ts):
        """seconds since the first line (wall prefix) or since the first timesync (derived)."""
        if ts is not None:
            return ts - self.first_ts
        if self._dev_last is None:
            return 0.0 if self._dev0 is None else None
        return (self._dev_last - self._dev0) / 1e6

    def load_meta(self):
        meta = sidecar(self.path, ".meta")
        if not meta:
            return
        with open(meta, "rt", errors="replace") as f:
            for ln in f:
                m = RE_META.match(ln)
                if m:
                    self.meta_kv[m.group(1)] = m.group(2)

    def reset_events(self):
        """A launcher retry truncated the raw log: drop what the failed attempt produced."""
        self.poses, self.drops, self.tsync, self.phases = [], [], [], []
        self.resyncs, self.fastok, self.comp_err, self.comp_exit = [], [], [], []
        self.bt_exit, self.reconnects, self.holo_err, self.giveup = [], [], [], []
        self.markers, self.ctrl_added, self.ctrl_late, self._mode_seen = [], set(), set(), False
        self.builder = None
        self.ready_t = None
        self.restarts += 1

    def parse(self):
        last = ""
        self.load_meta()
        with open_text(self.path) as f:
            for line in f:
                self.lines += 1
                if self.lines == 1:
                    m = RE_TS.match(line)
                    if m:
                        self.first_ts = float(m.group(1))
                        self.has_wall = True
                # The trailer and the post-stop 'down' marker are written after the service is gone;
                # they must not stretch the observed span (a 10 s tail would fake a "went quiet").
                if "AB_TS_END" not in line and "MONADO_MARKER: down" not in line:
                    last = line
                if not KEY.search(line):
                    continue
                if "AB_TS_RESTART" in line:
                    self.reset_events()
                    continue
                ts = None
                if self.has_wall:
                    m = RE_TS.match(line)
                    if m:
                        ts = float(m.group(1))
                self._event(ANSI.sub("", line), ts)
        if self.has_wall:
            m = RE_TS.match(last)
            if m:
                self.last_ts = float(m.group(1))
                self.dur_wall = self.last_ts - self.first_ts
        elif self._dev0 is not None and self._dev_last is not None:
            self.dur_wall = (self._dev_last - self._dev0) / 1e6
        self.derived_clock = not self.has_wall and self._dev0 is not None
        # The launcher's 'MONADO_MARKER: up' is appended with >> while the service keeps writing at
        # its own offset, so it is usually overwritten (verified with a shell experiment). The
        # runner records the ready time out of band; prefer the marker only when it survived.
        if self.has_wall and self.ready_t is None and "ready_epoch" in self.meta_kv:
            try:
                self.ready_t = float(self.meta_kv["ready_epoch"]) - self.first_ts
                self.ready_from_meta = True
            except ValueError:
                pass

    def _event(self, line, ts):
        if "Found pose for device" in line:
            m = RE_POSE.search(line)
            if m:
                self.poses.append((self.now(ts), int(m.group(1))))
            return
        if "Dropping" in line:
            m = RE_DROP.search(line)
            if m:
                self.drops.append((self.now(ts), m.group(1)))
            return
        if "timesync counter" in line:
            m = RE_TSYNC.search(line)
            if m:
                v = int(m.group(4))
                if v >= TWO63:
                    v -= TWO64
                if not self.has_wall:
                    if self._dev0 is None:
                        self._dev0 = v
                    # accept as the derived clock only if it moves forward sanely (two controllers
                    # interleave; they share the HMD SLAM clock so they agree within ms)
                    if self._dev_last is None or -1_000_000 < v - self._dev_last < 60_000_000:
                        self._dev_last = max(v, self._dev_last or v)
                self.tsync.append((self.now(ts), m.group(1), int(m.group(2)), v, int(m.group(3))))
            return
        if "Entering search phase" in line:
            m = RE_PHASE.search(line)
            if m:
                self.phases.append((self.now(ts), int(m.group(1))))
            return
        if "Triggering resync" in line:
            m = RE_RESYNC.search(line)
            if m:
                self.resyncs.append((self.now(ts), int(m.group(1))))
            return
        if "Fast processing for device" in line:
            m = RE_FAST.search(line)
            if m:
                self.fastok.append((self.now(ts), int(m.group(1))))
            return
        if "Error reading from companion" in line:
            m = RE_COMP_ERR.search(line)
            self.comp_err.append((self.now(ts), int(m.group(1)) if m and m.group(1) else 1))
            return
        if "Error reading from Hololens Sensors" in line:
            self.holo_err.append(self.now(ts))
            return
        if "RECONNECTED" in line:
            m = RE_RECON.search(line)
            self.reconnects.append((self.now(ts), int(m.group(2)) if m else -1))
            return
        if "Exiting reading thread" in line:
            (self.bt_exit if "Bluetooth" in line else self.comp_exit).append(self.now(ts))
            return
        if "giving up" in line:
            self.giveup.append((self.now(ts), line.strip()[:120]))
            return
        if "MONADO_MARKER" in line:
            t = self.now(ts)
            txt = line.split("MONADO_MARKER:", 1)[1].strip()
            self.markers.append((t, txt))
            if txt == "up" and self.ready_t is None:
                self.ready_t = t
            return
        if "Adding controller device" in line:
            m = RE_CTRL.search(line)
            if m:
                (self.ctrl_late if self._mode_seen else self.ctrl_added).add(int(m.group(1)))
            return
        if "Using builder" in line:
            self.builder = line.split("Using builder", 1)[1].strip().split()[0] if self.builder is None else self.builder
            return
        if "found display mode" in line:
            self._mode_seen = True
            return


# ---------------------------------------------------------------------------------------------
def bucketize(events, t0, width, nb):
    """events: list of t (None ignored). returns (pre, [counts...], post)."""
    pre = post = 0
    counts = [0] * nb
    for t in events:
        if t is None:
            continue
        r = t - t0
        if r < 0:
            pre += 1
            continue
        i = int(r // width)
        if i >= nb:
            post += 1
        else:
            counts[i] += 1
    return pre, counts, post


def gaps(times, min_gap):
    ts = sorted(t for t in times if t is not None)
    out = []
    for a, b in zip(ts, ts[1:]):
        if b - a >= min_gap:
            out.append((a, b - a))
    return out


def analyse(run, width):
    r = {}
    t0 = run.ready_t if run.ready_t is not None else 0.0
    end = run.dur_wall if run.dur_wall is not None else 0.0
    nb = max(1, int((end - t0) // width) + 1)
    r["file"] = run.path
    r["label"] = run.label
    r["lines"] = run.lines
    r["clock"] = "wallclock-prefix" if run.has_wall else ("timesync-derived (approximate)" if run.derived_clock else "none")
    r["span_s"] = None if run.dur_wall is None else round(run.dur_wall, 1)
    r["t0"] = ("ready_epoch from .meta" if run.ready_from_meta else "MONADO_MARKER: up") if run.ready_t is not None else "first line"
    r["ready_after_start_s"] = None if run.ready_t is None else round(run.ready_t, 1)
    r["builder"] = run.builder

    ptimes = [t for t, _ in run.poses]
    r["found_pose_total"] = len(run.poses)
    r["found_pose_by_device"] = dict(Counter(d for _, d in run.poses))
    known = [t for t in ptimes if t is not None]
    r["first_pose_since_start_s"] = None if not known else round(min(known), 2)
    r["first_pose_since_ready_s"] = None if not known else round(min(known) - t0, 2)
    r["last_pose_since_ready_s"] = None if not known else round(max(known) - t0, 2)
    pre, pc, post = bucketize(ptimes, t0, width, nb)
    r["pose_buckets"] = {"pre": pre, "per_bucket": pc, "post": post}
    # PROTOCOL C2 measure: Found pose lines in the first 60 s after ready (both hands)
    r["poses_first_60s"] = sum(1 for t in known if 0 <= t - t0 < 60)
    r["controllers_created"] = sorted(run.ctrl_added)
    r["controllers_added_late"] = sorted(run.ctrl_late)
    r["launcher_attempt"] = run.meta_kv.get("launcher_attempt")
    r["log_restarts"] = run.restarts

    # PROTOCOL C3: did the tracker resume after the nudge (controllers picked up and shaken)?
    nudge = None
    if run.has_wall and "nudge_epoch" in run.meta_kv:
        try:
            nudge = float(run.meta_kv["nudge_epoch"]) - run.first_ts
        except ValueError:
            nudge = None
    if nudge is not None:
        before10 = sum(1 for t in known if nudge - 10 <= t < nudge)
        before30 = sum(1 for t in known if nudge - 30 <= t < nudge)
        after = sorted(t for t in known if t >= nudge)
        r["nudge"] = {"at_since_ready_s": round(nudge - t0, 1), "poses_10s_before": before10,
                      "poses_30s_before": before30,
                      "poses_15s_after": sum(1 for t in after if t < nudge + 15),
                      "first_pose_after_s": None if not after else round(after[0] - nudge, 1)}
    else:
        r["nudge"] = None
    dt = [t for t, _ in run.drops]
    r["drop_slow"] = sum(1 for _, k in run.drops if k == "slow")
    r["drop_fast"] = sum(1 for _, k in run.drops if k == "fast")
    r["drop_buckets"] = bucketize([t for t, k in run.drops if k == "slow"], t0, width, nb)[1]
    r["fast_ok_total"] = len(run.fastok)

    # per-device tracked-ness proxy: gaps between Found pose lines (the service logs no explicit
    # tracked/lost event; hello_xr's pos:OK/trk:OK is client-side, and a lost controller keeps
    # reporting its stale pose as TRACKED -- docs/135 -- so only this proxy is meaningful)
    dev = {}
    for d in sorted(set(d for _, d in run.poses)):
        ts = [t for t, dd in run.poses if dd == d and t is not None]
        g = gaps(ts, 2.0)
        dev[d] = {"poses": len(ts), "first": round(min(ts) - t0, 1), "last": round(max(ts) - t0, 1),
                  "gaps_over_2s": len(g), "longest_gap_s": round(max([x for _, x in g] or [0]), 1)}
    r["per_device"] = dev

    # timesync
    ts = run.tsync
    r["tsync_total"] = len(ts)
    tsr = {}
    for hand in ("Left", "Right"):
        rows = [(t, c, v) for t, h, c, v, _ in ts if h == hand]
        if not rows:
            continue
        vals = [v for _, _, v in rows]
        back = 0
        worst_back = 0
        jumps = 0
        for a, b in zip(vals, vals[1:]):
            if b < a - 1000:          # > 1 ms backwards
                back += 1
                worst_back = max(worst_back, a - b)
            if b - a > 1_000_000:     # > 1 s forward in one packet interval
                jumps += 1
        ctr_bad = sum(1 for (_, c1, _), (_, c2, _) in zip(rows, rows[1:]) if c2 != (c1 % 3) + 1)
        rate = None
        wt = [t for t, _, _ in rows if t is not None]
        if run.has_wall and len(rows) > 10 and wt[-1] - wt[0] > 5:
            rate = round((vals[-1] - vals[0]) / 1e6 / (wt[-1] - wt[0]), 4)
        # What clock does the first packet imply? fix arm: time ~ headset clock itself.
        # no-fix arm: time = headset_clock - host_monotonic, so time + host uptime(at that line)
        # recovers the headset clock (host uptime from /proc/uptime at ready, advanced by wall time).
        implied = None
        if run.has_wall and "host_uptime_at_ready_s" in run.meta_kv and "ready_epoch" in run.meta_kv and rows[0][0] is not None:
            try:
                up_at_first = float(run.meta_kv["host_uptime_at_ready_s"]) + \
                    (run.first_ts + rows[0][0] - float(run.meta_kv["ready_epoch"]))
                implied = round(vals[0] / 1e6 + up_at_first, 1)
            except ValueError:
                implied = None
        tsr[hand] = {"n": len(rows), "first_us": vals[0], "last_us": vals[-1], "first_plus_host_uptime_s": implied,
                     "first_s": round(vals[0] / 1e6, 3), "last_s": round(vals[-1] / 1e6, 3),
                     "negative": sum(1 for v in vals if v < 0), "backward_steps": back,
                     "worst_backward_us": worst_back, "forward_jumps_over_1s": jumps,
                     "counter_seq_errors": ctr_bad, "device_vs_wall_rate": rate,
                     "advance_s": round((vals[-1] - vals[0]) / 1e6, 2)}
    r["timesync"] = tsr
    r["tsync_buckets"] = bucketize([t for t, *_ in ts], t0, width, nb)[1]
    r["led_intensity_values"] = sorted(set(x[4] for x in ts))

    # LED sync phases (log has no device id: both controllers interleave)
    r["phase_events"] = [(None if t is None else round(t - t0, 1), PHASES.get(p, str(p))) for t, p in run.phases]
    r["phase_counts"] = dict(Counter(PHASES.get(p, str(p)) for _, p in run.phases))
    r["resync_triggers"] = len(run.resyncs)
    r["resync_first_last_s"] = None if not run.resyncs else [
        None if run.resyncs[0][0] is None else round(run.resyncs[0][0] - t0, 1),
        None if run.resyncs[-1][0] is None else round(run.resyncs[-1][0] - t0, 1)]

    # health
    r["companion_read_errors_lines"] = len(run.comp_err)
    r["companion_first_error_s"] = None if not run.comp_err or run.comp_err[0][0] is None else round(run.comp_err[0][0] - t0, 1)
    r["companion_max_in_a_row"] = max([n for _, n in run.comp_err] or [0])
    r["hmd_read_thread_exits"] = [None if t is None else round(t - t0, 1) for t in run.comp_exit]
    r["bt_read_thread_exits"] = len(run.bt_exit)
    r["companion_reconnects"] = [(None if t is None else round(t - t0, 1), ms) for t, ms in run.reconnects]
    r["hololens_sensor_read_errors"] = len(run.holo_err)
    r["giving_up"] = [(None if t is None else round(t - t0, 1), s) for t, s in run.giveup]

    # sidecars
    usb = sidecar(run.path, ".usb.log")
    r["usb_changes"] = []
    if usb:
        with open(usb, "rt", errors="replace") as f:
            for ln in f:
                m = RE_TS.match(ln)
                if m and run.first_ts is not None:
                    r["usb_changes"].append((round(float(m.group(1)) - run.first_ts - t0, 1), ln[m.end():].strip()))
    kern = sidecar(run.path, ".kernel.log")
    r["kernel_usb_events"] = []
    r["kernel_note"] = None
    if kern:
        with open(kern, "rt", errors="replace") as f:
            for ln in f:
                if ln.startswith("#"):
                    r["kernel_note"] = ln.strip()
                    continue
                if re.search(r"USB disconnect|new .*speed USB device|HoloLens|Reverb|03f0|04b4", ln):
                    tt = None
                    m = re.match(r"(\d{4}-\d\d-\d\dT[\d:.]+[+-]\d\d:?\d\d)", ln)
                    if m and run.first_ts is not None:
                        try:
                            tt = round(datetime.fromisoformat(m.group(1)).timestamp() - run.first_ts - t0, 1)
                        except ValueError:
                            tt = None
                    r["kernel_usb_events"].append((tt, ln.strip()[:140]))
    meta = sidecar(run.path, ".meta")
    r["meta"] = {}
    if meta:
        with open(meta, "rt", errors="replace") as f:
            for ln in f:
                for k in ("service_git_head", "service_git_branch", "service_sha256", "time_to_ready_s",
                          "coredumps_since_start", "usb_before", "usb_after_stop", "raw_log_kept"):
                    if ln.startswith(k + ":") or (" " + k + ":") in ln[:60]:
                        r["meta"][k] = ln.split(k + ":", 1)[1].strip()[:120]
    done = sidecar(run.path, ".done")
    if done:
        with open(done, "rt", errors="replace") as f:
            r["done"] = f.readline().strip()

    # verdicts
    flags = []
    if r["found_pose_total"] == 0:
        flags.append("NO_POSES: tracker never logged 'Found pose' (is CONSTELLATION_TRACKER_LOG=debug set?)")
    for hand, d in tsr.items():
        if d["negative"]:
            flags.append("NEGATIVE_TIMESYNC(%s): %d/%d packets carry a negative device time "
                         "(docs/135 double-conversion signature)" % (hand, d["negative"], d["n"]))
        if d["backward_steps"]:
            flags.append("TIMESYNC_NOT_MONOTONIC(%s): %d backward steps, worst %d us" % (hand, d["backward_steps"], d["worst_backward_us"]))
        if d["forward_jumps_over_1s"]:
            flags.append("TIMESYNC_JUMPS(%s): %d forward jumps > 1 s" % (hand, d["forward_jumps_over_1s"]))
        if d["counter_seq_errors"]:
            flags.append("TIMESYNC_COUNTER(%s): %d breaks in the 1,2,3 sequence" % (hand, d["counter_seq_errors"]))
        if d["device_vs_wall_rate"] is not None and not 0.95 <= d["device_vs_wall_rate"] <= 1.05:
            flags.append("TIMESYNC_RATE(%s): device clock advances %.3fx wall time" % (hand, d["device_vs_wall_rate"]))
    if known and run.dur_wall is not None:
        quiet = (end) - max(known)
        if quiet > max(15.0, 1.5 * width):
            tsq = [t for t, *_ in ts if t is not None and t > max(known)]
            flags.append("WENT_QUIET: last Found pose at %+.1fs, then %.1fs with none (timesync packets still flowing "
                         "after that: %s; slow-sample drops after that: %d)" % (
                             max(known) - t0, quiet, "yes" if tsq else "NO", sum(1 for t in dt if t is not None and t > max(known))))
    if run.ctrl_added != {0, 1}:
        flags.append("CONTROLLERS_MISSING: 'Adding controller device N' before the display mode line for: %s (need 0 and 1; they must be "
                     "ONLINE before launch and WMR_LOG=debug must be set) -- run is VOID" % (sorted(run.ctrl_added) or "none"))
    if run.restarts or (run.meta_kv.get("launcher_attempt") not in (None, "1", "unknown")):
        flags.append("LAUNCHER_RETRY: attempt %s, %d raw-log restarts (the launcher relaunched the service; "
                     "only the last attempt's events are counted)" % (run.meta_kv.get("launcher_attempt", "?"), run.restarts))
    nz = r["nudge"]
    if nz is not None:
        if nz["poses_10s_before"] == 0 and nz["poses_15s_after"] > 0:
            flags.append("NUDGE_RESUMED: no poses in the 10 s before the nudge, %d in the 15 s after (first after %.1fs) "
                         "-> idle-controller hypothesis supported" % (nz["poses_15s_after"], nz["first_pose_after_s"]))
        elif nz["poses_10s_before"] == 0:
            flags.append("NUDGE_NO_RESUME: no poses before OR after the nudge (not an idle controller; check camera/timesync flow)")
        else:
            flags.append("NUDGE_NOT_NEEDED: tracker still had %d poses in the 10 s before the nudge" % nz["poses_10s_before"])
    if r["drop_slow"] > 100:
        flags.append("DROPPING_SLOW: %d slow samples dropped (tracker not keeping up or storm)" % r["drop_slow"])
    if run.comp_exit and not run.reconnects:
        flags.append("HMD_READ_THREAD_DEAD: 'Exiting reading thread' at %s with no companion reconnect "
                     "(head IMU + tunnelled controllers gone; !3004 absent or failed)" % r["hmd_read_thread_exits"])
    if run.comp_err and not run.comp_exit:
        flags.append("COMPANION_ERRORS: %d error lines (max %d in a row); read thread survived" % (len(run.comp_err), r["companion_max_in_a_row"]))
    if run.reconnects:
        flags.append("COMPANION_RECONNECTED x%d (USB2 re-enumeration absorbed)" % len(run.reconnects))
    nd = sum(1 for _, e in r["kernel_usb_events"] if "disconnect" in e.lower())
    if nd:
        flags.append("KERNEL_USB_DISCONNECTS: %d 'USB disconnect' lines in the kernel log (USB2 storm)" % nd)
    if run.holo_err or run.giveup:
        flags.append("SENSOR_READ_FAILURES: hololens-sensors errors %d, give-ups %d" % (len(run.holo_err), len(run.giveup)))
    if run.builder and run.builder != "wmr":
        flags.append("WRONG_BUILDER: 'Using builder %s' (Simulated HMD fallback; run is void)" % run.builder)
    r["flags"] = flags
    r["_t0"] = t0
    r["_nb"] = nb
    return r


def bar(counts, width=10):
    return " ".join("%d" % c for c in counts)


def render(r, width):
    o = []
    A = o.append
    A("=" * 100)
    A("VARIANT %s   (%s)" % (r["label"], os.path.basename(r["file"])))
    A("=" * 100)
    if r.get("done"):
        A("done marker : %s" % r["done"])
    for k, v in r["meta"].items():
        A("meta         %-22s %s" % (k, v))
    A("lines=%d  span=%ss  clock=%s  t0=%s%s  builder=%s" % (
        r["lines"], r["span_s"], r["clock"], r["t0"],
        "" if r["ready_after_start_s"] is None else " (ready %.1fs after first line)" % r["ready_after_start_s"],
        r["builder"] or "?"))
    A("")
    A("Found pose : total %d   by device %s" % (r["found_pose_total"], r["found_pose_by_device"]))
    A("              first pose %s after service start, %s after t0; last %s after t0" % (
        r["first_pose_since_start_s"], r["first_pose_since_ready_s"], r["last_pose_since_ready_s"]))
    A("Controllers created (WMR 'Adding controller device N'): %s   launcher attempt: %s   raw-log restarts: %s" % (
        r["controllers_created"], r["launcher_attempt"] or "?", r["log_restarts"]) +
      ("   LATE (not tracked): %s" % r["controllers_added_late"] if r["controllers_added_late"] else ""))
    A("Found pose in the first 60 s after ready (C2): %d" % r["poses_first_60s"])
    if r["nudge"]:
        A("Nudge      : %s" % r["nudge"])
    A("Dropping   : slow %d, fast %d     'Fast processing ... succeeded' lines: %d" % (r["drop_slow"], r["drop_fast"], r["fast_ok_total"]))
    for d, v in r["per_device"].items():
        A("  device %s  : %d poses, first %+.1fs last %+.1fs, %d gaps >2s (longest %.1fs)" % (
            d, v["poses"], v["first"], v["last"], v["gaps_over_2s"], v["longest_gap_s"]))
    A("")
    A("Per %d s bucket since t0 (pre-t0 / each bucket / after-last):" % width)
    pre, pc, post = r["pose_buckets"]["pre"], r["pose_buckets"]["per_bucket"], r["pose_buckets"]["post"]
    nb = len(pc)
    A("  window  %s" % "  ".join("%5s" % ("%d-%d" % (i * width, (i + 1) * width)) for i in range(nb)))
    A("  poses   %s   (pre %d, post %d)" % ("  ".join("%5d" % c for c in pc), pre, post))
    A("  slowdrp %s" % "  ".join("%5d" % c for c in r["drop_buckets"]))
    A("  tsync   %s" % "  ".join("%5d" % c for c in r["tsync_buckets"]))
    A("")
    A("Controller timesync (packet 'time <us>' is the SLAM/device clock; log prints uint64, read as signed):")
    if not r["timesync"]:
        A("  no timesync lines (needs WMR_LOG=debug)")
    for hand, d in r["timesync"].items():
        A("  %-5s n=%d first=%d us (%.3f s) last=%d us (%.3f s) advance=%.2fs" % (
            hand, d["n"], d["first_us"], d["first_s"], d["last_us"], d["last_s"], d["advance_s"]))
        if d["first_plus_host_uptime_s"] is not None:
            A("        first time + host uptime = %.1f s  (the headset clock IF this arm sends device-minus-host, i.e. no-fix; "
              "for the fix arm read 'first' directly)" % d["first_plus_host_uptime_s"])
        A("        negative=%d backward_steps=%d forward_jumps>1s=%d counter_breaks=%d device/wall=%s" % (
            d["negative"], d["backward_steps"], d["forward_jumps_over_1s"], d["counter_seq_errors"], d["device_vs_wall_rate"]))
    if r["timesync"]:
        A("  led_intensity values seen: %s" % r["led_intensity_values"])
    A("")
    A("LED-sync refinement phases (both controllers interleaved; the log line has no device id):")
    A("  counts %s   resync triggers %d %s" % (r["phase_counts"], r["resync_triggers"], r["resync_first_last_s"] or ""))
    ev = r["phase_events"]
    for t, name in ev[:30]:
        A("  %s  %s" % (fmt_t(t), name))
    if len(ev) > 30:
        A("  ... %d more; last: %s %s" % (len(ev) - 30, fmt_t(ev[-1][0]), ev[-1][1]))
    if not ev:
        A("  none (T_LED_SYNC_REFINEMENT_LOG default INFO should print 'Entering search phase')")
    A("")
    A("Link health:")
    A("  companion read error lines %d (first %s, max in a row %d)   HMD read-thread exits %s   BT exits %d" % (
        r["companion_read_errors_lines"], r["companion_first_error_s"], r["companion_max_in_a_row"],
        r["hmd_read_thread_exits"], r["bt_read_thread_exits"]))
    A("  companion RECONNECTED %s   hololens-sensor read errors %d   give-ups %s" % (
        r["companion_reconnects"], r["hololens_sensor_read_errors"], r["giving_up"]))
    if r["usb_changes"]:
        A("  usb watcher (changes only, relative to t0):")
        for t, s in r["usb_changes"][:20]:
            A("    %s  %s" % (fmt_t(t), s))
    if r["kernel_usb_events"] or r["kernel_note"]:
        A("  kernel log: %d usb events %s" % (len(r["kernel_usb_events"]), r["kernel_note"] or ""))
        for t, s in r["kernel_usb_events"][:12]:
            A("    %s  %s" % (fmt_t(t), s))
    A("")
    A("FLAGS: " + ("none" if not r["flags"] else ""))
    for f in r["flags"]:
        A("  * " + f)
    A("")
    return "\n".join(o)


def compare(rs):
    o = ["=" * 100, "COMPARISON", "=" * 100]
    cols = ["label", "poses", "p<60s", "poses/min", "1st pose", "last pose", "slow drops", "tsync<0", "tsync n", "quiet?",
            "ctrls", "comp err", "reconn", "flags"]
    rows = []
    for r in rs:
        span = (r["span_s"] or 0) - (r["ready_after_start_s"] or 0)
        neg = sum(d["negative"] for d in r["timesync"].values())
        n = sum(d["n"] for d in r["timesync"].values())
        quiet = any(f.startswith("WENT_QUIET") for f in r["flags"])
        rows.append([r["label"][:22], r["found_pose_total"], r["poses_first_60s"],
                     "%.0f" % (r["found_pose_total"] / span * 60) if span > 0 else "-",
                     r["first_pose_since_ready_s"], r["last_pose_since_ready_s"], r["drop_slow"], neg, n,
                     "YES" if quiet else "no", "".join(str(c) for c in r["controllers_created"]) or "-",
                     r["companion_read_errors_lines"], len(r["companion_reconnects"]),
                     len(r["flags"])])
    w = [max(len(str(c)), *(len(str(row[i])) for row in rows)) for i, c in enumerate(cols)]
    o.append("  ".join(str(c).ljust(w[i]) for i, c in enumerate(cols)))
    for row in rows:
        o.append("  ".join(str(c).ljust(w[i]) for i, c in enumerate(row)))
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--bucket", type=int, default=10, help="bucket width in seconds (default 10)")
    ap.add_argument("--json", action="store_true", help="print the metrics as JSON instead of text")
    a = ap.parse_args()
    results = []
    for p in a.logs:
        if not os.path.isfile(p):
            sys.stderr.write("not a file: %s\n" % p)
            continue
        if re.search(r"\.(launcher|kernel|usb|raw)\.log$", p):
            sys.stderr.write("skipping sidecar, pass only ab-<label>-<stamp>.log[.gz]: %s\n" % p)
            continue
        run = Run(p, a.bucket)
        run.parse()
        results.append(analyse(run, a.bucket))
    if a.json:
        for r in results:
            r.pop("_t0", None)
            r.pop("_nb", None)
        json.dump(results, sys.stdout, indent=1, default=str)
        print()
        return 0
    for r in results:
        print(render(r, a.bucket))
    if len(results) > 1:
        print(compare(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
