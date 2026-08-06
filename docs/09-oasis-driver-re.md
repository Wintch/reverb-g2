# 09 — Qué le manda Windows al panel del G2 (leído del driver Oasis)

**Resultado en una línea: el driver Oasis, que corre el G2 a 90 Hz en Windows NO le manda al
casco ningún comando de modo. El único comando de panel que existe es "encender pantalla",
y Monado ya lo manda.**

Esto cierra, con el binario en la mano, la hipótesis que el proyecto arrastró dos capítulos:
*"a nadie le está diciendo al casco que vaya a 90 Hz"*.

## De dónde salió

En el disco de Windows del rig, sin bootear Windows, montando las NTFS read-only:

```bash
sudo mount -t ntfs-3g -o ro,noatime /dev/nvme0n1p4 /mnt/win4
```

Hay **dos** drivers de WMR instalados por Steam, y la diferencia importa:

| | qué es | sirve para esto |
|---|---|---|
| `MixedRealityVRDriver` (Microsoft) | puente de SteamVR al runtime WMR del SO | **no** — delega, no toca el USB |
| `Oasis Driver for Windows Mixed Reality` (mbucchia) | driver standalone, habla con el casco **directo** | **sí** |

El de mbucchia es el bueno. Su manifiesto se ata al Hololens Sensors por VID:PID, o sea al mismo
device que usa Monado:

```json
{ "name": "oasis", "hmd_presence": [ "045E.0659" ] }
```

Binarios relevantes, en `bin/win64/`:

```
driver_oasis.dll        el driver SteamVR (importa HID.DLL directo)
HololensSensors.dll     sensores + panel, en userspace (importa HID.DLL directo)
MRUSBHost.dll           capa USB/HID cruda
MROEMFwHost.dll         firmware OEM
unlock/unlock_wmr.exe   examinado 2026-08-06, ver abajo
```

La ruta de build quedó embebida: `D:\a\WMR-Standalone-Oasis-Driver\...\driver_oasis\HmdDriver.cpp`
— es un build de GitHub Actions, así que existe un repo con ese nombre. No se buscó.

## Método (sin ghidra ni radare2, sólo binutils)

1. `strings` para ubicar los candidatos.
2. `objdump -h` para las secciones, y convertir offset de archivo → VA.
3. `objdump -d` y buscar la VA del string en el desensamblado: objdump ya resuelve los
   `lea` rip-relativos, así que las xrefs se encuentran por texto.
4. Para las llamadas a API importada: `objdump -p` da la RVA del thunk en la IAT, y se
   busca `call *0x...(%rip)  # 0x<thunk>` en el desensamblado.

El script está en el repo del lab como `scripts/xref.py` (uso:
`xref.py <dll> <asm> <substring>...`).

## Lo que se encontró

### El único comando de panel: Display Enable

`driver_oasis.dll` tiene **un solo** call site de `HidD_SetFeature` en todo el binario:

```asm
mov  $0x2,%ecx     ; ReportType = HidP_Feature
mov  $0x3,%edx     ; UsagePage  = 0x03   (VR Controls)
xor  %r8d,%r8d     ; LinkCollection = 0
mov  $0x21,%r9d    ; Usage      = 0x21   (Display Enable)
mov  %r13d,0x20(%rsp)   ; el valor (0/1)
call *... ; HidP_SetUsageValue
call *... ; HidD_SetFeature
```

`HololensSensors.dll` hace lo mismo, escrito distinto — misma página, mismo usage:

```asm
mov  $0x21,%r9d          ; Usage = 0x21
lea  -0x1e(%r9),%edx     ; UsagePage = 0x21-0x1e = 0x03
```

**Usage Page 0x03 / Usage 0x21 = "Display Enable" del HID Usage Table de VR Controls.** Es
exactamente el `{0x04, 0x01}` de `wmr_hmd_screen_enable_reverb()`. Windows lo expresa por
usages (deja que el report descriptor decida el report ID); Monado escribe los bytes a mano.
El efecto sobre el casco es el mismo.

Diferencia de estilo, no de contenido: el driver arma el reporte con `HidP_SetUsageValue` y
saca el report ID del `HIDP_VALUE_CAPS` (`movzbl 0x2(%rax)` = campo `ReportID`), en vez de
hardcodearlo.

### No hay comando de refresh rate. Se buscó y no está.

Dos falsos positivos que conviene dejar anotados para que nadie los vuelva a perseguir:

**`HmdDriver_SetFrameRate` es de las cámaras, no del panel.** Es un método RPC (el driver
usa ZMQ + jsoncpp) y sus parámetros lo delatan:

```
HmdDriver_SetFrameRate
    IspFrameRate
    SensorFrameRate
```

ISP = Image Signal Processor. Está en medio del bloque de cámaras
(`HmdDriver_GetCameraIntrinsics`, `HmdDriver_SetCameraCompatibilityMode`,
`HmdDriver_StartVideoStream`...). Concuerda con el string de `HololensSensors.dll`:
`OV7251SetFrameRate: 90hz requested but not USB3.0SS` — el OV7251 es el sensor de las
cámaras de tracking. **Ese 90 Hz es otro 90 Hz.**

**`Detected change of refresh rate %.0f -> %.0f` es contabilidad de SteamVR.** El código que
lo emite lee la propiedad `0x7d2` (2002 = `Prop_DisplayFrequency_Float`) del contenedor de
propiedades, la compara con la guardada, y si cambió recorre una tabla interna de modos
calculando `num/den` para actualizar `0x7d1` (2001 = `Prop_SecondsFromVsyncToPhotons`). No
sale un byte hacia el casco. `preferredRefreshRate` es la clave de settings de SteamVR que
lee (está pegada al string `steamvr` en `.rdata`).

Los otros cuatro `HidP_SetUsageValue` del driver son Usage Page `0x0E` (Haptics), usages
`0x21`/`0x23`, ReportType Output: rumble de los controllers.

### Strings del firmware del casco (para el que siga)

`HololensSensors.dll` trae strings de log del firmware, útiles como mapa del hardware:

```
Backlight_PowerOn / Backlight_PowerOff / BacklightState / DisplayPanel
SelectedRefreshRate          [%s] refresh_rate %d
panel_register_read   panel_backlight_duty   panel_brightness_control   panel_B9_check
[%s] left duty %d, right duty %d, frame timing %d, panel ID %d
[Panel %d]map BKLT current, left %dmA, right %dmA
Part: LIF-MD6000-6CSFBGA81
```

`LIF-MD6000` es un **Lattice CrossLink**, el puente MIPI/DP del casco. Que el firmware tenga
un concepto de `refresh_rate` y `SelectedRefreshRate` no contradice lo de arriba: el panel
sabe a qué refresh está: simplemente **nadie se lo dice por HID desde el host** — lo deduce
del timing de video que le llega.

## Qué se concluye, y qué NO

**Se concluye:** no falta ningún comando propietario. La secuencia HID de Monado es correcta
y suficiente. El panel adopta el refresh del video que recibe. `docs/07-windows-hid-capture.md`
queda archivado: ya no hace falta bootear Windows para capturar nada.

Es la **segunda** vez que esta hipótesis muere. La primera fue por argumento (Project-VR
llega a 90 Hz sin comandos propietarios, commit `3e2e7ac`); esta es por evidencia directa.
Entre las dos hubo un tramo en el que `CLAUDE.md` seguía dando la hipótesis por viva y se la
volvió a citar como "la única que explica los resultados". Corregido.

**NO se concluye** que el problema sea de NVIDIA por eliminación. Lo que queda abierto es
qué del enlace de video a 90 Hz no le gusta al casco — ver el análisis de ancho de banda en
`docs/04-lab-90hz.md`, que también deja mal parada a la teoría de DSC.

## Cerrado despues (2026-08-05)

- **`unlock_wmr.exe`** resulto ser mucho mas que su nombre: maneja **direct mode y estado de
  display** (`DirectModeHelper_Ctor`, `DisableDirectMode`, `SetDisplayState`, `Direct Mode: %s`,
  *"Device does not need manual activation of the display"*), usando
  `Windows.Devices.Display.Core`. Y trae rutas por fabricante de GPU: `ADL2_Display_*` y
  `agsSetDisplayMode` para **AMD**. O sea que en Windows una app puede pedir timings
  arbitrarios; en Linux NVIDIA no lo permite (medido: `vkCreateDisplayModeKHR` y
  `drmModeSetCrtc` rechazan todo lo que no este en el EDID).
- **`MROEMFwHost.dll`** es **exclusivamente el actualizador de firmware**: `BeginUpdate`,
  `CommitBuffer`, `CompleteUpdate`, verificacion de checksum, `WriteData`. Busca los reports
  por *usage* HID. Su `ReadDeviceInfo` sirve para decidir si hay que actualizar, no para leer
  estado del panel. **No hay camino ahi para consultar al ANX7530 en runtime.** Anotar que ese
  binario SI puede escribir firmware al casco: territorio en el que no conviene meterse sin
  una razon muy buena.
- **`client_utility.exe`** es un helper de la API de Steam (`STEAMSCREENSHOTS_INTERFACE_VERSION003`)
  y nada mas.

Con eso los cuatro binarios del driver Oasis quedan abiertos y sin nada mas que sacar.

## Suelto, sin mirar

- `driver_oasis.dll` tiene secciones `.detourc`/`.detourd`: usa Microsoft Detours para
  hookear APIs. No se investigó qué hookea.
- Las particiones se montaron read-only en `/mnt/win{3,4,5}`. Desmontar con
  `sudo umount /mnt/win3 /mnt/win4 /mnt/win5`.

## `unlock_wmr.exe`: no manda ningún comando de vinculación (2026-08-06)

Se retomó este binario buscando específicamente el protocolo de vinculación de
controllers, a raíz de que un botón oculto en el compartimento de pilas puede desvincular
un controller del casco (ver `docs/03-controllers.md`, sección "Vinculación / pairing" —
ahí está la conclusión completa, esto es el detalle técnico de dónde salió).

Repo original: `github.com/mbucchia/Oasis-Driver-for-Windows-Mixed-Reality` — resultó ser
sólo un issue tracker con wiki, sin código fuente publicado. La wiki sí tiene una página
`Pairing-Motion-Controllers` con el procedimiento (físico, botón del controller).

Imports de `unlock_wmr.exe`: `SETUPAPI.dll` (`SetupDiGetClassDevsW`,
`SetupDiEnumDeviceInterfaces`, ...), `CFGMGR32.dll` (`CM_Get_Device_Interface_ListW`,
`CM_Get_Device_Interface_PropertyW`) y `HID.DLL` — nada de Bluetooth (`bthprops`,
`Windows.Devices.Bluetooth`, WinRT device-pairing APIs no aparecen en ningún lado). Mismo
método que para Display Enable (`xref.py` sobre un `objdump -d` completo):

- Único call site de `HidP_SetUsageValue`/`HidD_SetFeature` en todo el binario: mismos
  argumentos que ya se documentaron arriba para Display Enable — `UsagePage=0x3`,
  `Usage=0x21`. **No hay un segundo comando HID distinto para vinculación.**
- La función que contiene los strings `"Start pairing new %s motion controller"` /
  `"Unpairing previous %s motion controller"` / `"Timeout pairing %s motion controller"`
  es un loop de polling con sleeps (`Sleep(100)` x60 ≈ 6s de timeout) que llama a un
  MessageBox-like (comparando el resultado contra 6/2 = IDYES/IDCANCEL) y strings como
  `"Found controller device (paired through Headset): %s"` — es la UI esperando a que
  `SetupDiGetClassDevsW` vea aparecer la interfaz HID del controller, no algo que dispara
  la vinculación en el casco.

Conclusión: la vinculación es un handshake de radio interno al casco, disparado
físicamente (botón del controller), sin comando de host que reproducir. Confirma y cierra
lo que ya sugería `docs/03-controllers.md` de entrada ("no hay que aparear nada en
Linux") — ahora con evidencia binaria, no sólo por lectura del driver Monado.
