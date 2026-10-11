#!/usr/bin/env python3
"""ab-ts.py -- follow a growing log file and prefix every complete line with '@<epoch.mmm> '.

Monado log lines carry no timestamps (u_logging.c prints only "LEVEL [func] msg"), so the A/B
analyzer's per-10-s buckets need an external clock. The prefix is the wall-clock time at which
this follower SAW the line (poll interval 50 ms), which is plenty for 10 s buckets.

    python3 -I ab-ts.py <in.raw.log> <out.log> <stop-file>

Runs until <stop-file> exists AND the input has been drained to EOF, then writes a final
'@<t> AB_TS_END lines=<n>' line to <out.log> and exits 0. Python 3 stdlib only.

Two real-launcher behaviours this follower has to survive (found reviewing jack-in-wayland.sh):
  * A launcher retry (attempt 2/3) restarts the service with `> $LOG`, i.e. TRUNCATES the file we
    are following. A plain tail would sit past EOF and silently lose the head of the new log. We
    detect truncation / replacement and restart from offset 0, writing an '@<t> AB_TS_RESTART' line
    so the analyzer can discard the failed attempt's events.
  * The launcher appends 'MONADO_MARKER: up' with `>>` while the service keeps writing at its own
    (non-append) file offset, so the next service write overwrites the marker. If we happened to
    read the marker in that window, our offset is 18 bytes into the next service line, so that ONE
    line arrives truncated at its front. Accepted (one line); ab-run.sh also records the ready time
    out of band (.meta ready_epoch) because the marker is not reliable.
"""
import os
import sys
import time


def main(argv):
    if len(argv) != 4:
        sys.stderr.write(__doc__)
        return 2
    src, dst, stop = argv[1], argv[2], argv[3]

    # The input may not exist yet when we start (the launcher creates it).
    while not os.path.exists(src):
        if os.path.exists(stop):
            break
        time.sleep(0.05)

    parent = os.getppid()
    n = 0
    pending = b""
    with open(dst, "wb", buffering=0) as out:
        fin = None
        try:
            while True:
                if fin is None and os.path.exists(src):
                    fin = open(src, "rb")
                if fin is not None:
                    # truncation / replacement of the followed file (launcher retry)
                    try:
                        st = os.stat(src)
                        fst = os.fstat(fin.fileno())
                        if st.st_ino != fst.st_ino or st.st_size < fin.tell():
                            fin.close()
                            fin = open(src, "rb")
                            if pending:
                                out.write(b"@%.3f " % time.time() + pending + b"\n")
                                n += 1
                                pending = b""
                            out.write(b"@%.3f AB_TS_RESTART lines_so_far=%d\n" % (time.time(), n))
                    except OSError:
                        pass
                chunk = fin.read(1 << 20) if fin else b""
                if chunk:
                    pending += chunk
                    *lines, pending = pending.split(b"\n")
                    if lines:
                        now = time.time()
                        buf = bytearray()
                        for ln in lines:
                            buf += b"@%.3f " % now + ln + b"\n"
                        n += len(lines)
                        out.write(bytes(buf))
                    continue
                # EOF for now. A vanished parent (SIGKILLed runner) counts as a stop request.
                if os.path.exists(stop) or os.getppid() != parent:
                    if fin is not None:
                        # one last drain so nothing written just before the stop is lost
                        tail = fin.read()
                        if tail:
                            pending += tail
                            continue
                    break
                time.sleep(0.05)
        finally:
            if pending:
                out.write(b"@%.3f " % time.time() + pending + b"\n")
                n += 1
            out.write(b"@%.3f AB_TS_END lines=%d\n" % (time.time(), n))
            if fin is not None:
                fin.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
