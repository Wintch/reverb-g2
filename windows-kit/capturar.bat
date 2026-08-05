@echo off
REM ===========================================================================
REM  Captura HID del HP Reverb G2 en Windows, con el casco andando a 90 Hz.
REM  Correr COMO ADMINISTRADOR desde esta carpeta.
REM ===========================================================================
setlocal

set TSHARK="C:\Program Files\Wireshark\tshark.exe"
set DUMPCAP="C:\Program Files\Wireshark\dumpcap.exe"

if not exist %TSHARK% (
    echo.
    echo  ERROR: no encuentro tshark en "C:\Program Files\Wireshark\".
    echo  Instala Wireshark y TILDA el componente USBPcap durante la instalacion.
    echo.
    pause
    exit /b 1
)

echo.
echo  === interfaces USBPcap disponibles ===
%TSHARK% -D | findstr /I "USBPcap"
echo.
echo  Elegi la del root hub donde esta enchufado el casco.
echo  Si no sabes cual, proba una: al final te dice si vio al casco.
echo.
set /p IFACE=  Nombre exacto de la interfaz (ej. \\.\USBPcap1):

if "%IFACE%"=="" (
    echo  No elegiste ninguna. Salgo.
    pause
    exit /b 1
)

set OUT=windows-90hz
echo.
echo  === CAPTURANDO en %OUT%.pcapng ===
echo.
echo    PONETE EL CASCO AHORA y confirma que ves imagen a 90 Hz.
echo    Mira 30 segundos, movete un poco.
echo    Despues volve aca y apreta Ctrl+C para cortar.
echo.
%DUMPCAP% -i %IFACE% -w %OUT%.pcapng

echo.
echo  === exportando a texto ===

REM Todo el trafico, con los campos que hacen falta para distinguir un reporte HID
REM real del ruido del bus. Sin bmRequestType/bRequest/wValue el analisis es basura.
%TSHARK% -r %OUT%.pcapng -T fields ^
   -e frame.time_relative -e usb.device_address -e usb.endpoint_address ^
   -e usb.transfer_type -e usb.bmRequestType -e usb.setup.bRequest ^
   -e usb.setup.wValue -e usb.capdata > %OUT%.tsv

echo.
echo  === verificacion: vimos al casco? ===
findstr /C:"05:00:01:01" %OUT%.tsv >nul 2>&1
if %ERRORLEVEL%==0 (
    echo    SI - hay mensajes DEVICE_STATUS del companion. La captura sirve.
) else (
    echo    NO se ven mensajes DEVICE_STATUS.
    echo    Probablemente elegiste la interfaz USBPcap equivocada.
    echo    Volve a correr esto y proba con otra.
)

echo.
for %%F in (%OUT%.tsv) do echo    %OUT%.tsv = %%~zF bytes
for %%F in (%OUT%.pcapng) do echo    %OUT%.pcapng = %%~zF bytes
echo.
echo  Listo. Llevate %OUT%.pcapng y %OUT%.tsv a Linux.
echo.
pause
