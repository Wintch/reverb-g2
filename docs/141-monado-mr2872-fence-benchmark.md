# 141 — Benchmarking Monado MR !2872 (persistent fences) on an NVIDIA GPU (2026-10-04)

The authors of Monado MR [!2872](https://gitlab.freedesktop.org/monado/monado/-/merge_requests/2872) (xytovl) asked for NVIDIA owners who can patch and benchmark it against the stock runtime. This document records what we ran, what we found, the traps on the way, and how to reproduce it.

**Status of the MR:** it was **closed by its author on 2026-09-28** ("it seems nobody is reporting issues that would be fixed by the vulkan layer, this change may not be useful anymore"). Numbers like the ones below are the kind of evidence that could justify reopening it.

## 1. What the MR does

It lets an IPC client commit a frame with a **persistent, pre-shared VkFence** (`layer_sync_with_fence`) instead of exporting a new temporary sync-fd fence every frame. The commit message says it gives "similar behaviour as timeline semaphores, without the need for the feature to be enabled". It is the same method the `monado-vulkan-layer` uses, moved inside the runtime. Ten commits; the first one (`c/util: Use reference counting for fences`) is a prerequisite that is easy to miss.

### 1.1 The most important finding: the new path is not used by default

`comp_vk_client.c` picks the commit path in this order: `submit_handle` → `submit_semaphore` → **`submit_fence`** (the MR) → `submit_temporary_fence` → `submit_fallback`. The persistent fences are only created when the client **cannot** use timeline semaphores (`vk_can_import_and_export_timeline_semaphore()` false). A client that lets Monado create its VkDevice (`xrCreateVulkanDeviceKHR`, e.g. `hello_xr`) always has timeline semaphores, so it never touches the new path. The target is clients that create their own VkDevice without that feature (the Proton/DXVK situation that WiVRn users hit).

Confirmed with gdb breakpoints on the generated IPC client calls: stock `hello_xr` hits `ipc_call_compositor_layer_sync_with_semaphore` only; neither `..._with_fence` nor `..._layer_sync` is ever called. A first A/B run with the patched service and the default client was therefore a no-op comparison (identical numbers, see 4.1) — a useful negative control.

## 2. Setup

| Item | Value |
|---|---|
| Machine | the lab machine, Debian 13, GNOME on Wayland (the DRM-lease launcher requires it; a KDE X11 session is refused) |
| GPU / driver | RTX 3060 Ti, NVIDIA 595.71.05 |
| Display | HP Reverb G2 via DRM lease, 4320x2160 @ 90 Hz, 3DoF, headset on the desk (no wearer, no controllers) |
| Stock tree | `~/vr/monado`, branch `lab-full` |
| Patched tree | `~/vr/monado-fence` (git worktree), branch `fence-test` = `lab-full` + 10 MR commits (`refs/merge-requests/2872/head`) + 2 local commits (below). Own build dir, same CMake options copied from the stock cache. |
| Client | our `hello_xr` (`~/vr/OpenXR-SDK-Source`, 360 photo mode), Vulkan2 |
| Measurement | the pacer log lines `Delivered frame X ms early/late` (`U_PACING_APP_LOG=debug`), 75 s per run, about 6.7k frames |

Local commits on top of the MR:

1. **Adapt** — `lab-full` already had a refactored `_update_layers(ics, slot)` returning `xrt_result_t`; the MR's `ipc_handle_compositor_layer_sync_with_fence` used the old signature and failed to compile. Fixed, and the fence reference is dropped on error.
2. **Test-only knob** — `XRT_TEST_NO_TIMELINE`. Unset = normal. `=1` makes the client behave as if timeline semaphores were unavailable, so it uses the MR's persistent fences. `=2` does the same but also skips creating the persistent fences, so the client falls back to the old per-frame temporary fence. This gives a single-binary A/B of "old path" vs "MR path" for a client without timeline semaphores. **Not for upstream.**

Caveat: the "old" arm is the old *client* path running against the *patched* server, not the stock library end to end.

## 3. Method

ABBA ordering (old, MR, MR, old) to cancel thermal and time drift; each run 75 s, `HELLO_XR_DURATION_S=75` with stdin held open by `sleep` (the player quits on stdin EOF). Each arm was verified with gdb to hit the intended IPC call before measuring (`=1` → `layer_sync_with_fence`, `=2` → `layer_sync`). Synthetic GPU load is `HELLO_XR_GPU_LOAD` (percent), calibrated first.

Calibration (30 s runs, MR arm): the load scale is very steep.

| `GPU_LOAD` | frames / 30 s | ≈ fps |
|---|---|---|
| 0 | (75 s runs) 6.7k | 89.6 |
| 3 | 2675 | 89.2 |
| 5 | 2676 | 89.2 |
| 7 | 2658 | 88.6 (at the edge) |
| 10 | 1340 | 44.7 |
| 15 | 1332 | 44.4 |
| 25 / 35 / 45 | 759 / 537 / 447 | 25 / 18 / 15 |
| 60 (75 s) | ~850 | ~11 |

Loads 10 and above fall off the 90 Hz cliff and measure nothing useful about pacing (all arms equal, GPU-bound). The usable points are 5 and 7.

## 4. Results

All values are "Delivered frame late" in ms (positive = late). Two runs per arm.

### 4.1 Negative control — default client (timeline semaphores), stock vs patched service

| | p95 | p99 | p99.9 | max | > 2 ms | > 5 ms |
|---|---|---|---|---|---|---|
| Stock service | 0.33 | 2.55 | 2.86 | 4.33 | 1.52 % | 0.00 % |
| Patched service | 0.20 | 2.54 | 3.31 | 3.91 | 1.49 % | 0.00 % |

Same path, same result, as expected (the fence code is not reached).

### 4.2 Light load (`GPU_LOAD` 0, about 5 ms total frame time)

| | p95 | p99 | p99.9 | max | > 2 ms | > 5 ms | stdev |
|---|---|---|---|---|---|---|---|
| Old path | 0.95 / 1.04 | 2.24 / 2.26 | 6.40 / 5.13 | 10.48 / 9.02 | 2.14 / 2.29 % | 0.16 / 0.10 % | 0.57 / 0.55 |
| MR path | 0.17 / 0.19 | 2.55 / 2.58 | 2.88 / 2.88 | 3.94 / 4.27 | 1.29 / 1.47 % | 0.00 / 0.00 % | 0.44 / 0.44 |

p95, p99.9, the maximum and the >5 ms tail improve clearly. **p99 is slightly worse with the MR here** (about +0.3 ms); we do not hide it. The ~2.5 ms population is a regular pacing artefact in both arms.

### 4.3 Calibrated load 5 (about 90 fps)

| | p95 | p99 | p99.9 | max | late > 0.5 ms | > 2 ms | > 5 ms | stdev |
|---|---|---|---|---|---|---|---|---|
| Old path | 0.08 / 0.10 | 0.63 / 0.68 | 2.76 / 2.24 | 5.39 / 33.15 | 1.1 / 1.1 % | 0.24 / 0.13 % | 0.03 / 0.04 % | 0.23 / 0.48 |
| MR path | 0.05 / 0.05 | 0.11 / 0.25 | 1.02 / 1.06 | 4.69 / 4.60 | 0.3 / 0.5 % | 0.06 / 0.06 % | 0.00 / 0.00 % | 0.10 / 0.11 |

### 4.4 Calibrated load 7 (about 89 fps, at the edge of the cliff)

| | frames | p95 | p99 | p99.9 | max | late > 0.5 ms | > 2 ms | > 5 ms |
|---|---|---|---|---|---|---|---|---|
| Old path | 6650 / 6655 | 0.05 / 0.04 | 0.45 / 0.48 | 2.92 / 2.92 | 8.17 / 8.24 | 1.0 / 1.0 % | 0.18 / 0.20 % | 0.06 / 0.06 % |
| MR path | 6710 / 6717 | 0.05 / 0.05 | 0.10 / 0.11 | 2.33 / 1.83 | 7.47 / 7.55 | 0.2 / 0.2 % | 0.10 / 0.09 % | 0.03 / 0.03 % |

The MR arm also delivered about 60 more frames per 75 s (≈ 89.5 vs ≈ 88.7 fps) near the edge. GPU-side compositor times (`gpu` median ≈ 2.06 ms at load 0) are identical between arms, so the difference is synchronisation, not rendering.

### 4.5 Reading

- Repeats agree with each other in every cell except the single 33 ms maximum in one old-path load-5 run; maxima are noisy and are not used as evidence.
- The consistent signal is in the middle-to-high percentiles (p95, p99, p99.9) and in the share of frames more than 0.5 ms late, which falls by roughly a factor of 2 to 5 under moderate load.
- At zero load p99 is not improved.

## 5. Limits of this measurement

- 3DoF, one client, one display mode, one GPU, one driver; no wearer.
- The "old" arm is the old client path on the patched server (see 2).
- Proxy metric: pacer lateness from the log. We did **not** capture compositor wake-period traces (Tracy/perfetto), which is what the MR authors asked about.
- The load is synthetic and the scale is steep (5 vs 10 is the difference between 90 and 45 fps).
- Not tested: a real Proton title without timeline semaphores, WiVRn itself, 60 Hz, or other NVIDIA generations.

## 6. Traps met on the way (read before repeating)

1. **Prerequisite commit.** Cherry-picking only the nine "fence" commits fails with `no member named 'reference'`; commit `24e71dcdf` (refcount fences) is the first of ten.
2. **Signature drift.** `lab-full`'s `_update_layers` differs from the MR base; see commit 1.
3. **Launcher needs GNOME Wayland.** The lab machine was in a KDE X11 session (left from an earlier test); `jack-in-wayland.sh` refuses it and writes `~/vr/.jack-in-failed`, which the next launch refuses until `--force`. An SSH shell has `XDG_SESSION_TYPE=tty`; the script recovers the real environment through `gui_env.py` only if `/run/user/1000/wayland-0` exists.
4. **Controller check.** The launcher waits for awake bonded controllers and exits otherwise; `VR_BT_CTRL_CHECK=0` skips it for a headset-only 3DoF run. Verify the log shows the real WMR/Reverb G2 head, not the Simulated HMD.
5. **`hello_xr` quits on stdin EOF.** Launching it with `</dev/null` makes it exit silently with code 0 right after printing the mode line. Hold stdin open (`sleep N | hello_xr`) and bound the run with `HELLO_XR_DURATION_S`.
6. **`HELLO_XR_PHOTO360`.** The default 360 photo path does not exist on the lab machine; point it at `photo360/testgrid.png`.
7. **Default client does not exercise the MR** (section 1.1). Always verify the IPC call with gdb before trusting an A/B.


## 7. Reproduce

The A/B scripts are not kept in the repo; the procedure is short enough to redo by hand. Working files go in `/tmp/ab-*`.

```bash
# 1. patched tree
cd ~/vr/monado && git worktree add ~/vr/monado-fence lab-full --detach
cd ~/vr/monado-fence && git fetch origin refs/merge-requests/2872/head:mr2872
git checkout -b fence-test && git cherry-pick 24e71dcdf^..e947c8951       # all 10 commits
# then apply the two local changes from section 2 (adapt _update_layers, XRT_TEST_NO_TIMELINE knob)
cmake -S . -B build -G Ninja -C <cache preload copied from ~/vr/monado/build/CMakeCache.txt> && ninja -C build

# 2. headset on, GNOME Wayland session, then launch the patched service
MONADO_SERVICE=~/vr/monado-fence/build/src/xrt/targets/service/monado-service \
  VR_BT_CTRL_CHECK=0 U_PACING_APP_LOG=debug ~/vr/jack-in-fence-ab.sh dev 3dof --force
#   (jack-in-fence-ab.sh = jack-in-wayland.sh with SERVICE="${MONADO_SERVICE:-...}")
```

For each arm (`XRT_TEST_NO_TIMELINE` unset / `=1` / `=2`, `HELLO_XR_GPU_LOAD` 0, 5 or 7), run `hello_xr` for 75 s with stdin held open and `U_PACING_APP_LOG=debug`, in ABBA order, then extract the `Delivered frame X ms early/late` lines from the log and compute p95 / p99 / p99.9 / max and the share of frames late by more than 0.5, 2 and 5 ms.
