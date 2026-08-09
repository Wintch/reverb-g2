# 25 — Standalone app research: the OpenXR toolbox

> Desk research, 2026-08-09, run as 5 parallel research agents + 1 synthesis agent with web
> search, verified against primary sources where possible (real LICENSE files, Monado's real
> CMakeLists via a GitHub mirror, GitHub/crates.io APIs). **Nothing here has been verified
> with the headset on** — the project's golden rule applies before acting on any of it.

The question: what already exists to avoid reinventing **text rendering, UI, animation and
shader tooling** when building the future standalone VR app — given this exact stack (Linux +
Monado + NVIDIA/Vulkan + the NVDEC zero-copy pipeline already working at 8K60 in the modified
`hello_xr`)?

## The verdict: don't switch stacks — the standalone app is a hello_xr that grows

The NVDEC zero-copy pipeline is the hardest-won, most-verified piece of the whole project.
None of the five researched paths offers a *proven* way to wrap it without real friction:

- **Godot 4.x** has the best-documented Monado support (its own docs list "Linux (SteamVR,
  Monado)" — the only general engine saying so) and a built-in **Equirect** composition layer
  node that maps directly onto this project's 360° use case. The hook for external VkImages
  exists and was verified in source (`RenderingDevice.texture_create_from_extension()`) —
  but it's only reachable from a C++ GDExtension, nobody has verified it against this stack,
  and it means swallowing an entire scene/node paradigm. Best-credentialed full-engine
  candidate, still an unverified bet on the one piece that's most expensive to rebuild.
- **StereoKit** names Monado in its own README, is active (push 2026-08-06), has text/UI
  built in, and its native `sk_gpu.h` exposes `skg_tex_create_from_existing()` — but it
  lives in permanent 0.4.0 previews with no stable release since 0.3.11 (mid-2024). Real
  maintenance risk.
- **Rust (openxr-rs + ash)** is the single best-evidenced finding: it is *hardware-verified
  in this exact lab* — xrizer runs precisely that combination against this same Monado
  (`openxr 0.19` pinned to a git rev, raw handles via `.as_raw()`). But that proves the
  layer that already works in C++ (session/interop), not the missing ones. No published Rust
  project has solved NVDEC→Vulkan zero-copy; `ffmpeg-next` exposes the same raw structs
  (same unsafe FFI, different language, no shortcut). Even the closest real Rust precedent,
  WlxOverlay-S, uses neither wgpu (it uses vulkano) nor egui-in-scene (draws its UI by hand).
- **wgpu is ruled out outright** for this app: no official OpenXR integration (gfx-rs/wgpu
  issue #602 still open), the canonical example archived since 2022, and neither of the two
  real Monado-on-Linux projects (xrizer, WlxOverlay-S) chose it. Immaturity bought, nothing
  gained, on a Vulkan/NVIDIA/Linux-only project that needs no portability.
- **hotham** is out by its own FAQ ("almost exclusively for the Oculus Quest 2", no desktop
  Linux/Monado mention, slowing cadence).

**External validation for staying hand-rolled:** WlxOverlay-S — the closest real
Linux+Monado precedent — independently rewrote its earlier StereoKit-based version to pure
Vulkan, explicitly citing NVIDIA+EGL pain on Linux: the same class of pain this project
already documented with Plasma/kwin (docs/20).

## Proposed architecture: current core + 3 new layers, all hand-rolled C++/Vulkan

1. **Core (untouched):** OpenXR session loop, stereo projection swapchain, NVDEC→CUDA→Vulkan
   zero-copy pipeline stay exactly as they are.

2. **Text/UI — composition layers, not the main projection layer:**
   - Glyph atlas via `stb_truetype` (same stb family already vendored for images; zero new
     dependencies), rasterized to a bitmap, minimal dedicated Vulkan pipeline (quad per
     glyph, one texture, alpha blend), submitted as `XR_TYPE_COMPOSITION_LAYER_QUAD` —
     **core OpenXR 1.0, no extension needed**.
   - Why a separate layer: its swapchain resolution is independent of the 3D render (text
     doesn't pay the 8K video's cost), and it skips the double resampling (scene composition
     + lens distortion) that blurs text living inside the eye-buffer.
   - Verified in Monado's real CMakeLists (via GitHub mirror — **reconfirm against
     `~/vr/monado`**, this project already lived through binary-vs-source drift once): the
     main compositor truly supports `cylinder` and `equirect2`, but `cube` and `equirect1`
     are build-blocked (`FATAL_ERROR` if forced). `cylinder` is the real option if a curved
     wrap-around menu is ever wanted.
   - Scaling path if stb_truetype aliases on close-up panels: swap the atlas to MSDF
     (`msdfgen`/`msdf-atlas-gen`, MIT — verified from their actual LICENSE files, offline
     generation only, FreeType never enters the runtime binary). Atlas + fragment shader
     change; architecture doesn't.
   - Dear ImGui only when real interactive widgets are needed (buttons/sliders/lists):
     official `imgui_impl_vulkan` backend rendering off-screen to the same quad-layer
     texture, input translated by hand from the existing OpenXR actions. **No public
     example joins ImGui+Vulkan+OpenXR quad layer end-to-end** (GitHub search: zero repos)
     — budget it as real integration work, not "install a library". Note Monado itself
     already vendors ImGui for its `XRT_DEBUG_GUI=1` desktop GUI, so the toolchain here
     demonstrably builds it. (Also: PlutoVR/imgui_vr is a verified false positive — one
     trivial commit, no VR code.)

3. **Animation — no heavy library:**
   - `Tweeny` (single header, MIT, active — push 2026-08-03) for fixed-duration transitions.
   - Hand-written critically-damped spring parameterized by halflife (~30-40 lines,
     reference: Daniel Holden's Spring-It-On) for anything continuously chasing the user:
     hand/head-anchored panels, settling after a recenter. Closed-form, framerate-
     independent, the industry standard for comfortable VR UI motion.
   - Choreograph rejected: more conceptual weight than needed, maintenance semi-stalled.

4. **Shader tooling — productivity, not new architecture:**
   - `shaderc` for runtime GLSL→SPIR-V (already packaged on this Debian 13:
     `apt install libshaderc-dev` — zero source builds; glslang-dev also packaged).
   - Own includer via `shaderc::CompileOptions::SetIncluder` + `GL_GOOGLE_include_directive`
     to share the equirect/VR180 projection helpers between shaders.
   - Hot-reload via inotify (Linux-only is fine here): dirty flag checked at frame start,
     new pipeline built, **old one destroyed only after a fence confirms the GPU is done
     with it** — the concrete risk is stalling the live 8K60 pipeline.
   - Specialization constants for fixed variants (360/VR180/flat, mono/stereo, quality
     tiers); push constants for per-frame data (time, eye index, small matrices).
   - Porting Shadertoy-style effects to VR: replace `iResolution` camera math with the real
     per-eye `XrView` matrices, split any screen-space pass per eye, and skip motion
     blur/chromatic aberration/dynamic FOV unless comfort-validated in the headset.
     `VK_KHR_multiview` if a heavy effect ever eats the 90Hz budget — measure first
     (and check whether the current renderer already uses it; not investigated).

## Quick wins adoptable in the CURRENT player

- Real text instead of colored bars: stb_truetype + atlas + quad layer (core OpenXR). The
  player's #1 gap, and the lowest-friction path of everything researched.
- `sudo apt install libshaderc-dev` now; wire includer + inotify hot-reload over the
  existing hand-rolled shaders.
- Tweeny for the transitions already wanted (panel fades, menu appearance).
- The ~40-line critical spring for UI that follows the user / settles after the
  `patches/xrizer/0001` recenter.
- Split specialization vs push constants in the current projection shader — cheap cleanup.
- Try `XR_KHR_composition_layer_cylinder` (confirmed in Monado's main compositor) for a
  curved settings panel without waiting for the full standalone app.
- Read `xr-video-player` (codeberg.org/yoshino/xr-video-player) — the only project found
  whose own README claims validation against Monado's WMR driver in git, the same driver
  this lab runs. Reference for session/swapchain architecture (its decode is mpv-based, not
  NVDEC zero-copy — verify before citing our advantage publicly, though no source mentions
  hw decode in it or in mpv-xr).

## What else the ecosystem scan found

- **The "DeoVR for Linux" gap is real**: DeoVR/Skybox have no Linux ports and no FOSS
  equivalents. The only OpenXR-native Linux players found are `xr-video-player` and
  `mpv-xr` (sourcehut blocked scraping — clone before citing details), both libmpv-based.
  VLC's 360° support on Linux is confirmed broken/absent. If the standalone app ships, it
  genuinely fills a hole.
- **Stardust XR** (Rust XR display server on Monado) documents a Lanczos filter for keeping
  text legible under perspective warp — technique worth citing, not embeddable code.
- **WlxOverlay-S patterns worth stealing:** laser-pointer interaction with per-click-type
  colors; PipeWire screen capture zero-copy on Wayland; hand-drawn bitmap-font UI directly
  on Vulkan.
- **Vulkan Video decode** (`VK_KHR_video_decode_queue`, the CUDA-free future path): the only
  Rust crate is a single-frame proof of concept; not usable today. Recheck in 6-12 months.
- **GStreamer + its `vulkan` plugin / DMA-BUF import** as an alternative decode path: left
  under-verified (research budget ran out) — pending a check on this machine before any
  conclusions.

## Ranked alternatives (if the recommendation is revisited)

| Option | Status | One-line tradeoff |
|---|---|---|
| Godot 4.x | Worth a bounded spike | Best-documented Monado support + built-in Equirect node; NVDEC bridge via GDExtension unverified; whole paradigm swallow. Spike = minimal GDExtension showing one decoded frame in the headset, a few days, before any commitment. |
| StereoKit | Escape hatch | Smallest mental jump from current C/Vulkan; permanent-preview release state since 2024 is a real maintenance risk. |
| Rust incremental | If growing Rust fluency is itself a goal | Session/input in Rust (xrizer's proven pattern), video core stays C++ behind FFI; doesn't solve text/UI/animation any better than C++. |
| Bevy + bevy_mod_openxr | Watch list | Cleanest documented Vulkan interop hook (`wgpu_hal texture_from_raw`); no composition layers yet; Monado never specifically confirmed. |
| hotham | Rejected | Its own FAQ: Quest 2 almost exclusively. |
| VLC / DeoVR / Skybox | Rejected | Broken or nonexistent on Linux/FOSS. |

## Risks / verification debt

- Zero headset verification in any of this — desk research only.
- Monado composition-layer flags checked against a GitHub mirror, not the canonical repo
  (gitlab.freedesktop.org blocks automated fetch) and not this lab's checkout — `grep` the
  real `~/vr/monado` before depending on them.
- Confirm at runtime (`xrEnumerateInstanceExtensionProperties`) that assumed extensions are
  enabled in the exact lab binary before writing code against anything non-core.
- inotify hot-reload can stall or desync the live 8K60 pipeline if the old pipeline is
  destroyed before its last in-flight frame's fence.
- A Rust rewrite of the video pipeline has no known shortcut — nobody has published
  NVDEC→Vulkan zero-copy in Rust.
- egui composited inside an XR scene has no verified precedent against Monado — budget as a
  spike if ever considered.
- The research agents' web-search budget ran out mid-session; the second half was verified
  via direct fetches of primary sources (LICENSE files, CMakeLists, GitHub/crates.io APIs).
  O3DE, Magnum, Filament and Diligent were never evaluated. hotham's last-push date came
  from the GitHub API (2026-04-28) after a cached page render suggested an older date.

## Key sources

Frameworks: [StereoKit](https://stereokit.net/) ·
[sk_gpu](https://github.com/StereoKit/sk_gpu) ·
[Godot OpenXR](https://godotengine.org/article/godot-openxr-support/) ·
[Godot RenderingDevice](https://docs.godotengine.org/en/stable/classes/class_renderingdevice.html) ·
[Godot composition layers](https://docs.godotengine.org/en/stable/tutorials/xr/openxr_composition_layers.html) ·
[hotham FAQ](https://github.com/leetvr/hotham/wiki/FAQ) ·
[bevy_mod_openxr](https://github.com/awtterpip/bevy_oxr) ·
[wgpu-hal texture_from_raw](https://docs.rs/wgpu-hal/latest/wgpu_hal/vulkan/struct.Device.html)

Text: [Dear ImGui](https://github.com/ocornut/imgui) ·
[ImguiVR (OpenVR-era pattern)](https://github.com/temcgraw/ImguiVR) ·
[stb](https://github.com/nothings/stb) ·
[msdf-atlas-gen](https://github.com/Chlumsky/msdf-atlas-gen) ·
[cylinder layer spec](https://registry.khronos.org/OpenXR/specs/1.0/man/html/XR_KHR_composition_layer_cylinder.html) ·
[immersive-web/layers explainer](https://github.com/immersive-web/layers/blob/main/explainer.md)

Players: [xr-video-player](https://codeberg.org/yoshino/xr-video-player) ·
[WlxOverlay-S](https://github.com/galister/wlx-overlay-s) ·
[Stardust XR](https://stardustxr.org/) ·
[mpv-xr](https://sr.ht/~shironeko/mpv-xr/) ·
[Linux VR Adventures FOSS index](https://wiki.vronlinux.org/docs/fossvr/)

Animation/shaders: [Tweeny](https://github.com/mobius3/tweeny) ·
[Spring-It-On](https://theorangeduck.com/page/spring-roll-call) ·
[Damped Springs (Juckett)](https://www.ryanjuckett.com/damped-springs/) ·
[shaderc](https://github.com/google/shaderc) ·
[Specialization constants](https://docs.vulkan.org/samples/latest/samples/performance/specialization_constants/README.html)

Rust: [openxrs](https://github.com/Ralith/openxrs) ·
[xrizer (this lab's hardware-verified precedent)](https://github.com/Supreeeme/xrizer) ·
[wgpu OpenXR issue #602](https://github.com/gfx-rs/wgpu/issues/602) ·
[vulkan_video (PoC)](https://docs.rs/vulkan_video/latest/vulkan_video/)
