# The last Windows trip — capturing what we need to never boot Windows again

**Goal, stated first because it is the whole point (user directive, 2026-08-20): abandon the
Windows dependency completely.** The G2 already runs end-to-end on Linux — activation, panel,
tracking, port recovery — with exactly ONE thing left that needs Windows: creating the initial
controller pairing. This capture gets the wire format for that one thing, so we implement it on
Linux and never need Windows for the G2 again. **This is not accepting Windows; it is the trip
that ends it.**

You do this alone on the Windows side (no Claude there). You come back with a folder and hand it
to Linux. Everything auto-decodes from there.

---

## Before you reboot (on Linux, 30 seconds)

Read the controller battery raw bytes NOW, so the Windows % has a no-recharge partner for the
`docs/46` cross-check. With a session up (or the service running):

```bash
grep -iE "battery raw byte" ~/vr/jack-in-wayland.log | tail -4   # note the raw value per hand
./scripts/controller-pair-check.py                                # confirm: left paired, right UNPAIRED
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
   - Left controller: **keep** its pairing (it is your safety anchor — see below).
   - Right controller: **pair** it → **this is the capture that matters.** Hold its
     battery-compartment button until the LEDs pulse slowly, let Oasis finish.
   - Power-cycle both controllers.
   - Note each controller's **battery %** and the **1.2 V switch** position; photograph both.
   - (Optional) SteamVR briefly to confirm both track.
5. It stops the capture and packages a `bringup-capture-<timestamp>` folder. **Zip it, bring it
   to Linux.**

## Should we also do the LEFT controller? (user asked "aprovechamos para el otro?")

**No — keep the left paired.** Reasons, in order:
- One pairing capture is enough to decode the format. The left↔right difference is at most an
  id byte (0 vs 1), which we read from the right capture against the known status packets.
- **Never have both controllers unpaired at once.** If Oasis hiccups mid-pair you could end up
  with zero working controllers and a harder recovery. The left is the anchor.
- If, after decoding, we find we genuinely need the left's pairing bytes too, it is a two-minute
  follow-up — done only *after* the right is confirmed re-paired and tracking.

## Should we also do the headset ("casco")? (user: "de paso podemos hacer casco")

**Yes, and it is free** — it is the same USBPcap trace. The unplug/replug + activation steps above
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
# 1. export the HoloLens Sensors traffic to TSV (docs/07 has the canonical tshark command;
#    controller pairing tunnels through 045e:0659, so target that device's address)
tshark -r bringup_USBPcapN.pcapng -Y "usb.device_address==<addr>" -T fields \
   -e frame.time_relative -e usb.device_address -e usb.bmRequestType \
   -e usb.setup.bRequest -e usb.setup.wValue -e usb.capdata > pairing.tsv

# 2. find the PAIR command and its real payload
./scripts/analyze-pairing.py pairing.tsv
```

`analyze-pairing.py` prints every `0x16` BT-control report and flags the `0x05 PAIR` line with its
full payload — **the bytes `controller-pair.py` was missing.** Cross-reference the timestamp in
`action-log.txt` (step 5) to be sure you are looking at the pairing moment and not a status poll.

Then: put that payload into `controller-pair.py`, unpair a controller with its button, and fire.
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
