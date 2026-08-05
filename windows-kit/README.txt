================================================================================
  KIT DE CAPTURA EN WINDOWS  —  HP Reverb G2 a 90 Hz  (v2, 2026-08-05)
  Proyecto: soporte del G2 en Linux.
================================================================================

QUE ESTAMOS BUSCANDO, EN UNA LINEA
----------------------------------
En Linux el casco a 90 Hz muestra el logo de HP y no engancha. En Windows anda.
Ya sabemos que NO es un comando HID de modo (desensamblamos el driver de HP: no
existe), NO es ancho de banda, NO es la duracion del vblank, y NO es el refresh
en si (medimos exactamente esto en Linux con un factorial completo). El unico
patron que sobrevive: el UNICO pixel clock que alguna vez mostro imagen es
~709.15 MHz. Lo que buscamos ahora es leer, CON EL CASCO ANDANDO A 90 Hz EN
WINDOWS, cuatro cosas — cada una barata, cada una puede ser la que cierre esto:

  1. HID del propio casco     (ya lo haciamos v1 — sigue siendo la base)
  2. El timing REAL que usa el driver a 90 Hz (pixel clock, htotal/vtotal,
     lane count, link rate)  <-- NUEVO, es la pregunta que mas importa ahora
  3. Si el driver activa DSC (compresion) sin que lo esperemos
  4. [opcional, mas trabajo] una traza ETW del lado del kernel de video

Los primeros tres se hacen en UNA sola sesion con el casco a 90 Hz, en
cualquier orden salvo el paso 1 (que necesita capturar ANTES de enchufar el
casco). El cuarto es una pasada aparte, opcional.


PREPARACION (una sola vez, requiere reiniciar por Wireshark/USBPcap)
---------------------------------------------------------------------
1. Wireshark, CON el componente USBPcap tildado en el instalador (no viene
   tildado por defecto):
       https://www.wireshark.org/download.html
   REINICIAR despues de instalar — USBPcap instala un filtro y no anda hasta
   el reboot.

2. HWiNFO64 (no necesita reboot, portable o instalado, como prefieras):
       https://www.hwinfo.com/download/
   Buscamos, en el panel de Sensors, cualquier campo de la GPU/Display que
   diga "Pixel Clock", "Link Rate" o "Lane Count" para el conector del casco.
   No todas las versiones/GPUs lo muestran — si no aparece nada, no es un
   fracaso, es un dato (anotalo y seguimos con CRU).

3. CRU (Custom Resolution Utility), portable, SIN instalar — bajar el .zip,
   descomprimir, correr CRU.exe directo:
       https://www.monitortests.com/forum/Thread-Custom-Resolution-Utility-CRU
   (es el sitio oficial del autor, ToastyX — ojo con dominios parecidos tipo
   customresolutionutility.dev/.net, no son la fuente oficial)

Nada de esto pisa el driver de NVIDIA ni el del casco — los tres son de solo
lectura/edicion de EDID en el registro, no tocan DPCD en caliente.


CAPTURA — PASE 1: HID + timing real + DSC (aprox. 20 minutos)
-----------------------------------------------------------------

  *** EL ORDEN IMPORTA MUCHISIMO PARA EL PASO USB. LEELO ANTES DE EMPEZAR. ***

  Lo que necesitamos del canal USB es el ARRANQUE del casco, no el uso.
  Medido en Linux: el casco manda su mensaje de estado SOLO CUANDO ALGO
  CAMBIA, y su log de firmware SOLO habla mientras el driver hace la
  secuencia de inicializacion. Si empezas a capturar con el casco ya andando
  en regimen, esa parte de la captura sale VACIA aunque todo parezca bien.

  Por eso: primero la captura USB, DESPUES el casco. Y no hace falta ningun
  juego — un juego solo agrega ruido al bus.

1. DESCONECTAR el casco (el USB). Que Windows lo pierda del todo.

2. Abrir "cmd" COMO ADMINISTRADOR, ir a esta carpeta, y correr:

       capture.bat

   Te lista las interfaces USBPcap y te pide elegir una. Es la del root hub
   donde vas a enchufar el casco. Si no sabes cual, elegi una: al cortar te
   dice si vio al casco o no, y si no lo vio probas con otra.

3. CON LA CAPTURA YA CORRIENDO, enchufar el casco y dejar que Windows lo
   levante entero (el portal de WMR / SteamVR con el driver Oasis).

4. Ponetelo y confirma que VES IMAGEN a 90 Hz. Mira unos 30 segundos.

5. CON EL CASCO TODAVIA ANDANDO A 90 Hz (no lo desconectes todavia), ahora
   sacamos los datos de timing y DSC:

   a) Abrir CRU.exe. Debería aparecer el Reverb G2 en la lista de displays.
      Seleccionalo, y andá a "Detailed resolutions" (o el equivalente en tu
      version) — ahi esta el timing detallado que CRU lee como ACTIVO para
      ese display: pixel clock, total horizontal/vertical, front/back porch,
      sync width. SACALE UNA CAPTURA DE PANTALLA a esa ventana completa.
      Cerra CRU SIN GUARDAR NADA (no queremos escribir un override, solo
      leer el que ya esta activo).

   b) Abrir HWiNFO64 -> Sensors. Buscá la seccion de la GPU o del display del
      casco. Si aparece algo de "Pixel Clock", "Link Rate" (deberia decir
      HBR2/HBR2.5/HBR3) o "Lane Count", SACALE UNA CAPTURA DE PANTALLA.

   c) Panel de control de NVIDIA -> Ayuda -> Informacion del sistema.
      SACALE UNA CAPTURA DE PANTALLA — ahi figura si el display usa DSC
      (Display Stream Compression). Calculamos que a 90 Hz no deberia hacer
      falta, pero nunca lo verificamos en Windows. Es un agujero de nuestro
      propio razonamiento y esta captura lo tapa.

6. Volve a la ventana de cmd de capture.bat y cortá con Ctrl+C.

7. Si podes, repetí TODO (los 3 sub-pasos de arriba tambien) forzando 60 Hz
   en la configuracion, y renombra los resultados agregando "-60hz". Es el
   control del lado de Windows y vale casi tanto como el de 90.


LO QUE TENES QUE TRAER DE VUELTA DEL PASE 1
----------------------------------------------
   windows-90hz.pcapng  y  windows-90hz.tsv     (los genera capture.bat)
   windows-90hz-cru.png                          (paso 5a)
   windows-90hz-hwinfo.png                       (paso 5b)
   windows-90hz-nvidia-info.png                  (paso 5c)
   y los mismos 5 archivos con "-60hz" si repetiste el control

Copialos todos juntos a un pendrive o a una particion que se vea desde Linux.


CAPTURA — PASE 2 (OPCIONAL, mas trabajo): traza ETW del kernel de video
----------------------------------------------------------------------
El propio driver Oasis trae un perfil de Windows Performance Recorder listo
para usar, en su carpeta de instalacion:

    <carpeta de instalacion de Oasis>\tracing\Capture-ETL.bat

(en Steam suele ser algo como
 C:\Program Files (x86)\Steam\steamapps\common\Oasis Driver for Windows Mixed Reality\tracing\)

Es una pasada APARTE de la del Pase 1 — no la corras al mismo tiempo que
capture.bat, se pisan. El procedimiento:

1. Casco desconectado.
2. Abrir "cmd" COMO ADMINISTRADOR en esa carpeta de tracing y correr
   Capture-ETL.bat. Va a decirte cuando esta listo para capturar.
3. Enchufar el casco, ponertelo, confirmar imagen a 90 Hz, esperar ~30s.
4. Volver a la consola y cortar como te indique el .bat (usualmente Ctrl+C
   o una tecla).
5. Te va a dejar un .etl en esa misma carpeta (o donde diga el .bat).

Este perfil es de Bucchianeri (autor de Oasis) — puede que no traiga
proveedores del lado del kernel de video de NVIDIA, en cuyo caso el .etl
sale liviano y sin nada de display. Igual vale la pena: aunque Oasis no
toque timing de video, el mismo archivo puede traer eventos correlacionables
por tiempo con lo que haga el resto del sistema.

TRAETE: el archivo .etl que te deje.


SI ALGO NO SALE
----------------
- El .tsv sale vacio  -> el device address esta mal, o elegiste la interfaz
  USBPcap equivocada. Probá otra.
- No aparece USBPcap en Wireshark -> no reiniciaste, o no tildaste el
  componente en el instalador.
- CRU no muestra al Reverb G2 en la lista -> confirmá que el casco sigue
  activo (imagen a 90Hz) en ese momento; CRU lista los displays conectados
  en el momento en que lo abrís.
- HWiNFO64 no muestra nada de Pixel Clock/Link Rate -> no es un fracaso, es
  un dato — anotalo así y seguí con el resto. No todas las versiones lo
  exponen para todos los GPUs.
- Windows no te deja elegir 60 Hz -> no importa, el de 90 es el que
  necesitamos; saltate el paso 7 / el Pase 2 a 60Hz.

No hace falta que entiendas la salida de nada de esto. Traela entera y la
analizamos en Linux con analyze-windows.py (para el HID) y a ojo el resto.
