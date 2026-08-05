# 18 — Upstreaming the Monado patches

State as of 2026-08-05: our seven Monado patches were regrouped into **four independent MR
branches**, rebased onto upstream `main` (`735e29e4e`, zero drift in `d/wmr` since our old
base), adversarially reviewed, reworked to fix three real defects the review found, and
build-tested (full build plus per-branch incrementals, no warnings; changed lines verified
clang-format-clean; every commit carries the DCO `Signed-off-by`).

The branches live in the **main system's** Monado clone,
`~/Documents/linux_vr_base/monado` (the refs are in the clone itself, not in any /tmp
worktree):

| branch | commits | what it does |
|---|---|---|
| `wmr-hid-resilience` | 4 | survive transient HID errors instead of killing the session |
| `wmr-controller-input-fixes` | 4 | squeeze click, haptic name, timestamps, opt-in deadzone |
| `wmr-camera-stream-toggle` | 1 | `WMR_CAMERAS=0` runs orientation-only, cameras never start |
| `steamvr-drv-origin-rpath` | 1 | `$ORIGIN` runtime path on `driver_monado.so` |

The same ten commits, as a linear series, are `patches/monado/0001–0010` in this repo, which
is what `bootstrap-lab.sh sources` applies (pinned base updated to `735e29e4e`).

## What the review changed (do not resubmit the old versions)

- **Bounded startup wait**: the first version exited when the *first* controller status
  arrived; upstream's cond fires only when *both* have been processed. That would routinely
  have lost the second controller. Now waits for both, 10 s deadline, re-requesting once per
  second inside the window.
- **Periodic status re-request dropped**: controllers are only surfaced to the runtime while
  `wmr_hmd_create` runs (no hotplug path — issue #617), so re-requesting forever created
  controllers nobody would ever see.
- **Firmware-read retries now validate replies**: fw replies only echo the command id, so
  with retries in play a late reply to an earlier request could corrupt the block. Replies
  are checked against the request (`block_id_echo`, `blk_remain + len == remain`).
- **Thumbstick "negative overshoot" claim removed**: `(0 - 0x07FF)/0x07FF` is exactly -1.0;
  only the positive end overshoots and upstream already clamps it. What survives is the
  **opt-in** radial deadzone (`WMR_STICK_DEADZONE`, default 0 = no behaviour change),
  following the `LH_STICK_DEADZONE` precedent (!2770).
- **`WMR_CAMERAS=0` now actually yields 3DoF**: the first version skipped the stream but left
  SLAM enabled, which froze the pose on SLAM-enabled builds (tracker got no frames and no
  IMU, yet still reported VALID+TRACKED). Now `setup_trackers` forces SLAM and hand tracking
  off when cameras are off.
- Debunked claims scrubbed: no more "physical-layer weakness of the cable", no more
  "camera traffic knocks the companion off the bus" (our own measurements falsified it).

## Prior art checked (2026-08-05)

None of the ten changes is implemented, in flight, or rejected upstream. Relevant context to
cite in the MRs is linked in the bodies below. One open MR (!2937, EuRoC recorder) touches
the same controller files — textual conflict risk only, no functional overlap.

## Submission runbook

1. **Account**: gitlab.freedesktop.org (OAuth via GitHub works). Use the Gmail identity.
   New freedesktop accounts may need a short approval before forking/CI.
2. **Fork** `monado/monado` in the web UI. Add your SSH key to the GitLab account.
3. **Push the branches** from the main system:

   ```bash
   cd ~/Documents/linux_vr_base/monado
   git remote add fork git@gitlab.freedesktop.org:YOUR_USER/monado.git
   git push fork wmr-hid-resilience wmr-controller-input-fixes \
                 wmr-camera-stream-toggle steamvr-drv-origin-rpath
   ```

4. **Open four MRs** against `monado/monado`, target `main`, one per branch, bodies below.
5. **Changelog fragment** (after each MR has a number — the convention is to add it as the
   final commit): create `doc/changes/drivers/mr.<N>.md` (for the three wmr MRs) or
   `doc/changes/misc_fixes/mr.<N>.md` (for the rpath one) with one or two lines, commit,
   push again. Fragments need no license header.
6. **Formatting**: changed lines were verified with clang-format 22 against the repo's
   `.clang-format`; upstream CI uses its own version and, if it disagrees, exports the fix
   as the `patches/fixes.diff` artifact of the `format-and-spellcheck` job — apply it and
   push.
7. **DCO**: every commit already carries `Signed-off-by: brunduk
   <nikolai.viktorovich@gmail.com>` matching the author. That sign-off is *your* legal
   certification of the DCO (developercertificate.org) — read it once before pushing.
   Note: some projects prefer a legal name in sign-offs; Monado's policy only requires that
   the tag match the git author. The commits also carry a `Co-Authored-By: Claude` trailer
   as an honest note that the work was AI-assisted; Monado has no rule about such trailers.
   Strip them before pushing if you prefer (`git rebase` + reword) — but do not add
   anyone's sign-off but your own.

**Testing disclosure (include in every MR, it will be asked):** everything was validated on
a single HP Reverb G2 (rev B) and its controllers over the tunnelled transport, on Debian
13 / X11, mostly 3DoF sessions. The direct-Bluetooth path and other WMR headsets (Odyssey,
Explorer, Visor, G1) are untested by us. Changes that would alter behaviour for those
devices default to off or preserve upstream behaviour.

---

## MR body 1 — `wmr-hid-resilience`

**Title:** `d/wmr: Survive transient HID errors instead of failing the session`

> On flaky USB (and on the Reverb G2's companion device, which can drop off the bus and
> re-enumerate while the display powers up), the WMR driver currently turns single transient
> HID errors into permanent failures:
>
> - one `os_hid_read` error on the companion device kills `wmr_run_thread`, taking down the
>   hololens sensors feed (IMU + tunnelled controller packets) of a still-healthy device;
> - one lost firmware-read reply fails the whole controller for the session (#491 is this
>   path in the wild);
> - one read error permanently silences the direct-Bluetooth controller thread while its
>   xdev stays registered;
> - a lost controller-status reply hangs `wmr_hmd_create` forever in an unbounded
>   `os_cond_wait` (the `@todo` at that spot).
>
> This series makes those paths tolerate *bounded, transient* trouble — retries with
> validation, bounded waits, error-run caps — before giving up, in line with the direction
> discussed in !2828 (transient handling belongs below the "device lost" decision). It is
> complementary to the hotplug design sketched in #617: nothing here creates or destroys
> devices outside `wmr_hmd_create`.
>
> Details worth reviewer attention:
> - the fw-read retry validates each reply against its request (`block_id_echo`,
>   `blk_remain + len == remain`) because fw replies only echo the command id, so with
>   retries a late reply to an earlier request could otherwise corrupt the block;
> - the per-chunk pacing drop (10 ms → 1 ms) also applies to BT-connected controllers,
>   where `read_sync` blocks identically but which we could not test;
> - the companion read loop gets no extra pacing on error: it shares its thread with the
>   blocking hololens read, which already paces the loop.
>
> Tested on an HP Reverb G2 (rev B), tunnelled transport, Debian 13/X11. Odyssey-era BT
> controllers untested; the BT change only widens one error into a capped run of ten.

## MR body 2 — `wmr-controller-input-fixes`

**Title:** `d/wmr: Controller input fixes (squeeze click, haptic name, timestamps, opt-in deadzone)`

> Four small input fixes for WMR controllers, found bringing up a Reverb G2:
>
> - **Squeeze click** read the analog squeeze float into its boolean, so any grip pressure
>   registered as a click. !1859 added `SQUEEZE_VALUE` but left the click on the analog
>   value; the parsed `squeeze_click` bit existed and was unused.
> - **G2 haptic output name** didn't match what the binding profiles and `bindings.json`
>   reference (`XRT_OUTPUT_NAME_G2_CONTROLLER_HAPTIC`), and `oxr_xdev_find_output()`
>   matches by name — haptic actions could never resolve on the G2 profile. (Driving the
>   motor still needs the wire command; this makes the action resolvable so that can be
>   built.)
> - **`xrt_input::timestamp` was never set**, so OpenXR reported `lastChangeTime == 0` for
>   every WMR action (same fix as !2080 for qwerty).
> - **`WMR_STICK_DEADZONE`** (default 0 = off): WMR configs carry no stick centre
>   calibration and per-unit centre offset shows up as constant drift; opt-in radial
>   deadzone with rescale, shared by the hp/og parsers, following the `LH_STICK_DEADZONE`
>   precedent (!2770). No behaviour change unless set.
>
> Plus two trivia: the input-activation loop wrote `inputs[0]` repeatedly (harmless only
> because `u_device_allocate()` pre-sets active), and the debug-GUI thumbstick x/y labels
> were swapped.
>
> Tested on a Reverb G2 pair over the tunnelled transport; the og-file changes affect
> Odyssey-era controllers, which is why the deadzone defaults to off.

## MR body 3 — `wmr-camera-stream-toggle`

**Title:** `d/wmr: Add WMR_CAMERAS=0 to run without tracking-camera streaming`

> Camera streaming is currently all-or-nothing: `wmr_source` starts unconditionally and a
> failed stream start destroys the whole HMD. A headset whose cameras are in a bad state
> cannot run at all, even orientation-only — #460 (G2 cameras fail to start), #200
> (`LIBUSB_ERROR_BUSY`), #501 are that situation in the wild.
>
> `WMR_CAMERAS=0` (default on; same `DEBUG_GET_ONCE_BOOL_OPTION` pattern as the driver's
> other `WMR_*` options) makes `setup_trackers` force SLAM and hand tracking off — their
> status vars report `Disabled by the user (WMR_CAMERAS=0)` — so the driver takes the
> existing 3DoF path and never reports poses from a tracker that receives no data, and the
> camera stream is never started, so a broken camera cannot abort the session.
>
> The camera USB interface is still claimed by `wmr_source_create`; skipping the source
> entirely is left as a follow-up since teardown assumes it exists.

## MR body 4 — `steamvr-drv-origin-rpath`

**Title:** `t/steamvr_drv: Add $ORIGIN runtime path so bundled deps resolve in pressure-vessel`

> SteamVR's `vrserver` runs inside the Steam Linux Runtime container, which has neither the
> host's locally-built libraries nor its `LD_LIBRARY_PATH`, so `driver_monado.so` fails to
> load whenever a direct dependency is missing from the runtime (#240, #423, #519). Adding
> `$ORIGIN` lets a deployment bundle those dependencies next to the `.so` — no host paths,
> no container configuration, and it also helps the relocatability concern in #336.
>
> Implementation note: the plugin ships via `install(DIRECTORY)` of the build output, so the
> build-tree binary is installed verbatim and `BUILD_RPATH` is what takes effect;
> `INSTALL_RPATH` is set alongside for the day the install method changes. Linux-only
> (`UNIX AND NOT APPLE`). `DT_RUNPATH` is non-transitive — it covers the driver's direct
> `NEEDED` entries, which is what the reported failures are.
>
> Complementary to !2802 (IPC-client mode), which solves the same environment the other way
> and is the better long-term answer; this is a two-line change that makes today's
> in-process driver deployable.
