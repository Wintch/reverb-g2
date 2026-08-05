<#
.SYNOPSIS
    Captura TODO lo que hace falta del lado de Windows para el diagnostico del
    HP Reverb G2 a 90Hz, en una sola corrida.

.DESCRIPTION
    Reemplaza el juntar herramientas a mano. Cada corrida:
      1. Busca sola las herramientas (Wireshark/tshark, USBDeview, dxdiag,
         nvidia-smi) -- en la carpeta del kit y en las rutas de instalacion
         tipicas -- e imprime que encontro y que falta.
      2. Junta SOLA, sin apretar nada, lo que tiene CLI:
         - USBDeview: lista completa de dispositivos USB (texto).
         - DxDiag: reporte completo de DirectX.
         - nvidia-smi: estado de la GPU (clocks, PCIe, driver).
         - PowerShell nativo: adaptador de video y monitores (WMI), sin
           depender de ninguna herramienta de terceros.
      3. Captura USB de TODAS las interfaces USBPcap a la vez, para agarrar
         el momento exacto en que el casco pasa a 60 o 90Hz.
      4. Para lo que NO tiene CLI (CRU, HWiNFO64, el panel de NVIDIA) abre la
         herramienta sola y te dice EXACTAMENTE que mirar y que capturar --
         vos solo miras la pantalla y sacas el screenshot.
      5. Deja todo en una sola carpeta con timestamp, lista para llevarse.

.PARAMETER Label
    Nombre de esta corrida: "60hz", "90hz", "idle" (casco conectado sin
    runtime), etc. Se antepone a todos los archivos que genera.

.EXAMPLE
    .\run-diagnostics.ps1 -Label 90hz

    Correr en PowerShell COMO ADMINISTRADOR desde esta carpeta (USBPcap
    necesita el driver a nivel admin; sin admin, esta parte sola falla y el
    resto sigue).
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

# Busca una herramienta que puede no estar en una ruta fija: primero las rutas
# locales/tipicas dadas, despues el PATH, despues el registro de "App Paths"
# (asi arranca "nvcplui.exe" normalmente sin ruta), y por ultimo una busqueda
# recursiva acotada a las carpetas de raiz que se le pasen. Sirve para
# herramientas que no se pueden empaquetar portable (dependen del instalador
# de otro producto, como el panel de NVIDIA) y cuya ruta exacta varia entre
# versiones de driver.
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
# 1. DESCUBRIR HERRAMIENTAS
# ============================================================================
Section "buscando herramientas instaladas"

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
# El panel de NVIDIA no se puede empaquetar portable (depende del driver
# instalado) y su ruta exacta cambia segun la version -- a veces ni siquiera
# es el .exe clasico, es una app empaquetada. Find-Tool cubre PATH + registro
# "App Paths" + busqueda recursiva, que es lo mismo que hace Windows cuando
# vos escribis "nvcplui" en el menu de inicio.
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
    "panel de NVIDIA"            = $NvcpExe
}
foreach ($t in $tools.GetEnumerator()) {
    if ($t.Value) { Write-Host ("  [OK]    {0,-28} {1}" -f $t.Key, $t.Value) -ForegroundColor Green }
    else          { Write-Host ("  [FALTA] {0,-28}" -f $t.Key) -ForegroundColor Yellow }
}

# ============================================================================
# 2. LO QUE SE JUNTA SOLO, SIN GUI
# ============================================================================
Section "recolectando lo que tiene linea de comandos (no hace falta tocar nada)"

if ($USBDeview) {
    $f = Join-Path $OutDir "$Label-usbdeview.txt"
    & $USBDeview /stext $f
    Write-Host "  USBDeview -> $f"
} else {
    Write-Host "  USBDeview: no encontrado, salteado."
}

if ($NvidiaSmi) {
    $f = Join-Path $OutDir "$Label-nvidia-smi.txt"
    & $NvidiaSmi -q > $f
    Write-Host "  nvidia-smi -q -> $f"
} else {
    Write-Host "  nvidia-smi: no encontrado, salteado."
}

Write-Host "  PowerShell nativo: adaptador de video y monitores (WMI)..."
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

Write-Host "  DxDiag (async, esto tarda unos 15-20s)..."
$dxf = Join-Path $OutDir "$Label-dxdiag.txt"
Start-Process -FilePath "dxdiag.exe" -ArgumentList @("/t", $dxf) -Wait
if (Test-Path $dxf) { Write-Host "  DxDiag -> $dxf" }
else { Write-Host "  DxDiag: no genero archivo a tiempo, reintentar a mano si hace falta." }

# ============================================================================
# 3. CAPTURA USB -- todas las interfaces USBPcap a la vez
# ============================================================================
Section "captura USB"

if (-not $Tshark -or -not $Dumpcap) {
    Write-Host "  tshark/dumpcap no encontrados -- SIN ESTO NO HAY CAPTURA USB." -ForegroundColor Red
    Write-Host "  Instala Wireshark con el componente USBPcap tildado, y reinicia."
} else {
    $ifaceLines = & $Tshark -D | Select-String "USBPcap"
    if (-not $ifaceLines) {
        Write-Host "  No aparece ninguna interfaz USBPcap en 'tshark -D'. Reinstalar/reiniciar." -ForegroundColor Red
    } else {
        $ifaces = foreach ($line in $ifaceLines) {
            if ($line -match '^(\d+)\.\s+(\S+)') { [PSCustomObject]@{ Num = $Matches[1]; Name = $Matches[2] } }
        }
        Write-Host "  interfaces USBPcap encontradas (se capturan TODAS):"
        $ifaces | ForEach-Object { Write-Host ("    {0}. {1}" -f $_.Num, $_.Name) }

        Write-Host ""
        Write-Host "  =========================================================="
        Write-Host "   El companion del casco solo manda su estado HID cuando"
        Write-Host "   algo CAMBIA -- la captura tiene que ser CORTA y puesta"
        Write-Host "   alrededor del momento de la transicion, no un regimen largo."
        Write-Host ""
        Write-Host "   1. Casco conectado, SteamVR/runtime de WMR CERRADO todavia"
        Write-Host "      (sin eso el panel no tiene 'modo', esta apagado)."
        Write-Host "   2. Arranca la captura con el Enter de abajo."
        Write-Host "   3. Recien AHI levanta el runtime a la frecuencia de '$Label'."
        Write-Host "   4. Ponetelo, confirma imagen. Volve y Enter, max 10-15s despues."
        Write-Host "  =========================================================="
        Read-Host "Enter para arrancar la captura USB"

        $procs = foreach ($ifc in $ifaces) {
            $file = Join-Path $OutDir ("{0}_USBPcap{1}.pcapng" -f $Label, $ifc.Num)
            Start-Process -FilePath $Dumpcap -ArgumentList @("-i", $ifc.Num, "-w", $file) -PassThru -WindowStyle Hidden
        }
        Write-Host "  Capturando en $($ifaces.Count) interfaz(ces)..." -ForegroundColor Yellow
        Read-Host "Enter para CORTAR"

        foreach ($p in $procs) { if (-not $p.HasExited) { Stop-Process -Id $p.Id -ErrorAction SilentlyContinue } }
        Start-Sleep -Seconds 2

        Write-Host "  exportando (se deja el .pcapng entero, sin recortar -- el tamano no importa,"
        Write-Host "  lo que importa es no perder nada del momento capturado)..."
        foreach ($ifc in $ifaces) {
            $raw = Join-Path $OutDir ("{0}_USBPcap{1}.pcapng" -f $Label, $ifc.Num)
            if (-not (Test-Path $raw) -or (Get-Item $raw).Length -eq 0) {
                Write-Host "    USBPcap$($ifc.Num): sin datos, salteo."
                continue
            }
            $tsv = Join-Path $OutDir ("{0}_USBPcap{1}.tsv" -f $Label, $ifc.Num)
            & $Tshark -r $raw -T fields `
                -e frame.time_relative -e usb.device_address -e usb.endpoint_address `
                -e usb.transfer_type -e usb.bmRequestType -e usb.setup.bRequest `
                -e usb.setup.wValue -e usb.capdata -e usbhid.data > $tsv
            $hit = Select-String -Path $tsv -Pattern "0500" -Quiet
            $marca = if ($hit) { "<-- ESTA ES la interfaz del casco" } else { "" }
            Write-Host ("    USBPcap{0}: {1} bytes  {2}" -f $ifc.Num, (Get-Item $raw).Length, $marca)
        }
    }
}

# ============================================================================
# 4. LO QUE NO TIENE CLI -- se abre solo, decis exactamente que mirar
# ============================================================================
Section "herramientas manuales -- se abren solas, mira la pantalla"

if ($CRU) {
    Write-Host "  Abriendo CRU..." -ForegroundColor Yellow
    Write-Host "    -> Selecciona el Reverb G2, anda a 'Detailed resolutions'."
    Write-Host "    -> Screenshot de esa ventana completa como '$Label-cru.png'."
    Write-Host "    -> Cerra CRU SIN GUARDAR (Cancel, no OK)."
    Start-Process -FilePath $CRU
} else {
    Write-Host "  CRU no encontrado en esta carpeta -- bajalo de monitortests.com si hace falta."
}

if ($HWiNFO) {
    Write-Host "  Abriendo HWiNFO64..." -ForegroundColor Yellow
    Write-Host "    -> Sensors -> busca Pixel Clock / Link Rate / Lane Count de la GPU/display."
    Write-Host "    -> Screenshot como '$Label-hwinfo.png' (aunque no aparezca nada, es un dato)."
    Start-Process -FilePath $HWiNFO
} else {
    Write-Host "  HWiNFO64 no encontrado -- bajalo (version 'Portable', no el instalador) de hwinfo.com/download."
}

if ($GPUZ) {
    Write-Host "  Abriendo GPU-Z..." -ForegroundColor Yellow
    Write-Host "    -> pestana 'Graphics Card': screenshot como '$Label-gpuz.png'."
    Write-Host "    -> si tiene pestana de sensores con Link Speed/Width, sumala tambien."
    Start-Process -FilePath $GPUZ
} else {
    Write-Host "  GPU-Z no encontrado -- bajalo (ya es portable) de techpowerup.com/gpuz."
}

if ($NvcpExe) {
    Write-Host "  Abriendo el Panel de control de NVIDIA..." -ForegroundColor Yellow
    Write-Host "    -> 'Cambiar resolucion': screenshot como '$Label-nvcp-resolution.png'."
    Write-Host "    -> Ayuda -> Informacion del sistema: 'Guardar en archivo de texto' como"
    Write-Host "       '$Label-nvidia-sysinfo.txt' directo en $OutDir"
    Start-Process -FilePath $NvcpExe
} else {
    Write-Host "  Panel de NVIDIA: no lo encontre solo (puede ser la version empaquetada nueva)."
    Write-Host "    Abrilo a mano: click derecho en el escritorio -> 'NVIDIA Control Panel'."
}

Write-Host ""
Write-Host "==========================================================================="
Write-Host " Cuando termines con las ventanas manuales, guarda los screenshots/archivos"
Write-Host " DIRECTO en:"
Write-Host "   $OutDir"
Write-Host " para que quede todo junto. Esa carpeta entera es lo que hay que llevarse."
Write-Host "===========================================================================" -ForegroundColor Green
