HP Reverb G2 — EDID and diagnostics
NVIDIA developer forum topic 379240

  g2-edid.bin              raw 384-byte EDID read from the headset (3 blocks)
  g2-edid-8bpc-repro.bin   same EDID with base byte 0x14 changed 0x80 -> 0xA0
                           (Color Bit Depth: undefined -> 8 bpc) and the base
                           block checksum corrected 0xE8 -> 0xC8. Only those two
                           bytes differ. Overriding the sink's EDID with this file
                           reproduces the effect of the nvkms-dpy.c patch without
                           patching the driver.
  g2-edid-decoded.txt      annotated decode of the raw EDID: hex dump, Video Input
                           Definition bit breakdown, CTA-861 feature byte, DisplayID
                           version dispatch, and all three modelines derived from
                           the descriptors.

Captured on driver 595.71.05 (open kernel modules), RTX 3060 Ti (GA104), Debian 13.
