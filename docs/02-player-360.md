# 02 — Player 360 (photos and video with NVDEC)

The player is `hello_xr` (OpenXR-SDK-Source, local branch `g2-360-viewer`) modified to
render an equirectangular skybox. The full patch series lives in
`patches/hello_xr-player/` (see its `README.md`). Base: OpenXR SDK 1.1.62.

## Build

```bash
cd ~/Documents/linux_vr_base/OpenXR-SDK-Source
cmake -B build -GNinja -DBUILD_TESTS=ON -DBUILD_API_LAYERS=OFF -DBUILD_CONFORMANCE_TESTS=OFF
ninja -C build hello_xr
```

(`hello_xr` lives under `src/tests/`, hence `BUILD_TESTS=ON`. It needs `libavcodec-dev
libavformat-dev libavutil-dev libswscale-dev` for the video path — if missing, it still
builds but with photos only. Audio additionally needs `libswresample` and `libpulse-simple`.)

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
or `~/vr`; `VR_BASE=` forces it). It wraps the player in `timeout` (default 300 s), so pass `-t`
for longer runs. In non-interactive mode the player gets a `sleep infinity` stdin keepalive via
process substitution (hello_xr treats stdin EOF as "end of run"); the wrapper kills that
keepalive after the run, because an orphaned one never notices its reader died.

### Controls

One list for all three input paths. The G2 controllers use the **`oculus/touch_controller`**
profile, not WMR (see `docs/03-controllers.md`, "The native `microsoft/motion_controller` profile never bound anything"): any new binding goes in that
block of `openxr_program.cpp` or it is dead on arrival. All three paths feed the same
`PlayerControl::` functions. When controllers connect, the player prints `Active profile
/user/hand/...` and the sources for each action: check that first for a dead button.

| Action | Keyboard (real terminal only) | VR controller (Touch) | Xbox 360 pad |
|---|---|---|---|
| Pause / resume | `space` | trigger, either hand (0.7/0.3 hysteresis) | A |
| Speed | `[` / `]` (0.125x-4x), `1` = normal | none | none |
| Seek -10 s / +10 s | `h` / `l` | thumbstick X, either hand (>0.7, re-arm below 0.3) | none |
| Step one frame back / forward (pauses first) | left / right arrow, or `<` / `>` | none | none |
| Zoom out / in | down / up arrow, or `v` / `^`; `0` = 1x | thumbstick Y, either hand (up = in) | none |
| Brightness down / up | `d` / `b`; `9` = 1x | right **B** / right **A** | none |
| Recenter (yaw only) | `enter` | grip squeezed hard, either hand (>0.7) | Start |
| Next / previous track | `n` / `p` | left **Y** / left **X** | RB / LB |
| Quit | `q` | **hold** left Menu ~1.5 s (red bar fills; releasing cancels) | hold Guide ~1.5 s |

Notes:

- Zoom steps multiplicatively by 1.15x, clamped to `[0.5, 4.0]`. Brightness is a plain
  multiplier (>1 brighter, <1 dimmer, 1.0 native). A/B exist only on the right Touch controller
  and not at all on `microsoft/motion_controller`, so brightness is Touch-only; the right Menu
  button does not exist on the Touch profile, hence Menu is left-only.
- Seek is absolute (`av_seek_frame`) on the decode thread (never from the render/input thread:
  `AVFormatContext` is not safe for that) and clamps to `[0, duration]`.
- If a dirty disconnect leaves the terminal mute: `stty sane`. In a pipe there are no keys and
  the run ends at stdin's EOF.
- The Xbox pad (`045e:028e`) is read as a Linux joystick (`/dev/input/jsN`, found through
  `/sys/class/input/jsN/device/id`, never a hardcoded node). It exists because Monado never
  re-probes for controllers after session start, so a session started with the VR controllers
  off has no controller input. Unlike the VR path it has real hotplug in both directions.
- Rapid next/previous presses are counted and coalesced into ONE `AdvanceTrackBy(net-delta)`
  jump (one destroy/reopen hitch, bad files skipped forward one at a time). Presses landing
  fully inside a hitch (the thread is blocked in `vkDeviceWaitIdle`) are still lost.
- Arrow keys are 3-byte escape sequences and `ESC` alone is the quit key: the key thread
  disambiguates with a 30 ms `poll()` after seeing `ESC`.

### On-screen feedback

There is no in-headset text rendering: everything is colored bars drawn in screen space inside
the skybox shader (no extra pass or pipeline).

- **Progress bar**: thin red marker over a lighter total-duration track, shown ~3 s after the
  last pause/speed/seek touch. Placed at `t` in `[0.58, 0.62]` and `s` in `[0.20, 0.80]`: the
  sharp, comfortable area of the G2's optics is clearly smaller than the nominal FOV, and bars
  near the edge were not visible. The **quit-hold bar** sits at `t` in `[0.30, 0.40]`.
- Both bars get a fixed 1.5 m HUD depth through a small-angle stereo parallax shift per eye
  (nominal half-IPD 31.5 mm); without it they read as glued to the lens at infinity against
  real stereo content.
- `HELLO_XR_THEME`: `night` (default) leaves the empty space outside the content black;
  `daylight` paints it light gray. The shader does `discard` outside the content so the app's
  clear color shows. Total black was once mistaken for "tracking died" on 360 content, but gray
  covered the entire rear 180 degrees of VR180 content, so black is the default.
- `HELLO_XR_ANY_KEY_QUITS=1`: any control also sets the quit flag (Menu's hold path is
  unchanged). It is meant for a short "controls legend" image shown before real content, and
  must be scoped to that phase only, never exported to the real playback.
- `HELLO_XR_DURATION_S` (patch 0020): internal graceful quit through the real quit-request path
  (a clean `END_SESSION`, unlike `timeout`'s SIGTERM); 0 = run forever.

## Projections and stereo (v3)

The player understands three projections — **360 equirect, VR180 half-equirect, flat**
(virtual screen) — each mono or stereo **side-by-side / over-under**. The eye
split is applied in the shader after the spherical mapping, so both eyes come from the same
decoded frame (a single upload per frame).

Detection matters because the layouts are ambiguous by dimensions alone: a 2:1 could be
360 mono **or** VR180 SBS, and getting it wrong looks "plausible but odd", not broken.
Resolution order (`ResolvePanoLayout()` in `projection360.cpp`):

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

VR180 3D was verified in the headset (2026-08-04).

### YouTube hides the VR streams

Same URL, different content: the normal client gets a flat monoscopic render
(3136x1764 in the measured example) and the `android_vr` client gets the real streams
(7680x4096 stereo "mesh"); in a `yt-dlp` format listing, `2160s60` = stereo, `2160p60` = flat.
Downside: `android_vr` doesn't accept cookies, so age-restricted videos only give the flat
version.

### Own content: 2D → 3D with `stereo3d-pack`

`stereo3d-pack` (a separate tool) converts ordinary monocular video into stereo (Depth Anything
V2 + DIBR, on GPU, ~3.5 fps at 1080x1920). It is the other source of stereo content for this
setup besides YouTube; its `tools/ver-en-casco.sh` calls `play360.sh` with the correct flags.

**Encode choice for flat/cinematic source: flat SBS beats VR180** (blind A/B, worn). The flat
SBS (4096x1152, i.e. 2048x1152 per eye) was clearly preferred over VR180 (3840x1920, 1920x1920
per eye) on resolution and on absence of geometric deformation. The flat SBS concentrates more
horizontal pixels per eye into a bounded screen and keeps the 16:9 framing; VR180 spreads a
similar pixel budget over a 180-degree dome (softer) and warps flat content onto a hemisphere.
With `--vr-fov 65` the content occupies only 694x1036 of a 1920x1920 per-eye canvas (19% of the
pixels, rest black). Reserve VR180 for material actually captured in 180 degrees.

`HELLO_XR_SCREEN_FOV` scales the 3D in flat mode: an SBS disparity is a fraction of the image
width, so angular disparity is that fraction times the apparent width in degrees. A bigger
screen means more depth and more fatigue without touching the file. For vertical 9:16 the
default 70 degrees makes the screen taller than the headset's FOV; the wrapper computes 47.

Detection of these outputs, as the player stands today:

| output | what it is | what the player detects |
|---|---|---|
| `--format vr180` + metadata | 3840x1920 equirect, `st3d`=2 + `sv3d/equi` bounds 0.25 | VR180 3D, by metadata |
| `--format vr180` without metadata | 3840x1920 | VR180 3D, by name + aspect |
| `--format sbs` | 2160x1920 (1080x1920 per eye) | **VR180 3D, wrong**: should be flat 3D; pass `-p flat -e sbs` |

## Known issues

- **Mixed-format / arbitrary-size playlists draw flat SBS content on a dome.** The fault is in
  `ResolvePanoLayout()` (`projection360.cpp`, the aspect-ratio fallback): once stereo is known
  from the filename but projection is not, the per-eye aspect is bucketed by a table tuned for
  camera-native footage (`>1.8` full 360 sphere, `1.4-1.8` flat, else VR180 dome) with no
  panoramic evidence. A stereo-packing signal alone must not imply a spherical projection. Seen
  on low-res SBS (1120x832, 960x852, 1504x416 shows as a "360" that wraps at the edges), on
  portrait-per-eye 4K SBS, and on square/2:1 mono photos. Not fixed. Planned fix, in order:
  (a) metadata first, and Stereo3D side-data present with Spherical absent means Flat;
  (b) filename tokens; (c) aspect ratio strictly last; (d) hard rule: with no independent
  panoramic signal (projection token, spherical metadata, or `AV_SPHERICAL_RECTILINEAR`),
  default to Flat, as YouTube does. Files from `stereo3d-pack` carry no container metadata at
  all. `ResolvePanoLayout` already runs per playlist entry; as a workaround pass `-p`/`-e`.
- **H.264 NVDEC ceiling.** This GPU's NVDEC rejects H.264 wider than 4096 px (`Video width 4320
  not within range from 48 to 4096`) and the player falls back to software decode; HEVC has no
  such ceiling. A 120 fps H.264 clip also failed `cuvidCreateDecoder` with
  `CUDA_ERROR_INVALID_VALUE` and fell back to software (fine for a short clip). A decoder
  failure *mid-playback* is not covered by `AdvanceTrackBy`'s skip-on-open-failure guard and
  can take the session down.
- **Between-tracks hitch.** Each track destroys and recreates the whole chain (a
  `vkDeviceWaitIdle` + realloc) because the next file may differ in resolution/projection.
- **No controller volume control.** Volume is only adjustable at the sink (`hmd-audio.sh set
  <pct>`); every input is already mapped, so a binding needs a modifier (for example grip held
  plus thumbstick Y). Photo mode has no confirmed playlist navigation.
- **Not verified live (worn)**: frame step, the Xbox pad's button dispatch, coexistence of the
  pad with a live VR-controller session, rapid-press coalescing, and going backward through a
  playlist. Everything else in the controls table was confirmed with the headset on.
- Audio: rate other than 0 or 1 is out of scope (audio plays at normal speed, no time-stretch).
- A vertical "rolling" artifact seen on one `stereo3d-pack` clip reproduces in plain `ffplay`
  and with software decode, so it is baked into the file, not a player bug.

## Stereo audio (`HELLO_XR_AUDIO=1`, patch 0021)

Plays the file's audio track through PipeWire, synced to video. Scope is narrow: **head-locked
stereo, no spatialization** (nothing this player plays is ambisonic). Verified in the headset
with `HELLO_XR_AUDIO=1` (log: `HELLO_XR_AUDIO on - 'aac' 44100 Hz -> 48000 Hz stereo S16,
head-locked`).

- **Unset means zero behavior change**: no thread, no audio codec, no `pa_simple` connection;
  audio packets are read and unref'd as before. The silent player must never gain risk.
- **Pipeline**: `Open()` finds the stream with `av_find_best_stream`, opens its own codec
  context and a `swresample` context normalizing anything to **S16LE / 48000 Hz / stereo**. A
  dedicated audio thread pulls packets from a second queue, decodes, resamples and blocks on
  `pa_simple_write()`; that blocking write is the pacing mechanism.
- **Audio is the master clock once active.** The thread counts stereo pairs written since an
  anchor in the file's pts timeline, subtracts `pa_simple`'s reported latency and publishes the
  result as an atomic; `AcquireCurrentSlot()` reads it lock-free as `playbackTime` (the render
  thread never calls `pa_simple`). It falls back to the wall-clock accumulator at startup and
  right after a loop seam or seek.
- **Loop / seek** raise an `audioResetPending` flag on a dedicated mutex/condvar pair so a busy
  audio thread never adds latency to the 90 Hz path; the audio thread drains its queue, flushes
  its codec and `pa_simple`, and re-anchors.
- **Pause** flushes `pa_simple` once on the transition, so audio stops immediately instead of
  playing out the server buffer.
- **Failure handling**: no audio stream, a codec/resampler that won't open, or an unreachable
  sound server each log one line and fall back to silent video. A demo must never die because of
  its audio.
- A file transcoded through `stereo3d-pack` may have lost its audio track: check with `ffprobe`
  before concluding a silent run is a bug.

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
| `HELLO_XR_FIXED_POSE=1` | ignores tracking — diagnostic (also used by the passthrough viewer, `docs/08-passthrough-limits.md`) |
| `HELLO_XR_AUDIO=1` | plays the file's audio track through PipeWire, head-locked stereo, synced to video |
| `HELLO_XR_THEME=night\|daylight` | color outside the content (default `night`, black) |
| `HELLO_XR_DURATION_S=N` | internal graceful quit after N seconds (0 = forever) |
| `HELLO_XR_ANY_KEY_QUITS=1` | any control also quits (legend phase only) |

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

Decisions that still hold: no swscale (YUV→RGB on GPU), sRGB texture with UNORM per-view write
(MUTABLE_FORMAT, gamma applied exactly once), 10-bit gets downconverted to 8-bit in the decode
thread.

**Push-constant budget.** The block is at Vulkan's guaranteed 128-byte limit, so new features
reuse spare slots instead of growing it: `mode.y`/`mode.z` carry the progress bar, `panoFov.z`
the zoom (`frag.glsl` divides the projection coordinate by it: the sphere or screen never
changes, only how much of it a ray picks up), `panoFov.w` the brightness (multiplied into
`FragColor.rgb` right after the texture sample, before the overlay bars so dimming never dims
the feedback), and spare bits of `mode.x` the eye index for the bars' stereo depth.

**Playlist**: each track destroys and recreates the whole chain (staging, planes, conversion
pass, skybox) because the next one may have a different resolution/projection. Wrap-around is
modulo (`(index ± 1) % count`) and was measured over several full cycles.

### Pitfalls fixed along the way

- **Controller-quit exit deadlock** (patch 0012). Quitting from the controller ended the XR
  session but the process never exited. Root cause (caught with `gdb -p`): the keyboard thread
  parks in `getchar()`, which holds stdin's `FILE` lock for the whole blocking read; `exit()`'s
  `_IO_flush_all()` then needs that lock. It was masked by `timeout`'s SIGTERM and by the old
  stdin-pipe EOF, and fake-pty keyboard tests never reproduce it. Fix: the key thread reads with
  raw `read(2)` (`ReadKeyByte()` in `main.cpp`). In the same dig, `~OpenXrProgram()` destroyed
  swapchain/session/instance with GPU work still in flight (the `vkFreeCommandBuffers` /
  `vkDestroySemaphore` "is in use" errors printed on every quit): `IGraphicsPlugin::
  WaitForGpuIdle()` now runs first in the destructor, and `PollActions()` latches
  `xrRequestExitSession()` itself when `QuitRequested()` goes true.
- **Loop-restart speed-up** (patch 0008). Short clips played fine through the first loop, then
  ran ~3x fast after the second restart. Cause: `loopOffset = lastPts + frameDuration` in
  `DecodeLoop()`'s EOF path was an assignment, not an accumulation, so every loop reused the same
  pts window and its frames were stale on arrival. Fix: `loopOffset += ...` (plus resetting
  `clockStarted` on automatic loop, a complementary fix that alone was insufficient).
- **Only the A/B/X/Y buttons are free on the Touch profile**; both thumbsticks carry seek (X)
  and zoom (Y), the trigger pauses, the grip recenters.

## Verification

With the headset on and `HELLO_XR_VIDEO_STATS=1`:
- "video upload: X frames/s" should match the file's fps, and "renderer starves" ≈ 0.
- "video decode:" should say `NVDEC direct-to-staging` (if it says `+ copy`, the direct
  transfer failed and it degraded on its own — functional but slower).
- The `MODE:` banner should match what the content actually IS.
- Visual 360: no band at the rear seam. VR180: black behind the shoulders, not
  repeated image. 3D: real depth (if it looks doubled, the eye split is wrong).

## Roadmap

- **Fourth detection criterion** for flat SBS without metadata: see "Known issues".
- **Gallery/browse mode for playlists**: page through files one at a time as a paused real
  decoded frame with a counter (single-item navigation, no thumbnail grid). Not started.
- **"Wall" mode**: previous/current/next decoding simultaneously, side by side. Architecture
  work, not a tweak: today there is one `Video360` instance (one decode thread, one staging
  ring, one texture set). Design around the H.264 4096 px NVDEC ceiling above.
- **Full-resolution native SBS from 4K sources** (7680 px wide): untested whether it decodes
  clean via HEVC; likely a better local default than VR180 if so. Check the `MODE:` banner and
  `HELLO_XR_VIDEO_STATS=1`, and look at it in the headset.
- **Per-controller battery indicator**: the raw battery byte is parsed by the WMR controller
  driver, and `get_battery_status` is wired by Monado patch 0040 and exposed through `libmonado`.
  The remaining gap is `XR_EXT_interaction_profile_battery_state_display` in Monado's OXR layer
  (not implemented), see `docs/03-controllers.md`, "Battery status".
- **Controller volume** (vertical bar mirroring the seek bar) and **photo-mode playlist control**.
- Real zero-copy CUDA↔Vulkan (import the NVDEC surface as a Vulkan image). Unnecessary today
  (full rate already); the optimization to reach for if 90 Hz + 8K demands more.
- YouTube "mesh" projection: our half-equirect is an approximation; if edge stretching is
  noticeable, adjust with `HELLO_XR_PANO_FOV` or implement the real mesh.
