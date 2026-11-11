# 116 — Procmon trace of a full multi-game Oasis session: method and result (2026-09-08)

A Linux-`strace`-equivalent pass over a real Windows VR session (two games, camera passthrough
toggled on and off): captured system-wide with Sysinternals Procmon, analysed entirely on Linux.

## Capture and method

`Procmon64.exe /AcceptEula /Quiet /Minimized /BackingFile <path>.pml`, stopped cleanly with
`/Terminate`. ~15 minutes, 12.7M events across two `.pml` files (Procmon rolls over at 4 GB).
Parse on Linux with the `procmon-parser` PyPI package (`procmon_parser.ProcmonLogsReader` on the
`.pml` files directly). Three gotchas silently produce garbage:

1. **A few events crash the detail parser** (`AttributeError: 'NoneType' object has no attribute
   'read'`, on a `Filesystem_Query_Name_Information` sub-operation). Iterate by index inside
   `try`/`except` (`for i in range(len(reader))`), not `for ev in reader`; 14 of 12.7M failed.
2. **`str(ev.operation)` is a bare integer on Python >= 3.11** (`IntEnum.__str__` changed). Use
   `ev.operation.name`.
3. **`ev.duration` is untrustworthy for long-pending async I/O**: `ReadFile` on
   `\Device\NamedPipe\mojo.*` (Chrome/CEF/Steam-webhelper IPC) reports absurd durations (a
   pending overlapped read flushed at `/Terminate`). Cap each duration (5000 ms here) before
   summing or ranking; even then the "slowest events" list is dominated by long-blocking-by-design
   calls (`NotifyChangeDirectory`, idle `SearchIndexer.exe`/`lsass` waits), which is normal.

## Result: no anomalies

After the duration cap the slowest real events are all benign. `vrserver.exe`,
`vrcompositor.exe`, `vrmonitor.exe` and Oasis's `client_utility.exe` show unremarkable I/O
(mostly `RegQueryValue`/`RegOpenKey` settings polling, well under 1 ms per operation); nothing
resembles a driver stall or DMA hiccup. Two curiosities, not treated as faults: one
`NVDisplay.Container.exe` instance does ~86K file reads/writes at ~10.6 ms each (plausibly
shader-cache or driver-log churn), and a regular ~60 s system-wide I/O spike (Windows Defender
the leading suspect) is independent of gameplay.

## Scope

This is an I/O-call trace, not a load profile. Procmon cannot see GPU command submission or
Direct3D/Vulkan present timing (`DeviceIoControl` did not reach the top 30), so a quiet trace
does not mean the HMD/GPU driver was idle. For frame-present/compositor latency use ETW with a
semantic decoder or a GPU profiler.
