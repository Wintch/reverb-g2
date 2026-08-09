# 26 — Diagnostic toolkit: what's wrong in the chain, and what to buy

The G2 is discontinued, no manufacturer support left. Nobody hands you a real diagnostic
flow for it. This chapter is that flow: a short decision tree that narrows a dead/flaky
headset down to one physical part, using the tools already in `scripts/`, so a purchase
decision is based on measurement instead of guessing. It's the buying-guide companion to
`docs/22-cable-connector-diagnosis.md` (the full narrative and evidence) and
`docs/00-hardware-usb.md` (the USB topology this all sits on) — read those for the "why",
this is the "what do I run, in what order, and what do I conclude."

## The chain, in one picture

```
12V brick --> cable --> visor connector (behind the magnetic face gasket, detachable)
                            |
                            +-- DP lanes + AUX --> display bridge --> panel (HP logo, image)
                            +-- USB2: hub (04b4:6506) -> companion HID (03f0:0580)
                            |                          -> audio (0bda:4c15)
                            +-- USB3: HoloLens Sensors / cameras (045e:0659)
                            +-- USB3: WMR hub component (04b4:6504)
```

Four independent branches share one cable and one connector. Each can fail on its own —
that's exactly why "the headset is dead" is never a useful symptom description; which
branch(es) are dead is.

## The toolkit

| Tool | What it checks | Needs root |
|---|---|---|
| `scripts/preflight.sh` | USB census (5 device IDs), controller online status, DP/EDID fingerprint | no |
| `scripts/panel.py activate` | Sends the WMR HID activation; the only way to wake the panel from cold | no |
| `scripts/drmprops.c` | Reads the connector's real EDID and checks it against the G2's known fingerprint (mfg `0x220e` "HPN", product `0x36c1`) instead of just byte-counting it | no |
| `scripts/usb-bus-reset.sh` | Kernel-level unbind/rebind of the USB2 root hub — a software reset with zero physical contact | **yes** |
| `scripts/check-lease.sh` | Does the Wayland compositor actually offer the HMD connector as a DRM lease | no |
| `scripts/capture-hid.sh` + `analyze-hid.py` | Deep HID traffic capture, for when the above isn't enough | **yes** |

The EDID fingerprint check is worth calling out: **EDID byte count alone is not a health
signal.** This lab's ordinary desktop monitors also report a plain 128-byte base block
with a perfectly healthy mode list — no DisplayID extension needed for a normal monitor.
What identifies the G2's panel unambiguously is checking the actual fingerprint bytes
(manufacturer + product ID) against a known-good capture
(`forum-attachments/g2-edid.bin`). When the visor's own connector doesn't carry that
fingerprint, what's there instead is pure zeros past the mandatory header — a synthetic
kernel placeholder, not a partial real EDID. Don't judge health by size.

## The decision tree

**1. USB census** — `./scripts/preflight.sh`, step 1/3.

| Result | Read |
|---|---|
| 5/5 | Both USB branches + contacts fine. Go to step 2. |
| Only `6504` + `0659` (2/5) | USB2 pair down (hub/companion/audio missing), USB3 fine. Contact issue on the USB2 half specifically. |
| 1/5 or 0/5 | Whole branch tree collapsing, or connector not seated / cable not in the PC at all. |

Cross-check with `journalctl -k --since "5 min ago" | grep "usb 3-"` (or whichever bus the
USB2 branch is on): `error -71` + `Cannot enable. Maybe the USB cable is bad?` is the
marginal-contact signature specifically — not a driver problem, don't debug Monado for it.
Silence (no retry storm at all, device just absent) is a *different*, worse state: the
kernel isn't even trying, which in this project's history has meant the connector needs a
physical reseat, not more waiting.

**2. Panel / DP check** — `./scripts/preflight.sh`, step 3/3 (wraps `panel.py activate` +
the EDID fingerprint match from `drmprops.c`).

| Result | Read |
|---|---|
| HP logo lights, EDID fingerprint matches | 12V rail + companion + display board + DP lanes all healthy. |
| No logo at all | 12V path or display board fault. USB being fine is irrelevant here — these are separate conductor groups. Check the brick before blaming the cable. |
| Logo lights, connector never reaches `non-desktop=1` with the real fingerprint | DP lanes/AUX/bridge specifically, or a stale detection race — retry the check (activation→hotplug latency isn't fixed, has measured as slow as ~6s). |

**3. If both branches show damage together** (USB2 down *and* DP/panel misbehaving,
or symptoms that drift across a session): this is the pattern that has meant "the cable
itself, not one isolated fault" every time it's been seen in this project (`docs/22`).

**4. The escalation ladder** — cheapest and least invasive first, stop as soon as one step
fixes it:

1. **Rest.** If it's actively storming (re-enumerating every few seconds), stop touching
   it and wait — repeatedly restarting services or cycling the panel is itself a known
   trigger that makes this worse, not better.
2. **Reboot** the host. (Not always neutral — measured once making things *worse*, 2/5 →
   1/5 across a reboot. Still worth trying before anything physical, but don't assume it's
   risk-free.)
3. **Software bus reset**, zero physical contact: `sudo ./scripts/usb-bus-reset.sh`.
   Targets the whole USB2 root hub, not a single device path — when the branch is fully
   absent there's no live device node for a narrower unbind to act on.
4. **Cable disconnect/reconnect at the PC end only** — isolates PC-side seating from
   visor-side seating as a variable, without touching the visor connector at all.
5. **Headset power cycle** (unplug the 12V brick, wait, replug) — has independently
   recovered the USB2 branch before, separate from any connector reseat.
6. **Reseat the cable at the visor end**, behind the magnetic face gasket — the connector
   is detachable, not fully integrated. This has been the single highest-hit-rate fix
   across this project's whole history.
7. **Replace the cable.** Only after step 6 has been tried and either doesn't hold or
   stops working — see "What to buy" below.

## What to buy, by symptom pattern

| Pattern | Likely fault | Buy |
|---|---|---|
| USB2 branch intermittently drops (storms of re-enumeration), reseat fixes it temporarily but it recurs | Visor connector contact, degrading | Replacement cable: **"HP Reverb G2 cable rev 2A"**, a.k.a. "OCuLink to USB-C + DisplayPort cable" — the same part HP shipped as a running fix for early-production G2 cable failures. Community-documented symptom match: USB fine, display dead or flaky, "not detected" errors. |
| No HP logo at all, ever, USB unaffected | 12V brick or power path, not the data cable | Test/replace the 12V power brick *before* assuming the cable — these are electrically independent of the USB/DP conductor groups. |
| DP never comes up (no EDID fingerprint match), USB and logo both fine | Software timing race (retry the check) or, if persistent, DP lanes/bridge specifically | Re-run `preflight.sh` a few times first — this exact symptom has been a detection race, not hardware, before. Only escalate to the cable if it's persistent across many clean attempts. |
| Everything simultaneously dead, zero enumeration anywhere, no retry storm in `journalctl -k` | Connector fully unseated, or genuinely dead cable | Reseat first (step 6 above) — this exact pattern has been "connector not actually engaged," not a dead cable, before. Only conclude "replace it" after a clean reseat attempt with the connector visibly, physically confirmed seated. |

## Multi-OS note

Everything above is Linux-specific (`lsusb`, `journalctl -k`, sysfs unbind/bind). The
underlying signal — which of the four conductor groups is affected, in what pattern — is
not OS-specific, and a Windows-equivalent checklist (Device Manager error codes, the
Windows Mixed Reality portal's own status page, `pnputil`/`devcon` for the USB reset
step) is a natural follow-up so this is useful to anyone with a failing G2, not just this
lab. Not started — logged as a direction, not a task in progress.
