# 07 — Capturing the 90Hz HID sequence on Windows

> ## ⚠ ARCHIVED (2026-08-04, 21:00) — NO NEED TO DO THIS
>
> This chapter existed to find out what HID command requests 90Hz mode from the headset.
> **That command doesn't exist.** The Oasis driver — the one that runs the G2 at 90Hz
> on Windows by talking to the headset directly — was disassembled, and its only panel
> command is *Display Enable* (Usage Page `0x03`, Usage `0x21`), which is exactly the
> `{0x04,0x01}` that Monado already sends.
>
> Evidence and method in **`docs/09-oasis-driver-re.md`**. Ruled out in chapter 06.
>
> The procedure is kept because the technique (usbmon + tshark + `analyze-hid.py`) is still
> useful for other questions — for example the USB2 hub resets under load.

**This document is followed solo, without an agent.** There's no Claude alongside you on
Windows: the idea is that you come out of this with two files and go back to Linux to
analyze them.

## Why

Chapter 04 measured that the 595-open patches **don't** fix the 90Hz issue, and Monado's
code shows why it might not be NVIDIA's fault: `wmr_hmd_activate_reverb()`
(`wmr_hmd.c:767`) **always sends the same HID sequence**, whether the panel runs at 60 or
90. Monado's "90Hz patch" (`wmr_hmd.c:1992`) only sets `nominal_frame_interval_ns`, which is
a number for pacing — it doesn't touch the panel.

Hypothesis: **the headset is never asked to switch the panel to 90Hz.** Windows does do
this, and the same headset runs 90Hz there for hours. We want to see that command.

## The experiment, and why this way

The tempting approach is to capture Windows and compare it against Monado. That's a dirty
diff: the entire stack differs, and you have to separate signal from noise by hand.

**Better: capture Windows at 60Hz and Windows at 90Hz.** Same machine, same headset, same
driver, same cable — the only variable is the refresh rate. Whatever shows up in the 90Hz
capture and not in the 60Hz one is, literally, the missing command.

If your Windows doesn't offer the 60Hz option, see "Plan B" at the end.

## What gets captured

Only the **companion `03f0:0580`** (HP, Inc QHMD A85V). It's Monado's `hid_control_dev`:
activation and `screen_enable` go through it.

**Don't capture the `045e:0659` (HoloLens Sensors)**: it spews IMU data at high frequency
and drowns the file. Not the cameras either.

## Preparation (one time)

1. Install **Wireshark** (https://www.wireshark.org/download.html).
2. During installation, **check the `USBPcap` component**. It isn't included by default.
3. **Reboot** — USBPcap installs a filter driver and doesn't work until you reboot.

## Capture

Repeat the whole thing for each refresh rate. The important trick is in step 3.

1. In **Windows Settings → Mixed reality → Headset display**, set the refresh rate. Look
   for something like *"Experience options"* / *"Opciones de experiencia"* / *"Frecuencia de
   actualización"*, with values **60 Hz / 90 Hz / Automatic**. Set an **explicit** value,
   never "Automatic" — we need to know which one was active.
2. Close Mixed Reality Portal and **unplug the headset's USB**.
3. Open Wireshark, choose the **USBPcap** interface for the root hub the headset connects
   to, and **start the capture BEFORE plugging it in**. This is what makes everything else
   easy: you'll see the full enumeration (which reveals the companion's device address) *and*
   the activation sequence, in the same file.
4. Plug in the headset. Open the Portal and **wait for the panel to actually turn on**
   (look inside: there has to be an image, not the HP logo).
5. Let it run for ~15 more seconds and **stop the capture**.
6. Save as `windows-90hz.pcapng` (or `windows-60hz.pcapng`).

Repeat with the other refresh rate.

### Finding the companion's device address

In Wireshark, filter:

```
usb.idVendor == 0x03f0 && usb.idProduct == 0x0580
```

That matches the descriptor response during enumeration. In that row, look at the
**Source/Destination** column: the number like `3.7.0` is `bus.device.endpoint`. Note down
the **device** (`7` in the example). If the filter returns nothing, look for
`usb.descriptor_type == 1` and go through the descriptors until you find HP's.

### Exporting to text

The Linux analyzer reads TSV, so there's no need to parse pcapng. From `cmd` or PowerShell
(adjust `N` to the device address you noted down):

**The field order matters**: the analyzer expects them exactly like this.

```
"C:\Program Files\Wireshark\tshark.exe" -r windows-90hz.pcapng ^
   -Y "usb.device_address==N" -T fields ^
   -e frame.time_relative -e usb.device_address ^
   -e usb.bmRequestType -e usb.setup.bRequest -e usb.setup.wValue ^
   -e usb.capdata > windows-90hz.tsv
```

The three middle fields (`bmRequestType`, `bRequest`, `wValue`) are what let you
distinguish a real `SET_REPORT` from just any descriptor. Without them the analysis is
garbage: this was tested, and the bus is full of traffic that *looks like* HID reports but
isn't.

Same for 60. **Verify that the `.tsv` files aren't empty** before considering the Windows
session done — if they're empty, the device address is wrong.

### Proof that the capture is good

Look in the `.tsv` for a row with `bRequest = 0x09` and `wValue = 0x0350`: it's the
Feature `SET_REPORT` for report `0x50`, the first command of the activation sequence. **If
it's not there, the capture didn't catch the headset's startup** — almost always because you
started capturing after plugging it in. Redo it.

## What to bring back

Copy to somewhere accessible from Linux (USB drive, shared partition, the cloud):

- `windows-90hz.pcapng` and `windows-60hz.pcapng` (the originals, in case you need to
  re-filter)
- `windows-90hz.tsv` and `windows-60hz.tsv` (what gets analyzed)
- Noted by hand: **which refresh option was set for each one**, and **what you saw inside
  the headset** in each run.

## Back on Linux

```bash
cd ~/Documents/reverb-g2

# The diff that matters: A=60Hz, B=90Hz. Whatever shows up in "IN B BUT NOT IN A" is the answer.
./scripts/analyze-hid.py diff windows-60hz.tsv windows-90hz.tsv

# And against what Monado sends (captured with scripts/capture-hid.sh):
./scripts/analyze-hid.py diff ~/vr/hid-mode0.txt windows-90hz.tsv
```

The script normalizes both captures to the same shape (direction, report ID, payload),
ignores timestamps and padding, and flags as `[UNKNOWN]` any report ID that Monado doesn't
send today. **An unknown report ID that only appears in the 90Hz capture is the candidate.**

## Plan B: if Windows doesn't offer a 60Hz option

Capture only 90Hz and diff against Monado:

```bash
./scripts/analyze-hid.py diff ~/vr/hid-mode0.txt windows-90hz.tsv
```

It's noisier — differences will show up that have nothing to do with the refresh rate
(enumeration order, telemetry, polling). It still works: what you're looking for is a
**report ID that Monado never sends**, and that stands out even with noise around it.

## How this gets closed out

If the command shows up, the path forward is a patch to Monado's WMR driver that sends it
when the requested mode is 90Hz. That would be one of our patches in `patches/monado/`, and
— importantly — **it would move the project's root cause from NVIDIA to Monado**, which is
the opposite of what had been assumed so far (see the correction in chapter 06).

If **no** extra command shows up — if Windows sends exactly the same thing at 60 and at
90 — then the hypothesis is dead, the mode is negotiated over DisplayPort, and we have to go
back to the video driver side. Write it down either way: a measured rule-out is worth as
much as a finding, and this project has already lost weeks from not writing them down.
