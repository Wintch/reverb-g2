# 111 — Windows control test for the panel flicker: what to look at and what to capture

> **DONE AND SUPERSEDED 2026-09-07 — see `docs/112`.**
>
> The Windows boot this brief calls for happened. Result: **Windows behaves identically to
> Linux** — 90 Hz clean, 60 Hz flickers. Contrary to this brief's prediction, flicker at 60 Hz
> on Windows does *not* mean the headset changed; it is factory backlight behaviour at a
> non-native panel frequency.
>
> Two premises inherited from `docs/110` were also wrong and are retracted there: "the flicker
> reproduces under `hmd-vk`" and "60 and 90 look identical on Linux" were both artifacts of
> `hmd-vk`'s non-solid default pattern. The USBPcap this brief asked for was captured and is
> analysed in `docs/112`; it shows Oasis sends nothing to the companion that
> `scripts/panel.py activate` does not already send.
>
> One stale fact worth carrying forward: the HMD connector is **card0-DP-1** as of this session,
> not DP-2 as written below. That name has drifted before (DP-1 → DP-3 → DP-1) — always resolve
> it live with `scripts/hmd-connector.sh` rather than trusting any doc.

Companion to `docs/110`, which records everything already ruled out on the Linux side. This is
the operator brief for the decisive experiment.

## Why Windows decides it

Every host-side variable on Linux is closed (see docs/110): our whole software stack, GPU clocks,
refresh rate, pixel clock across three modes, a full headset power cycle, the EDID, all four
NVIDIA patches, USB, and DP link status. What survives elimination is **persistent state written
into the headset by the new Oasis version's re-Unlock** — and Windows is the only environment
that can confirm that or clear it.

The test cuts both ways, which is what makes it worth doing:

- **Flicker present in Windows too** → the headset itself changed. Nothing on the Linux side is
  at fault, and Oasis becomes the tool to inspect or revert it.
- **Windows clean** → the headset is fine and something host-side on Linux was missed. Windows
  then serves as a working reference to diff against, and the capture below becomes the key
  artifact.

## Priority 1 — the one observation that matters

Look at a **bright, mostly white or light-grey scene** (the WMR/Oasis home, a white window in the
desktop view — anything with large bright flat areas and gradients). The Linux symptom, for an
exact like-for-like comparison, is:

- rapid flicker concentrated in the **bright** areas, not the dark ones
- **alternating colours** visible within the flicker, not just brightness pulsing
- present at a correct, smooth 90 fps — motion itself is fine

Confirm the headset is actually running at **90 Hz** while judging this (Oasis/WMR shows the
refresh rate), so the comparison is against the same mode that fails on Linux. If a 60 Hz option
is offered, check that too — on Linux the flicker was identical at 60 and 90, which is itself a
useful cross-check.

## Priority 2 — capture regardless of the answer

1. **Oasis version number** — screenshot. The update is the prime suspect; the exact version is
   needed to match against the changelog.
2. **Every Oasis settings tab** — screenshots. Especially anything touching display, refresh
   rate, resolution, brightness, colour depth, or persistence/strobing.
3. **The headset's firmware version**, if Oasis or Device Manager shows it. If Oasis's Unlock
   wrote persistent state, a firmware/config version string is the most likely place it shows up.
4. **Device Manager** → the headset entries and their driver versions.

## Priority 3 — the capture that could crack it

A **USBPcap capture of the headset coming up**, using the same workflow as the earlier captures
in this project (`camera_apareo_standby.pcapng` and friends):

1. Start USBPcap on the companion device — `03f0:0580`, shows as **"QHMD A85V"** / HP Windows
   Mixed Reality.
2. With the capture running, start SteamVR/Oasis so the panel powers on from cold.
3. Thirty seconds of capture past the point where the image appears is plenty.

**Why this matters more than anything else in this list:** it records exactly what Windows sends
to the companion at panel bring-up. If Windows does not flicker and Linux does, the difference is
in that byte stream — a panel parameter Windows sets that Monado never sends, or one whose value
changed with the Oasis update. That is directly actionable: Monado's activation sequence lives in
`wmr_hmd_activate_reverb()` and is already replicated in `scripts/panel.py activate`, so anything
found in the capture can be tried on Linux immediately.

Compare it against the existing `docs/re-windows/` material and the earlier captures rather than
starting from scratch.

## If Windows also flickers

Then the headset changed, and the questions become:

- Does Oasis offer a reset, re-pair, or factory-restore for the headset?
- Does re-running the Unlock (or undoing it) change anything?
- Is there a firmware version that differs from what the project has recorded before?

## Before booting: two physical checks worth two minutes

The USB side is already known good — 5/5 devices, correct negotiated speeds, zero kernel errors,
and both buses on the **CPU (Matisse `07:00.3`)** controller rather than the chipset, which is the
correct port per docs/22. So swapping USB ports is low-yield.

The **DisplayPort** side is the untested half of the same cable, and the cable was reconnected the
day the fault appeared:

1. Reseat the **visor-end connector** (remove the face cushion first). A half-millimetre gap there
   is documented to kill DP while leaving USB alive — the failure mode that most reliably fools
   the operator.
2. Move the DP plug to a **different output on the GPU** (currently DP-2). If the flicker follows
   the headset to another port, the port is cleared; if it changes, it was marginal contact.

Note for future reference: the Matisse USB controller is at PCI `07:00.3` since the 2026-09-03 GPU
swap. Older notes say `09:00.3`.
