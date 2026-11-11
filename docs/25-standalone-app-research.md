# 25 — Standalone app research: the OpenXR toolbox

> **Desk research only (2026-08-09), not verified on hardware.** Web searches plus
> primary sources where possible (LICENSE files, Monado's CMakeLists via a GitHub mirror,
> GitHub/crates.io APIs). Nothing here has been tried with the headset on; the project's
> golden rule applies before acting on any of it.

The question: what already exists to avoid reinventing **text rendering, UI, animation and
shader tooling** when building a future standalone VR app on this stack (Linux + Monado +
NVIDIA/Vulkan + the NVDEC zero-copy pipeline already working at 8K60 in the modified
`hello_xr`)?

## The verdict: don't switch stacks — the standalone app is a hello_xr that grows

The NVDEC zero-copy pipeline is the hardest-won, most-verified piece of the project. None
of the researched paths offers a *proven* way to wrap it without real friction, so the
plan is to keep the hand-rolled C++/Vulkan core and add layers around it.

External validation: WlxOverlay-S, the closest real Linux+Monado precedent, rewrote its
StereoKit-based version in pure Vulkan, citing NVIDIA+EGL pain on Linux — the same class
of pain documented here for Plasma/kwin (`docs/20-desktop-plasma-crash.md`).

| Option | Status | One-line tradeoff |
|---|---|---|
| Godot 4.x | Worth a bounded spike | Best-documented Monado support and a built-in Equirect layer node; external VkImages only via a C++ GDExtension (`RenderingDevice.texture_create_from_extension()`), unverified on this stack; swallows a whole scene paradigm. Spike = one decoded frame in the headset. |
| StereoKit | Escape hatch | Names Monado, has text/UI, `skg_tex_create_from_existing()`; permanent 0.4.0 previews, no stable release since 0.3.11 (mid-2024). |
| Rust (openxr-rs + ash) | Only if Rust fluency is a goal | Session/interop is hardware-verified in this lab (xrizer does it), but nobody has published NVDEC to Vulkan zero-copy in Rust; no shortcut for the video core. |
| Bevy + bevy_mod_openxr | Watch list | Cleanest Vulkan interop hook (`wgpu_hal texture_from_raw`); no composition layers yet; Monado never confirmed. |
| wgpu | Ruled out | No official OpenXR integration (gfx-rs/wgpu #602 open), example archived since 2022; neither xrizer nor WlxOverlay-S uses it. |
| hotham | Rejected | Its own FAQ: Quest 2 almost exclusively. |
| VLC / DeoVR / Skybox | Rejected | Broken or nonexistent on Linux/FOSS. |

## Proposed architecture: current core + 3 new layers, all hand-rolled C++/Vulkan

1. **Core (untouched):** OpenXR session loop, stereo projection swapchain and the
   NVDEC-CUDA-Vulkan zero-copy pipeline stay as they are.

2. **Text/UI as composition layers, not in the main projection layer.**
   - Glyph atlas via `stb_truetype` (same stb family already vendored), a minimal Vulkan
     pipeline (quad per glyph, alpha blend), submitted as `XR_TYPE_COMPOSITION_LAYER_QUAD`
     (core OpenXR 1.0, no extension).
   - A separate layer has its own swapchain resolution (text does not pay the 8K video's
     cost) and skips the double resampling that blurs text inside the eye buffer.
   - Per Monado's CMakeLists the main compositor supports `cylinder` and `equirect2`;
     `cube` and `equirect1` are build-blocked. Reconfirm against the lab's actual Monado
     checkout before depending on it. `cylinder` is the option for a curved menu.
   - If stb_truetype aliases on close-up panels: switch the atlas to MSDF (`msdfgen` /
     `msdf-atlas-gen`, MIT, offline generation only).
   - Dear ImGui only when real widgets are needed (official `imgui_impl_vulkan` rendering
     off-screen into the quad-layer texture, input translated from OpenXR actions). No
     public example joins ImGui + Vulkan + OpenXR quad layer end to end; budget it as real
     integration work. Monado itself vendors ImGui for its `XRT_DEBUG_GUI=1` GUI.

3. **Animation, no heavy library:** `Tweeny` (single header, MIT) for fixed-duration
   transitions; a hand-written critically-damped spring parameterized by halflife
   (~30-40 lines, Daniel Holden's Spring-It-On) for anything chasing the user (head- or
   hand-anchored panels, settling after a recenter).

4. **Shader tooling:** `shaderc` for runtime GLSL to SPIR-V (`apt install libshaderc-dev`),
   an own includer (`SetIncluder` + `GL_GOOGLE_include_directive`) to share projection
   helpers, inotify hot-reload (new pipeline built at frame start, **old one destroyed only
   after a fence confirms the GPU is done with it**, since a stall hits the live 8K60
   pipeline), specialization constants for fixed variants (360/VR180/flat, mono/stereo),
   push constants for per-frame data. For Shadertoy-style effects, replace the screen-space
   camera math with the real per-eye `XrView` matrices and skip motion blur / chromatic
   aberration / dynamic FOV unless comfort-validated.

## Quick wins for the current player

- Real text instead of colored bars (stb_truetype + atlas + quad layer): the player's
  biggest gap and the lowest-friction item above.
- Shaderc includer + inotify hot-reload over the existing shaders; Tweeny for panel fades;
  the critical spring for UI that follows the user / settles after the
  `patches/xrizer/0001` recenter.
- `XR_KHR_composition_layer_cylinder` for a curved settings panel.
- Read `xr-video-player` (codeberg.org/yoshino/xr-video-player), the only project found
  claiming validation against Monado's WMR driver. Its decode is mpv-based, not NVDEC
  zero-copy.

## Ecosystem notes

- No Linux port of DeoVR/Skybox and no FOSS equivalent; the only OpenXR-native Linux
  players found (`xr-video-player`, `mpv-xr`) are libmpv-based. VLC 360 support on Linux
  is absent or broken.
- Stardust XR documents a Lanczos filter for keeping text legible under perspective warp.
- Vulkan Video decode (`VK_KHR_video_decode_queue`, the CUDA-free path): only a
  single-frame Rust proof of concept exists; recheck later. GStreamer's `vulkan` plugin /
  DMA-BUF import as a decode path was left unverified.

## Verification debt

- Everything above is unverified with a headset. Monado layer flags came from a mirror,
  not the canonical repo or the lab checkout.
- Confirm at runtime (`xrEnumerateInstanceExtensionProperties`) that any non-core
  extension is enabled in the exact lab binary before writing code against it.
- O3DE, Magnum, Filament and Diligent were never evaluated.

## Key sources

[StereoKit](https://stereokit.net/) ·
[sk_gpu](https://github.com/StereoKit/sk_gpu) ·
[Godot OpenXR](https://godotengine.org/article/godot-openxr-support/) ·
[Godot composition layers](https://docs.godotengine.org/en/stable/tutorials/xr/openxr_composition_layers.html) ·
[bevy_mod_openxr](https://github.com/awtterpip/bevy_oxr) ·
[wgpu OpenXR issue #602](https://github.com/gfx-rs/wgpu/issues/602) ·
[msdf-atlas-gen](https://github.com/Chlumsky/msdf-atlas-gen) ·
[cylinder layer spec](https://registry.khronos.org/OpenXR/specs/1.0/man/html/XR_KHR_composition_layer_cylinder.html) ·
[xr-video-player](https://codeberg.org/yoshino/xr-video-player) ·
[WlxOverlay-S](https://github.com/galister/wlx-overlay-s) ·
[Stardust XR](https://stardustxr.org/) ·
[mpv-xr](https://sr.ht/~shironeko/mpv-xr/) ·
[Tweeny](https://github.com/mobius3/tweeny) ·
[Spring-It-On](https://theorangeduck.com/page/spring-roll-call) ·
[shaderc](https://github.com/google/shaderc) ·
[openxrs](https://github.com/Ralith/openxrs) ·
[xrizer](https://github.com/Supreeeme/xrizer)
