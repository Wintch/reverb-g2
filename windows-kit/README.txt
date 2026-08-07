================================================================================
  WINDOWS CAPTURE KIT  —  HP Reverb G2 / G2 support on Linux  (v3)
================================================================================

CURRENT STATUS: the USB/HID channel is already exhausted, that's not what's missing
---------------------------------------------------------------------
On Linux, the headset at 90 Hz shows the HP logo and doesn't lock on (white
flicker with the patches applied); on Windows it works perfectly, even
switching from 60 to 90 Hz live without reconnecting. This has already been
ruled out, with real captures from both sides:

  - Special-mode HID command: doesn't exist (the Oasis driver was
    disassembled).
  - Bandwidth / vblank duration / the refresh rate itself: ruled out with a
    full factorial test on Linux (docs/16-lab-vblank.md).
  - The state the headset reports over USB (`DEVICE_STATUS`, 33 bytes): it is
    BYTE-IDENTICAL between patched Linux and Windows, both at steady state
    and at the exact moment of a live 60<->90 transition. There is no extra
    USB command during the mode switch (docs/13-bug-6bpc.md).
  - DSC via the NVIDIA panel or Windows Settings: the Reverb G2 doesn't
    appear as a selectable display in either screen (it's in direct/HMD
    mode, not as a desktop monitor) -- that avenue is closed due to lack of
    access, not because of a negative result.

What's left -- silent DSC, closed-source GSP firmware, something in
DisplayPort's own link training -- is no longer visible from any angle
Windows can show through user-level tools. The real next step is the report
to NVIDIA (bug 5923212, docs/19), not another capture from this kit.

This kit remains as a general-purpose tool for the next chapter (for
example, a Windows baseline to compare against an AMD GPU when it arrives,
or if NVIDIA asks for something specific) -- not as a pending to-do list for
the 90Hz issue. If you come back to this folder wondering "where do I go
from here", the short answer is: through `docs/19` and through AMD, not
through here.


SETUP (one time only, requires a reboot for Wireshark/USBPcap)
---------------------------------------------------------------------
1. Wireshark, WITH the USBPcap component checked in the installer (it's not
   checked by default):
       https://www.wireshark.org/download.html
   REBOOT after installing -- USBPcap installs a filter and doesn't work
   until the reboot.

2. Optional but recommended, portable tools (no installation needed, each
   in its own folder next to this README):

       cru-1.5.3\CRU.exe        https://www.monitortests.com/forum/Thread-Custom-Resolution-Utility-CRU
                                 (official ToastyX site -- watch out for
                                 similar-looking domains like
                                 customresolutionutility.*)
       usbdeview-x64\USBDeview.exe   https://www.nirsoft.net/utils/usb_devices_view.html
       hwinfo64\HWiNFO64.exe    https://www.hwinfo.com/download/  ("Portable" version)
       gpuz\GPU-Z.exe           https://www.techpowerup.com/gpuz/  (already portable)

   `run-diagnostics.ps1` automatically looks for each one in its folder and
   only opens them if found -- if one is missing, it skips it without
   breaking anything.

None of this overwrites the NVIDIA driver or the headset's driver -- these
only read/edit EDID in the registry, they don't touch DPCD live.


CAPTURE -- a single command per run
---------------------------------------------------------------------
Once per PowerShell session, as administrator, from this folder:

    powershell -ExecutionPolicy Bypass -File run-diagnostics.ps1 -Label 90hz

(or `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` once and
then just `.\run-diagnostics.ps1 -Label 90hz` normally -- PowerShell blocks
unsigned scripts by default, this enables it only for that window.)

The script does everything in a single pass:

  1. Finds the tools on its own (local paths + PATH + Windows registry).
  2. Collects everything with a command-line interface without touching
     anything: USBDeview, nvidia-smi, WMI (video adapter and monitors),
     DxDiag.
  3. Captures USB from ALL USBPcap interfaces at once -- no need to guess
     which one enumerates the headset. It walks you through it in the
     console: it asks for an Enter to start the capture (with the
     WMR/SteamVR runtime STILL CLOSED -- without that the panel has no
     "mode", it's off), and another Enter to stop after confirming the
     image.
  4. For what has no CLI (CRU, HWiNFO64, GPU-Z, the NVIDIA panel), it opens
     each tool by itself and shows on screen what to look at and how to
     name the screenshot.
  5. Leaves everything in a `run_<Label>_<timestamp>\` folder -- that whole
     folder is what needs to be collected.

The headset's companion device (03f0:0580) only sends its `DEVICE_STATUS`
HID report when something CHANGES, not at steady state -- that's why a
SHORT capture (10-15s is enough) placed right around the moment the runtime
starts or the refresh rate changes is best, not left running for minutes.

Repeat with different `-Label` values (e.g. `60hz`, `90hz`, `idle`) as many
times as needed -- each run builds its own timestamped folder, they never
overwrite each other.


ANALYSIS -- back on the Linux side
---------------------------------------------------------------------
    python3 analyze-windows.py run_90hz_*/90hz_USBPcap*.tsv run_60hz_*/60hz_USBPcap*.tsv

Looks for the companion's `DEVICE_STATUS` (0x05, 33 bytes) and compares it
against `REF_LINUX` (reference captures from Linux, already with the bpc
patch applied). It also looks for the HoloLens Sensors firmware log
(0x03, ASCII).


IF SOMETHING GOES WRONG
---------------------------------------------------------------------
- No USBPcap interface shows up -> you didn't reboot after installing
  Wireshark, or you didn't check the USBPcap component in the installer.
- The NVIDIA panel doesn't open by itself -> newer versions package it
  differently; open it manually (right-click on the desktop -> NVIDIA
  Control Panel). The Reverb G2 still won't show up there as a selectable
  display either way -- that's an already-confirmed result, not something
  you did wrong.
- HWiNFO64 doesn't show anything for DisplayPort Pixel Clock/Link Rate ->
  that's not a failure, it's an already-confirmed data point: this
  version/GPU doesn't expose it.
- CRU doesn't show the Reverb G2 in the list -> confirms the headset is
  still active (image on) at that moment; CRU lists the displays connected
  at the moment it's opened.

There's no need to understand any of this output on the spot. Bring it all
back and it gets analyzed on Linux with `analyze-windows.py` (for the HID
data) and by eye for the rest.
