<#
.SYNOPSIS
  Long-running monitor for USB2-branch instability on the HP Reverb G2, so the Linux-side
  "companion storm" can be compared against Windows with the hardware held constant.

.DESCRIPTION
  THE QUESTION THIS ANSWERS. On Linux the headset's USB2 branch (hub 04B4:6506 + companion
  03F0:0580 + audio 0BDA:4C15) re-enumerates constantly: measured 2026-08-19 at 6-18 events
  per minute early in a session, climbing to 28-62/min after two hours, 796 events in 25
  minutes at its worst. The companion carries panel control, IPD/proximity (and therefore
  XR_EXT_user_presence), and audio; when it storms, HID reads fail at ~83/s and features
  that ride it silently freeze.

  The cable was suspected for months. It should not have been: the same cable and headset
  run long sessions on Windows normally, which is a controlled experiment with the hardware
  fixed and the OS as the only variable. This script turns that impression into a number.

  WHAT MAKES THE COMPARISON FAIR, and it is the whole point:
    * Same physical link, same headset, same PC.
    * Poll fast enough to see what Linux sees. Linux measured USB2 dropouts lasting ~3 s
      (docs/22, T183). A 1 s poll can straddle one; 250 ms cannot miss one. Polling slower
      than the event you are hunting is how you prove an absence you never could have seen.
    * Two independent instruments, because a polled sample can always miss: presence polling
      AND the Kernel-PnP event log, which records arrivals/removals the OS itself saw.
      If they disagree, believe the event log and say so.

  WHAT A RESULT MEANS:
    * Windows shows a comparable event rate  -> the instability is the LINK, and Linux is
      merely more sensitive to it. The cable/connector goes back on the table.
    * Windows shows near-zero over the same wall-clock and the same real use -> the link is
      fine and the fault is in the Linux USB stack (companion HID handling, autosuspend,
      host-controller behaviour). That is a bug someone can fix, not a part to buy.

  Deliberately NOT a driver-level trace: USBPcap/ETW would say more but needs installation
  and admin, and this question only needs event counts over a long session. Run it, play a
  game for an hour, read the summary.

.PARAMETER Minutes
  How long to monitor. Default 60. Use the real length of a real session; a five-minute
  sample of a fault that takes two hours to develop proves nothing.

.PARAMETER IntervalMs
  Poll interval, default 250 ms. See above for why this is not 1000.

.PARAMETER OutDir
  Where the CSV and summary land. Default: the script's own directory.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\usb-storm-monitor.ps1 -Minutes 90
#>

[CmdletBinding()]
param(
    [int]$Minutes = 60,
    [int]$IntervalMs = 250,
    [string]$OutDir = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'

# Same identifiers and same branch split power-on.ps1 uses -- keep them in sync.
$Usb2Branch = @(
    @{ Id = "VID_04B4&PID_6506"; Name = "hub-usb2" },
    @{ Id = "VID_03F0&PID_0580"; Name = "companion" },
    @{ Id = "VID_0BDA&PID_4C15"; Name = "audio" }
)
$Usb3Branch = @(
    @{ Id = "VID_04B4&PID_6504"; Name = "hub-ss" },
    @{ Id = "VID_045E&PID_0659"; Name = "hololens-sensors" }
)
$AllDevices = $Usb2Branch + $Usb3Branch

function Get-DeviceState($idFragment) {
    # Present AND not in an error state. A device sitting in Device Manager with problem
    # code 43/10 is exactly the "it is listed so it must be fine" trap power-on.ps1 warns
    # about, and it would read as healthy to a naive presence check.
    try {
        $d = Get-PnpDevice -PresentOnly -ErrorAction Stop |
             Where-Object { $_.InstanceId -like "*$idFragment*" } |
             Select-Object -First 1
        if ($null -eq $d) { return "ABSENT" }
        if ($d.Status -ne "OK") { return "PROBLEM:$($d.Status)" }
        return "OK"
    } catch {
        return "QUERY-FAILED"
    }
}

$stamp     = Get-Date -Format "yyyyMMdd-HHmmss"
$csvPath   = Join-Path $OutDir "usb-storm-$stamp.csv"
$summary   = Join-Path $OutDir "usb-storm-$stamp.txt"
$startTime = Get-Date
$endTime   = $startTime.AddMinutes($Minutes)

Write-Host ""
Write-Host "USB storm monitor -- HP Reverb G2" -ForegroundColor Cyan
Write-Host "  duration   : $Minutes min (until $($endTime.ToString('HH:mm:ss')))"
Write-Host "  poll       : every $IntervalMs ms"
Write-Host "  transitions: $csvPath"
Write-Host ""
Write-Host "  Use the headset normally while this runs -- play, look around, move the" -ForegroundColor DarkGray
Write-Host "  controllers. An idle capture answers a different question than a used one," -ForegroundColor DarkGray
Write-Host "  and on Linux this fault was measured in BOTH states." -ForegroundColor DarkGray
Write-Host ""

"timestamp,device,from,to" | Out-File -FilePath $csvPath -Encoding utf8

$state = @{}
foreach ($dev in $AllDevices) { $state[$dev.Name] = Get-DeviceState $dev.Id }
$transitions = @{}
foreach ($dev in $AllDevices) { $transitions[$dev.Name] = 0 }

Write-Host "  initial state:"
foreach ($dev in $AllDevices) {
    $mark = if ($state[$dev.Name] -eq "OK") { "[OK]" } else { "[--]" }
    Write-Host ("    {0} {1,-18} {2}" -f $mark, $dev.Name, $state[$dev.Name])
}
Write-Host ""
Write-Host "  monitoring (only transitions are printed; silence is the good outcome)..."
Write-Host ""

$lastHeartbeat = Get-Date
while ((Get-Date) -lt $endTime) {
    foreach ($dev in $AllDevices) {
        $now = Get-DeviceState $dev.Id
        if ($now -ne $state[$dev.Name]) {
            $ts = (Get-Date).ToString("HH:mm:ss.fff")
            "$ts,$($dev.Name),$($state[$dev.Name]),$now" | Out-File -FilePath $csvPath -Append -Encoding utf8
            $color = if ($now -eq "OK") { "Green" } else { "Red" }
            Write-Host ("    {0}  {1,-18} {2} -> {3}" -f $ts, $dev.Name, $state[$dev.Name], $now) -ForegroundColor $color
            $state[$dev.Name] = $now
            $transitions[$dev.Name]++
        }
    }

    if (((Get-Date) - $lastHeartbeat).TotalMinutes -ge 10) {
        $elapsed = ((Get-Date) - $startTime).TotalMinutes
        $total = ($transitions.Values | Measure-Object -Sum).Sum
        Write-Host ("    -- {0:N0} min elapsed, {1} transitions so far ({2:N2}/min) --" -f `
                    $elapsed, $total, ($total / [Math]::Max($elapsed, 1))) -ForegroundColor DarkGray
        $lastHeartbeat = Get-Date
    }

    Start-Sleep -Milliseconds $IntervalMs
}

# Second, independent instrument: what the OS itself recorded. A polled sample can miss a
# fast event; the event log cannot, so a disagreement means the poll rate was too slow and
# the event log is the number to trust.
$pnpEvents = @()
try {
    $pnpEvents = Get-WinEvent -FilterHashtable @{
        LogName   = 'Microsoft-Windows-Kernel-PnP/Configuration'
        StartTime = $startTime
    } -ErrorAction Stop | Where-Object {
        $_.Message -match 'VID_04B4|VID_03F0|VID_0BDA|VID_045E'
    }
} catch {
    $pnpEvents = $null
}

$elapsedMin = ((Get-Date) - $startTime).TotalMinutes
$totalTrans = ($transitions.Values | Measure-Object -Sum).Sum
$usb2Trans  = ($Usb2Branch | ForEach-Object { $transitions[$_.Name] } | Measure-Object -Sum).Sum
$usb3Trans  = ($Usb3Branch | ForEach-Object { $transitions[$_.Name] } | Measure-Object -Sum).Sum

$lines = @()
$lines += "USB storm monitor -- HP Reverb G2 -- Windows"
$lines += "started        : $($startTime.ToString('yyyy-MM-dd HH:mm:ss'))"
$lines += "duration       : $([Math]::Round($elapsedMin,1)) min, polled every $IntervalMs ms"
$lines += ""
$lines += "TRANSITIONS BY DEVICE (a drop and its recovery count as two)"
foreach ($dev in $AllDevices) {
    $branch = if ($Usb2Branch.Name -contains $dev.Name) { "usb2" } else { "usb3" }
    $lines += ("  {0,-18} {1,-5} {2,6}" -f $dev.Name, $branch, $transitions[$dev.Name])
}
$lines += ""
$lines += ("USB2 branch : {0} transitions = {1:N2}/min" -f $usb2Trans, ($usb2Trans / [Math]::Max($elapsedMin,1)))
$lines += ("USB3 branch : {0} transitions = {1:N2}/min" -f $usb3Trans, ($usb3Trans / [Math]::Max($elapsedMin,1)))
if ($null -ne $pnpEvents) {
    $lines += ("Kernel-PnP events for these devices: {0} ({1:N2}/min)" -f $pnpEvents.Count, ($pnpEvents.Count / [Math]::Max($elapsedMin,1)))
    $lines += "  (independent of the polling above -- if it is much higher, the poll was too slow)"
} else {
    $lines += "Kernel-PnP log unavailable (needs an elevated shell, or the log is disabled)."
    $lines += "  Not fatal: the polled transitions stand on their own at this interval."
}
$lines += ""
$lines += "COMPARISON -- Linux, same headset, same cable (2026-08-19, T223/T225):"
$lines += "  early session : 6-18 events/min"
$lines += "  after 2 hours : 28-62 events/min (796 in 25 min at worst)"
$lines += "  after a 220V cut of the headset : 1-3 events/min"
$lines += ""
$lines += "HOW TO READ THIS"
$lines += "  Windows rate comparable to Linux  -> the link itself is unstable and Linux is"
$lines += "    just more sensitive to it. Cable/connector goes back on the suspect list."
$lines += "  Windows near zero over a real session of similar length and real use -> the link"
$lines += "    is fine and the fault is in the Linux USB stack: companion HID handling,"
$lines += "    autosuspend, or host-controller behaviour. A bug, not a purchase."
$lines += ""
$lines += "  One caveat worth stating: this measures ENUMERATION events, not the HID read"
$lines += "  failures Linux counts (~83/s during a storm). A link could in principle stay"
$lines += "  enumerated on Windows while still misbehaving at the transfer level. If Windows"
$lines += "  reads clean here AND plays fine, that is two independent signals; if it reads"
$lines += "  clean but something still feels wrong, the next instrument is a USBPcap capture."

$lines | Out-File -FilePath $summary -Encoding utf8
$lines | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "  summary written to: $summary" -ForegroundColor Cyan
Write-Host "  bring both files back to the Linux side for the write-up." -ForegroundColor Cyan
