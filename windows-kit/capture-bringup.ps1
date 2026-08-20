<#
.SYNOPSIS
  One Windows session that captures EVERYTHING we need from the Windows/Oasis side in a single
  continuous USBPcap trace: the controller pairing wire format, the headset activation bytes,
  and (for free) the USB2 storm/re-enumeration timing. Built for reverb-g2 T236/T238.

.DESCRIPTION
  Why one capture: USBPcap records the whole device tree continuously, so we start it ONCE, drive
  the entire Oasis bring-up through it, and log a timestamp at each step. Back on Linux, each
  event is found in the trace by its timestamp -- no need to capture separately per action.

  THE GOAL, in priority order:
    1. PAIRING (the world-first enabler). The right controller is currently UNPAIRED (a failed
       Linux attempt, T236). Re-pairing it through Oasis both RECOVERS it and captures the real
       {0x16, 0x05, ...} pairing command Linux was missing -- it tunnels through the HoloLens
       Sensors device 045e:0659, which USBPcap sees.
    2. HEADSET ("casco") activation: what Oasis sends the companion 03f0:0580 to bring the panel
       up and bind the USB -- the other half of docs/31's "two Oasis functions".
    3. Battery cross-check: Oasis % per controller + the 1.2 V switch position, with the cells
       straight from the Linux session (no recharge), so the raw-byte fit in docs/46 gets its pair.

  DELIBERATELY NOT here (keep it safe and short): the two failure-mode captures (chipset port,
  port-moved-without-relaunch) live in a clearly-separate optional phase in the runbook -- do them
  only after this core capture is confirmed good.

  Run AS ADMINISTRATOR (USBPcap needs it). Needs Wireshark installed with the USBPcap component.

.PARAMETER OutDir
  Where the trace + logs land. Default: a timestamped folder next to this script.
#>
[CmdletBinding()]
param([string]$OutDir = $null)

$ErrorActionPreference = 'Stop'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $OutDir) { $OutDir = Join-Path $PSScriptRoot "bringup-capture-$stamp" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$log = Join-Path $OutDir 'action-log.txt'

function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'HH:mm:ss.fff'), $msg
    Add-Content -Path $log -Value $line
    Write-Host $line -ForegroundColor Cyan
}
function Step($n, $prompt) {
    Write-Host ""
    Write-Host "  [$n] $prompt" -ForegroundColor Yellow
    Read-Host "      (do it, then press Enter to timestamp it)" | Out-Null
    Log "STEP $n done: $prompt"
}

# --- admin + tools ---
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Must run AS ADMINISTRATOR (USBPcap needs it)." -ForegroundColor Red; exit 1
}
$dumpcap = @("C:\Program Files\Wireshark\dumpcap.exe","C:\Program Files (x86)\Wireshark\dumpcap.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $dumpcap) { Write-Host "dumpcap.exe not found. Install Wireshark WITH the USBPcap component, reboot, retry." -ForegroundColor Red; exit 1 }

# --- census helper (branch-labelled, matches the Linux census) ---
$G2 = @(
  @{Id="VID_04B4&PID_6504";N="hub-ss"}, @{Id="VID_045E&PID_0659";N="sensors"},
  @{Id="VID_04B4&PID_6506";N="hub-usb2"}, @{Id="VID_03F0&PID_0580";N="companion"}, @{Id="VID_0BDA&PID_4C15";N="audio"})
function Census($tag) {
    $present = foreach ($d in $G2) {
        $p = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -like "*$($d.Id)*" } | Select-Object -First 1
        "{0}={1}" -f $d.N, ($(if ($p) { if ($p.Status -eq 'OK') {'OK'} else {"PROBLEM:$($p.Status)"} } else {'ABSENT'}))
    }
    Log "CENSUS ($tag): $($present -join '  ')"
}

Write-Host ""
Write-Host "=== reverb-g2 bring-up capture ===" -ForegroundColor Green
Write-Host "  output: $OutDir"
Write-Host "  Follow the runbook (BRINGUP-CAPTURE-RUNBOOK.md). This script starts one USBPcap"
Write-Host "  trace and timestamps each step you confirm, so every event is findable on Linux."
Write-Host ""

# --- start capture on ALL USBPcap interfaces (headset spans two branches) ---
$ifaces = & $dumpcap -D 2>$null | Select-String "USBPcap"
if (-not $ifaces) { Write-Host "No USBPcap interface in 'dumpcap -D'. Reinstall Wireshark with USBPcap + reboot." -ForegroundColor Red; exit 1 }
$procs = @()
foreach ($m in $ifaces) {
    if ($m -match '^(\d+)\.\s') {
        $num = $matches[1]
        $f = Join-Path $OutDir ("bringup_USBPcap{0}.pcapng" -f $num)
        $procs += Start-Process -FilePath $dumpcap -ArgumentList @("-i",$num,"-w",$f) -PassThru -WindowStyle Hidden
        Log "CAPTURE started on USBPcap$num -> $f"
    }
}
Start-Sleep 2
Census "start"

# --- guided, timestamped bring-up ---
Write-Host ""
Write-Host "  --- PHASE 1: core capture (pairing + headset) ---" -ForegroundColor Green
Step 1 "Confirm the headset is on a rear CPU USB3 port and powered (18.5 V brick in)."
Census "headset-plugged"
Step 2 "Launch the Oasis 'Unlock your headset & controllers' tool from Steam."
Step 3 "When it asks, UNPLUG the headset USB at the PC end, wait ~5 s, plug it back (SAME port). [captures activation + re-enumeration]"
Census "after-replug"
Step 4 "LEFT controller: it is already paired -- when Oasis asks about the left, choose to KEEP it (No)."
Step 5 "RIGHT controller: choose to PAIR it. Power it on, hold the battery-compartment button until the LEDs pulse slowly, let Oasis complete. [THIS is the pairing capture]"
Census "after-pairing"
Step 6 "Power-cycle both controllers off and on, as the tool asks."
Census "after-cycle"
Step 7 "Open Oasis / SteamVR: note the BATTERY % for each controller and the 1.2 V switch state. Photograph both. [docs/46 cross-check]"
Step 8 "Optional: launch SteamVR briefly to confirm both controllers track. Then close it."

Write-Host ""
Write-Host "  Phase 1 done. Phase 2 (failure modes) is OPTIONAL and in the runbook -- skip if unsure." -ForegroundColor Green
$doP2 = Read-Host "  Do phase 2 failure-mode captures now? (y/N)"
if ($doP2 -eq 'y') {
    Step "2a" "Move the headset to a CHIPSET USB3 port (the runbook names which). Watch what Oasis says."
    Census "chipset-port"
    Step "2b" "Move it back to the good CPU port but do NOT relaunch Oasis. Note the symptom."
    Census "moved-no-relaunch"
    Step "2c" "Relaunch Oasis so it re-binds. Confirm it works again."
    Census "rebind"
}

# --- stop + package ---
Write-Host ""
Log "stopping capture"
foreach ($p in $procs) { try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {} }
Start-Sleep 2

# snapshots that help the Linux-side decode
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_(04B4|045E|03F0|0BDA)' } |
    Select-Object Status, Class, FriendlyName, InstanceId | Format-List |
    Out-File (Join-Path $OutDir 'pnp-devices.txt')
"Windows $([Environment]::OSVersion.Version)  $(Get-Date -Format o)" | Out-File (Join-Path $OutDir 'session.txt')

Write-Host ""
Write-Host "=== done ===" -ForegroundColor Green
Write-Host "  Everything is in: $OutDir" -ForegroundColor Green
Write-Host "  Zip that folder and bring it to Linux. Decode with:" 
Write-Host "    scripts/analyze-pairing.py   (the {0x16,...} pairing command)"
Write-Host "    scripts/analyze-hid.py       (the companion / panel activation)"
Write-Host "  The action-log.txt timestamps tell you where each event is in the trace."
