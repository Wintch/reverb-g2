================================================================================
  WINDOWS CAPTURE KIT  —  HP Reverb G2 / G2 support on Linux  (v3)
================================================================================

READ FIRST IF YOU JUST WANT THE HEADSET TO WORK ON WINDOWS
---------------------------------------------------------------------
This kit is a CAPTURE tool for the 90 Hz investigation. If what you need is
"make the G2 run on this Windows machine" (Windows 11 24H2 + Oasis driver +
SteamVR), that's a different thing and it lives next to this file:

    powershell -ExecutionPolicy Bypass -File .\power-on.ps1

It checks the USB enumeration branch by branch, controller pairing, and the
Oasis/SteamVR software state, and tells you what to physically fix. The
manual behind it, including what SteamVR errors 108 and 422 actually mean,
is docs/31-windows-bringup-and-errors.md.


STATUS OF THE 90 HZ INVESTIGATION: resolved, this kit is a general-purpose tool now
---------------------------------------------------------------------
The 90 Hz failure on Linux was the NVIDIA display driver clamping the G2 to
6 bpc (patches/nvidia/0004, root cause in docs/13-bug-6bpc.md, resolution in
docs/19-nvidia-bug-5923212-followup.md). With that patch the headset's
DEVICE_STATUS report (33 bytes) is byte-identical between Linux and Windows,
including at the moment of a live 60<->90 Hz switch on Windows, and no special
HID command exists for the mode switch (docs/09, docs/13). The vblank
factorial in docs/16 is kept as a record, but its central conclusion was
wrong (see its banner).

So nothing here is a pending to-do for the 90 Hz issue. The capture scripts
remain useful as a Windows baseline to compare against (USB behaviour, EDID,
HID reports), or for a new question such as controller pairing
(BRINGUP-CAPTURE-RUNBOOK.md).


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
patch applied; see also linux-reference.txt, a pre-patch capture with byte 18 = 06, superseded by REF_LINUX). It also looks for the HoloLens Sensors firmware log
(0x03, ASCII).


IF SOMETHING GOES WRONG
---------------------------------------------------------------------
- No USBPcap interface shows up -> you didn't reboot after installing
  Wireshark, or you didn't check the USBPcap component in the installer.
- The NVIDIA panel doesn't open by itself -> newer versions package it
  differently; open it manually (right-click on the desktop -> NVIDIA
  Control Panel). The Reverb G2 does not show up there as a selectable
  display (it is in direct/HMD mode), which is expected.
- HWiNFO64 doesn't show anything for DisplayPort Pixel Clock/Link Rate ->
  that's not a failure, it's an already-confirmed data point: this
  version/GPU doesn't expose it.
- CRU doesn't show the Reverb G2 in the list -> confirms the headset is
  still active (image on) at that moment; CRU lists the displays connected
  at the moment it's opened.

There's no need to understand any of this output on the spot. Bring it all
back and it gets analyzed on Linux with `analyze-windows.py` (for the HID
data) and by eye for the rest.
