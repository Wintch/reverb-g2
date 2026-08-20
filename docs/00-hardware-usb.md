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

### ⚠️ This chapter's port table was measured on a DIFFERENT board than the current lab machine

Written for a box whose xHCI controllers are `07:00.3` (Matisse/CPU) and `02:00.0` (A520
chipset). The lab machine as of 2026-08-19 is an **ASUS TUF GAMING B450M-PLUS II**, whose
controllers are **`09:00.3` (Matisse/CPU)** and **`02:00.0` (400 Series chipset)**. The port
map is a property of the BOARD, so do not carry numbers between them — run
`./scripts/usb-port-map.sh map`, which reads the live topology instead of trusting this table.

### Port-to-port reliability: the mechanism is the CONTROLLER, and it is now addressable (2026-08-19, T231)

**The user's standing observation, now with a mechanism**: of the rear USB3 sockets, some work
with the G2 and some do not, and *the manual does not say which* — a cheap board's manual never
mentions that its rear ports are wired to two different xHCI controllers. Measured live on the
B450M box:

```
usb1 / usb2   0000:02:00.0   400 Series Chipset USB 3.1 xHCI     <- the other path
usb3 / usb4   0000:09:00.3   Matisse USB 3.0 Host Controller     <- where the headset works
```

The headset sits on `usb3-port2` + `usb4-port2`, i.e. **the CPU controller**. The chipset
controller's four SuperSpeed ports sit empty. So "the two that go by another route and do not
work" has a concrete, checkable meaning: **they hang off the chipset xHCI, not the CPU one.**

**This also closes the addressing gap this chapter complained about below.** `ID_PATH` could not
tell two sockets apart; the **root-hub port topology** can. `/sys/bus/usb/devices/usbN/N-0:1.0/
usbN-portM` exists for every physical port, occupied or not, so every socket has a stable name
(`usb4-port2`) whether or not anything is plugged in — which means a socket can be *named*, a
verdict can be *recorded against that name*, and the next person can be told which socket to use
instead of being told to try all four.

**Standing rule: REAR SOCKETS ONLY.** The front-panel USB3 header has **never been tested** with
this headset, and it is not going to be, for a reason that is about risk and not curiosity: front
panels reach the board through an internal header and a length of case wiring, which is one more
marginal joint in a chain whose *first* joint has already cost this project weeks (`docs/22`).
The cable is enough of a mess on its own — do not add another variable to it. **Potentially
unsafe, not recommended**, and if someone tries it anyway the ledger below is where the result
belongs.

**Tooling, and it needs no Windows and no headset for the first half:**

```bash
./scripts/usb-port-map.sh map                      # name every socket + its controller
./scripts/usb-port-map.sh qualify "<socket label>" # with the headset plugged in: the ladder
```

`qualify` walks four rungs and says exactly where it stopped: (1) does anything enumerate,
(2) **does the USB2 branch come up** — the rung that actually separates good sockets from bad,
since the SuperSpeed pair can appear on a socket where the USB2 pair never will (docs/22), and
it prints the kernel's own `error -71` / `Cannot enable` lines when it fails, (3) does
`panel.py activate` succeed, (4) does a DP connector *appear*. Verdicts land in
`~/vr/usb-port-ledger.jsonl`, keyed by board + socket.

### What a BAD socket looks like from Linux — measured 2026-08-19 (T231)

Headset moved to a socket on the **chipset** controller. This is the capture that makes the
step-by-step possible, because it is what someone without Windows will actually see:

```
1. USB census: 2/5
   socket: 2-1   controller: 0000:02:00.0   400 Series Chipset USB 3.1 xHCI
2. USB2 branch INCOMPLETE:
     usb usb1-port1: Cannot enable. Maybe the USB cable is bad?     <- x4
     usb usb1-port1: attempt power cycle
     usb usb1-port1: unable to enumerate USB device
```

**The SuperSpeed pair comes up perfectly** — `04b4:6504` and `045e:0659`, i.e. the cameras, IMU
and controller tunnel — **and the entire USB2 branch never enumerates**: no `04b4:6506`, no
companion `03f0:0580`, no audio `0bda:4c15`. The kernel tries four times on the 480 M root-hub
port, power-cycles it, and gives up. With no companion there is no panel control, no activation,
no display, no audio, no IPD and no proximity: the headset is *present* and completely unusable.

> ### ⚠️ `Cannot enable. Maybe the USB cable is bad?` — the cable was FINE
>
> That message is the kernel guessing, and this capture proves the guess wrong: the same cable,
> minutes earlier and minutes later, gives a clean 5/5 on a CPU-controller socket. **The message
> means "this port could not enable this device", and the port is a cause it names nowhere.**
> This project spent weeks reading that line as evidence of a dying cable (`docs/06`, and the
> T039/T040 "the cable is dying wholesale" verdict rests partly on it).
>
> It does not retract those episodes — there the same signature appeared across several ports on
> two machines, which a controller cannot explain — but it does change the reading order:
> **when you see this line, check which controller the socket is on before you suspect the
> cable.** That check is free, takes one command, and this is exactly the case it catches.

**The discriminator, and it is what makes the diagnosis decisive.** A 2/5 census on its own is
ambiguous: T184 produced 2/5 on a *good* socket from a cable-orientation fault. The controller
resolves it:

| census | reading |
|---|---|
| 5/5 | socket is fine |
| **2/5 sustained** | **bad socket — try another, including others on the same controller** |
| 2/5 that recovers within a few seconds | not the socket: that is the ordinary USB2 storm (T226), keep watching |
| 4/5, SuperSpeed missing | a black USB2 socket: panel can work, tracking cannot |
| 0/5 | nothing enumerates: power, cable seating, or a dead port |

> **CORRECTED TWICE, and the second correction RETRACTS the first (T233 → T234).**
>
> **First version** keyed on the controller: 2/5 on the chipset meant "wrong socket", 2/5 on the
> CPU controller meant "suspect the cable". **Second version** (T233) keyed on the physical
> socket, after `4-1` on the CPU controller gave a sustained 2/5 while `4-2` on the same
> controller gave 5/5. **Both were wrong, and `docs/22` already contained the answer** — the user
> replied "no es que hay un USB de CPU malo y otro bueno, revisá bien la documentación."
>
> **What `docs/22` measured, in a ten-seat matrix on this exact controller**: the same physical
> port gives different branch subsets on different *insertions*. Rear A #1 gave SS-only; rear A
> #2 gave USB2-only on one seat and, **with a 180° flip of the C plug inside the C-to-A adapter,
> 5/5**. A phone enumerated fine on a port where the G2's USB2 pair had failed seven consecutive
> times — **port absolved, plug seat condemned**. The mechanism on file: SS pins sit at the tip of
> the connector tongue and the USB2 pair mid-connector, so worn contacts make **seating depth and
> angle select which group mates**.
>
> **Why "sustained for a minute" did not prove what I thought.** It rules out the *storm*, whose
> outages last ~3 s — that part was right. It does **not** distinguish a bad socket from a bad
> seat, because `docs/22` explicitly measured that a half-dead seat is **rock-stable**: "a
> 5-minute journal watch on a half-dead seat logged ZERO spontaneous events. No self-recovery, no
> flapping." Stability was already known to be a property of both, so it discriminates neither.
>
> **The rule that survives all three attempts**, and it is the one `docs/06` had from the start —
> *try the port first, the orientation second*:

| census | reading | the measured lever |
|---|---|---|
| 5/5 | this seat is good — **do not touch it again** | — |
| **2/5, SuperSpeed only** | **correct plug side**, USB2 branch didn't join | **PC-end USB-C unplug, ~10 s cold, replug SAME port SAME side** — T186, **6/6** |
| 2/5 that recovers in a few seconds | not the seat: the ordinary USB2 storm (T226) | wait; nothing to fix |
| 4/5, SuperSpeed missing | a black USB2 socket: panel can work, tracking cannot | move to a blue USB3 socket |
| **0/5**, headset powered | **wrong plug side** — T184: matched orientation = 0/5, always | flip the C plug 180°, same port |
| 0/5, headset unpowered | power first | mains brick, then the census |

> **Fourth and final version of this table tonight, and this one is not mine — it is the two
> levers the record already held, each tied to its census signature.** T184 (tape-marked A/B):
> the wrong orientation gives 0/5 *always*, so the flip is the 0/5 lever and nothing else. T186:
> from 2/5, a PC-end cold replug on the same port and same side went **6/6 to a clean 5/5**. The
> agent's intermediate versions keyed on the controller, then the socket, then told the user to
> flip out of a 2/5 — which would have landed on 0/5. Every wrong version generalised a fresh
> measurement over a better one sitting unread in `docs/22`; the user corrected all three from
> memory of his own record.

### The USB2-only socket, and the result that closes the activation question (T231)

Plugged into a **black rear USB2 port**, the census is **4/5 — not 3/5**, and the missing one is
not what you would guess:

```
[MISSING] 04b4:6504  SuperSpeed hub     the USB3 side of the cable's active hub
[ok]      045e:0659  HoloLens Sensors   enumerated at HIGH SPEED, on the 480 Mbps hub
[ok]      04b4:6506  USB2 hub
[ok]      03f0:0580  companion
[ok]      0bda:4c15  audio
```

**The HoloLens Sensors device does not disappear on USB2 — it falls back to high speed.** So
"a USB2 port means no cameras" is wrong. What is true is bandwidth: four 640×480 mono streams at
30 fps are **~295 Mbps on their own**, on a 480 Mbps bus that also carries the audio device and
the companion, against a real-world USB2 bulk ceiling of 300-400 Mbps. **Tracking there is
bandwidth-marginal — a thing to measure, not to assert in either direction.** Still unmeasured.

> ### ✅ The Linux activation procedure is proven, and Oasis is not needed for it
>
> On that same USB2-only socket, `panel.py activate` **succeeded and `card0-DP-3` appeared** —
> baselined, so this is a real hotplug and not a connector that was already awake: `DP-1` and
> `DP-2` (the desktop monitors) were connected before, `DP-3` was not.
>
> That closes a gap this project carried for a long time — *"first you have to activate the
> headset, and that procedure is pending on Linux; it was only ever tested on Windows"*. It is
> tested now, from a cold DP connector, with no Windows involved.
>
> **And the mechanism it exposes is worth more than the result**: DP hotplug is driven by the
> **companion alone**, over USB2, and never touches the SuperSpeed branch. **Panel and tracking
> are independent paths.** That is why the panel can light while tracking is dead, and why
> tracking can run on a headset whose panel never came up — a pattern this project has hit
> repeatedly without naming the cause.
>
> **The trap that follows from it**: a lit panel is *not* evidence that the socket is good. The
> tool said "GOOD SOCKET — leave the cable here" on the first run and had to be corrected; that
> advice would park someone on a socket where tracking cannot work. The verdict is now
> **PANEL YES, TRACKING NO**.

> ### 🚨 "Veo el logo HP" — the most misleading signal in the whole procedure
>
> It is the first thing anyone looks at, it appears during activation while they are watching,
> and it looks exactly like success. **It is an electrically lit marking on the FRONT SHELL of
> the headset — outside, visible without wearing it — not something drawn on the panel.**
> (Corrected 2026-08-19: an earlier version of this warning said "inside the visor", which
> would send someone to look in the wrong place and call a merely misplugged headset dead.) **It means the headset has power and the PC could talk to
> it over HID. That is all.** It does not mean the socket is right, that there will be an image,
> or that tracking will work — measured here, the logo lit on a **USB2-only socket where the
> cameras cannot be carried**, and `docs/22` already established it as a pure power+HID
> diagnostic independent of DisplayPort.
>
> The tool therefore prints the warning **before** running the activation, not after: by the time
> a verdict appears on the terminal, the person has already seen the logo and decided it worked.

**CLOSED (2026-08-20, T234): the full ladder is proven on the real socket.** `4-2`: plug →
5/5 in three seconds → activation accepted → **`card0-DP-3` appeared**, baselined against a
genuinely cold panel. T231's earlier proof was on the black USB2 socket (panel yes, tracking no);
this one is the socket a session actually uses, end to end, no Windows at any step. The two
recovery levers each have their census signature (table above), and one negative is on file:
T186's cold replug does **not** convert a never-good socket (`4-1`, two insertions, USB2 pair
failing actively with `error -71` while SuperSpeed enumerates beside it).

**Measured so far (2026-08-19, T231): all three socket types.** CPU-controller USB3 → 5/5,
activation accepted. Chipset-controller USB3 → 2/5, USB2 branch never enumerates. Black USB2 →
4/5, panel proven, tracking bandwidth-marginal. `4-2` on
`09:00.3` gives 5/5 and accepts activation; rung 4 could not be proven in that run because a DP
connector was already present from an earlier activation, and the tool says so rather than
claiming a pass. **Still unrun: the two chipset-controller sockets**, which is the whole point —
what a bad socket's failure *looks like* is what lets us write the step-by-step for someone who
does not have Windows to fall back on.

### Open item, not yet measured: reliability may differ port-to-port within the 4 (2026-08-09)

The table above says all 4 rear USB3 ports share the same controller — true, but it
doesn't mean they're identical. The user's own recollection (not yet backed by logged
incidents): of the 4, 2 have historically been reliable for the headset and 2 haven't,
independent of the cable/connector issues tracked in `docs/22`. The cable is connected via
a USB-C-to-USB3-A adapter.

> **CORRECTION (2026-08-12): this used to say the adapter was "fixed (non-reversible)" and
> concluded that cable-orientation flipping "isn't a variable here". Do not rely on that.**
> The adapter has since been **replaced** (HP `L56522-002` → Nisuta `NSADU30UC`) as the
> suspected fix for the `reqCmd 23`/`non-desktop:0` cluster — see `docs/22`'s hardware change
> log. Whether the current unit is orientation-reversible is unrecorded, and the claim always
> sat badly against `docs/06`, which reports that rotating the USB-C connector 180° inside the
> adapter *did* help once. Check the physical adapter before treating orientation as a
> non-variable.

`find-port.sh` can't distinguish this: it only tells you which *controller* a port
belongs to, and all 4 are on `07:00.3`. Confirming a real per-port difference needs
correlating `ID_PATH` (via `udevadm info -q path /sys/bus/usb/devices/usb3` or `usb4`,
whichever the headset lands on) against actual incident outcomes over time, not memory.

First real data points: 2026-08-09, same session, two different physical sockets tested,
both user-confirmed as historically-good ports — one next to the GPU's DisplayPort
output, one next to the motherboard's integrated HDMI (the two-pair split found in the
board's own manual, `2-6 Back Panel Connectors` diagram: the 4 rear USB 3.2 Gen1 ports
sit as one pair beside HDMI and one pair beside the RJ-45 LAN port, not in a single row).

![Rear panel of the A520M board: the 4 USB 3.2 Gen1 ports sit as two separated pairs, one
beside the HDMI output and one beside the RJ-45 LAN port](a520m-rear-usb3-port-pairs.png)

*The diagram is kept because the physical layout is the whole point: **the rear USB3 ports are
not interchangeable and they are not in a row.** Anyone reproducing this — or telling the user
over the phone which socket to use — needs to know that "the USB3 port" is four sockets in two
separated pairs, and that the user's own history says two of them have been reliable for the
headset and two have not. `find-port.sh` and `ID_PATH` cannot currently tell them apart (see
the paragraph above), so until that gap is closed the physical picture IS the addressing
scheme.*
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
