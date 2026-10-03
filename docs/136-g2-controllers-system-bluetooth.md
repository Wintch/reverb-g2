# 136 — G2 motion controllers on the host's Bluetooth adapter (2026-10-03)

Answers rpavlik's comment on !2967 (note 3667686): the G2 controllers do not have to use the
headset's radio. Re-paired to a TP-Link UB500 Plus (RTL8761B, plain `btusb` + `rtl8761bu_fw.bin`),
`wmr_bt_controller.c` works on real G2 hardware. Reply posted as note 3693637 (thread
`0e01f17a…`). Lab: dev (iashur), Debian 13, kernel 6.12, BlueZ 5.82, Monado `lab-full`.

Controller BD addresses are deliberately not in this repo; the scripts read them from
`G2_LEFT_BD` / `G2_RIGHT_BD`. Scripts live in `scripts/bt-controllers/`.

## Result

| Check | Result |
|---|---|
| Pair + bond to host adapter | works (recipe below; BlueZ's own order does not) |
| BlueZ creates hidraw `0005:045E:066A` | yes, once Paired + Bonded + Trusted and the controller reconnects |
| `wmr_find_bt_controller_pair` / `wmr_create_bt_controller` | both created, config read over BT (serial, calibration, 32 LEDs), battery parsed |
| 3dof orientation | follows both hands |
| `ctrl` mode (constellation) | both registered; position tracked ~36-41 % of samples in a held-in-front test (rings facing the headset: good; rings away: lost, as expected optically) |
| Report rate | 200 Hz while in use (5 ms device tick), 20 Hz idle (50 ms) |
| Buttons / sticks / grip / trigger | confirmed except left trigger, left Y, left Windows and both stick clicks (not captured, user timing; same parser both hands) |
| Haptics | works over BT, see below |

## Pairing recipe (the part that cost hours)

1. `bluetoothctl pairable on` first. With `Pairable: no` the pairing "succeeds" with *No Bonding*
   (`Store hint: No` → `Bonded: no`) and the link drops.
2. Keep an agent running (a long-lived `bluetoothctl`), put the controller in pairing mode
   (power-cycle, then hold the hidden battery-compartment button ~3 s, slow LED pulse; the
   window is ~30-60 s) and have it in one looped `bluetoothctl --timeout 25 scan on`.
3. **Windows order, not BlueZ's:** raw L2CAP `SOCK_SEQPACKET` to PSM 0x11 (HID control) with
   `BT_SECURITY=BT_SECURITY_MEDIUM` so the kernel pairs on demand, then PSM 0x13 (interrupt), both kept
   open. This is what the headset's WICED radio does (HID/SDP before SSP). `bluetoothctl pair`
   first and HID afterwards never worked: the controller ignores PSM 0x11 after ~1 s or refuses
   0x13 with "no resources". Never cut `bluetoothctl pair` with `timeout`.
4. `bluetoothctl trust <addr>` on each; BlueZ's input plugin then creates the hidraw when the
   controller reconnects by itself (incoming ACL).
5. The controllers only keep HID up while awake (LEDs steady after a shake).

Same symptom family as bluez/bluez#689 (WMR controllers dropping after pairing, closed stale).

## Findings

- **The G2's BT HID descriptor (741 B)** declares Input 1, Feature/Output 3 and 4 and does not
  declare Monado's fw-command reports 0x06/0x02. The controller answers 0x06 writes with 0x02
  replies anyway; Monado works despite the descriptor.
- **BT-controller creation failure is fatal for the whole system.** `wmr_create_bt_controller`
  failing → `goto error` → the wmr builder falls back to the Simulated HMD (headset included).
  Trigger: a bonded controller asleep when the service starts (fw read times out 250 ms × 3).
  `jack-in-wayland.sh` now guards against this (below).
- **Report rate is the controller's, not the link's.** btmon of ACL RX showed an alternation
  between 5 ms and 50 ms device ticks, 20 Hz after ~30 s without motion, 200 Hz as soon as the
  controller moves, regardless of distance (0 m and 1 m) and with no HCI mode-change events.
  Earlier "distance" and "~65 Hz" readings were artefacts: time-since-motion, and the
  measuring script's own `hcitool` calls overflowing the hidraw queue. Monado follows the idle ↔
  active switch without trouble.
- **RF:** the USB extension cost 7-16 dB of RSSI at 1 m (-18/-28 with it, -11/-12 direct in a
  USB 2.0 port). `hcitool rssi` is relative to the receiver's golden range (0 = ok, negative =
  weak) and works without root. Headset USB3/camera traffic did not change the link.
- **Haptics wire format is in the controller's own descriptor:** Output report **id 4**, Usage Page
  0x0E (Haptics): Manual Trigger (0x21) + Intensity (0x23), 8 bit each, logical range 0..100, so a
  hidraw write of `[04, trigger, intensity]`; Feature id 4 usage 0x28 is the waveform cutoff time.
  Measured by hand: index 3 is a **continuous buzz**; 1 and 2 also vibrate (character not yet
  recorded); **index 4 and index 0 (`[04 00 00]`) make the controller stop streaming** for ~10 s
  (ACL stays connected, it recovers by itself). Do not use 0 as a "stop". Patch 0078's guessed
  `{0x06,0x03,0x03,…}` is not this format. Open: what stops the buzz safely (intensity 0 on index 3?),
  1 vs 2 character, and the tunnel path (report id gets the controller's `hmd_cmd_base` added).
- Left trigger `isActive=0` in the hello_xr player is not BT-specific (same in the 2026-09-06 tunnel-era log).

## Game test: Propagation VR (2026-10-03)

Joys on the host adapter, Steam title via xrizer, wearer in the headset.
- `6dof` + `WMR_CONSTELLATION_CONTROLLERS=1`: controllers **0 / 67** tracked samples (anchored at a point,
  orientation from the IMU only), `monado-service` ~700 % CPU, 5 980 late frames, Basalt dropped 3 000
  camera frames, >10 700 trusted-yaw rejections. Head 6dof felt good. Same CPU-starvation family as docs/23.
- `ctrl`: ~330 % CPU; left 5 / 146 (3 %), right 39 / 146 (27 %) tracked samples. Hand rotations good;
  hands often sit near the headset (parked/placeholder); drew the weapon, aimed and fired; exiting the
  game with the controllers worked. The weak/parked left controller is the known constellation issue
  (docs/125-126), not a Bluetooth effect.

## LED brightness over system BT (2026-10-03, patch 0112)

**The command never reached host-BT controllers.** `wmr_hmd.c` ticks the LED pulse train (and the
keepalive) only for controllers in its own tunnelled table, so `WMR_CONTROLLER_LED_INTENSITY` was a silent
no-op for everything created through `wmr_bt_controller.c`. Patch 0112 ticks it from the BT read loop
(default behaviour unchanged: it does nothing unless the env option is set), adds
`WMR_CONTROLLER_LED_INTENSITY_LEFT/_RIGHT`, and logs one INFO line per controller on the first command
(`first LED pulse-train command sent (intensity N, 15 Hz): ok`).

**Validated by eye over BT** (`scripts/bt-controllers/bt-led.py`, phone camera shows the IR LEDs): report id 3,
12 bytes, byte-identical to the Windows capture decode (`03 cc 21 03 00 00 00 00 00 00 80 2c` for intensity 200);
brightness scales monotonically with the value (20 / 100 / 200 / 399). There is no "off" command: the controller
keeps the last brightness it received until it sleeps or is power-cycled (intensity 1 dims it).

**Per-hand mapping from the Windows capture** (docs/re-windows/04): report 0x08 (= 3 + base 0x05, left) is driven
~1.3-1.4x longer than 0x10 (right), roughly 225 vs 165 in the 1..399 scale; the ratio varies 0.5-3.2x over time,
so it looks adaptive rather than fixed.

**Static protocol** (`ab-static.sh`: headset fixed on a desk, both joys held still, rings toward the cameras, lit
room; per distance 12 s to place + 25 s measured; joys confirmed awake by a hidraw rate of ~200 Hz in every window):

| Arm (left / right) | 50 cm (L, R tracked of 25) | 75 cm | 100 cm |
|---|---|---|---|
| A: 0 / 0 (no command, historical) | 25, 25 | 0, 0 | 0, 0 |
| B: 200 / 200 | 25, 3 | 0, 0 | 0, 0 |
| C: 225 / 165 | 0, 11 | 0, 0 | 0, 0 |

- The **visibility cliff of docs/125 reproduces on system BT**: perfect at 50 cm, zero from 75 cm, joys awake throughout.
- **LED brightness does not move the cliff**, and at 50 cm more light did not help (only arm A is perfect for both hands).
- Which hand locks in B and C swaps, which looks like the blob-ownership lottery of docs/126 (the first device to win a
  solve keeps the shared blob pool), not a brightness effect. "Tracked yes/no over 25 s" therefore cannot answer the
  brightness question; the next instrument would be blob count and size per distance
  (`WMR_CONSTELLATION_BLOB_TELEMETRY`, patch 0111). Not run.
- Earlier worn A/B (0 vs 200, light vs dark, held in the hands) was dominated by how the joys were held and showed no clear effect.

## Launcher guard

`scripts/jack-in-wayland.sh` (commit de41ead): when ≥1 "Motion controller" is bonded to the host
adapter, wait up to `VR_BT_CTRL_WAIT` (30 s) for the BlueZ hidraw nodes, speak a prompt, abort with
rc=2 and **no fail marker** if none wakes. `VR_BT_CTRL_CHECK=0` skips it. Live-tested both ways
on 2026-10-03: joys off → aborts cleanly; joys shaken during the wait → full launch, both controllers created.

## Mechanics / traps

- btmon needs a real terminal for sudo (`! ssh` has no TTY); `sudo btmon -w ~/x` expands `~` to
  `/root`. Never reuse a capture file name.
- `monado-cli probe` against a live `monado-service` segfaults (LIBUSB_ERROR_BUSY). `PROBER_LOG=trace`
  is the prober trace variable.
- Controllers are now bonded to the host adapter, **not** the headset. Decision: they stay there.
  Needs the adapter directly in a USB 2.0 port and the controllers awake before Monado starts.
  Windows (same machine) would need its own pairing.

## Open

Hotplug/standby recovery inside Monado (HID drop mid-session is not recovered); haptics follow-up
above and a patch against `wmr_controller_base_set_output`; the unconfirmed controls; a long soak;
a Steam/xrizer title with these controllers; Oasis/Ignition (needs external BT, now possible).
