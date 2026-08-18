# Frame-pipeline tracing with Monado's built-in Tracy backend

Sources read for this document: `~/vr/monado-tracing` (isolated worktree of `~/vr/monado`,
branch `lab-full`, `c5b8bbeb6`) — `src/xrt/auxiliary/util/u_trace_marker.{c,h}`,
`CMakeLists.txt` (tracing options), `cmake/FindPercetto.cmake`,
`src/external/CMakeLists.txt` (vendored Tracy client), `src/external/tracy/COMMIT`,
`doc/tracing.md`, `doc/tracing-tracy.md`, `doc/tracing-perfetto.md`,
`src/xrt/compositor/main/{comp_compositor,comp_renderer,comp_target_swapchain}.c`,
`src/xrt/auxiliary/util/{u_pacing_app,u_pacing_compositor,u_pacing_compositor_fake}.c`,
`src/xrt/ipc/{client/ipc_client_compositor.c,server/ipc_server_handler.c}`,
`src/xrt/ipc/CMakeLists.txt`, `src/xrt/targets/{service,openxr}/CMakeLists.txt`. Also
`wolfpld/tracy` upstream at tag `v0.9.1` (the exact commit Monado vendors), cloned to
`~/vr/tracy-profiler` for the viewer/capture tooling, and `~/vr/jack-in-wayland.sh` (the
lab's launcher, read in full to build the tracing variant below).

No file inside `~/vr/monado`'s working tree (the production checkout) or its `build/` was
touched. All of this lives in a separate worktree and separate binaries.

## 1. What tracing support exists in Monado

Monado has two compile-time-exclusive tracing backends (`CMakeLists.txt:523`, "Max one
tracing backend"):

- **Percetto/Perfetto** (`XRT_HAVE_PERCETTO`) — traces render as a Perfetto protobuf,
  viewable at `ui.perfetto.dev`. Requires building and installing Percetto *and* a release
  build of Perfetto yourself (`cmake/FindPercetto.cmake` looks for a system/pkg-config
  install; neither `percetto` nor `perfetto` exists in Debian's apt — confirmed via
  `apt-cache search`, both empty), running Perfetto's own `traced`/`traced_probes` daemons,
  and exporting `XRT_TRACING=true` at runtime (`u_trace_marker.c:23`, a
  `DEBUG_GET_ONCE_BOOL_OPTION` gate that is a **no-op under the Tracy backend** — see below).
- **Tracy** (`XRT_HAVE_TRACY`) — Monado **vendors the entire Tracy client** in-tree at
  `src/external/tracy` (pinned to upstream tag `v0.9.1`, see `src/external/tracy/COMMIT`)
  and compiles it into a static lib, `xrt-external-tracy`
  (`src/external/CMakeLists.txt:157-164`). Building it needs **nothing beyond what a normal
  Monado build already needs** — no new apt packages, no daemon, no network access at build
  time. The client is single-instance-per-process, always-on (see §7 on overhead), and
  listens for a *viewer* to connect directly over TCP.

Both backends are gated by the same top-level switch, `XRT_FEATURE_TRACING`
(`CMakeLists.txt:306`), and both instrument the same call sites via a shared macro layer in
`u_trace_marker.h` (`COMP_TRACE_MARKER()`, `DRV_TRACE_MARKER()`, `IPC_TRACE_MARKER()`,
`XRT_TRACE_MARKER()`, `SINK_TRACE_MARKER()`, `TRACK_TRACE_MARKER()`, etc. — one family per
subsystem, 121 files, 500+ call sites in this tree). With no backend enabled these all
compile to nothing (`u_trace_marker.h:186-236`).

**Percetto was not attempted.** It needs a from-source build of Perfetto (which itself
pulls a large dependency chain via Google's own fetch tooling) plus Percetto on top, with no
Debian package for either — a much heavier, riskier lift than the disk budget on this box
warranted (9.9 GB free at the time of this build, see §8). Tracy was chosen because it is
**already fully vendored and builds with zero extra dependencies**, and because it directly
satisfies the "viewable in ui.perfetto.dev or Tracy viewer" requirement via its own half of
that either/or. The one real cost of this choice is documented honestly in §4: one specific
class of compositor-side timing detail is Percetto-only.

## 2. What was built

Isolated worktree, detached at the exact production commit, its own build directory:

```
git -C ~/vr/monado worktree add --detach ~/vr/monado-tracing c5b8bbeb6
```

(`lab-full` itself could not be checked out a second time — already checked out at
`~/vr/monado`, hence `--detach` at the same SHA rather than a second branch checkout. This
is source-identical to what `~/vr/monado` is currently running.)

Configured with the exact flag set the production `~/vr/monado/build` uses (read from its
`CMakeCache.txt`: full driver set, `XRT_FEATURE_SLAM=ON`, `XRT_FEATURE_SERVICE=ON`,
Wayland/DRM-lease compositor, etc. — see the cache for the complete list), plus the two
tracing flags:

```
cmake -GNinja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -D... <all the driver/feature flags matching production> ... \
  -DXRT_HAVE_TRACY=ON -DXRT_FEATURE_TRACING=ON \
  ~/vr/monado-tracing
ninja -j6   # in ~/vr/monado-tracing/build
```

Configure output confirmed `PERCETTO: <blank, not found>` and `TRACY: ON`,
`FEATURE_TRACING: ON`. Build finished clean, 661/661 targets, no errors
(`~/vr/monado-tracing/build/build.log`). Result:

```
~/vr/monado-tracing/build/src/xrt/targets/service/monado-service       137 MB, RelWithDebInfo, not stripped
~/vr/monado-tracing/build/src/xrt/targets/openxr/libopenxr_monado.so    38 MB  (client-side runtime, see §5)
~/vr/monado-tracing/build/openxr_monado-dev.json                        manifest for the above
```

`ldd` on the service binary shows no new runtime dependency versus the production binary —
Tracy is statically linked in.

### The naming trap, and how it's defused

`~/vr/jack-in-wayland.sh` (and every teardown/hygiene path in it) manages the service by
**exact process name**, `pgrep -x monado-service` (a hard-won fix from 2026-08-17, after an
earlier `-f` match killed the invoking agent's own shell — see the script's own comments).
Our tracing binary's `comm` (`/proc/PID/comm`, capped at 15 bytes by the kernel) would
**also read `monado-service`** if launched under that literal path — meaning the
production launcher's teardown, and its own pre-launch `kill -9` hygiene, cannot tell our
tracing binary apart from the real one and would kill either indiscriminately.

Fix: a symlink under a longer name, so the kernel-truncated `comm` differs:

```
ln -sf ~/vr/monado-tracing/build/src/xrt/targets/service/monado-service \
       ~/vr/monado-service-tracing
```

Verified live (with a harmless `/bin/sleep` symlinked the same way, not the real binary,
while the production `monado-service` — PID 587392 at the time — kept running undisturbed
throughout): a process executed as `monado-service-tracing` reports `comm` =
`monado-service-` (the first 15 bytes, note the trailing hyphen) — **not** equal to the
14-byte string `monado-service`, so `pgrep -x monado-service` correctly does not match it,
and `pgrep -x monado-service-` correctly does.

`~/vr/jack-in-wayland-tracing.sh` is a copy of the production launcher
(`scripts/jack-in-wayland-tracing.sh` also committed to this repo, mirroring the existing
`scripts/` ↔ `~/vr/` sync convention) with exactly three changes, everything else — the
panel pre-activation, DP polling, `systemd-run --scope` login-session fix, `XRT_NO_STDIN`,
mode/tracking argument handling — left untouched and reused as-is:

1. `SERVICE="$VR/monado-service-tracing"` instead of the production build path.
2. Every `pgrep -x monado-service` → `pgrep -x monado-service-` (6 occurrences: the `down`
   handler, its wait/escalate loop, pre-launch hygiene, and the two failure-path cleanups).
3. `LOG="$VR/jack-in-wayland-tracing.log"` — a separate log file, so a tracing run's log
   never overwrites or interleaves with a production run's `jack-in-wayland.log`.

**What this does and does not solve.** It prevents *accidental cross-script kills* — running
`jack-in-wayland.sh down` while a tracing capture is up leaves it running, and vice versa.
It does **not** allow both to run at once: both binaries bind the same fixed IPC socket
(`$XDG_RUNTIME_DIR/monado_comp_ipc` — intentionally identical, this is what lets an
unmodified game process using the production `XR_RUNTIME_JSON` transparently talk to
whichever server is actually up), and only one process can hold the headset's USB/DRM lease
at all. **A tracing session is a swap, not an addition**: stop production, run tracing, stop
tracing, resume production.

## 3. Launching a tracing session

```bash
# 1. Stop the production session (coordinate with whoever's wearing the headset first —
#    this is a full teardown, same as any other jack-in-wayland.sh down).
~/vr/jack-in-wayland.sh down

# 2. Launch the tracing binary through the same proven sequence, same argument contract
#    as the production script (action mode tracking, any order; see --help). Example,
#    matching the current default lab session:
~/vr/jack-in-wayland-tracing.sh dev 1 6dof

# 3. Play normally. The game/Steam launch is UNCHANGED -- it keeps using the production
#    XR_RUNTIME_JSON and talks IPC to whichever server is listening on the shared socket,
#    which is now the tracing binary. Nothing about the app-launch step needs to change
#    for server-side (compositor + driver + SLAM) tracing.

# 4. When done capturing (see #4 below for *when* to attach the viewer):
~/vr/jack-in-wayland-tracing.sh down

# 5. Resume the production pipeline:
~/vr/jack-in-wayland.sh up 1 6dof
```

`jack-in-wayland-tracing.sh`'s own `--verbose`/`dev` output and `jack-in-wayland-tracing.log`
tell you the same "found display mode" / "Using builder wmr" success signals the production
script's own hard-won checks rely on (docs/06's "verification is physical" rule still
applies to the panel itself, unchanged by any of this).

## 4. Capturing a trace

Tracy's client needs **no daemon on the traced side** — confirmed live with a standalone
harness (`ZoneScoped` + `TracyPlot` loop, linked against the exact same
`libxrt-external-tracy.a` this build produced, source at
`/tmp/.../scratchpad/tracy_smoke.cpp` if it's still around, not part of the deliverable): the
process opens a TCP `LISTEN` on `*:8086` and a UDP broadcast socket **the instant it
starts**, with no setup step. `ss -tlnp | grep 8086` while `monado-service-tracing` is
running is the sanity check that it's alive and traceable.

**To view live, or capture headlessly, you need the separate Tracy *profiler/capture*
tooling** — this is a viewer, not part of Monado, and was **not built** in this session
(see §8 for why). Source is already vendored and version-pinned for you though:

```bash
# Already done, source is at ~/vr/tracy-profiler, tag v0.9.1 -- matches the Tracy
# COMMIT pinned in ~/vr/monado-tracing/src/external/tracy exactly, so the wire
# protocol is guaranteed compatible. No need to re-clone.
```

Two build targets, two different dependency footprints (checked against this box's apt
cache, not installed):

- **Full GUI profiler** (`~/vr/tracy-profiler/profiler/build/unix`) — live view, zoom,
  flame graph, plot overlays. Needs `libfreetype-dev` and `libcapstone-dev` (both **not**
  currently installed; everything else the Makefile's `pkg-config` list asks for —
  `wayland-egl`, `wayland-cursor`, `egl`, `xkbcommon`, `dbus-1` — **is already installed**
  on this box, it's the same Wayland/EGL stack the VR pipeline itself uses). The default
  build uses the XDG desktop-portal file picker (`dbus-1`) rather than GTK, so
  `libgtk-3-dev` is not needed:
  ```bash
  sudo apt install libfreetype-dev libcapstone-dev
  make -C ~/vr/tracy-profiler/profiler/build/unix release
  # binary lands at ~/vr/tracy-profiler/profiler/build/unix/Tracy-release
  ./Tracy-release   # shows a "discovered clients" list (from the UDP broadcast) --
                     # click the lab machine's monado-service-tracing entry, or type
                     # 127.0.0.1:8086 to connect directly.
  ```
- **Headless `capture` CLI** (`~/vr/tracy-profiler/capture/build/unix`) — connects, records
  to a `.tracy` file, no display needed. Only needs `libcapstone-dev` (freetype2 is a GUI-only
  dependency). This is the better fit for "record on the lab box, look at it on the everyday
  machine" — matches how this project already treats the lab box as disposable/minimal:
  ```bash
  sudo apt install libcapstone-dev
  make -C ~/vr/tracy-profiler/capture/build/unix release
  # binary: ~/vr/tracy-profiler/capture/build/unix/capture-release
  ~/vr/tracy-profiler/capture/build/unix/capture-release -o session.tracy -a 127.0.0.1
  # Ctrl-C (or -s <seconds>) to stop; session.tracy is a self-contained trace file,
  # copy it anywhere and open it with the full GUI profiler built on any machine.
  ```

**When to attach the viewer matters** (see §7): connect it as close to the start of the
capture window as you can, because without `TRACY_ON_DEMAND` (not defined in this build —
see §7) the client is already buffering everything from process start, viewer or not.

### Getting client-side (app) spans too — optional, untested

Everything above captures the **server side**: compositor, WMR/SLAM driver zones, and the
server-side IPC handlers (`ipc_handle_compositor_predict_frame` /
`_wait_woke` / `_begin_frame` / `_discard_frame` / `_layer_sync`, in
`ipc_server_handler.c`) — this is where the historically-implicated cost has always lived
(docs/44, T162-T203: Basalt/SLAM, the compositor render loop, the WMR read thread). The
actual `xrWaitFrame()` call made **by the game process** (`ipc_compositor_wait_frame` /
`ipc_compositor_end_session`, `ipc_client_compositor.c`) lives in a different translation
unit that is linked into `libopenxr_monado.so` — the **client**-side OpenXR runtime shim a
game loads, not into `monado-service` (confirmed via `src/xrt/ipc/CMakeLists.txt`: `ipc_client`
is a separate static lib linked only into `${RUNTIME_TARGET}`, i.e. `src/xrt/targets/openxr`).

To also get that side, point the *game's* runtime at the tracing build instead of
production for that one run:

```bash
XR_RUNTIME_JSON=~/vr/monado-tracing/build/openxr_monado-dev.json IPC_IGNORE_VERSION=1 <app> --graphics Vulkan2
```

Both processes are the same tracing build, so there's no client/server tracing-protocol
mismatch to worry about. Each process's Tracy client independently tries to bind `8086`; by
default (`TRACY_PORT` unset) each one **searches upward from 8086** if the port is taken
(confirmed by reading `TracyProfiler.cpp`'s `dataPortSearch` path — the actual bound port
rides along in the discovery broadcast, so the profiler's client list shows both without any
manual port bookkeeping). **This combination was not tested live** — no hardware capture
was performed in this session (see §6) — treat it as a documented next step, not a verified
recipe, and don't be surprised if Steam's own launch-option plumbing needs adjusting to get
`XR_RUNTIME_JSON` through to the actual game process.

## 5. Reading a trace: what the key spans mean

Most of Monado's markers are bare `COMP_TRACE_MARKER()` / `DRV_TRACE_MARKER()` /
`XRT_TRACE_MARKER()` — these expand (Tracy backend) to `ZoneScoped`, which names the zone
after the **C function it's in**, so the Tracy timeline reads as real function names with
real wall-clock begin/end times, already enough to see which stage of a frame ran long.
Representative call sites relevant to a pacing miss (all confirmed present, function names
from the actual source, not guessed):

**Compositor (server, `comp_compositor.c` / `comp_renderer.c` / `comp_target_swapchain.c`)**
— this is the render loop, one thread, in `monado-service`:
- `compositor_predict_frame` — the wait_frame-equivalent: what the compositor tells the app
  to expect.
- `compositor_mark_frame` — frame timing marks (wake/begin/deliver/gpu-done bookkeeping).
- `compositor_layer_commit` — the app's submit landing.
- `renderer_wait_for_last_fence`, `renderer_acquire_swapchain_image`,
  `renderer_submit_queue`, `dispatch_graphics` / `dispatch_compute`,
  `renderer_present_swapchain_image`, `comp_renderer_draw` — the actual per-frame Vulkan
  work, each its own zone; a one-slot miss usually shows up as one of these running long,
  or a gap *between* consecutive zones on this thread (idle time nothing else explains).
- `vblank_event_func` (`comp_target_swapchain.c`) — vsync/present-timing callback.

**IPC boundary (server side, `ipc_server_handler.c`)** — the compositor's view of what the
app is doing, one call per IPC round-trip:
`ipc_handle_compositor_predict_frame`, `_wait_woke`, `_begin_frame`, `_discard_frame`,
`_layer_sync[_with_semaphore]`. A gap between `_predict_frame` and the next `_wait_woke` is
the app's own CPU+wait time as seen from the server side, even without client-side tracing.

**Client-side plots** (`u_pacing_app.c`, instantiated server-side per connected app in
`comp_multi_system.c` — despite the name, this runs in `monado-service`, no client-side
build needed): four `TracyPlot` time series per frame, directly answering "which stage
stole the time" at a glance without reading zone durations by hand —
`App CPU(ms)` (predicted-wake to render-begin), `App Draw(ms)` (begin to delivered),
`App GPU(ms)` (delivered to GPU-done), `App Frame(ms)` (total), plus `App Wake Diff(ms)`
and `App Frame Diff(ms)` — signed error against what was *predicted*, so a spike here
directly is the "missed the slot by N ms" number, no arithmetic needed.

**Driver / SLAM** (`DRV_TRACE_MARKER()` in `src/xrt/drivers/wmr/*.c`, 57 call sites;
`XRT_TRACE_MARKER()` / `XRT_TRACE_IDENT(slam_push)` in `t_tracker_slam.cpp`) — the WMR read
thread and Basalt hand-off, correlatable on the Tracy timeline against the compositor
thread above to see whether a stall started upstream (driver/SLAM) or downstream
(compositor/present).

**What Tracy does *not* give you, and Percetto would** (`u_pacing_compositor.c`'s
`do_tracing`, the real per-frame compositor pacer, is wrapped entirely in
`#ifdef U_TRACE_PERCETTO` with **no Tracy branch at all** — read directly in the source, not
inferred): the compositor-side named sub-spans "sleep / oversleep / gpu / gpu-time-travel /
margin / slippage / run-ahead / info / earliest / predicted / vsync" as their own dedicated
Perfetto tracks. Under Tracy you only get this indirectly, via the `App *(ms)` plots above
plus the raw compositor zone durations — usually enough to *find* the thief function, but
not as pre-digested as Percetto's own "slippage" vs "run-ahead" classification would be. If
this build's picture turns out ambiguous, that's the concrete reason to revisit Percetto
despite its build cost.

## 6. Validation performed (no hardware touched)

A monado-service process **was live and in active use throughout this build** (PID 587392,
`/home/iam/vr/monado/build/...`) — confirmed before starting and re-confirmed untouched
afterward. Nothing below connected to it, killed it, or shared any resource with it.

- **Static**: `nm` on the tracing binary shows 561 Tracy symbols (`___tracy_emit_*`,
  `___tracy_alloc_srcloc*`, etc.); `strings` finds every `App *(ms)` plot-name literal from
  `u_pacing_app.c` verbatim in the binary, and the Tracy protocol/version strings
  (`tracy::Profiler::*`, `TracyPrfH9`, etc.). `ldd` shows no new runtime dependency vs. the
  production binary (Tracy is statically linked).
- **Headless smoke test, zero Monado/hardware involvement**: a standalone C++ program
  (`ZoneScoped` + `TracyPlot` in a loop) compiled against this build's own
  `libxrt-external-tracy.a` was run for 5 seconds. `ss -tlnp` during that window showed it
  holding `LISTEN *:8086` and a UDP broadcast socket, both attributable to that PID by name
  — proving the vendored client actually initializes and opens the exact channel a viewer
  would connect to, end to end, without ever touching `monado-service`, the WMR driver, or
  the headset. Exercised the naming-truncation fact used for the `monado-service-tracing`
  symlink the same way, with a symlinked `/bin/sleep`, again with zero Monado involvement.
- **What was deliberately not done**: actually launching `monado-service-tracing` itself
  (any invocation risks probing/claiming the USB/DP devices the live session depends on),
  and building/running the Tracy viewer or capture tool (needs a `sudo apt install`, held
  back per the "don't install system-wide without need" instruction — see §8).

## 7. Overhead expectations

- **Per-zone cost**: Tracy's documented design target is on the order of tens of
  nanoseconds per zone push (lock-free per-thread queues) — not independently benchmarked
  on this pipeline in this session, no hardware run was performed.
- **Memory, the one real risk, confirmed from source**: Monado's Tracy integration does
  **not** define `TRACY_ON_DEMAND` (checked `src/external/CMakeLists.txt`'s
  `target_compile_definitions` — only `TRACY_ENABLE` is set). This means the client starts
  buffering zones **immediately at process start**, whether or not a viewer is ever
  connected, and keeps everything in memory until a viewer drains it. For a short capture
  window this is irrelevant; for an unattended multi-hour session (this project has run
  30-45+ minute sessions routinely) with nobody attached, memory grows unbounded for as
  long as the process runs. **Practical mitigation: attach the profiler or `capture` tool
  soon after launching `monado-service-tracing`**, not hours into a session — and don't
  leave a tracing build running unattended the way `docs/43`'s quiet/unattended mode does
  for production. This was not stress-tested; it's a source-level fact, not a measurement.
- **Disk**: the tracing build itself is 1.7 GB (`~/vr/monado-tracing/build`, RelWithDebInfo,
  not stripped) on top of the production build's 2.0 GB — 9.9 GB was free on `/` after both
  at the time of writing, worth checking again before a long session. A `.tracy` capture
  file's size scales with session length and zone density; not measured here (no capture
  was run), budget generously if planning an unattended-length capture given the point
  above.
- **CPU**: no measurement was taken (no hardware run). Tracy's own reputation is "safe to
  ship in production," but this project's own standing rule is not to trust that without
  checking on this specific pipeline — a first real capture should sanity-check `top`/CPU%
  on `monado-service-tracing` against the equivalent production baseline before trusting
  any timing conclusions drawn from it.

## 8. What was *not* installed, and why

Per instruction, apt packages were checked but not installed without a concrete need this
session actually had:

| Package | Needed for | Status |
|---|---|---|
| `percetto`, `perfetto` | Percetto backend | Not in Debian's apt at all; would need building from source |
| `libfreetype-dev` | Tracy **GUI** profiler | Available (`2.13.3+dfsg-1+deb13u1`), not installed |
| `libcapstone-dev` | Tracy GUI profiler **and** headless `capture` tool | Available (`5.0.7-1~deb13u1`), not installed |
| `libgtk-3-dev` | Tracy GUI profiler's GTK file picker (non-default; the portal/`dbus-1` picker is default and needs nothing extra) | Available, not needed |

Everything the Monado-side build itself needed was already satisfied by the existing lab
toolchain (Tracy is vendored; no new packages were required to build
`monado-service-tracing`). The two-package gap above only blocks *viewing/recording* traces
locally, not producing them — `monado-service-tracing` is already fully capable of being
traced by a viewer built on any other machine right now, using `~/vr/tracy-profiler`'s
already-vendored, version-matched source.

## 9. Cleanup

- Build products: `~/vr/monado-tracing` (worktree + `build/`, ~1.7 GB) and
  `~/vr/tracy-profiler` (vendored source, 33 MB, no binaries built) are left in place —
  they're the deliverable for the next hardware session. Remove with
  `git -C ~/vr/monado worktree remove ~/vr/monado-tracing` (only after
  `rm -rf ~/vr/monado-tracing` if `git worktree remove` complains about the build dir not
  being tracked) if this line of investigation is abandoned.
- `~/vr/monado-service-tracing` and `~/vr/jack-in-wayland-tracing.sh` are the launch
  surface for next time; harmless to leave in place, `rm` them if not needed.
- A `.tracy` capture file is self-contained — delete it once whatever it was for is
  resolved, same as any other log artifact from `docs/22`'s "log rotation" standing item.
- No system packages were installed, so there is nothing to uninstall.
- No daemon was started that needs stopping (Tracy has none; that's the whole point vs.
  Percetto's `traced`/`traced_probes`).
