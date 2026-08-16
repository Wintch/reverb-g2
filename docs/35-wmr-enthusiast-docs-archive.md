# 35 — Archived: Microsoft's "Windows Mixed Reality enthusiast documentation", Before you start

**Why this is here at all**: Microsoft's own page carries the banner *"This content has been
retired and may not be updated in the future. The product, service, or technology mentioned
in this content is no longer supported."* Windows Mixed Reality devices lose all support after
November 2026 (see `docs/31`), and the r/HPReverb preservation thread this project already
cited (`docs/31`, "Live capture" section) makes the case directly: Microsoft has already
pulled other WMR-era content offline without notice, and there's no guarantee this page
survives either. Archived verbatim here on 2026-08-16 so the source outlives Microsoft's own
copy of it.

This is a **preservation copy, not new investigation** — nothing in it is new to this
project (Windows 11 24H2+ incompatibility, WDDM 2.2 GPU requirement, and the general
adapter/controller/room-boundary prerequisites are all already covered by `docs/31` and
earlier chapters). Kept for the record and as a citable primary source, not because it
changes any conclusion here.

**Source**: Microsoft Learn, "Windows Mixed Reality enthusiast documentation" → "Before you
start". Last updated per the page: 01/08/2023. Retrieved 2026-08-16.

---

## Before you start

*Applies to: Windows 10 and Windows 11*

### What you'll need to run Windows Mixed Reality

- A Windows Mixed Reality head mounted display (HMD).
  - Windows Mixed Reality devices are **not supported with Windows 11, version 24H2 and
    newer**.
  - Windows Mixed Reality support is limited to Windows Mixed Reality compatible PC Windows 10
    Version 20H2 through Windows 11, version 23H2.
- A reliable internet connection.
- Display, USB, and Bluetooth adapters (if not pre-built into HMD or PC).
- Windows Mixed Reality motion controllers, an Xbox gamepad, or a mouse and keyboard.
- Headphones and microphone (if not pre-built into HMD or PC).
- A large, open space to support your virtual room boundary.

### Make sure your PC is compatible with Windows Mixed Reality

Check the Windows Mixed Reality minimum PC hardware compatibility guidelines or run the
Windows Mixed Reality Portal app on your PC to check for Windows Mixed Reality compatibility.

Read up on PC compatibility issues for more details.

### Make sure you have Windows 10 Version 20H2 or newer installed

You must be running Windows 10 Version 20H2 or newer to use Windows Mixed Reality. Compatible
versions of Windows include:

- Windows 10 Version 20H2
- Windows 10 Version 21H1
- Windows 10 Version 21H2
- Windows 11 Version 21H2
- Windows 11 Version 22H2

To see which version of Windows your device is currently running, select the Start button,
then select Settings > System > About.

To ensure that Windows is up to date on your PC, select the Start button, then select
Settings > Windows Update. Select Check for updates and if updates are available, install
them.

### Make sure your PC is connected to the internet

Check that your PC is connected to the internet through a stable and secure ethernet or Wi-Fi
connection.

### Make sure you have a compatible GPU driver

Your PC requires a **WDDM 2.2 or later** graphics driver in order to complete the Windows
Mixed Reality setup process. If your PC doesn't already have a compatible GPU driver, try
these resources:

- Check for the latest critical driver updates using Windows Update by selecting Start >
  Settings > Windows Update > Check for Updates.
- Check for the latest optional driver updates using Device Manager:
  - Right-click Start > Device Manager.
  - Expand Display Adapters.
  - Right-click on the graphics card and select Update Driver > Search automatically for
    drivers.
- Check the website for the manufacturer of your PC.
- Check the website for the manufacturer of your graphics card (for example, NVIDIA, AMD, or
  Intel).

### Make sure that you have any required adapters

Your PC may not have the full-sized video ports and/or USB ports required to connect your
HMD. Additionally, you might also need a Bluetooth adapter to meet the Mixed Reality Portal
requirements and successfully connect your HMD and motion controllers to your PC.

### Make sure that you have the necessary input devices

Windows Mixed Reality is designed to work best with Windows Mixed Reality supported motion
controllers, which provide precise interactions and tracking without the need to install
external tracking hardware on your walls. You can also use an Xbox gamepad or a mouse and
keyboard.

### Make sure that you have a large, open space to support your virtual room boundary

To safely move around while using Windows Mixed Reality, you'll need to have a large open
space for your virtual room boundary. During initial setup, you'll be asked to choose between
"Set me up for all experiences" or "Set me up for seated and standing". Choose "Set me up for
all experiences" and set up a room boundary if you plan to move around in room-scale
experiences.

**Seated and standing (doesn't require room boundary)**: you'll be using your HMD without a
room boundary. You'll need to stay in one location to avoid physical obstacles or tripping
hazards. You can still sit and stand, but you shouldn't move around. Certain apps may require
a room boundary and might not work or provide the same experience without one.

**All experiences (requires room boundary)**: set up a room boundary and be able to move
around in room-scale app experiences. Prepare your physical space by making sure there are no
obstacles, hazards, or fragile items within the area you'll be active — including above your
head.

> **Important**: Do not set up your room boundary on top of a staircase or under an
> extra-low ceiling fan. Remove all breakable objects and obstacles from the area, and make
> sure everyone using your headset reads and understands the health, safety, and comfort
> guidelines.
