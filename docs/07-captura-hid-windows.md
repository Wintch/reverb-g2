# 07 — Capturar la secuencia HID de 90Hz en Windows

> ## ⚠ ARCHIVADO (2026-08-04, 21:00) — NO hace falta hacer esto
>
> Este capítulo existía para averiguar qué comando HID le pide el modo de 90Hz al casco.
> **Ese comando no existe.** Se desensambló el driver Oasis —el que corre el G2 a 90Hz
> en Windows hablándole al casco directo— y su único comando de panel es *Display Enable*
> (Usage Page `0x03`, Usage `0x21`), que es exactamente el `{0x04,0x01}` que Monado ya manda.
>
> Evidencia y método en **`docs/09-oasis-driver-re.md`**. Descarte en el cap. 06.
>
> Se conserva el procedimiento porque la técnica (usbmon + tshark + `analyze-hid.py`) sigue
> sirviendo para otras preguntas — por ejemplo los resets del hub USB2 bajo carga.

**Este documento se sigue solo, sin agente.** En Windows no hay Claude al lado: la idea es
que salgas de acá con dos archivos y vuelvas a Linux a analizarlos.

## Por qué

El cap. 04 dejó medido que los parches del 595-open **no** arreglan el 90Hz, y el código de
Monado muestra por qué puede no ser culpa de NVIDIA: `wmr_hmd_activate_reverb()`
(`wmr_hmd.c:767`) manda **siempre la misma secuencia HID**, corra el panel a 60 o a 90. El
"parche 90Hz" de Monado (`wmr_hmd.c:1992`) sólo setea `nominal_frame_interval_ns`, que es un
número para el pacing — no toca el panel.

Hipótesis: **al casco nunca se le pide cambiar el panel a 90Hz.** Windows sí lo hace, y el
mismo casco corre 90Hz horas ahí. Queremos ver ese comando.

## El experimento, y por qué así

Lo tentador es capturar Windows y comparar contra Monado. Es un diff sucio: difieren en el
stack entero y hay que separar señal de ruido a mano.

**Mejor: capturar Windows a 60Hz y Windows a 90Hz.** Misma máquina, mismo casco, mismo
driver, mismo cable — la única variable es el refresh. Lo que aparezca en la captura de 90 y
no en la de 60 es, literalmente, el comando que falta.

Si tu Windows no ofrece la opción de 60Hz, ver "Plan B" al final.

## Qué se captura

Sólo el **companion `03f0:0580`** (HP, Inc QHMD A85V). Es el `hid_control_dev` de Monado:
por ahí van la activación y el `screen_enable`.

**No captures el `045e:0659` (HoloLens Sensors)**: escupe IMU a alta frecuencia y ahoga el
archivo. Tampoco las cámaras.

## Preparación (una vez)

1. Instalar **Wireshark** (https://www.wireshark.org/download.html).
2. Durante la instalación, **tildar el componente `USBPcap`**. No viene por defecto.
3. **Reiniciar** — USBPcap instala un filter driver y no funciona hasta el reboot.

## Captura

Repetir entero para cada refresh. El truco importante está en el paso 3.

1. En **Configuración de Windows → Realidad mixta → Pantalla del visor**, fijar la
   frecuencia de actualización. Buscá algo tipo *"Experience options"* / *"Opciones de
   experiencia"* / *"Frecuencia de actualización"*, con valores **60 Hz / 90 Hz /
   Automático**. Poné el valor **explícito**, nunca "Automático" — necesitamos saber cuál
   estaba activo.
2. Cerrar el Portal de Realidad Mixta y **desenchufar el casco del USB**.
3. Abrir Wireshark, elegir la interfaz **USBPcap** del root hub donde va el casco, y
   **arrancar la captura ANTES de enchufarlo**. Esto es lo que hace fácil todo lo demás:
   vas a ver la enumeración completa (que te revela el device address del companion) *y*
   la secuencia de activación, en el mismo archivo.
4. Enchufar el casco. Abrir el Portal y **esperar a que el panel encienda de verdad**
   (mirá adentro: tiene que haber imagen, no el logo de HP).
5. Dejar correr ~15 s más y **parar la captura**.
6. Guardar como `windows-90hz.pcapng` (o `windows-60hz.pcapng`).

Repetir con el otro refresh.

### Encontrar el device address del companion

En Wireshark, filtro:

```
usb.idVendor == 0x03f0 && usb.idProduct == 0x0580
```

Eso matchea la respuesta del descriptor durante la enumeración. En esa fila, mirá la
columna **Source/Destination**: el número tipo `3.7.0` es `bus.device.endpoint`. Anotá el
**device** (`7` en el ejemplo). Si el filtro no da nada, buscá `usb.descriptor_type == 1`
y recorré los descriptores hasta encontrar el de HP.

### Exportar a texto

El analizador de Linux lee TSV, así no hay que parsear pcapng. Desde `cmd` o PowerShell
(ajustá `N` al device address que anotaste):

**El orden de los campos importa**: el analizador los espera exactamente así.

```
"C:\Program Files\Wireshark\tshark.exe" -r windows-90hz.pcapng ^
   -Y "usb.device_address==N" -T fields ^
   -e frame.time_relative -e usb.device_address ^
   -e usb.bmRequestType -e usb.setup.bRequest -e usb.setup.wValue ^
   -e usb.capdata > windows-90hz.tsv
```

Los tres campos del medio (`bmRequestType`, `bRequest`, `wValue`) son los que permiten
distinguir un `SET_REPORT` real de un descriptor cualquiera. Sin ellos el análisis es
basura: se probó, y el bus está lleno de tráfico que *parece* reportes HID y no lo es.

Idem para 60. **Verificá que los `.tsv` no estén vacíos** antes de dar por terminada la
sesión de Windows — si están vacíos, el device address está mal.

### Prueba de que la captura sirve

Buscá en el `.tsv` una fila con `bRequest = 0x09` y `wValue = 0x0350`: es el `SET_REPORT`
Feature del report `0x50`, el primer comando de la activación. **Si no está, la captura no
agarró el arranque del casco** — casi siempre porque empezaste a capturar después de
enchufarlo. Repetila.

## Qué traer de vuelta

Copiar a algún lado accesible desde Linux (pendrive, partición compartida, la nube):

- `windows-90hz.pcapng` y `windows-60hz.pcapng` (los originales, por si hay que re-filtrar)
- `windows-90hz.tsv` y `windows-60hz.tsv` (lo que se analiza)
- Anotado a mano: **qué opción de refresh estaba puesta en cada una**, y **qué viste dentro
  del casco** en cada corrida.

## De vuelta en Linux

```bash
cd ~/Documents/reverb-g2-linux

# El diff que importa: A=60Hz, B=90Hz. Lo que salga en "EN B PERO NO EN A" es la respuesta.
./scripts/analyze-hid.py diff windows-60hz.tsv windows-90hz.tsv

# Y contra lo que manda Monado (capturado con scripts/capture-hid.sh):
./scripts/analyze-hid.py diff ~/vr/hid-mode0.txt windows-90hz.tsv
```

El script normaliza las dos capturas a la misma forma (dirección, report ID, payload),
ignora timestamps y padding, y marca como `[DESCONOCIDO]` todo report ID que Monado no
mande hoy. **Un report ID desconocido que sólo aparece en la captura de 90Hz es el
candidato.**

## Plan B: si Windows no ofrece elegir 60Hz

Capturar sólo 90Hz y diffear contra Monado:

```bash
./scripts/analyze-hid.py diff ~/vr/hid-mode0.txt windows-90hz.tsv
```

Es más ruidoso — van a aparecer diferencias que no tienen nada que ver con el refresh
(orden de enumeración, telemetría, polling). Sirve igual: lo que se busca es un **report ID
que Monado no manda nunca**, y eso destaca aunque haya ruido alrededor.

## Cómo se cierra esto

Si aparece el comando, el camino es un parche al driver WMR de Monado que lo mande cuando
el modo pedido es de 90Hz. Eso sería un parche nuestro en `patches/monado/`, y —
importante — **movería la causa raíz del proyecto de NVIDIA a Monado**, que es lo contrario
de lo que se venía asumiendo (ver la corrección en el cap. 06).

Si **no** aparece ningún comando extra — si Windows manda exactamente lo mismo a 60 y a 90 —
entonces la hipótesis está muerta, el modo se negocia por DisplayPort, y hay que volver al
lado del driver de video. Anotarlo igual: un descarte medido vale tanto como un hallazgo, y
este proyecto ya perdió semanas por no anotarlos.
