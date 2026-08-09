# 00 — USB Topology: Separating the Root Disk from the Headset

## Why This Comes First

On 2026-08-04 the machine hung completely (all displays dead except one, USB errors on
the console, manual reset). Cause: the **root SSD** (Crucial BX500 in a JMicron USB enclosure)
and the **entire HP Reverb G2** hang off the **same xHCI controller** (`07:00.3`, Matisse),
while the second controller (`02:00.0`, A520 chipset) sits almost empty. When the bus
chokes (the headset's companion board re-enumerating + transcodes writing to disk),
it takes the root disk link down with it → I/O to `/` frozen → total hang, and
partially-written files end up truncated (that's how we lost two .mp4 downloads, no moov atom).

Topology measured that day:

```
xHCI 07:00.3 (Matisse, CPU)  → usb3 (480M) + usb4 (10G)
   usb4/4-1     HP WMR hub → 4-1.1 HoloLens Sensors (cameras, 5G, continuous stream)
   usb4/4-2     VIA hub → 4-2.1 JMicron JMS578 → sda = ROOT DISK  ← PROBLEM
   usb3/3-1     Headset's Cypress hub → QHMD companion (03f0:0580) + audio
xHCI 02:00.0 (A520 chipset)  → usb1 (480M) + usb2 (10G, 3 ports)
   usb1/1-8     Logitech receiver (mouse)
   usb2         EMPTY  ← the disk goes here
```

## Ruled Out: Moving Things Between USB Ports (measured 2026-08-04, afternoon)

This was tried and **there is no USB-side solution on this machine**. Two attempts, both failed:

- **Moving the SSD to another port** (2026-08-04, morning): went from `4-3.1` to `4-4` — a different
  physical connector, same xHCI `07:00.3`.
- **Moving the headset to another port** (2026-08-04, afternoon): went from `4-1` to `4-2` — again the
  same `07:00.3`.

Probing with `scripts/find-port.sh` confirmed the definitive physical map:

| controller | bus | ports | physical location |
|---|---|---|---|
| `07:00.3` (Matisse, CPU) | usb3 (480M) / usb4 (10G) | 4 + 4 | **the 4 blue USB3 ports on the rear panel** |
| `02:00.0` (A520 chipset) | usb1 (480M) | 9 | the 2 rear USB2 ports (Logitech receiver is on `1-8`) + headers |

### Open item, not yet measured: reliability may differ port-to-port within the 4 (2026-08-09)

The table above says all 4 rear USB3 ports share the same controller — true, but it
doesn't mean they're identical. The user's own recollection (not yet backed by logged
incidents): of the 4, 2 have historically been reliable for the headset and 2 haven't,
independent of the cable/connector issues tracked in `docs/22`. The cable is connected via
a fixed (non-reversible) USB-C-to-USB3-A adapter, so cable-orientation flipping —
speculated elsewhere as a contributing factor — isn't a variable here.

`find-port.sh` can't distinguish this: it only tells you which *controller* a port
belongs to, and all 4 are on `07:00.3`. Confirming a real per-port difference needs
correlating `ID_PATH` (via `udevadm info -q path /sys/bus/usb/devices/usb3` or `usb4`,
whichever the headset lands on) against actual incident outcomes over time, not memory.

First real data points: 2026-08-09, same session, two different physical sockets tested,
both user-confirmed as historically-good ports — one next to the GPU's DisplayPort
output, one next to the motherboard's integrated HDMI (the two-pair split found in the
board's own manual, `2-6 Back Panel Connectors` diagram: the 4 rear USB 3.2 Gen1 ports
sit as one pair beside HDMI and one pair beside the RJ-45 LAN port, not in a single row).
**Both read the identical `ID_PATH`, `pci-0000:07:00.3-usb-0:1` ("root port 1").** So
`ID_PATH` via this method does NOT currently distinguish these two physical sockets from
each other — a real methodology gap, not a "they're the same port" conclusion. Don't trust
`ID_PATH` alone to tell physical sockets apart on this board until that's understood
(possibly needs the deeper `sysfs` port-topology path, not just the resolved device path).

Both sockets recovered the USB2 branch via a PC-end-only replug this session (see
`docs/pruebas.jsonl` around T117) — but the *first* attempt on the HDMI-side socket sat
silent at 0/5 for ~1m50s with zero re-enumeration attempts in `journalctl -k` (the same
"quiet, not storming" pattern as T115/T116) before a second, firmer reseat brought it back
in under 4 seconds. Lesson: a quick unplug/replug isn't always enough — worth confirming
it's genuinely fully seated, not just touched, before concluding a port/replug attempt
failed.

**Longer-term idea, not started:** if a real per-port pattern gets confirmed, worth
turning into a plain visual diagram ("plug USB here, DP there, avoid these two") as part
of the diagnostic-toolkit-for-anyone-with-this-headset direction, not just an internal
lab note.
| `02:00.0` (A520 chipset) | usb2 (10G) | 3 | **internal headers only — the case has no wired front panel** |

The rear panel has 6 ports: 2 USB2 + 4 USB3. The 4 USB3 ports are **all** on the CPU
(matches the 4 ports of `usb4`). The chipset's 3 USB3 ports — the only ones that
would have worked — exist only as internal headers this case doesn't expose.

**Conclusion: shuffling USB ports is a dead end.** Go straight to
Procedure 1.

## Procedure 1 — Move the Root Disk to SATA (POWERED OFF)

`sda` is a **Crucial CT240BX500SSD1**, i.e. a **2.5" SATA SSD stuffed inside a
JMicron JMS578 USB enclosure**. The board has the chipset's SATA controller
(`02:00.1`, AMD 500 Series) with **6 AHCI ports (`ata1`..`ata6`), all empty**.
Pulling it out of the enclosure and plugging it into SATA fixes the problem at the root:

- the headset ends up alone on `07:00.3`, with nothing to share the bus with → the cause of the hang disappears;
- it moves from the JMS578's ceiling (~430 MB/s) to SATA III (~550 MB/s);
- and most importantly, the root filesystem stops depending on a bus that resets itself.

### Verified in Advance — Boot Does NOT Break

| check | result |
|---|---|
| `/etc/fstab` | uses `UUID=` for `/` and for swap → the device name change is irrelevant |
| initramfs | contains `ahci`; `MODULES=most` in `initramfs.conf` |
| boot mode | **BIOS/legacy** (`/sys/firmware/efi` doesn't exist), `dos` partition table |
| bootloader | MBR on the disk itself → travels with the disk |
| SATA ports | 6 free |

### Steps

1. Power off completely and unplug from the mains (it's the root disk: never hot-swap).
2. Open the JMicron enclosure and take out the SSD.
3. Connect it to `SATA1` on the motherboard + a free **SATA power** connector from the PSU.
4. Mount it wherever possible (2.5" bay, or just resting/zip-tied — it's an SSD, no moving parts).
5. Power on, **enter the BIOS and set that disk first in the boot order**. This is the
   only step that might need manual intervention: the disk stops being "USB HDD" and becomes
   SATA, and not every BIOS reorders this on its own.

**The only thing that might be physically missing:** a **SATA data cable** (motherboards usually ship
with 1 or 2 in the box) and a free SATA power connector on the PSU.

### Verification Once Back Up

```bash
./scripts/check-usb-split.sh
# Should report OK: the SSD no longer shows up on USB at all.
lsblk -o NAME,SIZE,TRAN,MODEL   # sda should show TRAN=sata, not usb
```

## Procedure 2 — Kill Autosuspend for the Disk and Headset

The kernel default (`usbcore.autosuspend=2`) suspends "idle" devices; the hub carrying
the root disk was set to `auto`. A udev rule is prepared in
`scripts/71-usb-no-autosuspend.rules` in this repo:

```bash
sudo cp scripts/71-usb-no-autosuspend.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb
# Verify (everything listed should say "on"):
for d in /sys/bus/usb/devices/*/power/control; do
  v=$(cat ${d%/power/control}/idVendor 2>/dev/null)
  case "$v" in 152d|2109|03f0|04b4|045e) echo "$d -> $(cat $d)";; esac
done
```

## Procedure 3 — Readable Logs Without sudo

During the hang we couldn't read either `dmesg` or `journalctl -k` as a regular user (missing
groups + `dmesg_restrict=1`): the USB errors were only visible on the console and were lost.

```bash
sudo usermod -aG adm,systemd-journal brunduk
# log out and back in (or reboot), then verify:
journalctl -k | head    # should show kernel lines
```

Optional (more convenient for diagnostics, your call):

```bash
echo 'kernel.dmesg_restrict = 0' | sudo tee /etc/sysctl.d/10-dmesg.conf
sudo sysctl --system
```

## Procedure 4 — Stress Test (gate before continuing with the rest)

Reproduces the load from the day of the hang, now with the buses separated:

```bash
# Terminal 1: sustained NVENC transcode writing to the root disk
ffmpeg -y -f lavfi -i testsrc2=size=3840x2160:rate=30 -t 600 \
       -c:v hevc_nvenc -preset p5 -b:v 40M /tmp/stress_$(date +%s).mp4

# Terminal 2: full VR pipeline
./scripts/jack-in.sh 3dof
# + a while of the 360 player with video

# Terminal 3: monitoring
journalctl -kf | grep -iE 'usb|xhci|reset|uas'
```

**Success criterion:** 10 minutes with no xhci/uas resets in the journal and no companion device
dropout (03f0:0580 stable in `lsusb`). Only then move on to the next
phases (NVDEC, controllers, lab 90Hz).

## Note on the Enclosure

The headset's companion board fault is **physical** (it happens the same way on Windows; a suspect
cable/connector — see `06-known-issues.md`). Separating the buses doesn't fix it: it just keeps that
fault from dragging down the system disk. Procedure 1 (moving `/` to SATA) is exactly
that underlying fix — the NVMe drive stays 100% NTFS/Windows and is left untouched.

Once the SSD is moved to SATA, the JMS578 enclosure is free and perfectly usable
for something else (backups, external disks), just never again for the root filesystem.
