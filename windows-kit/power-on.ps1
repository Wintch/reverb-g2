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

    Code and comments in English (repo rule); the on-screen text is Spanish, the
    same as scripts/power-on.py, until vr_i18n.py grows an English preset.

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
    @{ Id = "VID_04B4&PID_6506"; Name = "Hub USB2 (cara 480M del hub del casco)" },
    @{ Id = "VID_03F0&PID_0580"; Name = "Companion (control del panel/HID)" },
    @{ Id = "VID_0BDA&PID_4C15"; Name = "Audio (auriculares del casco)" }
)
$SS_BRANCH = @(
    @{ Id = "VID_04B4&PID_6504"; Name = "Hub SuperSpeed (cara 5 Gbps)" },
    @{ Id = "VID_045E&PID_0659"; Name = "HoloLens Sensors (las 4 camaras)" }
)

function Say-Step($n, $title) {
    Write-Host ""
    Write-Host "> Paso $n/5 -- $title" -ForegroundColor Green
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
            if ($Detail) { Say-Bad ("{0} -- AUSENTE ({1})" -f $dev.Name, $dev.Id) }
        } else {
            $status = if ($d.Status) { $d.Status } else { "OK" }
            if ($status -ne "OK") {
                $missing += $dev
                if ($Detail) { Say-Bad ("{0} -- presente pero en error: {1}" -f $dev.Name, $status) }
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
    Say-Warn "Esperando que reconectes -- [Enter] re-chequear ya | [S] seguir sin VR"
    $deadline = (Get-Date).AddSeconds(90)
    $answered = $false
    $lastPrint = Get-Date
    while ($true) {
        if ((Get-Date) -gt $deadline) {
            Write-Host ""
            if ($answered) { Say-Warn "Se acabo el tiempo de espera (300s desde la ultima tecla)." }
            else { Say-Warn "Se acabo el tiempo de espera (nadie apreto nada)." }
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
    Say-Warn "Hay que reconectar. En orden de probabilidad (docs/22, T171):"
    if (-not $usb2Ok -and -not $ssOk) {
        Say-Dim "  > Saca el USB del casco de la PC y metelo DERECHO y A FONDO, sosteniendo"
        Say-Dim "    el peso del cable con la otra mano (cuelga y hace palanca)."
        Say-Dim "  > Usa un puerto USB3 TRASERO de la placa madre (los del CPU). Los del"
        Say-Dim "    frente y los del chipset no sirven para este casco."
    } elseif (-not $ssOk) {
        Say-Dim "  > Falta la rama SuperSpeed (las camaras). SIN cambiar de puerto: saca el"
        Say-Dim "    plug USB-C del adaptador, GIRALO 180 grados y metelo de nuevo, firme."
    } else {
        Say-Dim "  > Falta la rama USB2 (companion/audio). SIN cambiar de puerto: saca el"
        Say-Dim "    plug USB-C del adaptador, GIRALO 180 grados y metelo de nuevo, firme."
    }
    Say-Dim "  > Sigue igual? Proba OTRO puerto USB3 trasero (cada puerto asienta distinto)."
    Say-Dim "  > Nada? Reseat de la ficha del visor (detras del gasket magnetico) y despues"
    Say-Dim "    TODO junto: USB + DP + brick de 18.5V afuera ~1 min, y reconectar."
}

Write-Host "=== Encendiendo el HP Reverb G2 (Windows) ===" -ForegroundColor Green
Say-Dim "Esto corre en tu monitor normal. No hace falta administrador y no toca nada del sistema."

$problems = @()

# ---- 1/5: USB census ------------------------------------------------------
Say-Step 1 "Esta todo conectado?"
$missUsb2 = Test-Branch $USB2_BRANCH -Verbose
$missSs   = Test-Branch $SS_BRANCH -Verbose
$usb2Ok = $missUsb2.Count -eq 0
$ssOk   = $missSs.Count -eq 0

if ($usb2Ok -and $ssOk) {
    Say-Ok "5/5 piezas del casco responden (hub USB2, companion, audio, hub SS, camaras)."
} else {
    Say-Bad ("Rama USB2 {0} -- rama SuperSpeed {1}." -f
            $(if ($usb2Ok) { "OK" } else { "AUSENTE" }),
            $(if ($ssOk) { "OK" } else { "AUSENTE" }))
    Say-Dim "Este es el cuadro que produce 'Headset not detected (108)': para WMR/Oasis el"
    Say-Dim "casco no existe hasta que enumeran las DOS ramas -- la SuperSpeed sobre todo."
    Show-ReseatLadder $usb2Ok $ssOk
    $outcome = Wait-Reseat {
        ((Test-Branch $USB2_BRANCH).Count -eq 0) -and ((Test-Branch $SS_BRANCH).Count -eq 0)
    }
    if ($outcome -eq "fixed") {
        Say-Ok "5/5! Reconexion correcta, seguimos."
        $usb2Ok = $true; $ssOk = $true
    } elseif ($outcome -eq "skip") {
        Say-Warn "Saliendo a pedido tuyo."
        exit 1
    } else {
        $problems += "El casco no enumera completo (rama " +
                     $(if ($ssOk) { "USB2" } else { "SuperSpeed" }) + " ausente)."
    }
}

# ---- 2/5: which port ------------------------------------------------------
Say-Step 2 "Estas en un puerto que sirve?"
$hub = Get-G2Device "VID_04B4&PID_6504"
if (-not $hub) { $hub = Get-G2Device "VID_04B4&PID_6506" }
if ($hub) {
    try {
        $loc = (Get-PnpDeviceProperty -InstanceId $hub.InstanceId `
                -KeyName "DEVPKEY_Device_LocationInfo" -ErrorAction Stop).Data
        Say-Dim "Ubicacion segun Windows: $loc"
    } catch { }
    if ($ssOk) {
        Say-Ok "El hub SuperSpeed enumero: estas en un puerto USB 3.x real."
    } else {
        Say-Bad "Solo aparece la cara USB2 del hub: o el puerto no es USB3, o el plug no asento."
        Say-Dim "Oasis exige USB 3.0 para el tracking de los controles (Troubleshooting Guide)."
        $problems += "El casco no esta en un puerto USB 3.x utilizable."
    }
} else {
    Say-Warn "No hay ningun hub del casco enumerado -- nada que ubicar todavia."
}

# ---- 3/5: controllers over Bluetooth --------------------------------------
Say-Step 3 "Los controles estan vinculados (a la radio del casco)?"
Say-Dim "En el G2 los controles NO van por el cable: son Bluetooth contra la radio del casco"
Say-Dim "o la de la placa. Por eso el unico momento en que se abre la app de Oasis es para"
Say-Dim "aparearlos/desbloquearlos -- despues no hace falta lanzarla nunca mas."
$bt = @()
try {
    $bt = Get-PnpDevice -PresentOnly -ErrorAction Stop |
          Where-Object { $_.FriendlyName -match "Motion controller|Motion Controller" }
} catch { }
if ($bt.Count -ge 2) {
    Say-Ok ("{0} controles apareados y presentes." -f $bt.Count)
} elseif ($bt.Count -eq 1) {
    Say-Warn "Solo 1 control vinculado. Empareja el otro con el flujo de UNLOCK de Oasis"
    Say-Dim "(pregunta por control, izquierdo primero): boton del compartimiento de pilas"
    Say-Dim "apretado hasta el pulso lento del LED. El bond es contra la radio del CASCO."
} else {
    Say-Warn "No veo controles vinculados (no bloquea el casco, pero no vas a tener manos)."
    Say-Dim "Vincula con el flujo de unlock de Oasis (izquierdo primero, boton de pilas hasta"
    Say-Dim "el pulso lento). El bond es contra la radio del casco, no contra Windows."
}

# ---- 4/5: software state --------------------------------------------------
Say-Step 4 "El software esta como Oasis lo necesita?"

$build = [System.Environment]::OSVersion.Version.Build
if ($build -ge 26100) {
    Say-Ok "Windows 11 24H2 o mas nuevo (build $build) -- la configuracion soportada por Oasis."
} else {
    Say-Warn "Build $build: Oasis pide 24H2 (build 26100+). En 23H2 hay que deshabilitar a mano"
    Say-Dim "el dispositivo 'Mixed Reality' en el Administrador de dispositivos."
}

$steam = $null
foreach ($p in @("${env:ProgramFiles(x86)}\Steam", "$env:ProgramFiles\Steam", "C:\Steam")) {
    if (Test-Path (Join-Path $p "steamapps")) { $steam = $p; break }
}
if ($steam) {
    Say-Ok "Steam en $steam"
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
    if ($steamvrFound) { Say-Ok "SteamVR instalado." }
    else { Say-Bad "SteamVR no aparece instalado."; $problems += "Falta SteamVR." }
    if ($oasisFound) { Say-Ok "Oasis Driver instalado (app 3824490)." }
    else { Say-Bad "Oasis Driver NO instalado -- sin el, en 24H2 no hay runtime WMR de ningun tipo."
           $problems += "Falta el Oasis Driver." }
} else {
    Say-Warn "No encontre la instalacion de Steam en las rutas tipicas."
}

# openvrpaths.vrpath is what SteamVR actually reads to find external drivers.
# A fresh Windows/Steam install losing this registration is a documented cause
# of "SteamVR doesn't see the G2 even though Windows does".
$vrpath = Join-Path $env:LOCALAPPDATA "openvr\openvrpaths.vrpath"
if (Test-Path $vrpath) {
    $txt = Get-Content $vrpath -Raw
    if ($txt -match "(?i)oasis") {
        Say-Ok "El driver de Oasis esta registrado en openvrpaths.vrpath."
    } else {
        Say-Bad "openvrpaths.vrpath NO menciona Oasis: SteamVR no va a cargar el driver."
        Say-Dim "Fix: cerra SteamVR y volve a correr el unlock desde la app de Oasis."
        $problems += "El driver de Oasis no esta registrado en SteamVR."
    }
    # The legacy WMR driver declares hmd_presence "*.*" -- it claims ANY headset --
    # while Oasis declares exactly "045E.0659" (the HoloLens Sensors device, i.e.
    # the SuperSpeed branch). Two drivers claiming the same headset, one of them
    # backed by a runtime that no longer exists on 24H2, is a prime 422 shape.
    if ($txt -match "(?i)MixedRealityVRDriver") {
        Say-Warn "Tambien esta registrado el driver viejo de WMR (MixedRealityVRDriver, 'holographic')."
        Say-Dim "En 24H2 ese driver ya no tiene runtime detras, y su manifiesto reclama CUALQUIER"
        Say-Dim "casco (hmd_presence '*.*'), mientras Oasis reclama solo 045E.0659. Deshabilitalo:"
        Say-Dim "SteamVR > Configuracion > Inicio/Apagado > Administrar complementos > 'holographic' OFF."
    }
} else {
    Say-Warn "No existe $vrpath (SteamVR nunca arranco en esta cuenta todavia)."
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
                Say-Ok ("Ultimo casco visto por SteamVR: {0} via driver '{1}'" -f
                        $s.LastKnown.HMDModel, $s.LastKnown.ActualHMDDriver)
                if ($s.LastKnown.ActualHMDDriver -eq "oasis") {
                    Say-Dim "O sea: el unlock ya se hizo en esta maquina y Oasis anduvo. Si ahora da 108,"
                    Say-Dim "mira el paso 1 antes que cualquier cosa de software."
                }
            }
            if ($s.driver_oasis -and $s.driver_oasis.PSObject.Properties.Name -contains "enable" -and
                -not $s.driver_oasis.enable) {
                Say-Bad "El add-on 'oasis' esta DESHABILITADO en steamvr.vrsettings -- causa tipica de 422."
                Say-Dim "SteamVR > Configuracion > Inicio/Apagado > Administrar complementos: 'oasis' en ON."
                $problems += "El add-on de Oasis esta deshabilitado en SteamVR."
            } else {
                Say-Ok "El add-on de Oasis no figura deshabilitado."
            }
            if ($s.driver_holographic -and $s.driver_holographic.PSObject.Properties.Name -contains "enable" -and
                -not $s.driver_holographic.enable) {
                Say-Ok "El add-on viejo 'holographic' (WMR) figura deshabilitado, como corresponde en 24H2."
            }
        } catch {
            Say-Warn "No pude leer steamvr.vrsettings como JSON ($($_.Exception.Message))."
        }
    }
}

# Leftovers of the old stack. Not fatal by themselves on 24H2 (the Portal is
# gone from the OS), but the unlock tool's documented "MR USB device: 6" error
# is exactly the Portal holding the device open on older builds.
$mrp = $null
try { $mrp = Get-AppxPackage -Name "Microsoft.MixedReality.Portal" -ErrorAction Stop } catch { }
if ($mrp) {
    Say-Warn "Mixed Reality Portal sigue instalado: puede tomar el dispositivo USB y hacer"
    Say-Dim "fallar el unlock ('Unexpected error while opening MR USB device: 6')."
} else {
    Say-Ok "Sin Mixed Reality Portal instalado (lo esperable en 24H2)."
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
    if ($null -eq $value) { Say-Dim "$label : (sin personalizar, valor por defecto del plan)" }
    elseif ($value -eq $wanted) { Say-Ok "$label : $value (lo que queremos)" }
    else { Say-Warn "$label : $value (queremos $wanted)" }
}

Write-Host ""
Write-Host "> Ajustes de Windows que afectan las mediciones" -ForegroundColor Green
$isAdmin = ([Security.Principal.WindowsPrincipal] `
            [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Show-Setting "USB selective suspend (0 = apagado)" (Get-PowerSetting $GUID_SUB_USB $GUID_USB_SUSP) 0
Show-Setting "PCI Express ASPM (0 = apagado)"      (Get-PowerSetting $GUID_SUB_PCI $GUID_ASPM) 0
Show-Setting "CPU minimo % (100 = sin bajar)"      (Get-PowerSetting $GUID_SUB_PROC $GUID_PROC_MIN) 100
Show-Setting "CPU maximo %"                        (Get-PowerSetting $GUID_SUB_PROC $GUID_PROC_MAX) 100

$hiberboot = $null
try {
    $hiberboot = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power" `
                  -Name HiberbootEnabled -ErrorAction Stop).HiberbootEnabled
} catch { }
if ($hiberboot -eq 1) {
    Say-Warn "Inicio rapido (fast startup) ENCENDIDO."
    Say-Dim "Apagarlo importa dos veces: Windows no arranca desde un estado congelado (mediciones"
    Say-Dim "reproducibles) y deja el NTFS limpio, que es lo que permite escribir en C: desde Linux."
} elseif ($null -ne $hiberboot) {
    Say-Ok "Inicio rapido apagado."
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
    Say-Warn ("{0} dispositivos USB con ahorro de energia propio activo (hubs incluidos)." -f $usbPm.Count)
} else {
    Say-Ok "Ningun dispositivo USB con ahorro de energia propio activo (o no se pudo leer)."
}

if ($Tune) {
    if (-not $isAdmin) {
        Say-Bad "-Tune necesita PowerShell COMO ADMINISTRADOR. No cambie nada."
    } else {
        Say-Warn "Aplicando ajustes (esto cambia configuracion del sistema)..."
        & powercfg /setactive SCHEME_MIN 2>$null            # High performance
        & powercfg /setacvalueindex SCHEME_CURRENT $GUID_SUB_USB  $GUID_USB_SUSP 0
        & powercfg /setacvalueindex SCHEME_CURRENT $GUID_SUB_PCI  $GUID_ASPM     0
        & powercfg /setacvalueindex SCHEME_CURRENT $GUID_SUB_PROC $GUID_PROC_MIN 100
        & powercfg /setacvalueindex SCHEME_CURRENT $GUID_SUB_PROC $GUID_PROC_MAX 100
        & powercfg /change standby-timeout-ac 0
        & powercfg /change monitor-timeout-ac 0
        & powercfg /change disk-timeout-ac 0
        & powercfg /setactive SCHEME_CURRENT
        Say-Ok "Plan de energia en alto rendimiento, sin suspension USB/ASPM, CPU al 100%."
        & powercfg /h off 2>$null
        Say-Ok "Hibernacion e inicio rapido apagados (y sin hiberfil.sys)."
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
        Say-Ok "$n dispositivos USB con ahorro propio desactivado (efectivo tras reiniciar)."
        try {
            Set-ItemProperty "HKCU:\System\GameConfigStore" -Name GameDVR_Enabled -Value 0 -ErrorAction Stop
            Say-Ok "Game DVR apagado (dejaba de grabar en segundo plano durante las mediciones)."
        } catch { }
        Write-Host ""
        Say-Dim "Para deshacer: powercfg /setactive SCHEME_BALANCED ; powercfg /h on ; y poner en 1"
        Say-Dim "los EnhancedPowerManagementEnabled/SelectiveSuspendEnabled que se pusieron en 0."
    }
} else {
    Say-Dim "Para aplicar todo esto: correr este script COMO ADMINISTRADOR con -Tune."
}

# ---- 5/5: verdict + error triage -----------------------------------------
Say-Step 5 "Veredicto"
if ($problems.Count -eq 0) {
    Write-Host "  LISTO. " -ForegroundColor Green -NoNewline
    Write-Host "Arranca SteamVR: el casco tiene que aparecer solo (no hace falta abrir Oasis)."
    Say-Dim "Si es la primera vez en esta PC, o cambiaste GPU/reinstalaste Windows, hay que"
    Say-Dim "correr una vez el unlock desde la app de Oasis -- ver docs/31."
} else {
    Write-Host "  FALTA ALGO:" -ForegroundColor Yellow
    foreach ($p in $problems) { Say-Dim "  - $p" }
}

Write-Host ""
Write-Host "--- Que significan los errores que ya viste ---" -ForegroundColor Cyan
Say-Dim "108 'Headset not detected': SteamVR no tiene NINGUN casco. En este equipo eso"
Say-Dim "     coincidio siempre con la enumeracion incompleta del paso 1 (tipicamente la"
Say-Dim "     rama SuperSpeed sin entrar). Es un problema de cable/puerto, no de software:"
Say-Dim "     arregla el paso 1 y desaparece. Segundo sospechoso, si el paso 1 da 5/5:"
Say-Dim "     el driver de Oasis sin registrar en openvrpaths.vrpath (paso 4)."
Say-Dim "422 'SteamVR encountered an unexpected problem': SteamVR SI arranco y el driver"
Say-Dim "     fallo despues. Por eso es intermitente y por eso no lo arregla mover el cable."
Say-Dim "     Orden de causas: add-on de Oasis deshabilitado por modo seguro tras un crash,"
Say-Dim "     unlock que hay que rehacer (cambio de GPU / reinstalacion), SteamVR beta, y"
Say-Dim "     datos de entorno corruptos (borrar WindowsHolographicDevices y rehacer Room Setup)."
Say-Dim "498 'Failed to lease display': no es de Windows -- es el intento de SteamVR nativo"
Say-Dim "     en Linux (docs/pruebas.jsonl T170). Si aparece aca, no lo mezcles con lo de arriba."
Write-Host ""
Say-Dim "Manual completo: docs/31-windows-bringup-and-errors.md"
