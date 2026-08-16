# 36 — Archived: Microsoft's "Get help with PC compatibility in Windows Mixed Reality"

Second page from the same retired Microsoft Learn set as `docs/35` — same preservation
rationale, same caveat (nothing here overturns a project conclusion; archived because
Microsoft's own banner says it may vanish). **Source**: Microsoft Learn, "Windows Mixed
Reality enthusiast documentation" → "Get help with PC compatibility". Last updated per the
page: 11/23/2025. Retrieved 2026-08-16.

**One real, checkable technical claim in here, worth flagging** (see "This PC might not have
a compatible USB configuration" below): Microsoft's own troubleshooting names a specific
incompatible USB host chipset (**Etron**) and a specific check (whether Device Manager's
"eXtensible Host Controller" entry ends in "Microsoft" — i.e. the inbox xHCI class driver,
not a vendor one). **Checked live against this lab machine (`lspci -nnk`)**: both host
controllers are native AMD, not third-party — `02:00.0` "AMD 400 Series Chipset USB 3.1
xHCI Compliant Host Controller" (chipset-attached) and `09:00.3` "AMD Matisse USB 3.0 Host
Controller" (CPU-attached, Ryzen). No Etron/ASMedia discrete USB controller chip anywhere in
the topology (`lsusb -t`'s ASMedia PCI subsystem ID is just the board vendor tag on the AMD
silicon, not a separate controller). So the specific failure modes this page documents
(Etron incompatibility, non-Microsoft xHCI driver) **don't apply to this hardware** — ruled
out, not just assumed. This corrects/narrows a claim from earlier the same night (see
`docs/31`, "Live capture" section): Microsoft's docs *do* document real USB-port-related
compatibility failures for WMR — just not the specific "same physical device needs
re-pairing after a port change" mechanism this project is chasing. Different problem class,
same general "the G2 cares about which port" territory.

---

## Get help with PC compatibility in Windows Mixed Reality

*Applies to: Windows 10 and Windows 11*

When you set up Windows Mixed Reality or use the Mixed Reality Portal, you get a report on
whether your PC is compatible. The following sections provide specific details on what you
might see in the report.

> **Note**: Windows Mixed Reality devices aren't supported with Windows 11, version 24H2 and
> newer. Windows Mixed Reality support is limited to Windows 10, version 20H2 through Windows
> 11, version 23H2.

Before going any further, try the most common fixes:

- Make sure your computer meets the minimum PC hardware compatibility requirements
- Check that your graphics card and processor are compatible
- Check the recommended adapters list
- Update your graphics driver by selecting Start > Settings > Update & security > Check for
  updates

### You're good to go

Your PC can run Windows Mixed Reality! There's still variation among computer hardware and
configuration, so the Mixed Reality experience might not be the same on every PC.

### Supports some features

Your PC can run some Windows Mixed Reality experiences, but it might not provide the best
possible experience. Possible downsides include lagging graphics, performance hits, and some
applications and games that you can't run at all.

**This PC has an integrated graphics card with single-channel RAM** — install a compatible
discrete graphics card, install an additional RAM stick for dual-channel, or switch to a
compatible PC.

**This PC has a hybrid graphics configuration with an incompatible PCIe link** — might work,
but if you run into problems you need to switch to a compatible PC.

**This PC's graphics driver might not work well with Windows Mixed Reality** — update via
Windows Update or the manufacturer's site; failing that, add a compatible graphics card or
switch PCs.

**This PC's processor might not work well with Windows Mixed Reality** — not enough cores;
replace the processor or switch PCs.

**This PC might not have a compatible USB configuration**:

- Check the recommended adapters documentation for common compatibility issues.
- Consider using an external powered USB hub.
- Plug your headset into a different USB port, if you have one available.
- If that doesn't work, uninstall your PC's current USB driver and reinstall a Microsoft
  driver:
  1. Start > "device manager" > Device Manager.
  2. Expand Universal Serial Bus controllers.
  3. If the list includes an "eXtensible Host Controller" item that **doesn't** end in
     "Microsoft", that driver isn't compatible — uninstall it (right-click > Uninstall
     device > check "Delete the driver software for this device" > Uninstall).
  4. If the list includes an "eXtensible Host Controller" item with **"Etron"** in the name,
     that USB controller isn't compatible — use a different USB port or a different USB 3.0
     host controller.
  5. Restart your PC.
  6. Recheck Device Manager: if the entry now ends in "Microsoft", you're good. If not,
     repeat the uninstall for any remaining non-Microsoft versions.
- If that still doesn't work, add a PCIe USB card to your PC.

**This PC doesn't have Bluetooth 4.0 for controllers** — 2018+ WMR headsets have built-in
Bluetooth; older ones need Bluetooth 4.0, an Xbox controller, mouse/keyboard, or a USB
Bluetooth adapter.

**Depending on your headset, you might need a Bluetooth adapter to use motion controllers**
— some headsets pair controllers directly, others need a PC-side Bluetooth radio or dongle.

**This PC doesn't have a self-powered USB port** — needs a self-powered USB 3.0 port; connect
a powered USB 3.0 hub and use that port instead.

**This PC's graphics card / driver doesn't work with Windows Mixed Reality** — add a
compatible card or switch PCs; for the driver, try Windows Update or the manufacturer site
first.

**This PC's processor doesn't work with Windows Mixed Reality** — doesn't support AVX or
Popcnt instructions; replace it or switch PCs.

**This PC doesn't have enough free disk space** — needs 10 GB free for setup and best
performance.

**This PC is running an edition of Windows that doesn't support Windows Mixed Reality** —
needs Windows 10 Home/Pro or Windows 11.

**This PC has no USB 3.0 port** — desktops: add a PCIe USB card; laptops: switch PCs.

**You can't run this app via remote desktop** — needs a PC with a monitor connected (a
virtual display adapter plugged into DisplayPort can substitute).

### Getting the best performance

For slow loading, choppy visuals, or poor visual quality:

- Close any open apps running on your PC desktop.
- If using a USB-C or DisplayPort-to-HDMI adapter, try a different one.
- Disconnect extra monitors connected to the PC's graphics card.
- Try different mixed reality apps from the Windows Store — some work better with your setup.
- Update Windows Mixed Reality settings: Experience, Resolution, Frame-rate, Calibration.

> **Note**: "This hardware configuration might work with Windows Mixed Reality, but it hasn't
> been tested yet" can mean performance issues on long sessions.

### Working with SteamVR

After installing Steam: follow the instructions for using SteamVR with Windows Mixed Reality,
and install the SteamVR Performance Test apps.
