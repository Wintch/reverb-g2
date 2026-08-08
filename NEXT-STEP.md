# Next step

> **UPDATE (2026-08-08, midday session) — item 1 below got real progress (SUPERHOT's menu
> button, a related-but-different bug), and item 1's Poly Runner part got re-characterized,
> not closed.** Full session in `docs/pruebas.jsonl` T082-T086, patch in
> `patches/xrizer/0002`.
>
> **SUPERHOT's unresponsive menu button (T067, never resolved) is fixed for the left
> controller.** Confirmed first, via `XRT_DEBUG_GUI=1`, that raw input was 100% healthy at
> the Monado level on both controllers (trigger, squeeze, menu, Y/B, bt_pairing all
> register) — also confirmed trigger/grab/hand-tracking all work fine in-game now, so
> T067's "no button does anything" was almost certainly that night's USB2 instability, not
> a real bug. The menu specifically was real though: SUPERHOT's default oculus_touch
> bindings only offer two sources for its MENU action — a `long` press on X (input mode not
> implemented anywhere in xrizer) and a click on `system` (never a recognized path string in
> xrizer at all) — so the action was permanently unbound, regardless of controller type, not
> WMR/G2-specific. Patched the `system` half (`patches/xrizer/0002`, one line, same alias
> pattern already used for `application_menu`): confirmed live, left controller's physical
> menu button now opens SUPERHOT's pause menu. The `long`-press half is NOT fixed — more
> invasive, needs real long-press detection added to `ButtonInput`. Right hand also not
> expected to work (`Menu` is Left-only on this profile, matches real hardware).
>
> **Poly Runner VR's `IVRCompositor_013` diagnosis is still a dead end (confirmed again),
> but T072's "clean self-exit" characterization does NOT reproduce.** Retested twice: both
> times the game gets stuck permanently at OpenXR session state `READY`, spamming the
> interface request in a tight infinite loop (~1300 lines/sec, ~190% CPU), never exiting on
> its own — had to be killed by hand both times. The game keeps rendering normally in flat
> 2D throughout (confirmed physically), it just never enters stereo VR. Whoever picks up
> item 1 below for Poly Runner: start from this corrected behavior, not T072's.
>
> Also found and NOT fixed: `wmr_controller_hp.c` parses controller battery level from
> hardware but never wires it into Monado's generic `xrt_device::get_battery_status` API —
> only visible in the interactive debug GUI, not queryable via `libmonado`/IPC. Small,
> same-pattern fix if useful later.

> **RESOLVED (2026-08-08, ~05:25) — the item right below this note is fully closed.** Did
> exactly what it asked: rebuilt `~/vr/monado` clean via `git am` of `patches/monado/0001-
> 0011` only, re-ran the controller-registration scenario (3x, not just once) — clean every
> time, no drift, no `0012` needed. `0012` is now deleted from `patches/monado/`, README
> updated with the postmortem. Along the way, a much bigger and completely unrelated
> "the cable must be dying again" panic turned out to be a missing `panel.py` file in the
> lab's `~/vr/` deployment (not hardware) — see the CLAUDE.md milestone banner dated
> 2026-08-08 for the full night, including a new xrizer patch (global recenter,
> `patches/xrizer/0001`) and four real, human-verified working games with 6DoF head
> tracking. **Next things queued from that session, none started:**
> 1. Root-cause Poly Runner VR's real exit cause from scratch — the `IVRCompositor_013`
>    diagnosis was checked against every OpenVR header Valve ever shipped and found to be
>    wrong (that version never existed); the actual reason its xrizer session exits is
>    still unknown. See `patches/xrizer/README.md`.
> 2. War Robots VR: The Skirmish is blocked on HMD presence detection missing in BOTH
>    Monado (`wmr_hmd.c` never wires its own proximity sensor into `XR_EXT_user_presence`)
>    and xrizer (`ShouldApplicationPause`/`IsInputAvailable` are stubs) — a two-repo fix,
>    scoped but not started. `patches/xrizer/README.md` has the detail.
> 3. The rest of the game list from `docs/pruebas.jsonl` T073 (Overkill VR inconclusive,
>    Dark Room VR never even launched, Surgeon Simulator/Chornobayivka/World of Guns failed
>    fast) still needs a proper, unhurried look now that the panel/DP bug and the recenter
>    feature are both fixed — several of those failures might resolve or look different
>    with a working recenter available.
> 4. `patches/xrizer/0001` (global recenter) has only been field-tested on the
>    `oculus/touch_controller` profile (what our WMR controllers present as) -- the field
>    edits to `knuckles.rs`/`vive_controller.rs`/`simple_controller.rs`/`vive_focus3.rs`/
>    `meta_touch_plus.rs` compile and pass the existing binding tests, but were never tested
>    on real hardware of those types (none is available in this lab).

> **CORRECTION NEEDED (2026-08-07, from the comms session, mounted the lab SSD read-only to
> check upstream status) — patch `0012` does not describe a bug in anything pushed
> upstream; the tracked patch series is fine as-is.**
>
> Checked `wmr-hid-resilience` (MR !2967, tip `9f9ff4d16`, confirmed against the live GitLab
> MR) directly against `patches/monado/0003-...-Bound-the-controller-status-wait...patch`:
> they are byte-identical, and both already use the correct form —
> `while (!(wh->have_left_controller_status && wh->have_right_controller_status) && os_monotonic_get_ns() < deadline_ns)`,
> 10s deadline, `next_request_ns` re-request every second. No AND/OR bug here.
>
> `patches/monado/0012`'s "before" hunk shows a **3-second deadline** with a bare
> `!left && !right` condition and different comment text — that matches *neither* the
> pristine pre-patch upstream code *nor* the finalized/pushed `0003`. Whatever build was
> actually running on real hardware for T051/T066 (the SUPERHOT/xrizer session) had
> **drifted from the tracked patch series** before that test — most likely the 10s deadline
> got hand-shortened to 3s for faster iteration at some point, and the AND/OR slip happened
> in that same untracked edit.
>
> **Nothing was pushed to !2967 over this** — pushing `0012` as-is wouldn't even apply
> (context mismatch), and since `!(A && B)` and `(!A || !B)` are logically identical
> (De Morgan), forcing it through would just rewrite already-correct code.
>
> **Next step for whoever picks this up on the lab machine:** rebuild the actual test
> binary fresh from `patches/monado/0001-0011` (via `bootstrap-lab.sh sources`, no manual
> edits) and re-run T066's scenario against that clean build. If the 9/9 repro still
> happens, it's a real bug somewhere else and worth a fresh look; if it doesn't, the
> earlier finding was an artifact of the drifted live tree and `0012` can be dropped.
> Also worth a quick audit of the lab's build tree for other hand-edits that never made it
> into `patches/` — this is the kind of drift that's easy to lose track of mid-session.

> **UPDATE 2026-08-07:** items 2 of the list below (player/VR180 + playlist) are **DONE
> and verified** — the directory playlist chains videos unattended and real content at
> 4320x2160@90 through the full player is clean (T041, `docs/22-cable-connector-diagnosis.md`).
> That same night the headset appeared to die entirely (DP, panel, then USB2) — root cause
> was the visor-end cable connector, reseat fixed it; read `docs/22` before diagnosing any
> "headset dead" symptom. Items 1 (controllers stress test), 3 and 4 below remain as
> written. Also: the x3600 is now a validated second lab machine.

## READ FIRST — status as of 2026-08-06, early morning

Written from the everyday system with the lab SSD mounted read-write at `/mnt/lab`, before
the user reboots into the lab install to test physically. **This is what needs to be done
when back — the rest of the file, further below, is 90Hz history, do not read
first.**

Repo already public (`github.com/Wintch/reverb-g2`), last night's update posted on the
NVIDIA thread (379240), and the 4 Monado MRs opened against upstream (`monado/monado` #2967,
#2968, #2969, #2971) — none of that needs the lab, it's already resolved.

**What does need the lab, in order:**

1. **Controllers** (the 4 input/connection patches are already in `patches/monado/0001-0008`,
   applied via `bootstrap-lab.sh sources`; also already uploaded upstream as an MR, see
   above, but that doesn't change anything locally):
   ```bash
   ./jack-in.sh 3dof     # controllers must be ON BEFORE this (hot-add doesn't exist: T043
                         # proved late power-on never reaches Monado; the old "before or
                         # after, no longer matters" claim here overstated T025)
   grep -E "left:|right:" ~/Documents/reverb-g2/jack-in.log
   # should say: left: HP Reverb G2 Left Controller / right: HP Reverb G2 Right Controller
   ```
   Live diagnostics (sticks, battery, IMU per controller): `XRT_DEBUG_GUI=1` before
   starting the service, look at each controller's panels. Sticks at rest should read
   exactly (0,0) — if they drift, the deadzone patch didn't load correctly. Stress test:
   10 boot cycles with the controllers on, should connect 10/10 (see `docs/03`).

2. **Player / VR180:**
   ```bash
   ./play360.sh ~/Documents/reverb-g2/photo360/vr180_berlin_8k60.mp4   # 8K60 stereo, the good one
   ./play360.sh ~/Documents/reverb-g2/playlist_test/                   # playlist feature, never tested interactively
   ```
   With the headset on: confirm real stereo image (not flattened), no starves at 8K60, and that
   the transport keys (space pauses, `[`/`]` speed, `n` next, `q` quit)
   respond. If the terminal goes mute afterward: `stty sane`.

3. **Do NOT instrument the USB2 hub reset yet** — investigated by code review (no hardware)
   on 2026-08-06: autosuspend is already ruled out (rule `71-usb-no-autosuspend.rules` covers
   `04b4` from the bootstrap), and the mishandled-keepalive hypothesis doesn't hold up either
   after reading `wmr_hmd.c` (non-blocking poll, no periodic writes). If it needs to be
   picked up again in 1-2: add timestamped logging to `control_read_packets`/
   `hololens_sensors_read_packets` and run under load until it resets — that's the only way
   to see what happens right before, that data doesn't exist yet. Detail in `docs/06-known-issues.md`.

4. **Constellation tracking (controller 6DoF) — paused on purpose.** There's a trial merge
   already done (throwaway branch, already deleted) against `gitlab.freedesktop.org/thaytan/monado`
   branch `dev-constellation-controller-tracking`: 8 conflicts, all mechanical (CMake +
   reconciling the hand-tracking device list), none touching the files from our 4
   patches. **Do not resume yet** — waiting for the Monado reviewers to respond something on
   the 4 MRs before finishing that merge, to avoid rewriting code that might change based on
   feedback. See `docs/03-controllers.md`, section "Positional tracking (6DoF)".

None of this is urgent — the user explicitly asked for pacing ("we'll fit it in over time"). The
only reason for the reboot now is that the headset is physically in front of them and there's a wish to test it.

---

State as of 2026-08-05, late. Written from the everyday system with the lab SSD mounted
read-write at `/mnt/lab`, right before rebooting into the lab OS to resume physically.

Same physical machine, two separate Debian 13 installs on separate disks (see
`docs/17-publishing.md` history / the repo's own notes) — the headset does not need to be
unplugged to switch between them, just reboot and pick the lab SSD at the boot menu, log in
as `iam`.

## IN PROGRESS (2026-08-05, night): the factorial ran — CTRL fails, and points to resolution, not vblank

**The loading path (option 2, `nvidia_modeset.config_file` with the `DP-0` key) is
confirmed end to end**: reboot done, `dmesg` with no warning, `/sys/class/drm/card0-DP-1/edid`
byte-identical to `g2-vblank-test.edid`, and DRM went from seeing 3 modes to 6. Full detail and the
code chain that explains the `DP-0`/`DP-1` off-by-one is further below in this file
("Earlier this same session"), untouched.

**The full factorial ran: CTRL → B → A. All three fail** (HP logo, no video),
with the headset on. But with a new data point that the `docs/16` table didn't anticipate: the headset's
HID (`DEVICE_STATUS`) confirms, in all three cases, a **byte-for-byte identical** timing
to what was injected (exact htotal/vtotal/refresh/bpc) — so the override arrived perfectly all the way to
the physical link. That rules out "the override didn't arrive" as an explanation for the failure.

**What remains as the most likely explanation: the three injected modes are 2880x1440, and
that resolution never showed anything in the entire history of the project**, at any refresh
(the native 2880x1440@90 mode was already failing before). The only case that ever worked is
4320x2160@60. The resolution explains 100% of the results without needing to invoke
vblank or refresh — which **doesn't close the vblank hypothesis, it leaves it untested
for now**: the factorial needs to be repeated injecting into the DisplayID Type I descriptors
(4320x2160) instead of the base block, as `docs/16` already anticipated ("If it needs to be
repeated at 4320x2160"). The decoder for those descriptors already exists and is validated byte by byte against the
real EDID; the encoder (`inject-did`) still needs to be written — the byte layer is documented in
that same section with the exact offsets.

**Full detail, with the HID tables and the unexplained anomaly (byte 1 of A, see
below), in `docs/16-lab-vblank.md`, section "Run (2026-08-05): CTRL fails".**

**`inject-did` is now written, tested, and in use.** Symmetric encoder to `decode_did_type1`
in `scripts/edid-tool.py`, with a round-trip verified by the full decoder and both
checksums (DisplayID section + extension block) correct. It already generated the three EDIDs for
the second round: `experiments/vblank/g2-vblank-4k-{ctrl,b,a}.edid`, each with
descriptor #1 (the one that was failing at 90 Hz) replaced by `CTRL4K`/`B4K`/`A4K` and
descriptor #2 (@60, the one that works) intact as a control. Detail and why `B4K` uses vblank
240 and not 514 (bandwidth at a width of 4320) in `docs/16`, section "Second round".

**`CTRL4K` run and confirmed (T012): WORKS.** Colors alternating (blue/white/green) with
the headset on, HID confirms exact 60Hz and the backlight bit on. Descriptor #1
is not the cause of the failure — cloning a healthy timing there works the same as in its
original position. Detail in `docs/16`, section "`CTRL4K` run". Put together
`scripts/verify-override.sh` (runs as root, bundles dmesg + detect + md5 into a single
`sudo`) to avoid asking for the password command by command in each round.

**`B4K` run and confirmed (T013): FAILS.** Only the HP logo, headset on. Same
descriptor #1 that had just tested healthy with `CTRL4K` at 60 Hz — now at 90 Hz with a short
vblank (240) it doesn't lock. New data point still unexplained: the HID (`panel-status.py`) didn't
even get to report 90 Hz — it stayed showing the last known state (60, from
`CTRL4K`) and the companion re-enumerated with no further messages. Different from the previous
round, where the HID did confirm the injected timing byte for byte despite failing visually. Full
detail in `docs/16`, section "`B4K` run".

**`A4K` run and confirmed (T014): FAILS too — this closes the 2x2 factorial.**
`CTRL4K` (60Hz, vblank514) works; `A4K` (60Hz, vblank116) and `B4K` (90Hz, vblank240) both
fail. **It's not the refresh — it's the short vblank**, and it's not bandwidth either: `A4K` runs
at only 603.6 MHz, well below the HBR3 ceiling, and fails exactly the same as `B4K` at
954.72 MHz. The real limit is a minimum vertical blanking duration, not bits/second.
Full detail in `docs/16`, section "`A4K` run — and this closes the factorial".

**This reopens 90 Hz as achievable.** If the minimum vblank needed is compatible
with 90 Hz within HBR3, there's no need to lower the refresh. The most direct candidate has
already been generated: `experiments/vblank/g2-vblank-4k-90long.edid` — 4320x2160@90 with the same
vblank 514 that does work at 60 Hz (`./scripts/edid-tool.py inject-did ... 514@90:1`). Pixel clock
1063.72 MHz → 25.53 Gbps @24bpp, within the HBR3 ceiling (25.92, ~1.5% margin). The `.conf`
already points there.

**`90long` run and confirmed (T015): FAILS.** Only HP logo, headset on. This time the HID
did confirm 90Hz and exact timing (unlike `B4K`, which had stayed at the old
state) — so the mode arrived complete and still doesn't lock. The four results so far
(`A4K` 0.849ms FAILS, `B4K` 1.111ms FAILS, `90long` 2.136ms FAILS, `CTRL4K` 3.204ms
WORKS) sort cleanly by **vertical blanking time in ms**
(`vblank/((vact+vblank)·rate)`), not by lines — `90long` and `CTRL4K` have the same number
of lines (514) and just the different refresh alone is enough for one to fail and the other not.
Detail and the full table in `docs/16`, section "`90long` run".

**This is a serious problem for 90 Hz:** the HBR3 ceiling limits vblank to ~555 lines at
90 Hz, i.e. **~2.27 ms as the maximum possible** — below the 3.204 ms already known
to work. If the real time threshold is closer to 3.2 than to 2.27, 90 Hz may be
simply impossible within HBR3, regardless of vblank.

Before spending another reboot near the bandwidth limit at 90 Hz, a candidate was put together to
bound the real threshold **at 60 Hz** (without bandwidth pressure):
`experiments/vblank/g2-vblank-4k-bisect1.edid` — vblank=340 lines at 60Hz, the same 2.27 ms
that would be the maximum possible at 90 Hz. The `.conf` already points there.

**`bisect1` run and confirmed (T016): FAILS.** Only HP logo, HID confirms exact timing
(60Hz, vtotal 2500) delivered perfectly. vblank=340@60Hz gives 2.27ms — the same time that
would be the maximum possible at 90Hz within HBR3 — and it fails. **This rules out 90 Hz as
achievable within this HBR3 DisplayPort link**, regardless of what vblank is used: the
real time threshold is above 2.27ms, and the bandwidth ceiling at 90Hz doesn't allow
exceeding that value under any combination.

**Decision with the user (2026-08-05): instead of continuing to bisect the exact threshold at
60Hz, go straight to an intermediate refresh with real margin.** At 80Hz the bandwidth ceiling
allows up to 3.66ms (vs the known-working 3.204ms) — much more margin than at 90Hz.
`experiments/vblank/g2-vblank-4k-80hz.edid` was generated: vblank=775 lines at 80Hz, 1037.82
MHz, 3.301ms, 24.91 of 25.92 Gbps (~4% margin, not at the limit like the 90Hz attempts). The
`.conf` already points there. **This redefines the goal**: `CLAUDE.md` assumes that "the only cure"
for the flicker is 90Hz, but that was never tested at an intermediate refresh — if 80Hz reduces or
eliminates the perceptible flicker, the success criterion changes. Detail in `docs/16`, section
"`bisect1` run".

**`80hz` run and confirmed (T017): FAILS.** No image, only logo. HID confirmed exact
refresh of 80 and exact timing delivered. **This refutes the vblank time threshold
hypothesis**: `80hz` has 3.301 ms of blanking — more than the 3.204 ms of `CTRL4K`, which
does work — and still fails. The pattern that does survive across the 7 data points: the only pixel clock that
ever showed an image is **≈709.15 MHz** (the native 4320x2160@60 and its clone `CTRL4K`);
everything else failed, regardless of bandwidth, vblank in lines or in time. Full detail
and the table in `docs/16`, section "`80hz` run".

**Major pivot (2026-08-05, night):** instead of continuing to bisect blindly, the
hardware was investigated. The user brought the real datasheet for the **ANX7530** bridge (official
Analogix Product Brief, AA-004263-PB-7 — not versioned here, it carries a copyright notice; see `docs/10`
for the public link): it states the link ceiling as **HBR2.5 (6.75 Gbps/lane,
not HBR3)** and an explicit spec line — **"DisplayPort Receiver Input Bandwidth supports
up to 4K x 2K x 60Hz"** — which is a refresh ceiling declared by the manufacturer, not just
a bandwidth calculation. This matches the fact that `2880x1440@90` (total bandwidth LOWER than the
working 4320x2160@60) also always failed.

A separate research effort confirmed that this **is already a bug acknowledged by NVIDIA**: thread
`forums.developer.nvidia.com/t/.../337744`, internal bug **5923212**, reproduced on
RTX 2070S/3090/5070Ti/A5000 across drivers 590–610.43.02, always the same signature (60Hz works,
90Hz doesn't, even at lower resolution). No response from NVIDIA since 2026-03-20.

**Decision with the user: add this evidence to the NVIDIA thread instead of continuing with more
blind EDIDs.** Full draft of the post (in English, ready to copy/paste or edit)
at `docs/19-nvidia-bug-5923212-followup.md` — includes the table of the 7 factorial data
points, the chip identification (new to that thread, nobody had named it there
yet) and the open question for anyone with visibility into DPCD/MSA or the Windows
driver. **I did not post it** — it needs the user's forum account.

**Still to decide after posting:** whether to continue down the empirical path (the
`edid-tool.py` extension with `HBP:VBLANK@RATE` to separate exact-pixel-clock from
refresh/vblank is ready, not used yet) or whether to wait for a response from NVIDIA before
spending more reboots.

---

### Original instructions for the `80hz` reboot (already executed, kept for the record)

**STILL NEED THE REBOOT that loads `g2-vblank-4k-80hz.edid`.** Upon return:

1. `sudo ./scripts/verify-override.sh` — confirms loading (dmesg + md5).
2. Full PREFLIGHT (`docs/16`, at the very top), including `Notify Attach Begin` (root) —
   should say `pclk 1037820000 raster 4420x2935 24 bpp`.
3. `hmd-vk list` — `[1]` should report `80.000 Hz` (different from `[2]` at 60.000, this time
   with no index ambiguity).
4. Present `[1]` with `hmd-vk native 1`, headset on, HID (`panel-status.py`) in parallel,
   `testlog.py` to log it.
5. **If `80hz` WORKS:** besides "is there an image?", ask specifically **whether the
   flicker improved or disappeared** compared to 60Hz — that's the question that actually
   matters now that 90Hz is ruled out. If the flicker stays the same despite the
   image working, the lab's goal needs to be rethought from scratch (is the backlight strobe
   tied specifically to 90Hz by firmware, not to "any high refresh"?).
   **If `80hz` FAILS:** the vblank/time threshold is higher than estimated; go back to
   bisecting (at 60Hz, without bandwidth pressure) between 340 (fails) and 514 (works) to bound it
   before trying another intermediate refresh.

### Earlier this same session: the key was `DP-0`, not `DP-1`

Reboot done. `dmesg` confirmed `nvidia-modeset: Successfully read
/home/iam/Documents/reverb-g2/experiments/vblank/nvkms-override-candidates.conf` — no
warning, the bracket syntax from the previous section (below, untouched) was correct.
But the EDID at `/sys/class/drm/card0-DP-1/edid` was still the original `hmd.edid`.

The timing hypothesis was tested first (that a fresh `detect()` was missing since the
override loaded) by reading `cat /sys/class/drm/card0-DP-1/status` — that DOES trigger a real
`connector->funcs->detect()` (confirmed in `nvidia-drm-connector.c:274-283`, both the
`.force`/`.detect` callback fall into `__nv_drm_connector_detect_internal`). The entire
code chain was walked through by hand to confirm the plumbing exists end to
end: `nvDpyGetDynamicData` (`nvkms-dpy.c:3088`) → `GetEdidOverride` (`nvkms-dpy.c:195`,
which uses `nvDpyReadAndParseEdidEvo` with priority over `ReadEdidFromDP`) → back in
`nvkms-kapi.c:1544` the overridden EDID does get copied to `params->edid` because the
`overrideEdid` flag compared there is the DRM one (`connector->override_edid`, the one from
option 1, at `FALSE`) — not NVKMS's internal one → `nvidia-drm-connector.c:136` copies that EDID to
`nv_connector->edid` → line 301 calls `nv_drm_connector_update_edid_property`. The entire
path exists and should work. But status read `connected` with the old EDID
regardless.

**The real cause: an off-by-one between NVKMS and DRM in connector numbering.**
`nvkms-rm.c:880` — `AllocConnectorDispDataRec allocConnectorDispData = { };` — confirms that
`typeIndices` starts at 0. The first DP connector has `typeIndex = 0`, so its
internal name in NVKMS is **`DP-0`**. DRM, on the other hand, numbers from 1 (which is why the
actual listing in `/sys/class/drm/` is `card0-DP-1`, `card0-DP-2` — a `DP-0` never
appears). Same physical connector, two different names depending on the layer. `DPY_OVERRIDE_MATCHES`
(`nvkms-dpy-override.c:37-39`, `nvDpyEvoGetOverride` line 210) compares the `.conf`
key against NVKMS's **internal** name (`pConnectorEvo->name`), not against DRM's
— so the `DP-1` key never matched. The file was read without error because the parser
doesn't validate that the display name corresponds to a real connector; it just stores it in
the override table waiting for some connector to someday be named that.

`experiments/vblank/nvkms-override-candidates.conf` already has the corrected key:
`override.[0000:05:00.0].DP-0 = .../g2-vblank-test.edid`.

**Still need the reboot that tests the fix.** Upon return:
```
sudo dmesg -T | grep -iE 'nvkms|override|Error in|Syntax error|Successfully read'
cat /sys/class/drm/card0-DP-1/status          # triggers a fresh detect()
sudo cat /sys/class/drm/card0-DP-1/edid | md5sum
md5sum experiments/vblank/g2-vblank-test.edid  # should match
```
If they match, the override loaded successfully — continue with the `docs/16` factorial. If they do NOT
match but there's also no warning in dmesg, the problem may be in the PCI
function number (`0000:05:00.0` vs `.1`, the GPU has two functions — VGA on `.0`, audio on `.1`;
`.0` is already set correctly) or in the `debug=1` not actually enabling the
`nvEvoLogDebug` log from `nvDpyEvoGetOverride` line 212 — check whether
`NVDpyOverrideRec found: DP-0` appears in dmesg, which would confirm the match unambiguously.

### Earlier this same session (historical, untouched)

Option 1 (`debugfs edid_override`) was ruled out with evidence — see `docs/16`, section
under "PENDING". The NVIDIA driver does not go through the generic DRM helper for this
connector's EDID; it reads it through its own channel, and the override is ignored.

Moved on to option 2 (`nvidia_modeset.config_file`). The first attempt (RE via disassembly,
no source) failed: `dmesg` gave a single warning —
`Syntax error in override entry: Unknown GPU designator: 0000:05:00` — and `nvKmsReadConf`
aborts the entire file on the first error, so even the other two candidates never got
tested.

**Found something better than RE: `/usr/src/nvidia-595.71.05/src/nvidia-modeset/src/nvkms-conf.c`
is real source (open part of 595, MIT).** The exact grammar is right there, no need to
reconstruct it blind:

- The key splits `keyhead` (`override`) from `keytail` at the FIRST `.` — everything else goes
  whole to `Subparser_override`. That parser only activates the PCI address branch when
  `key[0] == '['` (`nvkms-conf.c:126`). **The brackets are mandatory**, not optional
  notation — without them it looks for the first loose `.`, which falls in the middle of the PCI
  address, and throws exactly the error we saw.
- Real format: `override.[<domain>:<bus>.<slot>.<function>].<dpy-name> = <value>`
  (the `:` and `.` inside the brackets are the 4-field hex delimiters, same as
  `lspci`/DRM: `0000:05:00.0`).
- Value: absolute path with no quotes or `<angle brackets>` — the file branch only activates if
  `value[0]=='/'` after stripping quotes; the `<angle brackets>` from the first attempt are NOT
  stripped, they remain as a literal part of the value (which is why that candidate wouldn't have
  worked either even if the key had been correct).

`experiments/vblank/nvkms-override-candidates.conf` already has the corrected line:
`override.[0000:05:00.0].DP-1 = .../g2-vblank-test.edid`.

**The `DP-1` display name was confirmed by reading the code, not by assumption:**
`nvkms-rm.c:616-623` builds `pConnectorEvo->name` as `"%s-%u"` with a `typeIndex` counter
per type (0-based, RM enumeration order). `nvidia-drm-connector.c:562` calls
`drm_connector_init()` without an explicit `type_id`, so DRM assigns its own incrementing in
the same order NVKMS already enumerated — same counter, same physical list, same order →
DRM's `DP-1` (`card0-DP-1`, where option 1's `edid_override` had already confirmed
the headset hangs off) and NVKMS's internal `DP-1` are the same connector. No need to
change the name.

`/etc/modprobe.d/99-nvkms-override-test.conf` (`config_file=... debug=1`) still points to the
same `.conf`, so all that's needed is for the module to read it again — it's read-only at
runtime, only read once when the module loads.

**Still need to trigger the reboot.** Upon return, first:
```
sudo dmesg -T | grep -iE 'nvkms|override|Error in|Syntax error|Successfully read'
```
If this time there's no warning (or it says `Successfully read...`), the override loaded
successfully. Only then verify physically: `/sys/class/drm/card0-DP-1/edid` should read as
`g2-vblank-test.edid` instead of `hmd.edid`, and continue with the `docs/16` factorial.

---

## Two independent tracks right now

1. **The vblank experiment** (`docs/16-lab-vblank.md`) — needs the lab OS booted natively.
   Blocked on an open question, see below.
2. **Monado upstreaming** (`docs/18-monado-upstreaming.md`) — needs nothing from the lab
   machine at all. Blocked on a GitLab account-verification issue on the everyday system's
   side. Do not waste lab time on this.

---

## Track 1 — vblank experiment: what to do first

**Before running PREFLIGHT, read the "PENDING" block near the top of
`docs/16-lab-vblank.md`.** While documenting this session I found and fixed a real error in
that doc: it claimed the EDID-override loading mechanism was "already proven in this lab".
It is not. The 6 bpc bug was closed with a *driver source patch* (0004), which sidestepped
ever needing NVIDIA to accept a fake EDID — so that claim was simply wrong, and following it
would have wasted lab time discovering there is no confirmed way to load the modified EDID.

**So the actual first task on the lab machine is resolving that**, trying in this order
(full detail now in `docs/16`, background in `docs/13`):

1. `/sys/kernel/debug/dri/*/DP-1/edid_override` (debugfs) — cheapest to try. Unconfirmed
   whether NVKMS's closed logic reads EDID through the generic DRM helper (would see this)
   or its own AUX channel (would not). Writing the file does not trigger hotplug — disconnect
   and reconnect the connector after.
2. `nvidia_modeset.config_file` — NVKMS's own mechanism, parameter exists and is compiled in,
   but the dpy-name syntax is undocumented. Discover it with `nvidia_modeset.debug=1` and
   reading dmesg as root during a real modeset.
3. Patching the EDID the headset itself reports over the cable, if there's an injection point
   between the Analogix bridge and the host — unexplored.

If none of the three works, the experiment is inconclusive by this route and needs a
different injection strategy before the factorial itself means anything.

### Once loading works: PREFLIGHT (5 checks, `docs/16`)

1. `grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' /proc/driver/nvidia/version` → must say `595.71.05`
2. `modinfo nvidia | grep -i license` → must include "Dual MIT/GPL"
3. `./scripts/verify-bpc.sh` → patch present
4. `lsusb | grep -E '04b4:6506|0bda:4c15|03f0:0580|04b4:6504|045e:0659' | wc -l` → must be 5
5. `dmesg | grep 'Notify Attach Begin' | tail -1` → must say `24 bpp`, not `18`

If any of the five fails, stop — measuring on the wrong driver gives a result that looks
good and points at the wrong thing.

### Then the experiment itself

Order: **CTRL → B → A**. If B works, that's the answer and A is just confirmation.
Verification is physical — put the headset on and look; the API reports 90.0 fps success
even with a black panel. For each mode: does the backlight come on, is there color or just
white/flicker, does `dmesg`'s `Notify Attach Begin` line say `24 bpp`, and the HID status
byte 18 (`scripts/decode-status.sh`).

The read-the-result table and the refresh-sweep follow-up are both in `docs/16`.

---

## Track 2 — Monado upstreaming: status

Four MR branches are ready (rebased on Monado `main` `735e29e4e`, adversarially reviewed,
three real defects found and fixed, zero warnings, DCO-signed, no AI co-author trailer per
the standing decision below). They live in the **everyday system's** clone
`~/Documents/linux_vr_base/monado`, refs `wmr-hid-resilience`, `wmr-controller-input-fixes`,
`wmr-camera-stream-toggle`, `steamvr-drv-origin-rpath`. Same content as
`patches/monado/0001–0010` in this repo.

**Blocked on GitLab account verification.** freedesktop.org's GitLab restricts new accounts
(anti-spam): they can't fork or create projects until an admin approves a request.
Filed as **issue #3736**
(`https://gitlab.freedesktop.org/freedesktop/freedesktop/-/work_items/3736`), open, no fixed
SLA. Check for a notification email, or ask to have it checked.

**Once approved:**
1. Add an SSH key to the GitLab account (can generate one in advance, same pattern as the
   lab machine's deploy key).
2. Fork `monado/monado`.
3. Push the four branches from `~/Documents/linux_vr_base/monado` to the fork.
4. Open four MRs against `main`. Titles and bodies are ready to paste, in
   `docs/18-monado-upstreaming.md`.
5. After each MR gets a number, add its `doc/changes/.../mr.<N>.md` changelog fragment as a
   final commit (path convention explained in docs/18).

---

## Idea to think about (2026-08-05, parked): scoped sudo + session auto-start

Came up while running the vblank factorial: the reboot → "I'm back" → PREFLIGHT →
present → look with the headset cycle has real copy-paste friction in the steps that need
sudo (already caused a bash history-expansion glitch when pasting output). Agreed to
request a scoped `sudoers.d` with `NOPASSWD` only for the read-only commands
(`verify-override.sh`, `dmesg`, the sysfs EDID `cat`, `modinfo`) — no blanket sudo
and no automating the `reboot` itself, because verification is physical: the user has to
be present as soon as the machine comes back anyway, so automating the reboot doesn't
save real time, and this is a single physical machine with no remote recovery if the boot
hangs. After that, the user proposed going one step further: having the Claude
Code session auto-start when the machine boots, to be able to interact as soon as it's back without the
"I'm back" step. **This was explicitly left pending to think about, not decided or implemented** —
pick it back up after running `g2-vblank-4k-90long.edid`. Full detail in memory
(`idea_agent_autostart_lab.md`, type `project`).

## Additional pending item (2026-08-05): GPU power profile

User hypothesis, not yet tested: on Windows it's always recommended to force the NVIDIA
panel to **"Prefer Maximum Performance"** for VR — leaving it at the default ("Adaptive",
dynamic clock) can cause problems. On Linux, the 595-open also boots into adaptive PowerMizer
by default. If the closed GSP firmware that decides the 90Hz lock (see
`docs/13-bug-6bpc.md`) is sensitive to the clock state at the moment of the modeset, a
downclock at the wrong moment could explain why the panel fails to sync.

Not investigated yet. When resumed: check the real P-state during the 90Hz modeset
attempt with `nvidia-smi -q -d PERFORMANCE` or `nvidia-settings`, and try forcing
maximum performance (`nvidia-settings -a '[gpu:0]/GPUPowerMizerMode=1'` or the
equivalent mechanism on the 595-open) before running the vblank experiment or in parallel with it.

## Pending (2026-08-06): comprehensive power management — system sleep + headset proximity sensor

Came up on the side, while a background transcode was running: automatic system
suspend (sleep) killed the process. It was worked around that time with a one-off sleep
inhibitor, but remains as a broader unresolved investigation — giving the user real control over
this machine's power saving so it doesn't kill background work by accident, and evaluating
whether or not automatic sleep should be enabled, and under what conditions.

Two related fronts, neither investigated yet:

1. **RESOLVED (2026-08-06, night).** System sleep (systemd) was killing background processes
   — root cause: it's not `logind` on its own (`IdleAction` unset in
   `/etc/systemd/logind.conf` or any drop-ins, default `ignore`), it's **PowerDevil (KDE Plasma)**
   requesting the suspend over D-Bus after its own idle timer, running with the
   compiled-in default because `~/.config/powerdevilrc` didn't exist. Confirmed in the journal: two
   suspend→resume cycles the same day (`16:09:04` and `16:51:48`). The one-off inhibitor
   (`systemd-inhibit ... sleep:idle` in `block` mode, used by `stereo3d-pack`) was already
   blocking it correctly, but as a per-job workaround, not as a fix. **Permanent fix
   applied:** `AutoSuspendIdleTimeoutSec=-1` in `[AC][SuspendAndShutdown]` of
   `~/.config/powerdevilrc` (created from scratch, didn't exist) — disables the idle-triggered
   suspend in the "Plugged in" profile, without touching `AutoSuspendAction`. Takes
   effect on this install's next boot; there was no Plasma session running here
   to hot-reload. The manual `stereo3d-pack` inhibitor still works the same way
   for one-off jobs, but no longer depends on remembering to use it.
2. **The G2's proximity/face detector was never gotten working.** The WMR stack exposes (on
   Windows) an IR proximity sensor that triggers automatic standby when the headset is
   taken off — not yet confirmed whether Monado reads it or ignores it in this driver. If it can be
   read, it would allow pausing the player and lowering consumption (GPU/panel) automatically when the
   headset comes off, without depending on the user remembering a manual command.

Goal: for this kind of behavior (power saving, automatic standby) to be under
explicit user control instead of running "half-baked" by default. Neither of the two
fronts has been investigated yet — noted for follow-up.

## Pending (2026-08-06): repurpose `test-powermizer-90hz.sh` — real efficiency (power limit vs. automatic regulator)

**Decision: the script is kept, not deleted** — it gets repurposed. Its original purpose (does
the 90Hz handshake fail due to a badly-timed PowerMizer downclock?) became obsolete once the
real cause of the 90Hz block was found (6bpc clamp, patch 0004). But the pattern it already
has (force `GPUPowerMizerMode` via `nvidia-settings`, measure, restore on exit) serves as a
starting point for a different and more general question.

**The phenomenon motivating this:** the user reports, measured more than once on Windows, that
capping the card's power draw in Watts (power limit) can achieve the SAME fps as the
automatic regulator (boost/adaptive PowerMizer) but with lower consumption — the automatic
regulator doesn't find that efficient point on its own. Cause unknown, not yet confirmed —
working hypothesis: the boost algorithm chases the highest P-state available on demand,
without optimizing consumption once the real fps is already capped by something else
(vsync/compositor), not by the GPU's raw throughput. Goal: reproduce and quantify
this on Linux, and decide the best power limit for this machine.

**Confirmed on this machine (2026-08-06), RTX 3060 Ti / driver 595.71.05-open, via
`nvidia-smi -q -d POWER`:** the power limit is indeed controllable here — range 100W-250W,
default/current 240W (`nvidia-smi --query-gpu=power.draw,power.limit,power.min_limit,power.max_limit
--format=csv`). Unlike the old script, this **does not need X11**: `nvidia-smi -pl
<watts>` works the same on Wayland — the original script's X11 requirement was only because
it used `nvidia-settings` to touch `GPUPowerMizerMode`, not because of the power limit itself.

**Two pieces needed before measuring seriously, per the user:**
1. **fps/latency** — already solved, the tools already exist (HID `DEVICE_STATUS`, compositor
   frame timing, `hmd-vk`).
2. **Being able to load the stack in a controlled way, so fps drops a bit below max** —
   does NOT exist yet. Without this, if the stack is already capped by vsync (ceiling = panel
   refresh), the GPU never gets to be constrained by its own throughput ceiling and the
   real power/performance trade-off can't be measured. Still need to decide how to generate that
   adjustable load — unexplored candidates: raising the compositor's supersampling resolution,
   adding a synthetic load multiplier to the player's shader, or running a second
   GPU-bound process in parallel (another `hmd-vk`/`vkcube`) to steal cycles in a measurable way.

**Method planned once both pieces are in place:**
- Sweep `nvidia-smi -pl <watts>` over a range (e.g. 100 to 240W in 20W steps).
- At each point, run the controlled load (#2) and log real fps/frame-time +
  real `nvidia-smi --query-gpu=power.draw` (not the log average, the instantaneous reading under
  steady load).
- Find the lowest power limit that sustains the same fps ceiling as the automatic
  regulator without capping — the "efficient point" the user already identified
  qualitatively on Windows.
- Compare against the automatic regulator at the same fps target, to quantify the gap.

**Not started yet** — the user explicitly left it to resume later. Do not touch
`test-powermizer-90hz.sh` until then (it stays as it was, X11-only, pattern
reference only).

---

## Standing convention decided this session

**No `Co-Authored-By: Claude` trailer on commits, and no repo-level AI disclaimer either.**
The `Signed-off-by` already certifies the content for publication; a tool-attribution note
adds nothing on top of that. Applies going forward to both this repo and the Monado series
(already applied there — the 10 patches and the reverb-g2 history were both rewritten to
drop it, and reverb-g2's rewritten history is already force-pushed to GitHub).

## Repo state

- Renamed `reverb-g2-linux` → **`reverb-g2`** (README explains why: the headset has no
  supported platform left on any OS, not just Linux). Working directory here is already the
  renamed one; GitHub remote is `Wintch/reverb-g2` (made public 2026-08-06 — this line
  predates that; see `docs/17-publishing.md`).
- `main` @ `301eaee`, matches GitHub, gate (`scripts/check-publishable.py`) passes clean.
- FCC PDFs dropped from the tree (linked to fccid.io instead); Oasis driver attribution fixed
  (it's Matthieu Bucchianeri's, not HP's); HP Omnicept noted as a related test target in
  `docs/10-resources.md` (same WMR display path per Monado's prober — a 90 Hz result there
  would show whether this is G2-wide or unit-specific) but not being pursued (no hardware).
