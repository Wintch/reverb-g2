# 02 — Player 360 (photos and video with NVDEC)

The player is `hello_xr` (OpenXR-SDK-Source, local branch `g2-360-viewer`) modified to
render an equirectangular skybox. The full patch lives in
`patches/hello_xr-player/`. Base: OpenXR SDK 1.1.62.

## Build

```bash
cd ~/Documents/linux_vr_base/OpenXR-SDK-Source
cmake -B build -GNinja -DBUILD_TESTS=ON -DBUILD_API_LAYERS=OFF -DBUILD_CONFORMANCE_TESTS=OFF
ninja -C build hello_xr
```

(`hello_xr` lives under `src/tests/`, hence `BUILD_TESTS=ON`. It needs `libavcodec-dev
libavformat-dev libavutil-dev libswscale-dev` for the video path — if missing, it still
builds but with photos only.)

## Usage

```bash
# 1. Bring up the VR pipeline (see 01-bringup-monado.md)
./jack-in.sh 3dof     # 3dof = orientation only, ideal for 360/VR180

# 2. Everything goes through the wrapper:
./play360.sh video.mp4                 # a single file, looping
./play360.sh photo360/                 # directory = playlist, sorted by name
./play360.sh -s foto_equirect.jpg      # photo
./play360.sh -t 60 video.mp4           # time limit
./play360.sh -p 180 -e sbs video.mp4   # force projection/stereo if detection fails
./play360.sh -w 47 video.mp4           # virtual screen width in degrees (flat mode)
```

`play360.sh` autodetects where the trees live just like `jack-in.sh` (`~/Documents/linux_vr_base`
or `~/vr`, and `VR_BASE=` forces it). Until 2026-08-04 it had this hardcoded to the main system and
on the lab machine it died with "hello_xr not built" with no further explanation.

When run from a **real terminal** (not piped or backgrounded), there are transport keys:
`space` pauses, `[`/`]` speed (0.125x–4x), `1` normal, `h`/`l` seek -10s/+10s,
left/right arrow (or `<`/`>`) step one frame back/forward, up/down arrow (or `^`/`v`) zoom
in/out, `0` zoom back to 1x, `b`/`d` brighter/dimmer, `9` brightness back to 1x, `enter`
recenters, `n` next,
`q` quit. If a dirty disconnect leaves the terminal mute:
`stty sane`. In a pipe there are no keys and the run ends at stdin's EOF, as always.

### Seek + progress bar (2026-08-06)

Added because with the headset on there's no way to reach the keyboard. Two paths, same
result (`PlayerControl::QueueSeek`, `patches/hello_xr-player/0004-*.patch`):

- **Keyboard** (for testing from the desktop, without the headset): `h` = -10s, `l` = +10s.
- **WMR controller**: pushing the left or right stick to one side (>0.7 deflection)
  triggers the same jump. With hysteresis (it has to return to <0.3 before it can
  fire again) so that holding it pushed doesn't fire a jump every frame.

The seek is absolute over `av_seek_frame`, runs on the decode thread (never directly from
the render/input thread — `AVFormatContext` isn't safe for that), and clamps to
`[0, duration]`. The progress bar is a narrow strip at the bottom of the
screen, drawn directly in screen space inside the same skybox shader (no
new pass or pipeline — it reuses the `mode.y`/`mode.z` slots of the existing push-constant,
which were unused). It only appears ~3s after the last touch to pause/speed/seek, then
hides itself.

**Tested by the agent:** keyboard seek (forward, backward, clamp at 0 without crashing,
without breaking existing pause/speed) — via a fake pty rigged with Python, since
`play360.sh` without a real terminal doesn't send keys. **Verified with the headset on
(2026-08-06):** left controller stick, trigger, and menu working.

### Full controller controls + themes (2026-08-06, `0005-*.patch`)

Heads up, first: the G2 controllers use the **`oculus/touch_controller`** profile, not WMR —
see `docs/03-controllers.md` ("Second pass") for why; any new binding goes
in THAT block of `openxr_program.cpp` or it's dead on arrival.

- **Trigger** (either hand): pause/resume, with 0.7/0.3 hysteresis like the stick.
- **Grip squeezed hard** (either hand; it's analog, runtime threshold 0.7) or
  `enter`: **recenter** — the direction you're looking becomes "forward". Only
  yaw; pitch/roll still follow the actual headset.
- **Menu (three lines), left controller only** — on the Touch profile the right menu
  button doesn't exist: **hold ~1.5s to exit**, with a red bar at the top filling up;
  releasing early cancels. A short tap no longer exits (before it exited on one tap, too
  easy to trigger by accident).
- **`HELLO_XR_THEME`**: `daylight` (default) paints the empty space outside the
  content light gray; `night` leaves it black as before. It exists because total black
  outside the frame was mistaken for "tracking died". The shader now does `discard` outside
  the content instead of painting black, so the app's clear color is finally visible.
- When controllers connect, the player prints `Active profile /user/hand/...` and the
  sources for each action — for a dead button, check that first.

### Frame-by-frame step (2026-08-07, `0006-*.patch`) — NOT YET VERIFIED LIVE

Left/right arrow steps back/forward exactly one frame, forcing a pause first (the jump is
too small to see while still playing). `<`/`>` are a plain-keyboard fallback in case a
terminal encodes arrows differently. No new decode machinery: it reuses the same
`Video360::Seek(seconds)` call `h`/`l` already use, just scaled by `1/FrameRate()` instead
of a fixed 10s — see `PlayerControl::StepFrame` in `playercontrol.cpp`.

Arrow keys are a 3-byte escape sequence (`ESC [ C/D`) and `ESC` alone is already the quit
key; `main.cpp`'s key thread disambiguates with a short (30ms) `poll()` after seeing `ESC` —
a bare Escape press has nothing following it, an arrow key's remaining bytes are already
buffered by the time the first one is read.

**Status: compiles clean, not run live.** `hello_xr` needs an active OpenXR runtime
(`monado-service` up) to get past instance creation at all — that wasn't brought up this
session, so this hasn't been exercised through even a fake-pty keyboard test, let alone
with the headset on. Next time the stack is up: fake-pty test first (arrows + `<`/`>`,
check the log for `player: frame +1`/`-1`), then confirm with the headset that stepping
while paused actually lands on the next/previous frame and not a multi-frame jump.

### Digital zoom (2026-08-08, `0007-*.patch`) — VERIFIED LIVE

Zoom in/out on whatever's showing (360, VR180, or flat), mapped to the vertical thumbstick
axis — completely unused until now, since `QueueSeek` already owns X on both the G2's real
`oculus/touch_controller` profile and `microsoft/motion_controller`. Same hysteresis-latch
shape as seek/pause: push past 0.7, must fall back under 0.3 before it fires again. Each
crossing steps the zoom multiplicatively by 1.15x, clamped to `[0.5, 4.0]`. Keyboard: up/down
arrows (same `ESC [ A/B` disambiguation `main.cpp` already does for the left/right `C`/`D`),
with `^`/`v` as a plain-key fallback — same idea as `<`/`>` for frame step — and `0` resets to
1x (pairs with `1` for normal speed).

No new render pass: `PlayerControl::Zoom()` is threaded into the shader through `panoFov.z`,
which was unused padding in the push-constant (see `vulkan_utils.h`) — same reuse-a-slot
reasoning as `mode.y`/`mode.z` for the progress bar. `frag.glsl` divides the coordinate
driving the projection mapping (`az`/`el` for 360/180, `screen` xy for flat) by the zoom
factor before the existing formulas: the sphere or virtual screen itself never changes, only
how much of it one physical ray picks up.

**Tested by the agent:** keyboard zoom in x3 / out x1 / reset, via a fake pty against the live
stack (real `monado-service`, real G2 hardware) — the log shows the exact expected sequence
(1.15 → 1.32 → 1.52 → 1.32 → 1.00x) and a clean quit. The action registers correctly against
real hardware too: `Zoom action is bound to 'Left/Right Oculus Touch Controller Thumbstick'`,
no collision with `Seek` on the same physical stick. One false lead ruled out along the way:
a `vkDestroySemaphore` validation warning on quit turned out to be pre-existing on the
unmodified baseline (reproduced by stashing this commit and quitting with zero zoom keys
pressed) — not something this patch introduced.

**Confirmed live with the headset on, same day.** Played two clips through the full
`play360.sh` path with real controller input while the user wore the G2: a flat 2D clip
(`stereo3d-pack/in/01pjni8u.mp4`, forced `-p flat`) and a flat stereo SBS clip
(`stereo3d-pack/out/03ehybrp_sbs.mp4`, forced `-p flat -e sbs` — see the `stereo3d-pack`
section above for why the override is needed on this kind of output). Thumbstick Y worked
exactly as assumed on the first try, no sign flip needed: **stick up = zoom in, stick down =
zoom out**, either hand. User verdict: "zoom anda perfecto". The `vkDestroySemaphore`
quit-time validation warning (pre-existing, see above) is the only open loose end, and it
isn't specific to zoom.

One incidental finding along the way, unrelated to zoom: `03ehybrp_sbs.mp4` (a
`stereo3d-pack` SBS output, 3840x1080) failed NVDEC init (`cuvidCreateDecoder ...
CUDA_ERROR_INVALID_VALUE`) and fell back to software decode - functionally fine for this
short 30s clip (120 fps produced, 0 renderer starves, comfortably above the 90 fps needed),
but worth a look if a longer `stereo3d-pack` output ever fails to keep up. Not investigated
further; noted here so it isn't mistaken for a zoom regression later.

### Brightness (2026-08-09, `0009-*.patch`) — VERIFIED LIVE

A plain multiplier on the displayed content: >1 brighter, <1 dimmer, 1.0 is native/off.
Bound to the right Touch controller's **A** (brighter) and **B** (dimmer) buttons - the last
free real inputs on `oculus/touch_controller`, since both thumbsticks already carry seek (X)
and zoom (Y). A/B only exist on the right Touch controller (the left one has X/Y instead)
and don't exist at all on `microsoft/motion_controller`, so this is Touch-only by necessity -
same reasoning `docs/03-controllers.md` already gives for why Menu is left-only. Edge-
triggered like recenter/quit (`changedSinceLastSync`), so it steps once per press instead of
spamming every frame while held. Keyboard: `b`/`d` (brighter/dimmer), `9` resets to 1x -
pairs with `1` (normal speed) and `0` (normal zoom).

Threaded through `panoFov.w`, the last unused push-constant slot (`x`/`y` were already
half-angles/half-extents, `z` is zoom) - still no push-constant growth. `frag.glsl`
multiplies `FragColor.rgb` by it right after the texture sample, before the progress-bar/
quit-hold overlay bars, so dimming the video never also dims that feedback.

**Confirmed live with the headset on**, same session as the loop-fix and rolling-artifact
investigation above. Keyboard sequence tested via fake pty first (up x3/down x1/reset ->
1.15 -> 1.32 -> 1.52 -> 1.32 -> 1.00x, same pattern as zoom), and the action registers
cleanly against real hardware (`BrightnessUp action is bound to 'Right Oculus Touch
Controller A'`, no collisions). User verdict pressing A/B during actual playback: "funciona
bien, sube y baja el brillo".

### Overlay bars: position, fake stereo depth, thinner + red (2026-08-09, `0010-*.patch`) — VERIFIED LIVE

The progress bar and quit-hold bar went through three rounds of live headset feedback the
same session, all against real VR180 4K content
(`blade_runner_visuals_vr180_4k.mp4`/`blade_runner_skyline_vr180_4k.mp4`, both `stereo3d-pack`
outputs, 3840x1920).

1. **Position.** They used to sit at `t` in `[0.94,0.98]` / `[0.02,0.06]` - 2-4% from the
   absolute edge of the render target. User: "aparece muy abajo, no lo llego a ver". A first
   move to `[0.80,0.88]` still wasn't enough ("se ve mejor, pero aun muy abajo") - the
   comfortable/sharp area of this headset's optics is clearly smaller than the nominal FOV
   suggests. Moved much further inboard to `[0.58,0.62]` (progress) / `[0.30,0.40]` (quit),
   explicitly trading subtlety for guaranteed visibility. Also inset horizontally - full-width
   `s` in `[0,1]` read as "se me va para los costados" once the bar was actually visible - to
   `s` in `[0.20,0.80]`, centered.
2. **Depth.** User: "hace que este a la distancia del video". Both bars used to draw
   identically for both eyes (zero disparity), reading as glued flat to the lens/at infinity
   against real stereo 3D content that has its own depth from camera parallax baked into the
   footage. Faked a fixed, comfortable HUD depth (1.5m) with a small-angle stereo parallax
   shift per eye (nominal half-IPD 31.5mm, same `tan(x)~=x` approximation this shader already
   uses elsewhere) - needed which-eye info in the shader, packed into spare bits of `mode.x`
   (only ever needed 0-2 for `PROJ_*`) rather than growing the push-constant struct.
3. **Style.** User: "el indicador de la posicion mas fino y rojo". Thickness folded into the
   position fix above; fill color changed from white/gray to red
   (`0.95,0.15,0.12` filled / `0.30,0.08,0.07` unfilled).

Final verdict: "se ve bien, funciona" - described it as reading like a thin red position
marker over a lighter total-duration track, which is exactly the intended design.

### Next track from the controller (2026-08-09, `0011-*.patch`) — VERIFIED LIVE

Directory playlists could only advance via the keyboard (`n`) - no way to do it with the
headset on, and the user asked directly: "como paso al proximo video si es una lista?".
Bound to **Y on the left Touch controller** (the mirror of A/B, right-hand-only, used for
brightness above - the last free real input on the profile), edge-triggered like
recenter/brightness/quit. `PlayerControl::RequestNextTrack()` factored out of what used to be
inline logic in `HandleKey`'s `'n'` case, so keyboard and controller share one
implementation.

Verified: the action registers against real hardware (`NextTrack action is bound to 'Left
Oculus Touch Controller Y'`), and confirmed live playing a real 3-file directory playlist
(`~/vr/media/playlist-test/`: `leblon_vr180_meta.mp4` 4320x2160/40s,
`short_vr180_meta.mp4` and `short_vr180_ovda_dirfill_meta.mp4` both 3840x1920/15s, all VR180
SBS with container metadata) - pressed Y, log shows `player: siguiente` immediately followed
by the next file's projection line, user confirmed watching it change: "si, cambio bien".

**Still open, scoped but not started:** a lightweight "gallery"/browse mode for playlists -
user wants to page through files one at a time as a paused thumbnail (a real decoded video
frame, not a separate pre-generated image) with a counter, instead of blind sequential
autoplay, so you get a sense of what's in a folder before committing to watching something
in full. Scope agreed via AskUserQuestion: single-item navigation (not a multi-thumbnail
grid), thumbnail source is a real frame decoded from the video itself (not a companion
`.jpg`). Not yet designed in code terms - next session's starting point if picked back up.

### Previous track (2026-08-09) — VERIFIED (binding), continuation of Next track

Mirror of Next track above: **X on the left Touch controller** (the other left-hand face
button, next to Y), plus `p`/`P` on the keyboard. `AdvanceTrack()` and the new
`PreviousTrack()` (`graphicsplugin_vulkan.cpp`) are exact mirrors - same skip-on-failure
loop, `(index + count - 1) % count` instead of `(index + 1) % count` for the wraparound
(unsigned index, so `count - 1` avoids underflowing past 0). `PlayerControl::
RequestPreviousTrack()`/`TakePreviousTrackRequest()` mirror the Next-track refactor exactly.
Verified against real hardware: `PrevTrack action is bound to 'Left Oculus Touch Controller
X'`, no collisions. Not yet exercised live going backward through a real playlist -
next-track's own live playlist test (`0011`) covered the forward direction; this landed
right after and hasn't had its own dedicated headset check yet.

### Background theme default flipped to black (2026-08-09)

`HELLO_XR_THEME`'s default was "daylight" (medium grey) - for VR180 content specifically,
that grey covers the entire rear 180 degrees the frame doesn't hold. User: "en el player la
parte de atras de mi queda blanca... hagamos negro todo por ahora". Default is now "night"
(black); pass `HELLO_XR_THEME=daylight` to get the grey back if ever needed. Confirmed live:
"se ve todo negro atrás, perfecto".

### Playlist wrap-around — CONFIRMED, not a bug (2026-08-09)

User asked directly whether the playlist restarts from the beginning after the last file.
Before touching anything, checked the existing code (`AdvanceTrack()` already used
`(index + 1) % count`, correct modulo wraparound) and then measured it directly rather than
trusting the read: a 220s run of the 3-file test playlist logged three full clean cycles
(`2/3 → 3/3 → 1/3`, repeated three times) via `journalctl`-style log grep, then reproduced
again with the headset on (five cycles this time). Playlist wraparound already worked;
nothing needed fixing. Worth remembering as a lesson, not just a data point: the user likely
hadn't personally watched a full cycle complete in earlier, shorter test runs - the code was
never actually broken.

### "Any key advances" for a temporary controls-legend flow (2026-08-09)

New wrapper script, no player architecture change: **`scripts/play-with-legend.sh`** shows a
static image with the current control list (rendered as pixels via ImageMagick, English -
see `~/vr/media/controles.png`, the filename kept from an earlier Spanish draft but the
content is now English to match the rest of this repo) using the player's existing photo
mode, then chains straight into the real content. Exists because there's no in-headset text
rendering at all today (everything on screen is colored bars, not glyphs) - a real text
engine would be a much bigger feature, and this was explicitly requested as a temporary
measure instead.

During this, the user asked for **any button except Menu to instantly skip the legend**,
rather than needing the same 1.5s hold-to-quit gesture a real session uses to end. Added
`PlayerControl::SetAnyKeyQuits(bool)` plus a new `HELLO_XR_ANY_KEY_QUITS=1` env var (read
once at startup in `main.cpp`) - when set, every control's action function (pause, speed,
seek, frame-step, zoom, brightness, recenter, next/prev track) also sets the quit flag via a
new shared `MaybeQuitOnAnyKey()` helper, deliberately kept separate from
`TouchInteraction()` (zoom/brightness don't touch the progress-bar timer, but should still
count as "a key was pressed" here). Menu's own dedicated hold-to-confirm path is completely
untouched - still the only way to *quit* a real session outright.

**Scoping bug caught and fixed before it caused confusion:** the env var must apply to the
legend phase ONLY, not the real content phase after it (where every button needs its actual
job back, not "instantly quit"). First attempt set it as a blanket prefix on the whole
wrapper script invocation - wrong, would have made every button quit real playback too.
Fixed inside the script itself: `HELLO_XR_ANY_KEY_QUITS=1` scoped to just the legend's
`play360.sh` call, explicitly `env -u`'d back off for the real content's `exec`.

The first "confirmed live" of this flow ("vamos RE bien!") turned out to be misleading: the
legend *closed* on a button press, but the video never followed. Chasing that uncovered two
real exit bugs — see the next section, the biggest find of the session. After both fixes,
the complete flow was confirmed live for real: button press on the legend → content starts
within a second or two ("ahora funcionó, el video arrancó al toque"). `0012-*.patch`.

### The controller-quit exit deadlock (2026-08-09, `0012-*.patch`) — ROOT-CAUSED WITH GDB, FIXED, VERIFIED LIVE

**Symptom:** any quit initiated from the controller (Menu hold, or any button under
`HELLO_XR_ANY_KEY_QUITS=1`) ended the XR session — backlight-only in the visor — but the
process never exited, so anything chained after it (like `play-with-legend.sh`'s content
phase) never started. Reproduced repeatedly with the headset on; never reproducible via
fake-pty keyboard tests, which was the tell.

**Root cause, caught red-handed with `gdb -p` on a live hang:** a classic two-thread
deadlock inside glibc.

- The keyboard thread (ours, since patch 0003) waits for keys in `getchar()` — stdio, which
  holds stdin's internal `FILE` lock for the entire blocking read.
- A controller-driven quit means no key was ever pressed, so that thread is still parked
  there, lock held, when the main thread returns from `main()` and enters `exit()` — whose
  `_IO_flush_all()` needs that exact lock. Deadlock; the process is immortal.

**Latent since the Menu-quit patch (0005, 2026-08-06), masked by two accidental backstops:**
interactive runs got killed by `timeout --foreground`'s SIGTERM at the `-t` bound, and the
old non-interactive `sleep N | hello_xr` stdin pipe delivered EOF at N seconds — waking the
keyboard thread, releasing the lock, and letting `exit()` finish *late*. Every "Menu quit
worked" before tonight was really "the hang resolved itself before anyone measured it".
Tonight's `sleep infinity` stdin change removed the EOF backstop and the controller-quit
feature made the trigger the common case — which is what finally surfaced it.

**Fix:** the keyboard thread reads via raw `read(2)` (`ReadKeyByte()` in `main.cpp`) instead
of `getchar()`. A kernel-level read holds no user-space locks, so the thread parks in it at
exit harmlessly forever. Side bonus: `poll()`+`read()` on the same fd (the arrow-key
disambiguation) is also more coherent than the old `poll()`+`getchar()` mix, where bytes
could sit in stdio's buffer invisible to `poll()`.

**Second, separate exit bug found in the same dig:** `~OpenXrProgram()` destroyed the
swapchain/session/instance with the last frame's GPU work potentially still in flight — the
actual source of the `vkFreeCommandBuffers`/`vkDestroySemaphore` "is in use" validation
errors that had been printing on *every* quit all along (long dismissed as harmless
shutdown noise; T099 even "ruled it out" as pre-existing — pre-existing yes, harmless no).
New `IGraphicsPlugin::WaitForGpuIdle()` (no-op default, `vkDeviceWaitIdle` in the Vulkan
backend), called first thing in the destructor. Also fixed on the way: the quit flag set by
controller paths was only ever *watched* by the keyboard thread, so `PollActions()` now
latches `xrRequestExitSession()` itself when `QuitRequested()` goes true.

**Also fixed in `play360.sh` during the same arc:** the non-interactive mode's `sleep N |`
pipe made the script block the full N seconds even after `hello_xr` exited early (the shell
waits for both pipe members); replaced with `timeout` on `hello_xr` directly plus a
`sleep infinity` stdin keepalive via process substitution — which then needed explicit
cleanup (`kill` after the run), since an orphaned keepalive never notices its reader died
(six had accumulated within the hour).

Verification: keyboard paths re-checked via fake pty after the raw-read switch (all keys
work, clean exit in 0.06s), and the full controller flow confirmed live with the headset on.

### Stereo audio (2026-08-26, `0021-*.patch`) — NOT YET VERIFIED LIVE

`HELLO_XR_AUDIO=1` plays the file's audio track through PipeWire, synced to video. Scope is
deliberately narrow: **head-locked stereo passthrough, no spatialization.** Everything this
player actually plays comes from `get360.sh`'s `android_vr` YouTube path or is plain stereo
to begin with — never ambisonic — so there is no HRTF/head-rotation work to do; the two
channels just get decoded, resampled, and handed to the sound card as-is.

**Default is unset, and unset means zero behavior change.** No new thread starts, no audio
codec or `pa_simple` connection opens, and the demux loop routes audio packets exactly like
it always did (reads them, never touches them, `av_packet_unref`s them). This was load-
bearing for the design: the silent player is a working demo people rely on, and audio was
not allowed to add any risk to it when off.

**How it plays, when on:** `Open()` finds the file's audio stream with `av_find_best_stream`,
opens its own `AVCodecContext`, and sets up an `swresample` context that normalizes whatever
the file carries (any sample rate/format/channel count) to a fixed **S16LE / 48000 Hz /
stereo**, matching what `pa_simple` is told to expect. A dedicated audio thread pulls packets
the video demux thread now routes into a second queue (previously discarded), decodes,
resamples, and blocks on `pa_simple_write()` — that blocking write is the entire pacing
mechanism: PipeWire only accepts more data once the hardware has consumed what's already
queued, the same way the video side's `TakeFreeSlot()` blocking paces decode against the
renderer.

**Sync — audio becomes the master clock once active.** The existing video clock
(`playbackTime`, a wall-clock accumulator scaled by `rate`) is real-time-accurate but drifts
independently of whatever's actually audible. Once `HELLO_XR_AUDIO` is active, the audio
thread tracks how many stereo sample-pairs it has written since a known anchor point in the
file's own pts timeline, subtracts `pa_simple`'s own reported latency (samples written but
still sitting in the server buffer, not yet audible), and publishes the result as an atomic.
`AcquireCurrentSlot()` reads that atomic with no locking — the render thread never calls into
`pa_simple` itself — and uses it as `playbackTime` instead of the wall-clock accumulator.
Falls back to the old accumulator for the brief startup window before the first audio chunk
lands, and for one beat right after a loop seam or a manual seek while the audio thread is
mid-flush.

**Loop and seek** both already reset the video side's own clock state
(`clockStarted`/`loopOffset`/the frame queue) in `DecodeLoop()`; the same two spots now also
raise an `audioResetPending` flag on a second mutex/condition-variable pair dedicated to
audio, so a busy audio thread can never add latency to the 90 Hz render path. The audio
thread answers by draining its packet queue, calling `avcodec_flush_buffers` on its own
codec context, flushing `pa_simple`'s buffer, and re-anchoring to the new position — so
stale pre-seek or pre-loop audio never bleeds across the seam. (Not reset on either seam:
`swresample`'s own internal resampling delay line, a sub-millisecond artifact at typical
44.1/48 kHz source rates — not worth a full close/reinit on every loop.)

**Pause** (`SetRate(0)`, the grip button since patch 0005) leaves the audio thread holding a
fully-decoded, fully-resampled chunk rather than writing it, after flushing `pa_simple`
exactly once on the transition into pause — so whatever was already buffered goes silent
immediately instead of audibly finishing itself out over the sound server's buffer. This
matches the gesture's intent: pause is supposed to be instant.

**Rate ≠ 0 or 1 (slow-mo/fast-forward) is out of scope** — the demo only ever uses rate 1.
Audio keeps playing at normal speed regardless of `rate` (it has no independent time-stretch
path); the only guarantee made for other rates is that it won't crash.

**Failure handling:** anything that can go wrong here — no audio stream in the file, the
codec or resampler won't open, `pa_simple_new()` can't reach a sound server — logs exactly
one line and falls back to silent, video-only playback. This was a hard requirement: a demo
must never die because its audio track or output device didn't cooperate.

**What's verified and what isn't.** Built clean (`ninja hello_xr`) under this project's full
warning set (`-Wall -Werror=unused-parameter -Wpointer-arith -Werror=implicit-fallthrough
-Werror=undef -Werror=missing-braces -Werror=unreachable-code`), linking cleanly against
`libswresample` and `libpulse-simple`. Separately confirmed with a standalone test program
that `pa_simple` actually reaches this box's live PipeWire-Pulse sink (connect, six chunks
written, latency readback climbing to a plateau as expected, clean drain and shutdown) — so
the output side of the design is known-good on this hardware. **Not yet run end to end**:
doing that needs a live XR session (real headset or Monado's simulated-HMD fallback), which
this change didn't attempt, matching this project's own rule that anything audiovisual is
verified by a human, not by logs. Still to check with the headset on: audio is actually
audible; A/V sync holds over a full loop (the seam is exactly where this design's riskiest
logic lives); grip-pause silences audio immediately, not with a tail; and quitting mid-
playback doesn't hang or crash (join order in the destructor: audio thread first, then
`pa_simple_free`/`swr_free`/codec context — untested against a live process).

Command to test once the headset session is up: `HELLO_XR_AUDIO=1 ~/vr/play360.sh <a
VR180/360 file that actually has an audio track> [args]`. A file transcoded through
`stereo3d-pack` may have dropped its audio track entirely — check with `ffprobe` before
assuming a silent run means the feature is broken.

## Projections and stereo (v3)

The player understands three projections — **360 equirect, VR180 half-equirect, flat**
(virtual screen) — each mono or stereo **side-by-side / over-under**. The eye
split is applied in the shader after the spherical mapping, so both eyes come from the same
decoded frame (a single upload per frame).

Detection matters because the layouts are ambiguous by dimensions alone: a 2:1 could be
360 mono **or** VR180 SBS, and getting it wrong looks "plausible but odd", not broken.
Resolution order:

1. Overrides: `HELLO_XR_PROJECTION` (360|180|flat) and `HELLO_XR_STEREO` (mono|sbs|tb)
2. Container metadata (MP4 boxes `sv3d`/`st3d` — VR180 cameras and YouTube write these)
3. Filename conventions (vr180, sbs, _tb, 360…)
4. Aspect ratio as last resort

Whatever it decided is ALWAYS printed before drawing (with the headset on there's no other
way to know):

```
  MODE: VR180 3D (side-by-side)
  File: 7680x4096  ->  3840x4096 per eye  |  59.94 fps  |  av1
```

**VR180 3D verified in the headset 2026-08-04** ("the 3D effect is really good").

### YouTube hides the VR streams

Same URL, different content: the normal client gets a flat monoscopic render
(3136x1764 in the measured example) and the `android_vr` client gets the real streams
(7680x4096 stereo "mesh"). `get360.sh` requests `android_vr` first; in the `-l` listing,
`2160s60` = stereo, `2160p60` = flat. Downside: `android_vr` doesn't accept cookies, so
age-restricted ⇒ flat version only (automatic fallback).

## Own content: 2D → 3D with `stereo3d-pack` (2026-08-04)

`~/Documents/stereo3d-pack` converts ordinary monocular video into stereo (Depth Anything V2 +
DIBR, on GPU, ~3.5 fps at 1080x1920). It's the other source of stereo content for this setup besides
YouTube, and works for any flat video the user has. Its bridge over here is
`stereo3d-pack/tools/ver-en-casco.sh`, which calls `play360.sh` with the correct flags.

**The important part on this side**: its outputs expose a hole in the detection chain.

| output | what it is | what the player detects |
|---|---|---|
| `--format vr180` + metadata | 3840x1920 equirect, `st3d`=2 + `sv3d/equi` bounds 0.25 | VR180 3D ✅ by metadata |
| `--format vr180` without metadata | 3840x1920 | VR180 3D ✅ by name + aspect |
| `--format sbs` | 2160x1920, i.e. 1080x1920 per eye | **VR180 3D ❌** — should be FLAT 3D |

The bad case: there's no container signal saying "flat", the filename only contributes the `sbs`,
and the per-eye aspect (0.56) falls into the `HalfEquirect180` branch of `ResolvePanoLayout`. The
flat video ends up wrapped onto a hemisphere: it looks odd, not broken. You have to pass `-p flat -e sbs`.

Fixing it properly would need a fourth criterion in `projection360.cpp` (for example: if the
container declared stereo but **did not** declare projection, a "normal video" per-eye aspect is
more likely flat than VR180). **The player wasn't touched**: the tree was frozen for the 90 Hz test
when this was prepared, and either way it's better to look inside the headset first before
changing detection heuristics. Noted for later.

Counter-intuitively, **for material that was born flat, `sbs` is the better choice, not VR180**:
the 180°x180° projection with `--vr-fov 65` leaves the content occupying 694x1036 of a
1920x1920 canvas per eye — 19% of the pixels, the rest black. `sbs` goes at native resolution on
the virtual screen. VR180 is for uploading to YouTube or for headsets that only understand spheres.

And a detail that applies to the whole flat mode, not just this: **`HELLO_XR_SCREEN_FOV` scales
the 3D**. An SBS disparity is a fraction of the image width, so the angular disparity
≈ that fraction × the apparent width in degrees. A bigger screen = more depth and more fatigue,
without touching the file. For vertical 9:16 it also needs to be lowered: with the default 70°
the screen ends up more than 100° tall, more than the headset's FOV (the wrapper computes 47°).

## Environment variables

| Variable | Effect |
|---|---|
| `HELLO_XR_PHOTO360=/path.jpg` | equirectangular photo (JPG/PNG) |
| `HELLO_XR_VIDEO360=/path` | video OR directory (playlist); H.264/HEVC/AV1/VP9 |
| `HELLO_XR_PROJECTION=360\|180\|flat` | forces the projection |
| `HELLO_XR_STEREO=mono\|sbs\|tb` | forces the stereo packing |
| `HELLO_XR_PANO_FOV=AxB` | 180 frame arc in degrees (default 180x180) |
| `HELLO_XR_SCREEN_FOV=N` | apparent width of the virtual screen in flat mode (default 70°, flag `-w`) |
| `HELLO_XR_VIDEO_HW=0` | forces software decode |
| `HELLO_XR_VIDEO_DIRECT=0` | disables direct NVDEC→staging (for A/B) |
| `HELLO_XR_VIDEO_STATS=1` | separate decode and upload stats |
| `HELLO_XR_POSE_STATS=1` | fps + rotation delta between frames |
| `HELLO_XR_FIXED_POSE=1` | ignores tracking — diagnostic |
| `HELLO_XR_AUDIO=1` | plays the file's audio track through PipeWire, head-locked stereo, synced to video (see "Stereo audio" above) — NOT YET VERIFIED LIVE |

## How the video works (v3, zero-memcpy)

```
file → libavformat → NVDEC (decoder chosen by hand: ffmpeg's default for AV1 is
        libdav1d, which does NOT have hwaccel! — measured fix: 25→59 fps at 8K60)
        → av_hwframe_transfer_data DIRECT to the mapped Vulkan staging buffer
          (ring of 8 buffers; the render thread no longer copies ANYTHING)
        → vkCmdCopyBufferToImage → Y (R8) + CbCr (R8G8) textures
        → GPU YUV→RGB pass (601/709 matrix + range per stream)
        → skybox level 0 (sRGB) → mip chain (capped at 6) → skybox shader
          (projection + eye split via push constants)
```

Optimization history (8K, measured):

| version | upload | render thread |
|---|---|---|
| v2: decode→own RAM, memcpy to staging | 19 fps | 14.5 ms |
| v3: NVDEC→staging direct | 30 fps (HEVC file cap) | 8.2 ms |
| v3 + AV1 decoder fix (8K60) | ~48 fps | 6.5 ms |
| v3 + ring 5→8 buffers | **60.0 fps, 0 starves** | 6.3 ms |

The ring went from 5 to 8 because decode jitter (keyframes) was draining a 3-frame
buffer: the renderer found no new frame in ~25% of vsyncs even though decode
averaged 59 fps. +126 MB of RAM at 8K, none at 4K.

Decisions carried over from v2 that still hold: no swscale (YUV→RGB on GPU), sRGB texture with
UNORM per-view write (MUTABLE_FORMAT, gamma applied exactly once), 10-bit gets downconverted to
8-bit in the decode thread.

**Playlist**: each track destroys and recreates the whole chain (staging, planes, conversion
pass, skybox) because the next one may have a different resolution/projection. The hitch
between tracks is a vkDeviceWaitIdle + realloc — it only happens between videos.

## Verification

With the headset on and `HELLO_XR_VIDEO_STATS=1`:
- "video upload: X frames/s" should match the file's fps, and "renderer starves" ≈ 0.
- "video decode:" should say `NVDEC direct-to-staging` (if it says `+ copy`, the direct
  transfer failed and it degraded on its own — functional but slower).
- The `MODE:` banner should match what the content actually IS.
- Visual 360: no band at the rear seam. VR180: black behind the shoulders, not
  repeated image. 3D: real depth (if it looks doubled, the eye split is wrong).

## Pending / roadmap

- ~~Test the transport keys live~~ DONE 2026-08-06 (see "Seek + progress bar" above:
  keyboard tested via fake pty, controller verified with the headset on) and the playlist
  path verified with video 2026-08-07 (T041).
- ~~Zoom with the headset on~~ DONE 2026-08-08 (see "Digital zoom" above): confirmed live,
  no sign flip needed, user verdict "zoom anda perfecto".
- ~~Brightness controls~~ DONE 2026-08-09 (see "Brightness" above, `0009-*.patch`): A/B on
  the right Touch controller, confirmed live.
- ~~Overlay bar position/depth/style~~ DONE 2026-08-09 (see "Overlay bars" above,
  `0010-*.patch`): three rounds of live tweaking, final verdict "se ve bien, funciona".
- ~~Next track from the controller~~ DONE 2026-08-09 (see "Next track from the controller"
  above, `0011-*.patch`): Y on the left Touch controller, confirmed live on a real playlist.
- **Gallery/browse mode for playlists** — scoped, not started (see "Next track from the
  controller" above for the agreed scope: single-item paged navigation, real decoded video
  frame as the thumbnail, no multi-thumbnail grid). Next session's pickup point if resumed.
- **"Wall" mode: 3 videos decoding and playing simultaneously** (previous/current/next from
  a playlist, side by side, works the same in flat 2D and real VR) — proposed 2026-08-09,
  needs a real design pass before any code. Two purposes: a genuine way to preview/browse a
  playlist, and a stress test for how many concurrent NVDEC sessions and how much bandwidth
  this GPU can actually sustain. Only the video in the middle gets audio - moot until audio
  itself exists at all (still on this list, below). This is architecture work, not a tweak:
  today there is exactly one `Video360` instance (one decode thread, one staging ring, one
  texture set) - three concurrent means three full instances running in parallel plus a new
  multi-screen layout, not just calling existing code three times. Real, already-measured
  constraint to design around: **H.264 hits a hard 4096px-wide ceiling on this GPU's NVDEC**
  (`Video width 4320 not within range from 48 to 4096`, hit live 2026-08-09 by
  `leblon_vr180_meta.mp4`, fell back to software decode) - HEVC does not have this ceiling
  (matches the `stereo3d-pack --vr-size 2160` finding same session). Sourcing the wall from
  H.264 VR180/SBS content wide enough to hit that limit would silently degrade one lane to
  software before even adding the other two. Not started; suggested next step is a proper
  design session (Plan mode) before touching code.
- **Per-controller battery indicator** — a colored light (red/yellow/white) per controller,
  drawn at its actual tracked position, shown when a session starts. Investigated 2026-08-09
  whether the data is even available before promising anything - see
  `docs/03-controllers.md`, "Battery status" section, for the full technical finding.
  Short version: the raw battery byte is already parsed by the WMR controller driver
  (`wmr_controller_hp.c:277`) but never reaches OpenXR - two real changes needed in
  `~/vr/monado` before `hello_xr` could draw anything at all (wire the driver's own
  `get_battery_status`, then implement `XR_EXT_interaction_profile_battery_state_display`
  from scratch, which doesn't exist in Monado today). Deliberately bundled with real
  controller position (6DoF) tracking rather than tackled alone - a light drawn at a
  position isn't meaningful while controllers are still 3DoF-only. Not started; user's own
  call to defer both together.
- ~~Rapid next/prev presses collapsing into one advance~~ FIXED 2026-08-09
  (`0013-*.patch`, found live on a 13-file playlist): the next/prev request was a latched
  bool, so N quick presses collapsed into one advance, and each advance paid the full
  between-tracks hitch during which further taps were invisible to `xrSyncActions`. Now
  counted and coalesced — N presses become ONE `AdvanceTrackBy(net-delta)` jump with a
  single destroy/reopen hitch (modulo-normalized, negatives/over-wraps included; bad files
  skip forward one at a time). Presses landing fully *inside* a hitch are still lost
  (thread blocked in `vkDeviceWaitIdle`) — shrinking the hitch is future work. Built clean;
  **not yet verified live** (shipped mid-session; applies on next launch).
- ~~Loop-restart pacing bug~~ FIXED 2026-08-09 (`0008-*.patch`, NOT the zoom patch's fault —
  see also `docs/pruebas.jsonl` T099 for the first, incomplete diagnosis, and
  `BUG_player_loop_speedup_2026-08-09.md` in the `stereo3d-pack` repo for the write-up with
  real evidence that actually cracked it). Short clips played fine through the first loop,
  then blew up to a sustained ~3x speed right after the SECOND loop-restart and never
  recovered. Real cause: `loopOffset = lastPts + frameDuration` in `DecodeLoop()`'s
  EOF-restart path (`video360.cpp`) was a plain **assignment**, not an accumulation.
  `lastPts` is always the file's own raw, 0-based last timestamp — it naturally lands near
  the same value every loop, since the file is re-read from position 0 each time — so the
  assignment silently discarded every earlier loop's accumulated offset. From the second
  loop onward every loop reused the *exact same* pts window the previous loop had just
  finished catching up to, so its frames were stale the instant they were queued, the next
  EOF/seek/flush cycle fired almost immediately, then the next one even faster — dozens of
  loop-restarts per real second, not slow motion or a one-time jump. Fixed by accumulating
  (`loopOffset += ...`). The original T099 guess (bad `lastPts` at the EOF-flush drain) and
  the first fix tried (resetting `clockStarted` on automatic loop, mirroring the manual-seek
  path) were both real but insufficient on their own — confirmed by measurement: with only
  the `clockStarted` reset in place, the bug still reproduced almost identically. Kept that
  reset anyway as a smaller complementary fix (it discards wall-clock drift from the
  seek/flush itself, which the `loopOffset` fix doesn't address). Verified with live
  instrumented runs against the bug report's own repro clip
  (`stereo3d-pack/out/media_sbs_lowres.mp4`, 7.75s/30fps): 90s run, ~12 loop crossings, 44
  stat samples all 29.8–30.4 fps, decode steady at 30.1 fps with 0 renderer starves
  throughout, confirmed with the headset on too.

  **The report's second symptom (a vertical "rolling" artifact, same clip) is NOT this
  project's bug.** Same-day follow-up: confirmed live with the headset on that it survives
  the loop fix; ruled out `TransferDirect`'s NVDEC stride assumption by forcing
  `HELLO_XR_VIDEO_HW=0` (software decode, which repacks rows explicitly) — rolling still
  there, identical. Ruled out this player's Vulkan pipeline entirely by playing the same
  file in plain `ffplay` on the desktop, fully outside OpenXR/Vulkan — **same rolling
  artifact, confirmed by the user.** The defect is baked into the file itself, from
  `stereo3d-pack`'s own conversion — not something `video360.cpp`/`graphicsplugin_vulkan.cpp`
  can fix by definition, since a completely independent player reproduces it identically.
  Flagged back to the `stereo3d-pack` repo (`BUG_player_loop_speedup_2026-08-09.md`) rather
  than tracked further here.
- **Full-resolution native SBS from 4K sources, once `stereo3d-pack` has the test file ready
  (2026-08-09).** Finding from today's session: `--vr-size 2160` for VR180 output matches the
  headset panel exactly and decodes clean via NVDEC/HEVC (the format switch is automatic on
  output width, not a flag) — same mechanism that already proved clean tonight, zero errors,
  zero starves. Open question: does full SBS at native 4K width (7680px) decode equally
  clean now that the assumed H.264 ceiling may not actually apply? If yes, it's likely the
  better default over VR180 in general for content that stays local (VR180's equirect warp
  already documented above as wasting ~80% of the per-eye canvas — 694x1036 of 1920x1920).
  **Review this one carefully when it lands, don't rubber-stamp it** — check the `MODE:`
  banner picked the right projection/stereo, check `HELLO_XR_VIDEO_STATS=1` for a clean
  NVDEC/HEVC decode with 0 renderer starves same as tonight's clips, and this project's core
  rule still applies: a human has to actually look at it in the headset before it counts as
  verified, the same rigor as the loop-speedup and rolling-artifact bugs this session.
- Watch the `stereo3d-pack` material in the headset (prepared 2026-08-04, never seen inside the
  visor): `sbs` vs `vr180`, and calibrate depth with `-w`.
- Fourth detection criterion for flat SBS without metadata (see the `stereo3d-pack` section).
  The 90 Hz freeze is over (resolved 2026-08-06, `docs/19`) — this is unblocked, pending by
  priority only.
- ~~Video audio (silent today; decode→PipeWire + A/V sync)~~ IMPLEMENTED 2026-08-26
  (`0021-*.patch`, `HELLO_XR_AUDIO=1` — see "Stereo audio" above): built and linking clean,
  `pa_simple` confirmed reachable on this box; the decode/resample/sync path itself and every
  in-headset behavior (audible, A/V sync over a loop, pause, clean quit) still needs a human
  with the headset on before it counts as verified.
- Real zero-copy CUDA↔Vulkan (import the NVDEC surface as a Vulkan image, zero PCIe).
  Unnecessary today: we're already at full rate. This is THE optimization if 90Hz+8K demands more.
- YouTube "mesh" projection: our half-equirect is an approximation; if stretching is
  noticeable at the edges, adjust with `HELLO_XR_PANO_FOV` or implement the real mesh.
