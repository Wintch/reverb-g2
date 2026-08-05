================================================================================
  KIT DE CAPTURA EN WINDOWS  —  HP Reverb G2 a 90 Hz
  Proyecto: soporte del G2 en Linux.  Fecha: 2026-08-05
================================================================================

QUE ESTAMOS BUSCANDO, EN UNA LINEA
----------------------------------
En Linux el casco a 90 Hz muestra el logo de HP y no engancha. En Windows anda.
Ya sabemos que NO es un comando HID de modo (desensamblamos el driver de HP: no
existe). Lo que queremos ahora es leer, CON EL CASCO ANDANDO A 90 Hz EN WINDOWS,
los dos canales que el propio casco emite — y compararlos byte a byte con lo que
emite en Linux cuando falla.

Canal 1  DEVICE_STATUS         del companion 03f0:0580  (reporte 0x05, 33 bytes)
Canal 2  LOG DE FIRMWARE       del HoloLens Sensors 045e:0659 (reporte 0x03, 509 bytes)

Lo que ya medimos en Linux, para que sepas contra que se compara:

  60 Hz ANDA   05 00 01 01 00 3c 00 00 00 05 2c 1e 02 00 77 00 ...
  90 Hz FALLA  05 00 01 01 00 5a 00 00 00 0c 1a 14 02 00 77 00 ...
                           ^^          ^^ ^^ ^^ ^^
                        refresh      estos NO sabemos que son

  byte 5      = refresh en decimal (0x3c=60, 0x5a=90)   [confirmado]
  bytes 19-20 = htotal little-endian                    [confirmado]
  bytes 21-22 = vtotal little-endian                    [confirmado]
  bytes 9,10,12,14,15 y 24-31 = DESCONOCIDOS            <-- el objetivo

Si en Windows, con el panel encendido a 90, esos bytes son distintos a los
nuestros, ahi esta la diferencia. Si son identicos, el casco esta en el mismo
estado en los dos sistemas y la causa esta en otra capa. Los dos resultados
sirven.


PREPARACION (una sola vez, requiere un reinicio)
------------------------------------------------
1. Instalar Wireshark:  https://www.wireshark.org/download.html
2. EN EL INSTALADOR, TILDAR EL COMPONENTE "USBPcap". No viene tildado por defecto.
3. REINICIAR. USBPcap instala un filter driver y no anda hasta el reboot.


CAPTURA  (aprox. 15 minutos)
-----------------------------

  *** EL ORDEN IMPORTA MUCHISIMO. LEELO ANTES DE EMPEZAR. ***

  Lo que necesitamos es el ARRANQUE del casco, no el uso. Medido en Linux: el
  casco manda su mensaje de estado SOLO CUANDO ALGO CAMBIA, y su log de firmware
  SOLO habla mientras el driver hace la secuencia de inicializacion. Si empezas a
  capturar con el casco ya andando en regimen, la captura sale VACIA aunque todo
  parezca bien.

  Por eso: primero la captura, DESPUES el casco.

  Y no hace falta ningun juego. Un juego solo agrega ruido al bus.

1. DESCONECTAR el casco (el USB). Que Windows lo pierda del todo.

2. Abrir "cmd" COMO ADMINISTRADOR, ir a esta carpeta, y correr:

       capture.bat

   Te lista las interfaces USBPcap y te pide elegir una. Es la del root hub donde
   vas a enchufar el casco. Si no sabes cual, elegi una: al cortar te dice si vio
   al casco o no, y si no lo vio probas con otra.

3. CON LA CAPTURA YA CORRIENDO, enchufar el casco y dejar que Windows lo levante
   entero (el portal de WMR / SteamVR con el driver Oasis).

4. Ponetelo y confirma que VES IMAGEN a 90 Hz. Mira unos 30 segundos.

5. Volve a la ventana de cmd y cortá con Ctrl+C.

6. Si podes, repetí TODO forzando 60 Hz en la configuracion, y renombra el
   resultado a windows-60hz.pcapng / .tsv. Es el control del lado de Windows y
   vale casi tanto como el de 90.


LO QUE TENES QUE TRAER DE VUELTA
---------------------------------
   windows-90hz.pcapng      (y windows-60hz.pcapng si lo hiciste)
   windows-90hz.tsv         (los genera el .bat)
   captura-nvidia.png       ver abajo

Copialos a un pendrive o a una particion que se vea desde Linux.


EXTRA, 2 MINUTOS, Y VALE MUCHO
-------------------------------
Con el casco andando a 90 Hz:

   Panel de control de NVIDIA -> Ayuda -> Informacion del sistema

Sacale una captura de pantalla. Ahi figura si el display usa DSC (Display Stream
Compression). Nosotros calculamos que a 90 Hz no hace falta, pero NUNCA
verificamos si el driver la activa igual. Es un agujero de nuestro propio
razonamiento y esta captura lo tapa.


SI ALGO NO SALE
----------------
- El .tsv sale vacio  -> el device address esta mal, o elegiste la interfaz
  USBPcap equivocada. Probá otra.
- No aparece USBPcap en Wireshark -> no reiniciaste, o no tildaste el componente
  en el instalador.
- Windows no te deja elegir 60 Hz -> no importa, el de 90 es el que necesitamos.

No hace falta que entiendas la salida. Traela y la analizamos en Linux con
analyze-windows.py, que esta en esta misma carpeta.
