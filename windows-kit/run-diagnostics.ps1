<#
.SYNOPSIS
    Captures EVERYTHING needed from the Windows side for the HP Reverb G2
    90Hz diagnostic, in a single run.

.DESCRIPTION
    Replaces gathering tools by hand. Each run:
      1. Finds the tools on its own (Wireshark/tshark, USBDeview, dxdiag,
         nvidia-smi) -- in the kit folder and in the typical install
         paths -- and prints what it found and what's missing.
      2. Gathers, ON ITS OWN, without pressing anything, everything with a CLI:
         - USBDeview: complete list of USB devices (text).
         - DxDiag: complete DirectX report.
         - nvidia-smi: GPU state (clocks, PCIe, driver).
         - Native PowerShell: video adapter and monitors (WMI), without
           depending on any third-party tool.
      3. Captures USB from ALL USBPcap interfaces at once, to catch the
         exact moment the headset switches to 60 or 90Hz.
      4. For what does NOT have a CLI (CRU, HWiNFO64, the NVIDIA panel), it
         opens the tool on its own and tells you EXACTLY what to look at and
         what to capture -- you just watch the screen and take the screenshot.
      5. Leaves everything in a single timestamped folder, ready to take with you.

.PARAMETER Label
    Name of this run: "60hz", "90hz", "idle" (headset connected without the
    runtime), etc. Prepended to every file it generates.

.EXAMPLE
    .\run-diagnostics.ps1 -Label 90hz

    Run in PowerShell AS ADMINISTRATOR from this folder (USBPcap needs the
    driver at admin level; without admin, only this part fails and the rest
    continues).
#>
param(
    [Parameter(Mandatory = $true)][string]$Label
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Stamp     = Get-Date -Format "yyyyMMdd-HHmmss"
$OutDir    = Join-Path $ScriptDir ("run_{0}_{1}" -f $Label, $Stamp)
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Section($title) {
    Write-Host ""
    Write-Host "=== $title ===" -ForegroundColor Cyan
}

function Find-First($paths) {
    foreach ($p in $paths) { if ($p -and (Test-Path $p)) { return $p } }
    return $null
}

# Looks for a tool that may not be at a fixed path: first the given
# local/typical paths, then PATH, then the "App Paths" registry key
# (that's how "nvcplui.exe" normally starts without a path), and finally a
# recursive search scoped to whatever root folders are passed in. Useful for
# tools that can't be packaged portable (they depend on another product's
# installer, like the NVIDIA panel) and whose exact path varies between
# driver versions.
function Find-Tool($exeName, $explicitPaths, $searchRoots) {
    $found = Find-First $explicitPaths
    if ($found) { return $found }

    $cmd = Get-Command $exeName -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $appPathKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$exeName"
    $appPath = (Get-ItemProperty -Path $appPathKey -ErrorAction SilentlyContinue).'(default)'
    if ($appPath -and (Test-Path $appPath)) { return $appPath }

    foreach ($root in $searchRoots) {
        if (Test-Path $root) {
            $hit = Get-ChildItem -Path $root -Recurse -Filter $exeName -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($hit) { return $hit.FullName }
        }
    }
    return $null
}

# ============================================================================
# 1. DISCOVER TOOLS
# ============================================================================
Section "looking for installed tools"

$Tshark  = Find-Tool "tshark.exe"  @("C:\Program Files\Wireshark\tshark.exe")  @("C:\Program Files\Wireshark")
$Dumpcap = Find-Tool "dumpcap.exe" @("C:\Program Files\Wireshark\dumpcap.exe") @("C:\Program Files\Wireshark")
$USBDeview = Find-First @(
    (Join-Path $ScriptDir "usbdeview-x64\USBDeview.exe"),
    (Join-Path $ScriptDir "USBDeview.exe")
)
$CRU = Find-First @(
    (Join-Path $ScriptDir "cru-1.5.3\CRU.exe"),
    (Join-Path $ScriptDir "CRU.exe")
)
$HWiNFO = Find-First @(
    (Join-Path $ScriptDir "hwinfo64\HWiNFO64.exe"),
    "C:\Program Files\HWiNFO64\HWiNFO64.exe",
    (Join-Path $ScriptDir "HWiNFO64.exe")
)
$GPUZ = Find-First @(
    (Join-Path $ScriptDir "gpuz\GPU-Z.exe"),
    (Join-Path $ScriptDir "GPU-Z.exe")
)
$NvidiaSmi = Find-Tool "nvidia-smi.exe" @(
    "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    "C:\Windows\System32\nvidia-smi.exe"
) @("C:\Program Files\NVIDIA Corporation")
# The NVIDIA panel can't be packaged portable (it depends on the installed
# driver) and its exact path changes between versions -- sometimes it's not
# even the classic .exe, it's a packaged app. Find-Tool covers PATH +
# "App Paths" registry + recursive search, which is the same thing Windows
# does when you type "nvcplui" in the start menu.
$NvcpExe = Find-Tool "nvcplui.exe" @(
    "C:\Program Files\NVIDIA Corporation\Control Panel Client\nvcplui.exe"
) @("C:\Program Files\NVIDIA Corporation")

$tools = [ordered]@{
    "tshark (Wireshark+USBPcap)" = $Tshark
    "dumpcap"                    = $Dumpcap
    "USBDeview"                  = $USBDeview
    "CRU"                        = $CRU
    "HWiNFO64"                   = $HWiNFO
    "GPU-Z"                      = $GPUZ
    "nvidia-smi"                 = $NvidiaSmi
    "NVIDIA panel"               = $NvcpExe
}
foreach ($t in $tools.GetEnumerator()) {
    if ($t.Value) { Write-Host ("  [OK]      {0,-28} {1}" -f $t.Key, $t.Value) -ForegroundColor Green }
    else          { Write-Host ("  [MISSING] {0,-28}" -f $t.Key) -ForegroundColor Yellow }
}

# ============================================================================
# 2. WHAT GETS GATHERED AUTOMATICALLY, NO GUI
# ============================================================================
Section "collecting everything with a command line (nothing to touch)"

if ($USBDeview) {
    $f = Join-Path $OutDir "$Label-usbdeview.txt"
    & $USBDeview /stext $f
    Write-Host "  USBDeview -> $f"
} else {
    Write-Host "  USBDeview: not found, skipped."
}

if ($NvidiaSmi) {
    $f = Join-Path $OutDir "$Label-nvidia-smi.txt"
    & $NvidiaSmi -q > $f
    Write-Host "  nvidia-smi -q -> $f"
} else {
    Write-Host "  nvidia-smi: not found, skipped."
}

Write-Host "  Native PowerShell: video adapter and monitors (WMI)..."
$f = Join-Path $OutDir "$Label-wmi-display.txt"
"--- Win32_VideoController ---"                                   | Out-File $f
Get-CimInstance Win32_VideoController | Format-List *             | Out-File $f -Append
"--- WmiMonitorID (root\wmi) ---"                                  | Out-File $f -Append
Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorID -ErrorAction SilentlyContinue |
    Format-List *                                                  | Out-File $f -Append
"--- WmiMonitorBasicDisplayParams (root\wmi) ---"                  | Out-File $f -Append
Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorBasicDisplayParams -ErrorAction SilentlyContinue |
    Format-List *                                                  | Out-File $f -Append
Write-Host "  WMI display/monitor -> $f"

Write-Host "  DxDiag (async, this takes about 15-20s)..."
$dxf = Join-Path $OutDir "$Label-dxdiag.txt"
Start-Process -FilePath "dxdiag.exe" -ArgumentList @("/t", $dxf) -Wait
if (Test-Path $dxf) { Write-Host "  DxDiag -> $dxf" }
else { Write-Host "  DxDiag: did not generate the file in time, retry manually if needed." }

# ============================================================================
# 3. USB CAPTURE -- all USBPcap interfaces at once
# ============================================================================
Section "USB capture"

if (-not $Tshark -or -not $Dumpcap) {
    Write-Host "  tshark/dumpcap not found -- WITHOUT THIS THERE IS NO USB CAPTURE." -ForegroundColor Red
    Write-Host "  Install Wireshark with the USBPcap component checked, and reboot."
} else {
    $ifaceLines = & $Tshark -D | Select-String "USBPcap"
    if (-not $ifaceLines) {
        Write-Host "  No USBPcap interface shows up in 'tshark -D'. Reinstall/reboot." -ForegroundColor Red
    } else {
        $ifaces = foreach ($line in $ifaceLines) {
            if ($line -match '^(\d+)\.\s+(\S+)') { [PSCustomObject]@{ Num = $Matches[1]; Name = $Matches[2] } }
        }
        Write-Host "  USBPcap interfaces found (ALL will be captured):"
        $ifaces | ForEach-Object { Write-Host ("    {0}. {1}" -f $_.Num, $_.Name) }

        Write-Host ""
        Write-Host "  =========================================================="
        Write-Host "   The headset's companion device only sends its HID state when"
        Write-Host "   something CHANGES -- the capture needs to be SHORT and placed"
        Write-Host "   around the moment of the transition, not a long steady period."
        Write-Host ""
        Write-Host "   1. Headset connected, SteamVR/WMR runtime STILL CLOSED"
        Write-Host "      (without that the panel has no 'mode', it's off)."
        Write-Host "   2. Start the capture with the Enter below."
        Write-Host "   3. ONLY THEN bring up the runtime at the '$Label' frequency."
        Write-Host "   4. Put it on, confirm the image. Come back and Enter, max 10-15s later."
        Write-Host "  =========================================================="
        Read-Host "Enter to start the USB capture"

        $procs = foreach ($ifc in $ifaces) {
            $file = Join-Path $OutDir ("{0}_USBPcap{1}.pcapng" -f $Label, $ifc.Num)
            Start-Process -FilePath $Dumpcap -ArgumentList @("-i", $ifc.Num, "-w", $file) -PassThru -WindowStyle Hidden
        }
        Write-Host "  Capturing on $($ifaces.Count) interface(s)..." -ForegroundColor Yellow
        Read-Host "Enter to STOP"

        foreach ($p in $procs) { if (-not $p.HasExited) { Stop-Process -Id $p.Id -ErrorAction SilentlyContinue } }
        Start-Sleep -Seconds 2

        Write-Host "  exporting (the full .pcapng is kept, uncropped -- size doesn't matter,"
        Write-Host "  what matters is not losing anything from the captured moment)..."
        foreach ($ifc in $ifaces) {
            $raw = Join-Path $OutDir ("{0}_USBPcap{1}.pcapng" -f $Label, $ifc.Num)
            if (-not (Test-Path $raw) -or (Get-Item $raw).Length -eq 0) {
                Write-Host "    USBPcap$($ifc.Num): no data, skipping."
                continue
            }
            $tsv = Join-Path $OutDir ("{0}_USBPcap{1}.tsv" -f $Label, $ifc.Num)
            & $Tshark -r $raw -T fields `
                -e frame.time_relative -e usb.device_address -e usb.endpoint_address `
                -e usb.transfer_type -e usb.bmRequestType -e usb.setup.bRequest `
                -e usb.setup.wValue -e usb.capdata -e usbhid.data > $tsv
            $hit = Select-String -Path $tsv -Pattern "0500" -Quiet
            $marca = if ($hit) { "<-- THIS IS the headset's interface" } else { "" }
            Write-Host ("    USBPcap{0}: {1} bytes  {2}" -f $ifc.Num, (Get-Item $raw).Length, $marca)
        }
    }
}

# ============================================================================
# 4. WHAT HAS NO CLI -- opens itself, tells you exactly what to look at
# ============================================================================
Section "manual tools -- open by themselves, watch the screen"

if ($CRU) {
    Write-Host "  Opening CRU..." -ForegroundColor Yellow
    Write-Host "    -> Select the Reverb G2, go to 'Detailed resolutions'."
    Write-Host "    -> Screenshot of that whole window as '$Label-cru.png'."
    Write-Host "    -> Close CRU WITHOUT SAVING (Cancel, not OK)."
    Start-Process -FilePath $CRU
} else {
    Write-Host "  CRU not found in this folder -- download it from monitortests.com if needed."
}

if ($HWiNFO) {
    Write-Host "  Opening HWiNFO64..." -ForegroundColor Yellow
    Write-Host "    -> Sensors -> look for Pixel Clock / Link Rate / Lane Count for the GPU/display."
    Write-Host "    -> Screenshot as '$Label-hwinfo.png' (even if nothing shows up, that's still a data point)."
    Start-Process -FilePath $HWiNFO
} else {
    Write-Host "  HWiNFO64 not found -- download it (the 'Portable' version, not the installer) from hwinfo.com/download."
}

if ($GPUZ) {
    Write-Host "  Opening GPU-Z..." -ForegroundColor Yellow
    Write-Host "    -> 'Graphics Card' tab: screenshot as '$Label-gpuz.png'."
    Write-Host "    -> if there's a sensors tab with Link Speed/Width, capture that too."
    Start-Process -FilePath $GPUZ
} else {
    Write-Host "  GPU-Z not found -- download it (already portable) from techpowerup.com/gpuz."
}

if ($NvcpExe) {
    Write-Host "  Opening the NVIDIA Control Panel..." -ForegroundColor Yellow
    Write-Host "    -> 'Change resolution': screenshot as '$Label-nvcp-resolution.png'."
    Write-Host "    -> Help -> System Information: 'Save to text file' as"
    Write-Host "       '$Label-nvidia-sysinfo.txt' directly in $OutDir"
    Start-Process -FilePath $NvcpExe
} else {
    Write-Host "  NVIDIA panel: could not find it automatically (might be the new packaged version)."
    Write-Host "    Open it manually: right-click on the desktop -> 'NVIDIA Control Panel'."
}

Write-Host ""
Write-Host "==========================================================================="
Write-Host " When you're done with the manual windows, save the screenshots/files"
Write-Host " DIRECTLY in:"
Write-Host "   $OutDir"
Write-Host " so everything stays together. That whole folder is what needs to be collected."
Write-Host "===========================================================================" -ForegroundColor Green
