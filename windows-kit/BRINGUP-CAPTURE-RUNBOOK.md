# Windows bring-up capture runbook

> Status: historical runbook. The capture was done and the PAIR protocol decoded (docs/03).
> Host-Bluetooth bonding (docs/136) now covers the pairing need on Linux.

Purpose: capture the Oasis controller-pairing and headset-activation wire format with USBPcap,
so the pairing step can be implemented on Linux and the Windows dependency removed. The G2
already runs end-to-end on Linux (activation, panel, tracking, port recovery); creating the
initial controller pairing was the one step that still needed Windows.

Run this on the Windows machine, then copy the output folder back to the Linux machine;
everything auto-decodes from there.

---

## Before rebooting into Windows (on Linux, 30 seconds)

Note the controller battery raw bytes first, so the Windows % has a no-recharge partner for the
`docs/46` cross-check. With a session up (or the service running):

```bash
grep -iE "battery raw byte" ~/vr/jack-in-wayland.log | tail -4   # note the raw value per hand
./scripts/controller-pair-check.py                                # note which controllers are paired
```

Do NOT recharge the cells between this and the Windows reading, or the pair is worthless.

---

## What you need on Windows (once)

- **Wireshark**, installed **with the USBPcap component checked** (it is an optional component in
  the installer). Reboot after installing. Without USBPcap there is no capture.
- The Oasis Steam app, already set up.

## Run it

1. Copy the `windows-kit` folder to the Windows side.
2. Open **PowerShell as Administrator**, `cd` into `windows-kit`.
3. `powershell -ExecutionPolicy Bypass -File .\capture-bringup.ps1`
4. Follow its prompts. It starts one USBPcap trace and timestamps each step you confirm, so every
   event is findable in the trace afterward. The runbook order is:
   - Headset on a rear **CPU** USB3 port, powered.
   - Launch Oasis "Unlock your headset & controllers".
   - Unplug/replug the headset USB when asked (same port) → **captures activation + how fast
     Windows re-enumerates the companion**, the docs/60 recovery question, for free.
   - Left controller: **keep** its pairing (it is the safety anchor — see below).
   - Right controller: **pair** it → **this is the capture that matters.** Hold its
     battery-compartment button until the LEDs pulse slowly, let Oasis finish.
   - Power-cycle both controllers.
   - Note each controller's **battery %** and the **1.2 V switch** position; photograph both.
   - (Optional) SteamVR briefly to confirm both track.
5. It stops the capture and packages a `bringup-capture-<timestamp>` folder. **Zip it, bring it
   to Linux.**

## Pair only one controller per capture

Pair only the right controller and keep the left paired. Reasons, in order:
- One pairing capture is enough to decode the format. The left↔right difference is at most an
  id byte (0 vs 1), which can be read from the right capture against the known status packets.
- **Never have both controllers unpaired at once.** If Oasis hiccups mid-pair you could end up
  with zero working controllers and a harder recovery. The left paired controller is the anchor.
- If decoding shows the left controller's pairing bytes are needed too, it is a two-minute
  follow-up — done only *after* the right is confirmed re-paired and tracking.

## Headset activation is captured in the same trace

Headset activation needs no extra capture: it is the same USBPcap trace. The unplug/replug + activation steps above
already capture what Oasis sends the companion to bring the panel up and bind the USB. No extra
work; it is folded into phase 1.

## The two failure modes (optional phase 2)

The script offers this at the end. Only do it if phase 1 was clean and you have appetite: move
the headset to a **chipset** USB3 port and see what Oasis says, then move it back without
relaunching Oasis (the "must relaunch to re-bind" symptom), then relaunch. Valuable for docs/31,
but not required for the pairing goal — skip if unsure.

---

## Back on Linux — decode (this is where Windows dies)

```bash
# 1. export the HoloLens Sensors traffic to TSV (controller pairing tunnels through 045e:0659, so target that device's address)
tshark -r bringup_USBPcapN.pcapng -Y "usb.device_address==<addr>" -T fields \
   -e frame.time_relative -e usb.device_address -e usb.bmRequestType \
   -e usb.setup.bRequest -e usb.setup.wValue -e usb.capdata > pairing.tsv

# 2. find the PAIR command and its real payload
./scripts/analyze-pairing.py pairing.tsv
```

`analyze-pairing.py` prints every `0x16` BT-control report and flags the `0x05 PAIR` line with its
full payload — **the bytes our pairing script was missing.** Cross-reference the timestamp in
`action-log.txt` (step 5) to be sure you are looking at the pairing moment and not a status poll.

Then: put that payload into `scripts/controller-pair-v2.py`, unpair a controller with its button, and fire.
If it pairs — **the last Windows dependency is dead, and the G2 is Linux-only, end to end.**

## For the headset activation, same trace

```bash
tshark -r bringup_USBPcapN.pcapng -Y "usb.device_address==<companion_addr>" -T fields \
   -e frame.time_relative -e usb.device_address -e usb.bmRequestType \
   -e usb.setup.bRequest -e usb.setup.wValue -e usb.capdata > activation.tsv
./scripts/analyze-hid.py resumen activation.tsv
```

Cross-check against what Monado already sends (`wmr_hmd.c`); anything extra is what Oasis does at
activation that we might fold in. We already match the panel command (docs/09), so expect little —
but the re-enumeration timing around the replug is the docs/60 recovery datum, and it is in here.
