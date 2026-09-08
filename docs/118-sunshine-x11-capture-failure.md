# 118 — Sunshine capture backend breaks under X11; stay on Wayland for streaming (2026-09-07/08)

A side-effect of the X11 session switch for `docs/117`'s Oasis/Ignition test: Moonlight
connections to this rig's Sunshine host started failing with a 503 the moment the desktop
session changed from Wayland to X11. Recorded here because it settles a real architecture
question for `pmadminka`/game-streaming, independent of the VR test that triggered it.

## What broke, and why

Sunshine's own systemd user service (`app-dev.lizardbyte.app.Sunshine.service`) restarted
cleanly under the new X11 session with correct `DISPLAY`/`XAUTHORITY` — the service itself
wasn't the problem. The failure only appears when a stream is actually requested: on the first
Moonlight connection attempt, Sunshine tried all four of its capture/encode backends in order
and **every one failed**:

```
Trying encoder [nvenc]    -> failed
Trying encoder [vulkan]   -> failed
Trying encoder [vaapi]    -> failed
Trying encoder [software] -> failed
```

`software` failing too (a CPU x264 fallback that doesn't depend on any GPU-specific capture
path) points at a capture-source problem, not an encoder problem. Under Wayland, Sunshine
captures via the `xdg-desktop-portal` **ScreenCast** portal — the compositor (Mutter) exports
frames as DMA-BUF over PipeWire, no direct framebuffer access needed. Under X11 with an NVIDIA
GPU, Sunshine's classic path is **NvFBC** (NVIDIA Frame Buffer Capture), which NVIDIA restricts
on consumer GeForce cards unless the driver is patched (the well-known community
`keylase/nvidia-patch`, which rewrites `libnvidia-fbc.so`). Checked this rig directly: **no
trace of that patch ever having been applied** — no backup files, no patch script present,
current driver 595.71.05 unpatched. That fully explains the failure: X11 was never a supported
capture path on this machine to begin with, it just was never exercised because production
streaming has always run under Wayland.

## The separate, easily-confused patch: NVENC session-count limits

The same `nvidia-patch` toolkit also lifts a **different** restriction — the number of
*simultaneous* NVENC hardware-encode sessions GeForce cards are allowed to run (patches
`libnvidia-encode.so`, a different library from the NvFBC one). That limit applies to the
*encoder*, not the *capture path*, so it is relevant under **both** Wayland and X11 if this rig
ever needs more than one concurrent hardware-encoded stream (multiple viewers, or a stream plus
a local recording at the same time). Not applicable to tonight's single-stream failure, but
worth remembering as a distinct, still-live consideration for `pmadminka` regardless of which
display server is in use.

## Recommendation: don't move streaming infrastructure to X11

The NvFBC latency advantage that used to justify X11+NvFBC over Wayland's portal path has
narrowed a lot as Mutter's DMA-BUF screencast support and NVIDIA's Wayland driver support have
matured — on a modern stack the two should be close, not a decisive win either way. Concretely,
on this rig, right now: Wayland's PipeWire-portal path **already works** (production has run on
it without issue), while X11's NvFBC path is **unpatched and non-functional** today. Getting X11
to even match what Wayland already does for free would mean applying and then perpetually
re-applying `nvidia-patch` after every driver update — a real, recurring maintenance cost paid
to chase a latency difference that's likely marginal on current driver/compositor versions, not
worth it for a one-off VR-compatibility test's sake. **Wayland remains the right choice for
`pmadminka`'s streaming path.** Switch this rig's session back from X11 to Wayland at the login
screen once `docs/117`'s test is done with, to restore normal Sunshine/Moonlight streaming.
