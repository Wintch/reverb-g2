# Issue para github.com/AshishKumar4/Project-VR

HOW TO POST: New issue en https://github.com/AshishKumar4/Project-VR/issues
(si el repo no tiene issues habilitados, alternativa: mencionarlo en el hilo 337744 del
foro de NVIDIA, que es suyo — pero el issue es el canal directo).

TITLE (pegar tal cual):

Your NVIDIA series validated on Ampere (RTX 3060 Ti, Debian 13) — plus a 4th patch it needed there: NVKMS 6 bpc clamp

--- COPY BELOW THIS LINE ---

First: thank you. Your three consolidated NVIDIA patches
(`patches/consolidated/nvidia/`, `g2-patches-on-595.71.05`) are the backbone of getting my
HP Reverb G2 running at 90 Hz on Linux. This issue is to report back what I believe is the
first independent validation of your series on different hardware — and to contribute the
one extra patch it turned out to need there.

**Setup:** RTX 3060 Ti (Ampere/GA104), Debian 13, `nvidia-open` 595.71.05 from NVIDIA's
own debian13 apt repo, HP Reverb G2, Monado. Your three patches applied unmodified.

**Result with your three patches alone: 90 Hz still did not light the panel** on this GPU
(black past the HP logo; 4320x2160@60 fine). Root cause, found after a lot of dead ends:
NVKMS clamps DisplayPort sinks to **6 bpc** when the EDID leaves color depth undeclared —
and the G2's EDID does exactly that (byte 0x14 = 0x80, "undefined"). At 6 bpc the 90 Hz
modes never light; at 60 Hz it gets away with it. Two-line fix: fall back to 8 bpc instead
of 6 when the EDID declares nothing.

- Patch: https://github.com/Wintch/reverb-g2/blob/main/patches/nvidia/0004-nvkms-do-not-clamp-to-6bpc-when-EDID-leaves-color-de.patch
- Full root-cause writeup (NVIDIA forum):
  https://forums.developer.nvidia.com/t/hp-reverb-g2-clamped-to-6-bpc-because-its-edid-leaves-color-depth-undefined-root-cause-found-two-line-patch-but-90-hz-still-fails-to-light/379240

**With all four patches, validated physically on Ampere:** both 90 Hz modes light and are
visually clean — the native 2880x1440@90 (the EDID base DTD, byte-identical to what
Windows drives per a CRU capture) and the supersampled 4320x2160@90. Verified with a
static solid-white pattern and cross-checked against the headset's own HID DEVICE_STATUS
messages (refresh/htotal/vtotal/backlight byte). One methodological note that cost us a
day and might save you one: a test pattern that alternates colors every frame reads as
"panel flicker" — it strobes by construction. 60 Hz shows the same backlight flicker on
Linux that it shows on Windows (factory panel behavior at its non-native rate).

An open question you may have insight on: why didn't your RTX 4080 need this? Either Ada
takes a different path through the bpc selection, or your setup ended up at 8 bpc for some
other reason — I only have Ampere here to test, so I can't tell from my side.

**Two more things in our repo that may be useful to you or your users:**

1. **Debian delivery that survives kernel upgrades:** we apply your patches (plus 0004)
   through the `PATCH[]` hook of NVIDIA's own `nvidia-kernel-open-dkms` debian13 package,
   so DKMS re-applies them on every kernel update — no manual `.ko` installs. Details:
   https://github.com/Wintch/reverb-g2 (docs/04, patches/nvidia/README.md).
2. **An upstream Monado bug that affects any WMR user:** the HP G2 controller driver
   (`wmr_controller_hp.c`) registers no `binding_profiles` remap for the native
   `/interaction_profiles/microsoft/motion_controller` profile, so an app that suggests
   bindings only under that profile silently gets nothing on real G2 hardware (masked for
   apps that also suggest oculus/touch, which is the remap Monado actually selects).
   Patch: https://github.com/Wintch/reverb-g2/blob/main/patches/monado/0011-d-wmr-Add-native-WMR-motion_controller-binding-profi.patch

The repo also has a dated log of every attempt (including all the failures), EDID tooling,
and a controller-pairing state checker, in case any of it is useful. Happy to test things
on Ampere if that helps you.
