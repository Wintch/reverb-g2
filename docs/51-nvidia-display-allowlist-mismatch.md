# NVIDIA direct-mode allowlist mismatch on this rig — DIAGNOSED, mitigation confirmed working (2026-08-18)

## Symptom

`jack-in.sh`'s `wake_panel()` probe reports **"Panel never came up. Check the headset's DC
supply and the DisplayPort cable."** even though the headset is fully connected (USB 5/5,
companion device found, config read succeeds, HID activation report sent). The probe's own
25-second wait loop never sees `Started vblank event thread` in the log, so it `kill -9`s the
service and the script exits 1 before the real launch ever begins.

**Not a hardware fault** — no `img_xfer_cb` "Invalid frame magic" errors, no companion drops,
no HID config-read failure marker (`~/.cache/g2-jackin-config-read-fail` absent), USB
enumeration stable across the probe attempts. This is a separate failure class from the
cable/connector issues in [[docs/22]].

## Root cause

Monado's NVIDIA direct-mode compositor path (`comp_window_direct_nvidia.c::_test_for_nvidia`)
only takes the direct (leased, non-desktop) display path if the Vulkan-reported display name
matches an entry in a small compiled-in allowlist (`NV_DIRECT_ALLOWLIST`,
`src/xrt/compositor/main/comp_settings.h`). If no entry matches, Monado silently falls back to
a **windowed X11 compositor** — the service keeps running and can even track fine, but it
never leases the physical panel, so `wake_panel()`'s log grep for the direct-mode-only
`Started vblank event thread` line legitimately never fires. Confirmed live with
`XRT_COMPOSITOR_LOG=debug`:

```
ERROR [_test_for_nvidia] NVIDIA: No allowlisted displays found!
    == Current Allowlist (9) ==
        ... HPN ...
    == Found Displays (4) ==
        ... HP Inc. (DP-4) ...
ERROR [comp_window_direct_randr_init] No non-desktop output available.
DEBUG [compositor_check_deferred] Deferred target backend X11(XCB) Windowed selected!
```

On this box's NVIDIA driver, the G2 panel's Vulkan `VkDisplayPropertiesKHR::displayName`
reports as **`HP Inc.`** — the allowlist only has **`HPN`** (a 3-character prefix, presumably
the panel's EDID vendor/model string on whatever driver upstream tested against). `HP Inc.`
does not share a prefix with `HPN`, so the `strncmp`-based prefix match
(`_match_allowlist_entry`) never hits.

**This is not a new regression to "just fix" by broadening the allowlist.** `git log` on
`comp_settings.h` shows upstream **used to** allowlist `"HP Inc."` too, with the comment
`// Also Reverb G2?`, and deliberately removed it:

```
commit 3b7f85cd8 — "c/main: remove HP desktop monitor from NV whitelist" (Sep 2024, !2326)
- "HP Inc.",                     // Also Reverb G2?
```

`HP Inc.` is HP's generic corporate name and plausibly appears in the EDID of real HP
**desktop monitors** too — re-adding it to the compiled-in, upstream-shared allowlist risks
Monado trying to direct-mode-lease someone's actual productivity monitor. That is exactly the
regression the 2024 removal was for, so **do not re-add `"HP Inc."` to
`NV_DIRECT_ALLOWLIST` in `comp_settings.h`.**

## Fix (already in place, now confirmed correct)

`jack-in.sh`'s `COMMON_ENV` already sets:

```bash
XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY="HP Inc."
```

This is the officially-supported per-run override (`comp_settings.c`:
`DEBUG_GET_ONCE_OPTION(nvidia_display, "XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY", NULL)`,
checked in `_test_for_nvidia` after the compiled allowlist). It is scoped to this one launcher
invocation, not the shared binary default, so it can't affect anyone else's desktop monitor —
the same safety property the 2024 upstream removal was protecting. Confirmed working today
with a clean manual repro (`XRT_COMPOSITOR_LOG=debug`):

```
DEBUG [check_vulkan_caps] Selecting direct NVIDIA window type!
DEBUG [create_vblank_event_thread] Started vblank (first pixel out) event thread.
INFO  [comp_target_swapchain_create_images] Started vblank event thread!
```

So on a normal run, `jack-in.sh` already carries the right fix and should reach direct mode.

## Open item, NOT resolved this session

Even with the override correctly in place, the *probe* (`wake_panel()`) and the *real* launch
that follows it don't always agree: one session today saw the probe succeed
(`Panel is up.`) but the subsequent real launch fail to reach the vblank thread and fall back
to windowed anyway (`Compositor did not reach the vblank thread.`), while
`monado-service` kept running and tracking (SLAM/`VIT_COLLAPSE_LOG` output looked healthy) in
that windowed state. This looks like real, intermittent flakiness in the Vulkan display
acquire step itself — distinct from the allowlist issue above, which is now understood and
already mitigated — and may be related to the still-not-root-caused
`nv_drm_revoke_modeset_permission` kernel WARN pattern documented in
[[project-g2-controller-6dof]]'s 2026-08-15 session notes (a process vanishing/failing to
acquire the display with no user-visible error). Not chased further this session; worth
instrumenting a repeated probe-then-real-launch loop (10-20x) to get a real failure rate
before trying a fix, rather than patching on a single repro.
</content>
