<#
.SYNOPSIS
    Windows-side bring-up gate for the HP Reverb G2 -- the twin of
    scripts/power-on.py, for the current Windows stack (Windows 11 24H2 +
    Oasis driver + SteamVR), where the Mixed Reality Portal no longer exists.

.DESCRIPTION
    Answers, in order, the only questions that decide whether SteamVR will see
    the headset at all -- and, when one of them fails, says WHICH physical or
    software step fixes it instead of leaving a bare error code on screen:

      1. USB census, split by branch (this is what SteamVR error 108 is about)
      2. Which USB controller/port the headset landed on
      3. Bluetooth: are the motion controllers bonded (to the headset's radio)?
      4. Software state: SteamVR, the Oasis add-on, OpenXR runtime, WMR leftovers
         (this is where the intermittent 422 lives)
      5. Verdict, plus a triage table for errors 108 / 422 / 498

    Nothing here writes to the system: it reads Device Manager, the registry and
    Steam's own config files. The only interactive part is the reseat wait,
    which mirrors the Linux script (Enter = re-check, S = skip).

    Code, comments and on-screen text are all English (repo rule), like
    scripts/power-on.py.

.PARAMETER Quick
    Skip the interactive reseat wait -- report and exit. For scripted captures.

.PARAMETER Tune
    Apply the measurement tuning (power plan, USB selective suspend, PCIe ASPM,
    CPU floor, fast startup, per-device USB power management). NEEDS
    ADMINISTRATOR and CHANGES SYSTEM SETTINGS -- without this switch the script
    only reports what those settings currently are. Undo commands are printed
    at the end and documented in docs/31.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\power-on.ps1

    Diagnose only. Does NOT need administrator. Run it before launching SteamVR.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\power-on.ps1 -Tune

    Same, plus applies the tuning. Run from an ADMIN PowerShell.
#>
param([switch]$Quick, [switch]$Tune)

$ErrorActionPreference = "Continue"

# --- the G2's five USB devices, split into its two electrically independent
# pin groups. Same split as docs/22's anatomy and power-on.py's branch_flags():
# a marginal C-plug/adapter seat engages ONE group per insertion (T171), so
# "3 of 5 devices" is useless information -- WHICH group is missing is the
# whole diagnosis. WMR/Oasis needs the SuperSpeed group for tracking; without
# it SteamVR reports "headset not detected".
$USB2_BRANCH = @(
    @{ Id = "VID_04B4&PID_6506"; Name = "USB2 hub (the 480M face of the headset hub)" },
    @{ Id = "VID_03F0&PID_0580"; Name = "Companion (panel control/HID)" },
    @{ Id = "VID_0BDA&PID_4C15"; Name = "Audio (headset earphones)" }
)
$SS_BRANCH = @(
    @{ Id = "VID_04B4&PID_6504"; Name = "SuperSpeed hub (the 5 Gbps face)" },
    @{ Id = "VID_045E&PID_0659"; Name = "HoloLens Sensors (the 4 cameras)" }
)

function Say-Step($n, $title) {
    Write-Host ""
    Write-Host "> Step $n/5 -- $title" -ForegroundColor Green
}
function Say-Ok($m)   { Write-Host "  [OK] $m"   -ForegroundColor Green }
function Say-Bad($m)  { Write-Host "  [--] $m"   -ForegroundColor Red }
function Say-Warn($m) { Write-Host "  [!!] $m"   -ForegroundColor Yellow }
function Say-Dim($m)  { Write-Host "     $m"     -ForegroundColor DarkGray }

# Present == enumerated AND not in an error state. A device sitting there with a
# Problem code (28 = no driver, 43 = device reported failure, 10 = cannot start)
# is exactly the "it's in Device Manager so it must be fine" trap.
function Get-G2Device($idFragment) {
    try {
        $d = Get-PnpDevice -PresentOnly -ErrorAction Stop |
             Where-Object { $_.InstanceId -like "*$idFragment*" } |
             Select-Object -First 1
        return $d
    } catch {
        try {
            return Get-CimInstance Win32_PnPEntity -ErrorAction Stop |
                   Where-Object { $_.PNPDeviceID -like "*$idFragment*" } |
                   Select-Object -First 1
        } catch { return $null }
    }
}

# -Detail, not -Verbose: without [CmdletBinding()] a switch called Verbose is
# legal but shadows the common parameter, which is a trap for the next reader.
function Test-Branch($branch, [switch]$Detail) {
    $missing = @()
    foreach ($dev in $branch) {
        $d = Get-G2Device $dev.Id
        if ($null -eq $d) {
            $missing += $dev
            if ($Detail) { Say-Bad ("{0} -- MISSING ({1})" -f $dev.Name, $dev.Id) }
        } else {
            $status = if ($d.Status) { $d.Status } else { "OK" }
            if ($status -ne "OK") {
                $missing += $dev
                if ($Detail) { Say-Bad ("{0} -- present but in error: {1}" -f $dev.Name, $status) }
            } elseif ($Detail) {
                Say-Ok ("{0}" -f $dev.Name)
            }
        }
    }
    return ,$missing
}

# Interactive reseat wait, same contract as power-on.py's wait_for_reseat():
# [Enter] re-checks now and rearms the clock, [S] gives up on VR. Two clocks on
# purpose -- 90 s if nobody ever answers, 300 s from the last keypress -- so an
# unattended run can't hang and a human with their hands in the cable can't get
# cut off mid-reseat (that exact bug, T172, is why this shape exists).
function Wait-Reseat($recheck) {
    if ($Quick) { return "giveup" }
    Write-Host ""
    Say-Warn "Waiting for you to reconnect -- [Enter] recheck now | [S] continue without VR"
    $deadline = (Get-Date).AddSeconds(90)
    $answered = $false
    $lastPrint = Get-Date
    while ($true) {
        if ((Get-Date) -gt $deadline) {
            Write-Host ""
            if ($answered) { Say-Warn "Wait timed out (300s since the last key)." }
            else { Say-Warn "Wait timed out (nobody pressed anything)." }
            return "giveup"
        }
        while ([Console]::KeyAvailable) {
            $k = [Console]::ReadKey($true)
            if ($k.Key -eq "S") { return "skip" }
            $answered = $true
            $deadline = (Get-Date).AddSeconds(300)
            $lastPrint = (Get-Date).AddSeconds(-99)
        }
        if (& $recheck) { return "fixed" }
        if (((Get-Date) - $lastPrint).TotalSeconds -ge 10) {
            $left = [int]($deadline - (Get-Date)).TotalSeconds
            $u2 = (Test-Branch $USB2_BRANCH).Count -eq 0
            $ss = (Test-Branch $SS_BRANCH).Count -eq 0
            Say-Dim ("USB2 {0} | SuperSpeed {1}   [{2}s]" -f
                     $(if ($u2) { "OK" } else { "--" }),
                     $(if ($ss) { "OK" } else { "--" }), $left)
            $lastPrint = Get-Date
        }
        Start-Sleep -Milliseconds 400
    }
}

function Show-ReseatLadder($usb2Ok, $ssOk) {
    Say-Warn "You need to reconnect. Most likely fix first (docs/22, T171):"
    if (-not $usb2Ok -and -not $ssOk) {
        Say-Dim "  > Unplug the headset USB from the PC and plug it back in STRAIGHT and ALL THE WAY,"
        Say-Dim "    holding the cable weight with your other hand (it hangs and levers the plug)."
        Say-Dim "  > Use a REAR USB3 port on the motherboard (the CPU-fed ones). The front"
        Say-Dim "    ones and the chipset ones do not work for this headset."
    } elseif (-not $ssOk) {
        Say-Dim "  > The SuperSpeed branch is missing (the cameras). WITHOUT changing port: pull the"
        Say-Dim "    USB-C plug out of the adapter, ROTATE it 180 degrees and reinsert it firmly."
    } else {
        Say-Dim "  > The USB2 branch is missing (companion/audio). WITHOUT changing port: pull the"
        Say-Dim "    USB-C plug out of the adapter, ROTATE it 180 degrees and reinsert it firmly."
    }
    Say-Dim "  > Still the same? Try ANOTHER rear USB3 port (every port seats differently)."
    Say-Dim "  > Nothing? Reseat the connector at the visor end (behind the magnetic gasket), then"
    Say-Dim "    everything together: USB + DP + 18.5V brick out for ~1 min, then reconnect."
}

Write-Host "=== Powering on the HP Reverb G2 (Windows) ===" -ForegroundColor Green
Say-Dim "This runs on your normal monitor. It does not need administrator and does not touch anything on the system."

$problems = @()

# ---- 1/5: USB census ------------------------------------------------------
Say-Step 1 "Is everything connected?"
$missUsb2 = Test-Branch $USB2_BRANCH -Verbose
$missSs   = Test-Branch $SS_BRANCH -Verbose
$usb2Ok = $missUsb2.Count -eq 0
$ssOk   = $missSs.Count -eq 0

if ($usb2Ok -and $ssOk) {
    Say-Ok "5/5 headset parts respond (USB2 hub, companion, audio, SS hub, cameras)."
} else {
    Say-Bad ("USB2 branch {0} -- SuperSpeed branch {1}." -f
            $(if ($usb2Ok) { "OK" } else { "MISSING" }),
            $(if ($ssOk) { "OK" } else { "MISSING" }))
    Say-Dim "This is the picture that produces 'Headset not detected (108)': for WMR/Oasis the"
    Say-Dim "headset does not exist until BOTH branches enumerate -- the SuperSpeed one above all."
    Show-ReseatLadder $usb2Ok $ssOk
    $outcome = Wait-Reseat {
        ((Test-Branch $USB2_BRANCH).Count -eq 0) -and ((Test-Branch $SS_BRANCH).Count -eq 0)
    }
    if ($outcome -eq "fixed") {
        Say-Ok "5/5! Reconnected correctly, moving on."
        $usb2Ok = $true; $ssOk = $true
    } elseif ($outcome -eq "skip") {
        Say-Warn "Exiting at your request."
        exit 1
    } else {
        $problems += "The headset does not enumerate completely (" +
                     $(if ($ssOk) { "USB2" } else { "SuperSpeed" }) + " branch missing)."
    }
}

# ---- 2/5: which port ------------------------------------------------------
Say-Step 2 "Are you on a port that works?"
$hub = Get-G2Device "VID_04B4&PID_6504"
if (-not $hub) { $hub = Get-G2Device "VID_04B4&PID_6506" }
if ($hub) {
    try {
        $loc = (Get-PnpDeviceProperty -InstanceId $hub.InstanceId `
                -KeyName "DEVPKEY_Device_LocationInfo" -ErrorAction Stop).Data
        Say-Dim "Location according to Windows: $loc"
    } catch { }
    if ($ssOk) {
        Say-Ok "The SuperSpeed hub enumerated: you are on a real USB 3.x port."
    } else {
        Say-Bad "Only the USB2 face of the hub shows up: either the port is not USB3, or the plug did not seat."
        Say-Dim "Oasis requires USB 3.0 for controller tracking (Troubleshooting Guide)."
        $problems += "The headset is not on a usable USB 3.x port."
    }
} else {
    Say-Warn "No headset hub is enumerated -- nothing to locate yet."
}

# ---- 3/5: controllers over Bluetooth --------------------------------------
Say-Step 3 "Are the controllers bonded (to the headset radio)?"
Say-Dim "On the G2 the controllers do NOT go over the cable: they are Bluetooth against the headset radio"
Say-Dim "or the motherboard one. That is why the only time the Oasis app gets opened is to"
Say-Dim "pair/unlock them -- after that it never needs to be launched again."
$bt = @()
try {
    $bt = Get-PnpDevice -PresentOnly -ErrorAction Stop |
          Where-Object { $_.FriendlyName -match "Motion controller|Motion Controller" }
} catch { }
if ($bt.Count -ge 2) {
    Say-Ok ("{0} controllers paired and present." -f $bt.Count)
} elseif ($bt.Count -eq 1) {
    Say-Warn "Only 1 controller bonded. Pair the other one with Oasis' UNLOCK flow"
    Say-Dim "(it asks per controller, left first): battery-compartment button"
    Say-Dim "held until the slow LED pulse. The bond is against the HEADSET radio."
} else {
    Say-Warn "No bonded controllers seen (does not block the headset, but you will have no hands)."
    Say-Dim "Bond with Oasis' unlock flow (left first, battery button held until"
    Say-Dim "the slow pulse). The bond is against the headset radio, not against Windows."
}

# ---- 4/5: software state --------------------------------------------------
Say-Step 4 "Is the software the way Oasis needs it?"

$build = [System.Environment]::OSVersion.Version.Build
if ($build -ge 26100) {
    Say-Ok "Windows 11 24H2 or newer (build $build) -- the configuration Oasis supports."
} else {
    Say-Warn "Build ${build}: Oasis asks for 24H2 (build 26100+). On 23H2 you have to disable by hand"
    Say-Dim "the 'Mixed Reality' device in Device Manager."
}

$steam = $null
foreach ($p in @("${env:ProgramFiles(x86)}\Steam", "$env:ProgramFiles\Steam", "C:\Steam")) {
    if (Test-Path (Join-Path $p "steamapps")) { $steam = $p; break }
}
if ($steam) {
    Say-Ok "Steam at $steam"
    # Oasis is Steam app 3824490 -- installed means the appmanifest exists in
    # SOME library, not necessarily the default one.
    $libs = @($steam)
    $vdf = Join-Path $steam "steamapps\libraryfolders.vdf"
    if (Test-Path $vdf) {
        Select-String -Path $vdf -Pattern '"path"\s+"(.+?)"' -AllMatches |
            ForEach-Object { $_.Matches } |
            ForEach-Object { $libs += ($_.Groups[1].Value -replace '\\\\', '\') }
    }
    $oasisFound = $false
    $steamvrFound = $false
    foreach ($l in ($libs | Select-Object -Unique)) {
        if (Test-Path (Join-Path $l "steamapps\appmanifest_3824490.acf")) { $oasisFound = $true }
        if (Test-Path (Join-Path $l "steamapps\appmanifest_250820.acf"))   { $steamvrFound = $true }
    }
    if ($steamvrFound) { Say-Ok "SteamVR installed." }
    else { Say-Bad "SteamVR does not appear installed."; $problems += "SteamVR is missing." }
    if ($oasisFound) { Say-Ok "Oasis Driver installed (app 3824490)." }
    else { Say-Bad "Oasis Driver NOT installed -- without it, 24H2 has no WMR runtime of any kind."
           $problems += "The Oasis Driver is missing." }
} else {
    Say-Warn "Could not find the Steam installation in the usual paths."
}

# openvrpaths.vrpath is what SteamVR actually reads to find external drivers.
# A fresh Windows/Steam install losing this registration is a documented cause
# of "SteamVR doesn't see the G2 even though Windows does".
$vrpath = Join-Path $env:LOCALAPPDATA "openvr\openvrpaths.vrpath"
if (Test-Path $vrpath) {
    $txt = Get-Content $vrpath -Raw
    if ($txt -match "(?i)oasis") {
        Say-Ok "The Oasis driver is registered in openvrpaths.vrpath."
    } else {
        Say-Bad "openvrpaths.vrpath does NOT mention Oasis: SteamVR will not load the driver."
        Say-Dim "Fix: close SteamVR and run the unlock again from the Oasis app."
        $problems += "The Oasis driver is not registered in SteamVR."
    }
    # The legacy WMR driver declares hmd_presence "*.*" -- it claims ANY headset --
    # while Oasis declares exactly "045E.0659" (the HoloLens Sensors device, i.e.
    # the SuperSpeed branch). Two drivers claiming the same headset, one of them
    # backed by a runtime that no longer exists on 24H2, is a prime 422 shape.
    if ($txt -match "(?i)MixedRealityVRDriver") {
        Say-Warn "The old WMR driver is also registered (MixedRealityVRDriver, 'holographic')."
        Say-Dim "On 24H2 that driver no longer has a runtime behind it, and its manifest claims ANY"
        Say-Dim "headset (hmd_presence '*.*'), while Oasis claims only 045E.0659. Disable it:"
        Say-Dim "SteamVR > Settings > Startup/Shutdown > Manage Add-ons > 'holographic' OFF."
    }
} else {
    Say-Warn "$vrpath does not exist (SteamVR has never started on this account yet)."
}

# Safe mode: after a crash SteamVR disables third-party add-ons and then reports
# a generic failure on the next run -- one of the concrete 422 stories. Also
# read LastKnown, which answers "did Oasis EVER work on this machine?" -- if it
# names oasis, the unlock has been done here and a 108 is almost certainly USB.
if ($steam) {
    $vrsettings = Join-Path $steam "config\steamvr.vrsettings"
    if (Test-Path $vrsettings) {
        try {
            $s = Get-Content $vrsettings -Raw | ConvertFrom-Json
            if ($s.LastKnown -and $s.LastKnown.ActualHMDDriver) {
                Say-Ok ("Last headset seen by SteamVR: {0} via driver '{1}'" -f
                        $s.LastKnown.HMDModel, $s.LastKnown.ActualHMDDriver)
                if ($s.LastKnown.ActualHMDDriver -eq "oasis") {
                    Say-Dim "That is: the unlock was already done on this machine and Oasis worked. If it now gives 108,"
                    Say-Dim "look at step 1 before anything software-related."
                }
            }
            if ($s.driver_oasis -and $s.driver_oasis.PSObject.Properties.Name -contains "enable" -and
                -not $s.driver_oasis.enable) {
                Say-Bad "The 'oasis' add-on is DISABLED in steamvr.vrsettings -- a typical cause of 422."
                Say-Dim "SteamVR > Settings > Startup/Shutdown > Manage Add-ons: 'oasis' ON."
                $problems += "The Oasis add-on is disabled in SteamVR."
            } else {
                Say-Ok "The Oasis add-on is not listed as disabled."
            }
            if ($s.driver_holographic -and $s.driver_holographic.PSObject.Properties.Name -contains "enable" -and
                -not $s.driver_holographic.enable) {
                Say-Ok "The old 'holographic' (WMR) add-on is listed as disabled, as it should be on 24H2."
            }
        } catch {
            Say-Warn "Could not read steamvr.vrsettings as JSON ($($_.Exception.Message))."
        }
    }
}

# Leftovers of the old stack. Not fatal by themselves on 24H2 (the Portal is
# gone from the OS), but the unlock tool's documented "MR USB device: 6" error
# is exactly the Portal holding the device open on older builds.
$mrp = $null
try { $mrp = Get-AppxPackage -Name "Microsoft.MixedReality.Portal" -ErrorAction Stop } catch { }
if ($mrp) {
    Say-Warn "Mixed Reality Portal is still installed: it can grab the USB device and make"
    Say-Dim "the unlock fail ('Unexpected error while opening MR USB device: 6')."
} else {
    Say-Ok "Mixed Reality Portal not installed (expected on 24H2)."
}

# ---- Bonus: Windows tuning for measurements -------------------------------
# Everything here exists because it can silently corrupt a MEASUREMENT, not
# because VR won't run without it. USB selective suspend in particular is the
# one that overlaps this project's oldest ghost: a branch that "disconnects on
# its own" reads exactly like the marginal contact in docs/22, and the two are
# worth telling apart before blaming the cable again.
# Power setting GUIDs are language-independent; powercfg's OUTPUT is not, so
# current values are read from the registry, never by parsing its text.
$GUID_SUB_USB  = "2a737441-1930-4402-8d77-b2bebba308a3"
$GUID_USB_SUSP = "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"
$GUID_SUB_PCI  = "501a4d13-42af-4429-9fd1-a8218c268e20"
$GUID_ASPM     = "ee12f906-d277-404b-b6da-e5fa1a576df5"
$GUID_SUB_PROC = "54533251-82be-4824-96c1-47b60b740d00"
$GUID_PROC_MIN = "893dee8e-2bef-41e0-89c6-b55d0929964c"
$GUID_PROC_MAX = "bc5038f7-23e0-4960-96da-33abaf5935ec"

function Get-ActiveSchemeGuid {
    $out = & powercfg /getactivescheme 2>$null
    if ($out -match '([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})') { return $Matches[1] }
    return $null
}
function Get-PowerSetting($sub, $setting) {
    $g = Get-ActiveSchemeGuid
    if (-not $g) { return $null }
    $k = "HKLM:\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes\$g\$sub\$setting"
    try { return (Get-ItemProperty -Path $k -Name ACSettingIndex -ErrorAction Stop).ACSettingIndex }
    catch { return $null }
}
function Show-Setting($label, $value, $wanted) {
    if ($null -eq $value) { Say-Dim "$label : (not customized, the plan default)" }
    elseif ($value -eq $wanted) { Say-Ok "$label : $value (what we want)" }
    else { Say-Warn "$label : $value (we want $wanted)" }
}

Write-Host ""
Write-Host "> Windows settings that affect measurements" -ForegroundColor Green
$isAdmin = ([Security.Principal.WindowsPrincipal] `
            [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Show-Setting "USB selective suspend (0 = off)" (Get-PowerSetting $GUID_SUB_USB $GUID_USB_SUSP) 0
Show-Setting "PCI Express ASPM (0 = off)"         (Get-PowerSetting $GUID_SUB_PCI $GUID_ASPM) 0
Show-Setting "CPU minimum % (100 = never lower)"  (Get-PowerSetting $GUID_SUB_PROC $GUID_PROC_MIN) 100
Show-Setting "CPU maximum %"                      (Get-PowerSetting $GUID_SUB_PROC $GUID_PROC_MAX) 100

$hiberboot = $null
try {
    $hiberboot = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power" `
                  -Name HiberbootEnabled -ErrorAction Stop).HiberbootEnabled
} catch { }
if ($hiberboot -eq 1) {
    Say-Warn "Fast startup is ON."
    Say-Dim "Turning it off matters twice over: Windows does not boot from a frozen state (reproducible"
    Say-Dim "measurements) and it leaves NTFS clean, which is what allows writing to C: from Linux."
} elseif ($null -ne $hiberboot) {
    Say-Ok "Fast startup is off."
}

# Per-device USB power management -- the Device Manager checkbox "let the
# computer turn off this device", but read/written where it actually lives.
$usbPm = @()
try {
    foreach ($d in (Get-PnpDevice -Class USB -PresentOnly -ErrorAction Stop)) {
        $k = "HKLM:\SYSTEM\CurrentControlSet\Enum\$($d.InstanceId)\Device Parameters"
        try {
            $v = Get-ItemProperty -Path $k -ErrorAction Stop
            if ($v.EnhancedPowerManagementEnabled -eq 1 -or $v.SelectiveSuspendEnabled -eq 1) {
                $usbPm += $d
            }
        } catch { }
    }
} catch { }
if ($usbPm.Count -gt 0) {
    Say-Warn ("{0} USB devices have their own power saving active (hubs included)." -f $usbPm.Count)
} else {
    Say-Ok "No USB device has its own power saving active (or it could not be read)."
}

if ($Tune) {
    if (-not $isAdmin) {
        Say-Bad "-Tune needs PowerShell AS ADMINISTRATOR. Nothing was changed."
    } else {
        Say-Warn "Applying settings (this changes system configuration)..."
        & powercfg /setactive SCHEME_MIN 2>$null            # High performance
        & powercfg /setacvalueindex SCHEME_CURRENT $GUID_SUB_USB  $GUID_USB_SUSP 0
        & powercfg /setacvalueindex SCHEME_CURRENT $GUID_SUB_PCI  $GUID_ASPM     0
        & powercfg /setacvalueindex SCHEME_CURRENT $GUID_SUB_PROC $GUID_PROC_MIN 100
        & powercfg /setacvalueindex SCHEME_CURRENT $GUID_SUB_PROC $GUID_PROC_MAX 100
        & powercfg /change standby-timeout-ac 0
        & powercfg /change monitor-timeout-ac 0
        & powercfg /change disk-timeout-ac 0
        & powercfg /setactive SCHEME_CURRENT
        Say-Ok "Power plan set to high performance, no USB suspend/ASPM, CPU at 100%."
        & powercfg /h off 2>$null
        Say-Ok "Hibernation and fast startup off (and no hiberfil.sys)."
        $n = 0
        foreach ($d in (Get-PnpDevice -Class USB -PresentOnly)) {
            $k = "HKLM:\SYSTEM\CurrentControlSet\Enum\$($d.InstanceId)\Device Parameters"
            if (Test-Path $k) {
                try {
                    New-ItemProperty -Path $k -Name EnhancedPowerManagementEnabled -Value 0 `
                        -PropertyType DWord -Force -ErrorAction Stop | Out-Null
                    New-ItemProperty -Path $k -Name SelectiveSuspendEnabled -Value 0 `
                        -PropertyType DWord -Force -ErrorAction Stop | Out-Null
                    New-ItemProperty -Path $k -Name AllowIdleIrpInD3 -Value 0 `
                        -PropertyType DWord -Force -ErrorAction Stop | Out-Null
                    $n++
                } catch { }
            }
        }
        Say-Ok "$n USB devices had their own power saving disabled (effective after a reboot)."
        try {
            Set-ItemProperty "HKCU:\System\GameConfigStore" -Name GameDVR_Enabled -Value 0 -ErrorAction Stop
            Say-Ok "Game DVR turned off (it used to record in the background during measurements)."
        } catch { }
        Write-Host ""
        Say-Dim "To undo: powercfg /setactive SCHEME_BALANCED ; powercfg /h on ; and set back to 1"
        Say-Dim "the EnhancedPowerManagementEnabled/SelectiveSuspendEnabled values that were set to 0."
    }
} else {
    Say-Dim "To apply all of this: run this script AS ADMINISTRATOR with -Tune."
}

# ---- 5/5: verdict + error triage -----------------------------------------
Say-Step 5 "Verdict"
if ($problems.Count -eq 0) {
    Write-Host "  READY. " -ForegroundColor Green -NoNewline
    Write-Host "Start SteamVR: the headset should show up on its own (no need to open Oasis)."
    Say-Dim "If this is the first time on this PC, or you changed GPU / reinstalled Windows, you must"
    Say-Dim "run the unlock once from the Oasis app -- see docs/31."
} else {
    Write-Host "  SOMETHING IS MISSING:" -ForegroundColor Yellow
    foreach ($p in $problems) { Say-Dim "  - $p" }
}

Write-Host ""
Write-Host "--- What the errors you have already seen mean ---" -ForegroundColor Cyan
Say-Dim "108 'Headset not detected': SteamVR has NO headset at all. On this machine that"
Say-Dim "     always coincided with the incomplete enumeration in step 1 (typically the"
Say-Dim "     SuperSpeed branch not coming up). It is a cable/port problem, not software:"
Say-Dim "     fix step 1 and it goes away. Second suspect, if step 1 gives 5/5:"
Say-Dim "     the Oasis driver not registered in openvrpaths.vrpath (step 4)."
Say-Dim "422 'SteamVR encountered an unexpected problem': SteamVR DID start and the driver"
Say-Dim "     failed afterwards. That is why it is intermittent and why moving the cable does not fix it."
Say-Dim "     Causes in order: Oasis add-on disabled by safe mode after a crash,"
Say-Dim "     unlock that must be redone (GPU change / reinstall), SteamVR beta, and"
Say-Dim "     corrupt environment data (delete WindowsHolographicDevices and redo Room Setup)."
Say-Dim "498 'Failed to lease display': not a Windows error -- it is the native SteamVR attempt"
Say-Dim "     on Linux (docs/pruebas.jsonl T170). If it shows up here, do not mix it up with the above."
Write-Host ""
Say-Dim "Full manual: docs/31-windows-bringup-and-errors.md"
