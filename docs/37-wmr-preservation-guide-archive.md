# 37 — Archived: community guide for preserving WMR past the November 2026 cutoff

**Why this is here**: pasted in full by the user from a r/HPReverb thread ("Usability of
Reverb G2 with WMR after November 2026", posted by u/abbaaba, ~2024, with a 2025-02-19 update
from u/divxmaster confirming an all-offline install on Windows 11 23H2). Same preservation
rationale as `docs/35`/`docs/36`: this is a Reddit post, not an official Microsoft page, so it
has no retirement banner to warn anyone — but it's exactly the kind of practical, hard-won
recipe that vanishes the moment the thread scrolls off attention, and it's the only place this
project has found the concrete package list and install order. **Not independently verified
by this project** — archived as found, not tested.

**Context this project already had, so this isn't read as if from nothing**: Microsoft
deprecated Windows Mixed Reality in Windows 11 24H2 (`docs/31`); the Mixed Reality Portal,
"Windows Mixed Reality for SteamVR", and the WMR OpenXR runtime are gone from current Windows
installs and stay usable on Windows 11 23H2 or Windows 10 only through November 2026 per
Microsoft's own EOL notice (`docs/35`). This guide is a third-party attempt to keep the whole
stack installable **offline**, in case the download servers themselves go away too.

## The core problem, per the post's own framing

Matthieu Bucchianeri (mbucchia, ex-Microsoft OpenXR, author of the OpenXR Toolkit and — for
this project's purposes — the Oasis Driver already covered in `docs/09`/`docs/31`) is quoted
making the harder point: some WMR components are embedded in the Windows OS itself, not
separately downloadable, so keeping installer files around may not be sufficient if those
OS-level pieces are ever removed from future Windows builds. The dotted-line (OS-embedded)
components in his diagram are the ones nobody can substitute.

## The offline-preservation recipe, as posted

1. **Keep an OS ISO**: Windows 10 22H2 (speculative pick — smaller officially-unsupported
   install base than Windows 11 might mean Microsoft keeps patching it longer, similar to XP)
   and/or Windows 11 23H2 (the last Windows 11 version with official WMR support), from
   `microsoft.com/en-in/software-download/windows10`. Getting the ISO option directly may
   require spoofing the browser's user agent to a non-Windows OS. Flash-drive install: format
   NTFS, extract the ISO contents to the root with 7zip.
2. **Save the "Windows Mixed Reality enthusiast documentation" PDF** (the same doc family as
   `docs/35`/`docs/36` — download button at the bottom of the page).
3. **Get the Windows Mixed Reality device driver, version `10.0.19041.2054`** — the exact
   version this project already has in `docs/10`'s local zip note, confirmed hash-identical to
   what's installed on this lab's Windows disk.
4. **Get the applicable Windows Mixed Reality FOD (Feature-on-Demand) packages** for the
   target Windows 10/11 version.
5. **Copy the SteamVR and "Windows Mixed Reality for SteamVR" runtime directories** onto
   portable media from a PC with full internet access (Steam Library → SteamVR → Properties →
   Local Files → Browse), rather than relying on Steam to redownload them later.
6. **Get the Microsoft Store app packages via `store.rg-adguard.net`** (paste the Store page
   URL, dropdown to "Retail", download the `.appxbundle` — not the `.eappxbundle` — plus
   listed dependencies; verify by digital signature, HP's or Microsoft's, if paranoid about
   integrity). Package list as posted:
   - **Mixed Reality Portal**: `Microsoft.MixedReality.Portal_2000.21051.1282.0_neutral_~_8wekyb3d8bbwe.appxbundle`,
     `Microsoft.VCLibs.140.00_14.0.33519.0_x64__8wekyb3d8bbwe.appx`
   - **HP Reverb G2 VR Headset Setup**: `AD2F1837.HPReverbG2VRHeadsetSetup_1.0.8.0_neutral_~_v10z8vjag6ke6.appxbundle`,
     `Microsoft.NET.Native.Framework.1.7_1.7.27413.0_x64__8wekyb3d8bbwe.appx`,
     `Microsoft.NET.Native.Runtime.1.7_1.7.27422.0_x64__8wekyb3d8bbwe.appx`
   - **OpenXR for Windows Mixed Reality**: `Microsoft.WindowsMixedReality.Runtime_113.2403.5001.0_x64__8wekyb3d8bbwe.Appx`,
     `Microsoft.WindowsMixedRealityRuntimeApp_2024.305.1904.0_neutral_~_8wekyb3d8bbwe.AppxBundle`
   - **Optional, "important" per the post — OpenXR Tools for Windows Mixed Reality**:
     `Microsoft.MixedRealityRuntimeDeveloperPreview_113.2403.5001.0_x64__8wekyb3d8bbwe.msix`,
     `Microsoft.UI.Xaml.2.7_7.2208.15002.0_x64__8wekyb3d8bbwe.appx`,
     `Microsoft.WindowsMixedReality.PreviewRuntime_113.2403.5001.0_x64__8wekyb3d8bbwe.appx`
   - Optional: 3D Viewer and its dependencies.
   - **For other WMR headsets**: swap in that headset's own companion app instead of HP's;
     the post doesn't know whether all WMR headsets have one.

## Install order, as posted

1. Install the OS from the saved ISO.
2. Double-click, in order: `Microsoft.VCLibs` → `Microsoft.MixedReality.Portal` →
   `Microsoft.NET.Native.Framework` → `Microsoft.NET.Native.Runtime` →
   `HPReverbG2VRHeadsetSetup` → `Microsoft.WindowsMixedRealityRuntimeApp` →
   `Microsoft.WindowsMixedReality.Runtime` → optionally `Microsoft.UI.Xaml` →
   `Microsoft.MixedRealityRuntimeDeveloperPreview` →
   `Microsoft.WindowsMixedReality.PreviewRuntime` → optionally 3D Viewer and its deps.
3. Install the FOD package: `Dism /Online /Add-Package /PackagePath:"<FOD package path>"`
   (admin PowerShell).
4. Windows Settings → Windows Update → Check for updates (**needs internet**; save the
   offline installers for whatever updates land, for future re-installs).
5. Extract the WMR device driver; with the headset connected, Device Manager → "HoloLens
   Sensors" under Other devices → Update driver → browse to the extracted folder.
6. Open Mixed Reality Portal, proceed through setup. **After the compatibility check page,
   internet is needed again, briefly** — the post flags this as the one step that could break
   the whole offline approach if whatever URL it calls ever goes dark. Nobody has captured
   what that URL actually is (a comment thread asked; unanswered in what was pasted).

## What a later commenter (`divxmaster`, 2025-02-19) added, confirmed working end to end

- Got the whole process working **fully offline**, no internet touched at any point, on both
  Windows 10 and later Windows 11 23H2.
- Some pieces from `store.rg-adguard.net` didn't work cleanly (notably the OpenXR-related
  packages) — used **UWPBACKUP** instead for those.
- Needed `KB5043064` (Windows 10 cumulative update, installed via `.cab` file) and the G2
  controllers' own driver package, **`MotionController0669_10.0.19041.2034.zip`** (a Microsoft
  `.inf`-based driver, distinct from the HoloLens Sensors one already in `docs/10`/`docs/31`
  — not yet obtained or examined by this project).
- **"Also had to change two reg entries under Holographic to get it to work"** — no specifics
  given on which two. Not chased further this session; if this recipe is ever actually
  attempted, that's the first loose end to run down, and it's a plausible lead for anyone
  still hunting the mechanism behind this project's own ContainerID/provisioning
  investigation (`docs/31`, T185) even though it's a different Windows version/context.
- **Confirms WMR genuinely cannot be forced onto Windows 11 24H2**: even getting the Portal
  app to run, "the Holographic device driver wont load, the entire class has been removed" —
  independent confirmation of what this project found directly in the registry the same night
  (`docs/31`: the `Holographic` ClassGuid `{d612553d-...}` and the literal string are both
  completely absent from this lab's 24H2 SYSTEM hive).

## Not archived here, deliberately

The thread's other comments (speculation about Windows 10 EOL timing, a Wisconsin consumer
complaint against Microsoft, general venting, an ISO-hash-verification follow-up post) are
opinion/tangential, not technical recipe — left out on purpose. If the ISO hash post is ever
needed, its own thread ID was `1ctk9qv`, same subreddit.
