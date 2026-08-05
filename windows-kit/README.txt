================================================================================
  KIT DE CAPTURA EN WINDOWS  —  HP Reverb G2 / soporte del G2 en Linux  (v3)
================================================================================

ESTADO ACTUAL: el canal USB/HID ya esta agotado, no es lo que falta
---------------------------------------------------------------------
En Linux el casco a 90 Hz muestra el logo de HP y no engancha (parpadeo blanco
con los parches puestos); en Windows anda perfecto, incluso cambiando de 60 a
90 Hz en vivo sin reconectar. Ya se descarto, con captura real de los dos
lados:

  - Comando HID de modo especial: no existe (se desensamblo el driver Oasis).
  - Ancho de banda / duracion del vblank / el refresh en si: descartado con
    un factorial completo en Linux (docs/16-lab-vblank.md).
  - El estado que reporta el casco por USB (`DEVICE_STATUS`, 33 bytes): es
    BYTE-IDENTICO entre Linux parchado y Windows, tanto en regimen estable
    como en el momento exacto de una transicion 60<->90 en vivo. No hay
    ningun comando USB extra durante el cambio de modo (docs/13-bug-6bpc.md).
  - DSC vede el panel de NVIDIA o desde Configuracion de Windows: el Reverb
    G2 no aparece como display seleccionable en ninguna de las dos pantallas
    (esta en modo directo/HMD, no como monitor de escritorio) -- esa via esta
    cerrada por falta de acceso, no por un resultado negativo.

Lo que queda -- DSC en silencio, GSP firmware cerrado, algo del propio link
training de DisplayPort -- ya no es visible desde ningun angulo que Windows
pueda mostrar por herramientas de usuario. El siguiente paso real es el
reporte a NVIDIA (bug 5923212, docs/19), no otra captura de este kit.

Este kit queda como herramienta general para el proximo capitulo (por
ejemplo, un baseline en Windows para comparar contra una GPU AMD cuando
llegue, o si NVIDIA pide algo puntual) -- no como una lista de tareas
pendientes para el 90Hz. Si volves a esta carpeta preguntandote "por donde
sigo", la respuesta corta es: por `docs/19` y por AMD, no por aca.


PREPARACION (una sola vez, requiere reiniciar por Wireshark/USBPcap)
---------------------------------------------------------------------
1. Wireshark, CON el componente USBPcap tildado en el instalador (no viene
   tildado por defecto):
       https://www.wireshark.org/download.html
   REINICIAR despues de instalar -- USBPcap instala un filtro y no anda hasta
   el reboot.

2. Opcional pero recomendado, herramientas portables (no requieren instalar
   nada, cada una en su propia carpeta al lado de este README):

       cru-1.5.3\CRU.exe        https://www.monitortests.com/forum/Thread-Custom-Resolution-Utility-CRU
                                 (sitio oficial de ToastyX -- ojo con dominios
                                 parecidos tipo customresolutionutility.*)
       usbdeview-x64\USBDeview.exe   https://www.nirsoft.net/utils/usb_devices_view.html
       hwinfo64\HWiNFO64.exe    https://www.hwinfo.com/download/  (version "Portable")
       gpuz\GPU-Z.exe           https://www.techpowerup.com/gpuz/  (ya es portable)

   `run-diagnostics.ps1` busca cada una en su carpeta automaticamente y las
   abre solo si las encuentra -- si falta alguna, la saltea sin romper nada.

Nada de esto pisa el driver de NVIDIA ni el del casco -- son de solo
lectura/edicion de EDID en el registro, no tocan DPCD en caliente.


CAPTURA -- un solo comando por corrida
---------------------------------------------------------------------
Una vez por sesion de PowerShell, como administrador, parado en esta carpeta:

    powershell -ExecutionPolicy Bypass -File run-diagnostics.ps1 -Label 90hz

(o `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` una vez y
despues `.\run-diagnostics.ps1 -Label 90hz` normal -- PowerShell bloquea
scripts sin firmar por default, esto lo habilita solo para esa ventana.)

El script hace todo en una sola pasada:

  1. Busca las herramientas solo (rutas locales + PATH + registro de Windows).
  2. Junta lo que tiene linea de comandos sin tocar nada: USBDeview, nvidia-smi,
     WMI (adaptador de video y monitores), DxDiag.
  3. Captura USB de TODAS las interfaces USBPcap a la vez -- no hay que
     adivinar cual enumera el casco. Te va guiando en la consola: pide un
     Enter para arrancar la captura (con el runtime de WMR/SteamVR TODAVIA
     CERRADO -- sin eso el panel no tiene "modo", esta apagado), y otro Enter
     para cortar despues de confirmar imagen.
  4. Para lo que no tiene CLI (CRU, HWiNFO64, GPU-Z, el panel de NVIDIA) abre
     cada herramienta sola y dice en pantalla que mirar y como nombrar el
     screenshot.
  5. Deja todo en una carpeta `run_<Label>_<timestamp>\` -- esa carpeta
     completa es lo que hay que llevarse.

El companion del casco (03f0:0580) manda su `DEVICE_STATUS` HID solo cuando
algo CAMBIA, no en regimen -- por eso conviene una captura CORTA (10-15s
alcanza) puesta justo alrededor del momento en que arranca el runtime o se
cambia el refresh rate, no dejarla corriendo minutos.

Repetir con distintos `-Label` (por ejemplo `60hz`, `90hz`, `idle`) las veces
que haga falta -- cada corrida arma su propia carpeta con timestamp, nunca se
pisan entre si.


ANALISIS -- ya del lado Linux
---------------------------------------------------------------------
    python3 analyze-windows.py run_90hz_*/90hz_USBPcap*.tsv run_60hz_*/60hz_USBPcap*.tsv

Busca el `DEVICE_STATUS` (0x05, 33 bytes) del companion y lo compara contra
`REF_LINUX` (capturas de referencia en Linux, ya con el parche del bpc
puesto). Tambien busca el log de firmware del HoloLens Sensors (0x03, ASCII).


SI ALGO NO SALE
---------------------------------------------------------------------
- No aparece ninguna interfaz USBPcap -> no reiniciaste despues de instalar
  Wireshark, o no tildaste el componente USBPcap en el instalador.
- El panel de NVIDIA no abre solo -> las versiones nuevas lo empaquetan
  distinto; abrilo a mano (click derecho en el escritorio -> NVIDIA Control
  Panel). El Reverb G2 de todas formas no va a aparecer ahi como display
  seleccionable -- es un resultado ya confirmado, no un error tuyo.
- HWiNFO64 no muestra nada de Pixel Clock/Link Rate de DisplayPort -> no es
  un fracaso, es un dato ya confirmado: esta version/GPU no lo expone.
- CRU no muestra al Reverb G2 en la lista -> confirma que el casco sigue
  activo (imagen prendida) en ese momento; CRU lista los displays conectados
  al momento de abrirlo.

No hace falta entender la salida de nada de esto en el momento. Traela
entera y se analiza en Linux con `analyze-windows.py` (para el HID) y a ojo
el resto.
