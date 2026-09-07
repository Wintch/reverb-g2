# 114 — Windows live diagnostic session: the `0x03` debug channel, error 108, and a real Oasis crash (2026-09-07)

First session with live SSH access into the lab's Windows dual-boot (OpenSSH Server enabled,
firewall rule widened from `Private` to `Any`, a key added to
`administrators_authorized_keys`). Four independent findings came out of one evening on that
box before rebooting back to Debian.

## 1. The `0x03` debug channel, decoded — closes a long-open lead

`flicker.pcapng` (captured 2026-08-05, on the external Windows SSD) has 134 packets carrying
report ID `0x03` immediately after the USBPcap URB header, each followed by the 4-byte magic
`"Dlo+"` (`0x2b6f6c44`). Decoded the full payload of all of them (bus 2, device 4 then 6 after
a mid-capture re-enumeration).

**It is the camera/IMU subsystem's own firmware boot+runtime log, not a panel/backlight
channel.** Representative strings, in order: `BOARD_ID: 3`, `SpiInit`, `UpdaterInit`,
`CX3 Flash MfgID 0xc8...`, `FPGA Flash MfgID 0xc8...`, `Active 3BL image 0x50000`,
`CamerasInit:GpifSMStart passed`, `OV7251Initialize` / `OV7251StartStreaming` /
`OV7251StopStreaming`, `IMU: Who-Am-I=0x12`, `CamerasUpdateTrackingMode: Switching to mode N`.

This retracts the standing hypothesis (carried since `docs/09`) that this channel might carry
the panel's duty-cycle/frame-timing format string — grepped the full decoded log for `duty`,
`frame timing`, `backlight`, `brightness`: zero matches. Either that string is never emitted
over this USB channel, or it lives on a path this particular capture never exercised.

The `"Dlo+"` magic is the same one Monado's `img_xfer_cb` validates on real camera frames (the
"Invalid frame magic, expected 2b6f6c44" fault signature from the USB-port-fault family) — same
framing protocol on both the log channel and the image-data channel, not a coincidence, but a
different symptom; don't conflate the two.

**A DMA-error pattern in that same capture, corrected by a live retest the same night:**
`flicker.pcapng` showed the camera pipeline repeating a full `BOARD_ID` reflash roughly every
20–30 seconds across its 267s length, each `ICMStart` followed within 18–27ms by a
`DMA CMT ERR` then `CamerasDmaReset` — read at the time as a possible reproduction of the
USB-port-fault family. Two live captures taken this session (a clean 218s Room View passthrough
and a ~108s walk + Dreams-of-Dalí + exit) showed **zero** and **exactly one** `DMA CMT ERR`
respectively — the single one paired 1:1, at the moment of exit, with one `CamerasDmaReset`,
one `OV7251StopStreaming`, one `CmdCamerasStopStreaming`. **Conclusion: `DMA CMT ERR` alone is
the firmware's normal log line for "in-flight DMA aborted because streaming was told to
stop"** — routine, not a fault. What the older capture showed that real use never reproduced is
the *repeated full reboot* every 20–30s specifically — that remains unexplained, but is now
better explained by however that capture's test methodology cycled the headset's connection,
not by a live, ongoing hardware fault.

## 2. SteamVR error 108, root-caused

`VRInitError_Init_HmdNotFound` (108) is not a live "headset not found" error — SteamVR probes
each registered external driver (`openvrpaths.vrpath` → `external_drivers`) for hardware
**exactly once, at `vrserver.exe` startup**. If the headset isn't connected at that moment, the
driver is marked unavailable for the entire lifetime of that `vrserver` process; plugging the
headset in afterwards does nothing until `vrserver` itself is relaunched. Fix confirmed live:
connect the headset, then restart SteamVR (not just reconnect the USB cable).

## 3. Room View passthrough — visual confirmation

Two screenshots of Oasis's Room View (SteamVR 2.16.7, `2.3 of 11.1 ms (90 Hz)` overlay,
`FPS N/A | GPU 23% | CPU 11% | LAT N/A`) confirm the existing documentation: stylised cyan
wireframe over the real scene, not photorealistic passthrough — matches prior notes exactly,
nothing new to correct here. (Note for future readers: "Dreams of Dalí" is a Steam VR demo
title played during this session and is unrelated to this project's own "Dalí" SLAM-latency
work in `docs/113`.)

## 4. A real Oasis crash, caught live

During this same evening, Oasis's `HmdDriver.cpp:5001` hit a fatal `Check` failure on a
`HidD_SetFeature` call returning an ordinary Win32 failure instead of succeeding — the driver
treats that as fatal rather than retrying. Recovered with a manual SteamVR restart. Circumstance
was a re-don right after removing the headset, but that's not proven causal (could equally be
an unrelated race, e.g. a HID transaction landing while a WPR/ETW provider was attaching to the
same process). A second full session later that same night (walk + own Aircar demo + manual
exit) closed with an ordinary graceful exit, no repeat. Not yet reported upstream — worth doing
if it recurs with a clean repro, since treating a normal Win32 API failure as fatal reads like a
real robustness bug in the driver, not a config issue on our end.

## Method notes

- USBPcap capture over SSH needs `tshark`, not `dumpcap` (`dumpcap -D` doesn't enumerate
  USBPcap's extcap interfaces at all; `tshark -D` does, at index 6/7/8+ alongside the real
  NICs).
- Windows' OpenSSH puts spawned processes in a Job Object that dies with the SSH channel — a
  `Start-Process`-then-return script's "detached" child is killed the instant the SSH command
  exits. Keep the whole start → wait → stop sequence inside **one** long-lived SSH invocation,
  gated on a `while (-not (Test-Path $stopFlag))` poll loop with an external "create this file"
  signal, instead of guessing a fixed duration.
