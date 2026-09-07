# 116 — Procmon trace of a full multi-game Oasis session: method and result (2026-09-08)

A Linux-`strace`-equivalent pass over a real Windows VR session: two games, camera passthrough
toggled on and off, captured system-wide with Sysinternals Procmon and analysed entirely on
Linux afterwards.

## Capture

`Procmon64.exe /AcceptEula /Quiet /Minimized /BackingFile <path>.pml`, launched and cleanly
stopped (`/Terminate`) from inside one long-lived SSH session (see `docs/114`'s method notes on
why that matters on Windows). Session length ~15.25 minutes (`01:45:29`–`02:00:44` UTC),
12,704,094 events across two `.pml` files (Procmon's own 4GB-per-file rollover), ~5.9GB total.

## Analysis method, and three gotchas

Parsed with the `procmon-parser` PyPI package on Linux — no Windows round-trip needed. Mount
the external SSD read-only (`udisksctl mount -b /dev/sdX`, no root required for a removable
drive), point `procmon_parser.ProcmonLogsReader` at the `.pml` files directly.

Three things will silently produce garbage if not handled:

1. **A handful of events crash the library's detail parser outright** (an
   `AttributeError: 'NoneType' object has no attribute 'read'` several frames deep, on a
   `Filesystem_Query_Name_Information` sub-operation in this capture). Iterate by index —
   `for i in range(len(reader)): try: ev = reader[i]` — rather than `for ev in reader`, and skip
   failures; a single bad record does not corrupt the offsets table for the rest. 14 of 12.7M
   events failed this way here — negligible.
2. **`str(ev.operation)` returns a bare integer on Python ≥3.11**, not the operation name
   (`IntEnum.__str__` changed upstream after this library was written). Use `ev.operation.name`
   instead, or every "top operations" table comes out as meaningless numbers.
3. **`ev.duration` is not trustworthy for operations that can have a long-pending async I/O.**
   `ReadFile` on `\Device\NamedPipe\mojo.*` (Chrome/CEF/Steam-webhelper IPC) reported
   "durations" in the tens of quadrillions of milliseconds — not corrupted data, but Procmon
   flushing an IRP that had been a pending overlapped read since the pipe opened, logged at
   `/Terminate` as if it had just completed. This silently dominates any naive duration-based
   ranking. Fix: cap the duration contribution at a sane ceiling (5000ms here) before summing or
   ranking. Even under that cap, expect the "slowest events" list to still be dominated by
   ordinary long-blocking-by-design calls (`NotifyChangeDirectory` watching a folder, idle
   `SearchIndexer.exe`/`lsass`/`srvsvc` waits) — that is normal, not a finding.

## Result: no anomalies

After the duration fix, the slowest real events in the entire window are all benign,
long-blocking-by-design calls — nothing resembling a driver stall or DMA hiccup anywhere near
the VR stack. `vrserver.exe`, `vrcompositor.exe`, `vrmonitor.exe`, and Oasis's
`client_utility.exe` instances show unremarkable I/O, mostly `RegQueryValue`/`RegOpenKey`
(settings polling) plus modest file I/O, averaging well under a millisecond per operation.

Two curiosities, neither treated as a fault:

- Two `NVDisplay.Container.exe` instances behave very differently: one is registry-only and
  trivial, the other does ~86K file reads/writes averaging ~10.6ms each (~914s of cumulative
  I/O time over the session) — plausibly shader-cache or driver-log churn. Not investigated
  further; flagged in case it ever correlates with a real symptom later.
- A very regular ~60-second system-wide I/O spike (300K–1M events in a single 10-second bucket,
  landing right on the minute mark) runs throughout, independent of gameplay — most likely a
  background service heartbeat (Windows Defender's realtime scan was the top event-count
  process and is the leading suspect), not something the VR session itself causes.

## Scope, stated plainly

This is an I/O-call trace, not a load profile. A companion `Get-Counter`-based per-process
CPU/GPU-utilization script was written the same night but never actually launched during this
session — there is no CPU/GPU utilization data from this capture, only I/O latency and
frequency. And even if it had run: Procmon structurally cannot see GPU command submission or
DirectX/Vulkan present-call timing — `DeviceIoControl` did not even reach the global top-30
operations list, and that does not mean the HMD/GPU driver was idle, it means that layer is
invisible to this tool by construction. For real frame-present/compositor latency, ETW plus a
semantic decoder (or a GPU-specific profiler) is the right tool, not Procmon.
