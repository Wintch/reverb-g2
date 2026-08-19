# The Windows control for the USB2 storm — the fault is the LINK, not the Linux stack

**Status: measured 2026-08-19, 79-minute capture. This document RETRACTS the retraction made
the same day.** At the close of T225 the rev2A cable recommendation was withdrawn on the
argument that "the same cable and headset run long sessions on Windows normally". That was an
impression, not a measurement. `windows-kit/usb-storm-monitor.ps1` was written to turn it into
a number, the user ran it, and **the number says the opposite of the impression**.

## The pre-registered decision rule

Written into NEXT-STEP.md and the script's own header *before* any Windows data existed, so it
could not be bent afterwards:

> * Windows shows a comparable event rate → the instability is the LINK, and Linux is merely
>   more sensitive to it. The cable/connector goes back on the table.
> * Windows shows near-zero over the same wall-clock and the same real use → the link is fine
>   and the fault is in the Linux USB stack.

## What was run

* **Machine**: Ryzen 5 3600 / RTX 3060 Ti / 32 GB / TUF GAMING B450M-PLUS II — i.e. the *same
  physical box* as the Linux lab machine, SSD swapped. Same board, same USB host controllers,
  same cable, same headset. **The OS is the only variable.** This is the cleanest control this
  project has ever had on this question.
* **Windows** 10.0.26200, SteamVR 2.16.7, NVIDIA 610.47.
* **Instrument**: `usb-storm-monitor.ps1`, 250 ms polling of `Get-PnpDevice -PresentOnly` for
  the five G2 USB endpoints, transitions only.
* **Capture**: `windows-kit/captures/usb-storm-20260819-200956.csv` (1077 transitions),
  console transcript in `usb-storm-20260819-console.txt`. Window 20:10:34 → 21:29:34 = 79 min.
* **What the machine was doing**: **the G2 itself, under Oasis + SteamVR, for the whole 79
  minutes** — five different titles launched and played, SteamVR cycled up and down a couple of
  times, both controllers working normally. This is a *loaded* capture, the direct counterpart
  of a real Linux session, not an idle one.
  *(The OpenVR Benchmark screenshots from the same hour report the headset as "Oculus - Oculus
  Quest2". That is the benchmark mislabelling the device: there is no Quest 2 in the lab, and
  its own reported render target, 2576×2520@90, matches SteamVR's G2 target. Noted here because
  docs/23 planned to use that app's per-GPU+headset leaderboard as the beat-Windows metric — on
  the Oasis path it would file the result under the wrong hardware.)*

## The result

Per-device, over 79 minutes:

| device | branch | outages | rate | outage p50 | worst | % of session absent |
|---|---|---|---|---|---|---|
| hub-ss `04B4:6504` | USB3 | **0** | 0.00/min | — | — | 0% |
| hololens-sensors `045E:0659` | USB3 | **0** | 0.00/min | — | — | 0% |
| hub-usb2 `04B4:6506` | USB2 | 22 | 0.28/min | 2.25 s | 3.03 s | 1.1% |
| companion `03F0:0580` | USB2 | 230 | 2.91/min | 2.32 s | 11.5 s | 15.3% |
| audio `0BDA:4C15` | USB2 | 274 | 3.47/min | 2.55 s | 20.2 s | 25.0% |

Branch-level (the analogue of Linux's `hw-monitor.sh` 5/5 → <5/5 counter): **274 drops,
3.47/min, p50 2.9 s, p90 10.5 s — the USB2 branch was incomplete for 27% of the session.**
Twelve transitions passed through a Device-Manager error state (`PROBLEM:Error`), nine of them
on audio — so this is not merely a presence-poll artifact; Windows itself flagged the devices.

Side by side with Linux (`~/vr/logs/hw-monitor.log`, 2026-08-16, 18 h span, 938 drop starts):

| | Linux | Windows |
|---|---|---|
| USB2 drop starts | 0.92 – 4.63 /min (per hour) | 3.47 /min |
| outage p50 | 3.0 s | 2.9 s |
| outage p90 | 12 s | 10.5 s |
| USB3 branch | never dropped | never dropped |
| escalates within a session | yes | yes |

**Same rate. Same ~3 s outage. Same p90. Same USB3 immunity. Same escalation.** The Windows
capture even reproduces the shape of the ramp: 0 events in the first 10 minutes after
enumeration, 6 in the next, then 38 / 40 / 52 / 52 / 45 / 41 per 10 minutes — quiet start,
climb, plateau, exactly the Linux profile.

## What this means, stated narrowly

1. **The storm is a property of the link, not of the operating system.** Two operating systems,
   one machine, one cable, one headset, indistinguishable fault rates.
2. **The rev2A cable is back on the suspect list** — that is the pre-registered rule, applied.
   Not proven to be the cable specifically: the marginal element could be the connector, the
   active cable's Cypress hub silicon (docs/22's long-standing firmware hypothesis), or the
   headset-side USB2 PHY. What is now excluded is "the Linux USB stack does this to itself".
3. **The Linux stack is not exonerated as an amplifier, only as the cause.** Linux counts ~83
   companion HID read failures per second and freezes presence when the channel dies; Windows
   rides the same outages and the user's five titles played without a problem. The difference
   in *consequence* is still ours to fix, and `patches/monado/0049`'s backoff plus a proper
   reconnect path are the right work regardless of who owns the cable.
4. **The user perceived the fault on Windows too, unprompted**: audio dropping out during the
   session. That matches the audio device's 274 disconnects exactly. "Windows runs fine" was
   true about *gameplay*, not about the link.

## Why the earlier reasoning went wrong

The retraction at T225's close was logically sound and empirically unfounded: it treated an
unmeasured impression ("Windows sessions run normally") as a control. The failure mode is worth
naming, because this project has hit it before — **a control you did not instrument is not a
control, it is a memory.** The same paragraph that made the wrong call also named the right
next step (run the Windows capture), which is why it took one evening to correct.

T189/T190's "the storm is universal at idle" finding was cited in support of the Linux-stack
conclusion. It never supported it: universality at idle rules out *load* as the trigger, on
either OS, and is equally consistent with a bad link. It is now on the correct side of the
ledger.

## What is still open

* **Which physical element.** A rev2A cable swap is the cheap discriminator and is now
  justified; if a new cable changes nothing, the visor-side USB2 PHY is next and that is
  service territory.
* **Why Windows tolerates it.** This is the sharpest open question left, and now it is very
  sharply posed: Windows took 274 disconnects *while driving the headset and playing five
  titles*, and the only symptom the wearer noticed was audio cutting out. How fast does the
  Windows stack re-enumerate the companion, and does Oasis re-open its HID handles
  transparently? `usbmon` versus USBPcap, still the named next step, but it is now a question
  about *recovery* rather than about *cause* — and that recovery path is the model for ours.
* **The `PROBLEM:Error` states**, 12 of them: what error code Windows assigned would say
  whether these are the same enumeration failures Linux reports as `error -71`.

## Addendum — the benchmark numbers from the same hour, and why they are not yet a comparison

The two OpenVR Benchmark screenshots are the same G2 on the same machine, so they look like the
long-wanted Linux-vs-Windows head-to-head. They are not one yet, for a reason this capture itself
uncovered.

| | render target | avg | 1% low | 0.3% low |
|---|---|---|---|---|
| Windows, pass 1 | 2576×2520 (6.49 Mpx) | 26.02 | 20.39 | 19.70 |
| Windows, pass 2 *(same process)* | 2576×2520 | **354.77** | 40.05 | 19.16 |
| Linux (T219), *not a first pass* | 2160² (4.67 Mpx) | 19.25 | — | 9.80 |

354 FPS at 6.49 Mpx on a 3060 Ti is not a physical result, so **the benchmark's second run inside
one process is broken on Windows too** — on Linux the same second run *wedges* instead. Different
symptom, same locus: the app's own second-run path. That downgrades, without clearing, T219's
suspicion that our XR-session re-cycle causes the wedge.

It also contaminates the comparison: our 19.25 was itself measured after a 4.66 warm-up run in the
same process, i.e. exactly the run class now known to be unreliable. Naive normalisation would put
Windows at ~1.9× our pixel throughput, with its 0.3% low (19.70) equal to our average — a gap worth
chasing, but not yet a measurement.

**The valid comparison is pass 1 versus pass 1, one run per process, same render target.** Cheap to
obtain: re-run on Linux at 2576×2520 (`XRT_COMPOSITOR_SCALE_PERCENTAGE`), take the first run only,
restart the app between measurements. Standing rule either way: **one benchmark run per process
lifetime.**
