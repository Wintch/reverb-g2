# 00 — USB Topology: Separating the Root Disk from the Headset

## Why This Comes First

The **root SSD** (a SATA SSD in a USB enclosure, JMicron JMS578) and the **entire HP Reverb G2**
hung off the **same xHCI controller** (`07:00.3`, Matisse) on the dev kit, while the second
controller (`02:00.0`, chipset) sat almost empty. When the bus chokes (the headset's companion
board re-enumerating plus transcodes writing to disk), it takes the root disk link down with it:
I/O to `/` freezes, the machine hangs completely, and partially written files end up truncated.
The lesson: **never put the root filesystem (or any disk under write load) on the controller that
carries the headset.**

Topology of that configuration:

```
xHCI 07:00.3 (Matisse, CPU)  → usb3 (480M) + usb4 (10G)
   usb4/4-1     HP WMR hub → 4-1.1 HoloLens Sensors (cameras, 5G, continuous stream)
   usb4/4-2     VIA hub → 4-2.1 JMicron JMS578 → sda = ROOT DISK  ← PROBLEM
   usb3/3-1     Headset's Cypress hub → QHMD companion (03f0:0580) + audio
xHCI 02:00.0 (chipset)       → usb1 (480M) + usb2 (10G, 3 ports)
   usb1/1-8     Logitech receiver (mouse)
   usb2         EMPTY  ← the disk would go here
```

## Ruled Out: Moving Things Between USB Ports

There is **no USB-side solution on that board**. Moving the SSD to another rear port (`4-3.1` →
`4-4`) and moving the headset to another rear port (`4-1` → `4-2`) both stay on the same xHCI
`07:00.3`. Probing with `scripts/find-port.sh` gave the definitive physical map:

| controller | bus | ports | physical location |
|---|---|---|---|
| `07:00.3` (Matisse, CPU) | usb3 (480M) / usb4 (10G) | 4 + 4 | **the 4 blue USB3 ports on the rear panel** |
| `02:00.0` (chipset) | usb1 (480M) | 9 | the 2 rear USB2 ports (Logitech receiver on `1-8`) + headers |
| `02:00.0` (chipset) | usb2 (10G) | 3 | **internal headers only — the case has no wired front panel** |

All 4 rear USB3 ports are on the CPU. The chipset's 3 USB3 ports (the only free ones) exist only
as internal headers the case does not expose. **Shuffling USB ports is a dead end: go straight to
Procedure 1.**

## Which kit you are on

The project uses **two host kits** (dev and local), with different boards and CPU xHCI addresses
(`07:00.3` vs `09:00.3`); see [`63-hardware-map.md`](63-hardware-map.md). The rule that holds on
both is "the CPU-fed Matisse controller works, the chipset controller fails" — only the address
differs. A port map is a property of the board, so never carry port numbers between kits: run
`./scripts/usb-port-map.sh map` (reads the live topology) and
`cat /sys/devices/virtual/dmi/id/board_name` to know which board you are on. The first port tables
in this chapter were measured on the `07:00.3` kit.

### Board reference: ASUS TUF GAMING B450M-PLUS II (official + measured)

From ASUS's spec page and rear-panel diagram plus live `lspci`/sysfs measurement. Socket **AM4**,
chipset **B450**, Ryzen 5000 / 5000G / 4000G / 3rd/2nd/1st gen. Rear USB: **6 ports**; front
(internal headers): **6 ports**. PCIe: 1× 3.0 x16 (CPU) + 1× 2.0 x16 max x4 (chipset).

**Rear panel, by ASUS's numbering:**

| # | Port | Note |
|---|---|---|
| 1 | PS/2 combo | |
| 2 | **USB 3.2 Gen 2, Type-A, teal blue, up to 10 Gbps** | the single fastest Type-A |
| 3 | Ethernet (Gigabit) | |
| 4 / 5 | Line In (blue) / Line Out (lime) | |
| 6 | **USB 2.0 ×2** | the black pair: the headset gives panel yes, tracking no |
| 7 | BIOS FlashBack button | |
| 8 | DVI-D | |
| 9 | HDMI | |
| 10 | **USB Type-C** (USB 3.2 Gen 2) | |
| 11 / 12 | **USB 3.2 Gen 1 (5 Gbps), Type-A** | the blue stack — the headset's home |
| 13 | Mic (pink) | |

**ASUS does not publish which port hangs off the CPU and which off the B450 chipset — and that
decides everything.** The live measurement for this board:

```
usb3 / usb4   0000:09:00.3   AMD Matisse USB 3.0 Host Controller     <- CPU (Ryzen 3000). Headset works here (4-2).
usb1 / usb2   0000:02:00.0   AMD 400 Series Chipset USB 3.1 xHCI     <- B450 chipset. Headset fails here (2-1).
```

The WMR headset needs the **CPU-fed** ports. The manual's diagram tells you the port TYPES; only a
live census tells you the CONTROLLER. Plug a mouse into each blue Type-A socket, run
`usb-port-map.sh map`, and match ASUS's numbers to the `usbN-portM` names.

## Port-to-port reliability: the mechanism is the controller

Some rear USB3 sockets work with the G2 and some do not, and the manual never says which: rear
ports can be wired to two different xHCI controllers. On the B450M box the headset sits on
`usb3-port2` + `usb4-port2` (the CPU controller) and the chipset controller's four SuperSpeed
ports sit empty; "the ports that do not work" are the ones on the chipset xHCI.

`ID_PATH` cannot tell two sockets apart (two physically different rear sockets read the identical
`pci-0000:07:00.3-usb-0:1`), but the **root-hub port topology** can:
`/sys/bus/usb/devices/usbN/N-0:1.0/usbN-portM` exists for every physical port, occupied or not, so
every socket has a stable name (`usb4-port2`), a verdict can be recorded against that name, and
the next person can be told which socket to use.

The rear USB3 ports are not in a row. On the A520M board they are two separated pairs, one beside
the HDMI output and one beside the RJ-45 LAN port, so "the USB3 port" is four sockets in two
pairs; the physical picture is part of the addressing scheme:

![Rear panel of the A520M board: the 4 USB 3.2 Gen1 ports sit as two separated pairs, one
beside the HDMI output and one beside the RJ-45 LAN port](a520m-rear-usb3-port-pairs.png)

**Standing rule: REAR SOCKETS ONLY.** The front-panel USB3 header has never been tested with this
headset: front panels add an internal header and a length of case wiring, one more marginal joint
in a chain whose first joint (the cable connector, `docs/22`) is already the main fault source.
Potentially unsafe, not recommended.

**Tooling** (the first half needs no Windows and no headset):

```bash
./scripts/usb-port-map.sh map                      # name every socket + its controller
./scripts/usb-port-map.sh qualify "<socket label>" # with the headset plugged in: the ladder
```

`qualify` walks four rungs and says where it stopped: (1) does anything enumerate, (2) **does the
USB2 branch come up** — the rung that separates good sockets from bad, since the SuperSpeed pair
can appear on a socket where the USB2 pair never will (`docs/22`); it prints the kernel's own
`error -71` / `Cannot enable` lines on failure, (3) does `panel.py activate` succeed, (4) does a DP
connector *appear*. Verdicts land in `~/vr/usb-port-ledger.jsonl`, keyed by board + socket.

### What a BAD socket looks like from Linux

Headset on a socket of the **chipset** controller:

```
1. USB census: 2/5
   socket: 2-1   controller: 0000:02:00.0   400 Series Chipset USB 3.1 xHCI
2. USB2 branch INCOMPLETE:
     usb usb1-port1: Cannot enable. Maybe the USB cable is bad?     <- x4
     usb usb1-port1: attempt power cycle
     usb usb1-port1: unable to enumerate USB device
```

The **SuperSpeed pair comes up perfectly** (`04b4:6504` and `045e:0659`: cameras, IMU and
controller tunnel) and the **entire USB2 branch never enumerates**: no `04b4:6506`, no companion
`03f0:0580`, no audio `0bda:4c15`. With no companion there is no panel control, activation,
display, audio, IPD or proximity: the headset is *present* and completely unusable.

> **`Cannot enable. Maybe the USB cable is bad?` — the cable was fine here.** That message is the
> kernel guessing: the same cable gives a clean 5/5 on a CPU-controller socket. It means "this port
> could not enable this device", and the port is a cause it names nowhere. It does not retract
> genuine cable failures (the same signature across several ports on two machines is not explained
> by a controller), but it changes the reading order: **when you see this line, check which
> controller the socket is on before you suspect the cable.** One command, free.

### Reading a census (the discriminator)

A 2/5 census alone is ambiguous: a cable-orientation fault gives 2/5 on a *good* socket. Keying
the diagnosis on the controller, or on the physical socket, was tried and was wrong. `docs/22`
measured in a ten-seat matrix on one controller that **the same physical port gives different
branch subsets on different insertions**: with a 180° flip of the C plug inside the C-to-A adapter
a port went from USB2-only to 5/5, and a phone enumerated fine on a port where the G2's USB2 pair
had failed seven times in a row — **port absolved, plug seat condemned**. The mechanism: SS pins sit
at the tip of the connector tongue and the USB2 pair mid-connector, so worn contacts make seating
depth and angle select which group mates. A half-dead seat is also rock-stable (a 5-minute journal
watch logged zero events), so "sustained" does not distinguish a bad socket from a bad seat.
**Try the port first, the orientation second:**

| census | reading | the measured lever |
|---|---|---|
| 5/5 | this seat is good — **do not touch it again** | — |
| **2/5, SuperSpeed only** | **correct plug side**, USB2 branch didn't join | **PC-end USB-C unplug, ~10 s cold, replug SAME port SAME side** — 6/6 |
| 2/5 that recovers in a few seconds | not the seat: the ordinary USB2 storm | wait; nothing to fix |
| 4/5, SuperSpeed missing | a black USB2 socket: panel can work, tracking cannot | move to a blue USB3 socket |
| **0/5**, headset powered | **wrong plug side** (matched orientation = 0/5, always) | flip the C plug 180°, same port |
| 0/5, headset unpowered | power first | mains brick, then the census |

One negative is on file: the cold replug does **not** convert a never-good socket (two insertions
with the USB2 pair failing actively with `error -71` while SuperSpeed enumerates beside it). A
quick unplug/replug is also not always enough: one reseat sat silent at 0/5 for ~1m50s with zero
re-enumeration attempts in `journalctl -k` before a second, firmer reseat brought it back in under
4 seconds. Confirm the plug is fully seated before concluding a replug failed.

### The USB2-only socket, and the result that closes the activation question

Plugged into a **black rear USB2 port**, the census is **4/5 — not 3/5**:

```
[MISSING] 04b4:6504  SuperSpeed hub     the USB3 side of the cable's active hub
[ok]      045e:0659  HoloLens Sensors   enumerated at HIGH SPEED, on the 480 Mbps hub
[ok]      04b4:6506  USB2 hub
[ok]      03f0:0580  companion
[ok]      0bda:4c15  audio
```

**The HoloLens Sensors device does not disappear on USB2 — it falls back to high speed.** What is
true is bandwidth: four 640×480 mono streams at 30 fps are **~295 Mbps on their own**, on a
480 Mbps bus that also carries audio and the companion, against a real-world USB2 bulk ceiling of
300-400 Mbps. Tracking there is bandwidth-marginal (unmeasured either way).

On that socket `panel.py activate` **succeeded and `card0-DP-3` appeared** (baselined: the desktop
monitors were connected before, `DP-3` was not), so **the Linux activation procedure is proven from
a cold DP connector with no Windows involved, and Oasis is not needed for it.** The same ladder was
then proven end to end on the socket a session actually uses (`4-2`: plug → 5/5 in three seconds →
activation accepted → `card0-DP-3`).

The mechanism it exposes: DP hotplug is driven by the **companion alone**, over USB2, and never
touches the SuperSpeed branch. **Panel and tracking are independent paths**, which is why the panel
can light while tracking is dead and vice versa. Hence a lit panel is *not* evidence that the socket
is good; the tool's verdict on such a socket is **PANEL YES, TRACKING NO**.

> ### The HP logo is the most misleading signal in the whole procedure
>
> It is the first thing anyone looks at, it appears during activation, and it looks exactly like
> success. **It is an electrically lit marking on the FRONT SHELL of the headset — outside, visible
> without wearing it — not something drawn on the panel.** **It means the headset has power and the
> PC could talk to it over HID. That is all.** It does not mean the socket is right, that there
> will be an image, or that tracking will work: the logo lit on a USB2-only socket where the cameras
> cannot be carried, and `docs/22` already established it as a pure power+HID diagnostic independent
> of DisplayPort. The tool prints this warning **before** running the activation.

**Measured, all three socket types:** CPU-controller USB3 → 5/5, activation accepted.
Chipset-controller USB3 → 2/5, USB2 branch never enumerates. Black USB2 → 4/5, panel proven,
tracking bandwidth-marginal.

## Procedure 1 — Move the Root Disk to SATA (POWERED OFF)

The dev kit's `sda` is a **Crucial CT240BX500SSD1**, a **2.5" SATA SSD inside a JMicron JMS578 USB
enclosure** (ceiling ~430 MB/s). The board has the chipset's SATA controller (`02:00.1`, AMD 500
Series) with **6 AHCI ports (`ata1`..`ata6`), all empty**. Plugging the SSD into SATA fixes the
problem at the root: the headset ends up alone on `07:00.3`, the disk moves to SATA III
(~550 MB/s), and the root filesystem stops depending on a bus that resets itself.

Boot is not affected (verified in advance): `/etc/fstab` uses `UUID=` for `/` and swap;
initramfs contains `ahci` (`MODULES=most`); boot mode is BIOS/legacy with a `dos` partition table
and an MBR on the disk itself, which travels with the disk.

1. Power off completely and unplug from the mains (root disk: never hot-swap).
2. Open the enclosure and take out the SSD.
3. Connect it to `SATA1` + a free **SATA power** connector from the PSU (you may need a SATA data cable).
4. Mount it in a 2.5" bay or just rest/zip-tie it (an SSD has no moving parts).
5. Power on, **enter the BIOS and set that disk first in the boot order**: it stops being "USB HDD"
   and becomes SATA, and not every BIOS reorders this on its own.

Verify:

```bash
lsblk -o NAME,SIZE,TRAN,MODEL   # sda should show TRAN=sata, not usb
```

## Procedure 2 — Kill Autosuspend for the Disk and Headset

The kernel default (`usbcore.autosuspend=2`) suspends "idle" devices; the hub carrying the root
disk was set to `auto`. A udev rule is in `scripts/71-usb-no-autosuspend.rules`:

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

When the bus hangs, the USB errors are only visible on the console unless a regular user can read
`dmesg` / `journalctl -k` (missing groups + `dmesg_restrict=1`):

```bash
sudo usermod -aG adm,systemd-journal <your-user>
# log out and back in (or reboot), then verify:
journalctl -k | head    # should show kernel lines
```

Optional (more convenient for diagnostics):

```bash
echo 'kernel.dmesg_restrict = 0' | sudo tee /etc/sysctl.d/10-dmesg.conf
sudo sysctl --system
```

## Procedure 4 — Stress Test (gate before continuing with the rest)

Reproduces the load that caused the hang, now with the buses separated:

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
dropout (03f0:0580 stable in `lsusb`).

## Note on the Enclosure

The headset's companion board fault is **physical** (it happens the same way on Windows; a suspect
cable/connector, see `06-known-issues.md`). Separating the buses does not fix it: it keeps that
fault from dragging down the system disk. Once the SSD is on SATA, the JMS578 enclosure is free for
backups or external disks, just never again for the root filesystem.
