# 06 — Problemas conocidos y por qué NO los perseguimos (con evidencia)

## Audio del casco: RESUELTO — era el puerto USB (2026-08-04)

> Esta sección decía que el audio era una falla física incurable del cable. **Era falso.**
> Se deja el error documentado porque costó meses de diagnóstico equivocado.

El cable del G2 lleva una rama SuperSpeed y una rama USB 2.0 por el mismo puerto físico. En
el puerto USB-A que usábamos, la rama SuperSpeed enumeraba bien y **la rama USB 2.0 nunca
entrenaba el link**:

```
usb usb3-port2: Cannot enable. Maybe the USB cable is bad?
usb 3-2: device not accepting address 6, error -71
usb usb3-port2: unable to enumerate USB device
```

Todo lo que vive en esa rama quedaba ausente: el companion `03f0:0580` (HID de control **y**
audio). Por eso Monado caía a Simulated HMD y por eso no aparecía ningún device de audio.
En terminología WMR esto es el **error 7-14**, "required USB2 components not found", una
falla documentada del G2: el cable es extra largo y deja los márgenes de señal USB muy
justos.

**Mover el casco a otro puerto USB-A trasero lo arregló por completo.** Cero `error -71`
desde entonces. Girar el conector USB-C 180° dentro del adaptador C→A también ayudó por su
cuenta (levantó los sensores HoloLens). Probar el puerto primero, la orientación después.

### Enumeración correcta — los cinco tienen que estar

```
3-1    04b4:6506  HP WMR hub (USB2)         480M
3-1.2  0bda:4c15  USB Audio                 480M   <- parlantes + micrófono del casco
3-1.3  03f0:0580  QHMD A85V s/n REDACTED   12M   <- companion, HID de control
4-1    04b4:6504  HP WMR hub (USB3)        5000M
4-1.1  045e:0659  HoloLens Sensors         5000M
```

Si falta `03f0:0580`, **no debuguear Monado** — revisar el puerto.

### Matiz importante, medido en el lab (2026-08-04, tarde)

"Cambiar de puerto" resultó ser una descripción incompleta de la cura. Reproducido con
método en el lab:

1. Estado inicial: enumeraba **sólo** el hub SuperSpeed (`04b4:6504`), nada detrás de él.
   `usb3-port2: Cannot enable` + `error -71` en la rama USB2.
2. Se movió el cable a otro puerto USB-A trasero. **El fallo se movió con el casco**:
   pasó a `usb3-port3`, mismo `error -71`. Eso **descarta que el puerto sea la causa** — lo
   que sí cambió es que aparecieron los `045e:0659 HoloLens Sensors`.
3. Recién al reconectar el conjunto (cable + orientación del USB-C en el adaptador C→A)
   enumeraron los cinco de una.

O sea: los márgenes de señal de ese cable están tan justos que el resultado depende del
contacto concreto, no de qué puerto sea. **El síntoma es progresivo, no binario** — se puede
tener SuperSpeed sin USB2, o SuperSpeed + sensores sin companion. Criterio de corte: contar
los cinco en `lsusb`, nunca "parece conectado".

Corolario para diagnóstico: **si el companion falta, el display tampoco aparece**. Con
`03f0:0580` ausente, `DP-0` figura `disconnected` en xrandr y el kernel no ve ningún sink
DisplayPort nuevo, porque el panel no linkea hasta recibir la activación WMR por HID. Ver
`DP-0 disconnected` con el casco enchufado **no** significa problema de video ni de cable
DP: mirar primero el USB.

### El audio, cómo encontrarlo

Enumera como card ALSA `USB-Audio - Generic USB Audio` (`0bda:4c15`, chip Realtek), **sin
ninguna cadena HP/Reverb/WMR**. Por eso los chequeos que grepeaban `hp|reverb|wmr` daban
"no hay audio del casco" aun estando presente. Confirmado audible 2026-08-04, y estable:
30 segundos de reproducción continua sin un solo corte.

Sink `alsa_output.usb-Generic_USB_Audio-00.analog-stereo` + su source (el micrófono). El
device reporta mal su rango de volumen (`Unlikely big volume range (=800)`, PCM en `-25600`)
y PipeWire delega el volumen a esa escala rota, así que **un porcentaje intermedio puede ser
inaudible: probar siempre al 100%**.

Esto explica también el síntoma que el usuario venía sufriendo en Windows desde siempre
(device de audio que aparece, se mutea y desaparece). Nunca fue un problema de sistema
operativo.

## Caídas del hub USB2 bajo carga: NO es la fuente (2026-08-04, tarde)

Con el panel encendido, el hub USB 2.0 interno (`04b4:6506`) se resetea cada tanto y se
lleva al companion `03f0:0580` y al audio. Desconexión limpia + re-enumeración limpia, sin
`error -71`. Medido a la mañana con gradiente de carga: 0/10 drops sin Monado → 6/15 con
panel + render. Eso parecía un brownout, y la conclusión de la mañana fue "cambiar la
fuente DC".

**Esa conclusión está retirada.** Evidencia del usuario: en **Windows 11 el mismo casco,
misma fuente, mismo todo, anduvo HORAS a 90Hz** (que consume más que nuestro 60Hz) sin una
sola caída. Si faltara corriente, Windows caería igual — el hardware no sabe qué OS corre.
Lo único frágil en Windows fue siempre el audio (device que aparece, se mutea, desaparece),
o sea la rama de audio es problemática en ambos OS por su cuenta.

Reproducido además 2 veces hoy: companion caído durante horas de uso → `kill` a Monado →
**vuelve solo a los ~5 segundos**. Un problema eléctrico no se arregla cerrando un proceso.

**Hipótesis vigente:** el driver WMR de Monado maneja los reportes HID (keepalive/estado)
distinto que el stack de Windows, y algo de ese tráfico — o su ausencia — hace que el
firmware del casco recicle el hub. Correlaciona con carga porque Monado bajo carga cambia
su timing de HID. Pendiente: instrumentar `wmr_hmd.c` (logging de cada report + timestamps)
la próxima vez que se caiga. **No comprar fuente.**

## Basalt SLAM diverge (6DoF de cabeza)

~3° de error medio entre frames con el casco INMÓVIL (spam de `det(Q1Jl)==0`). Se usa
`WMR_SLAM=0` (IMU 3DoF, impecable) para todo lo orientation-only. Investigación pendiente:
¿calibración? ¿textura visual del ambiente? ¿exposición? Es el desbloqueo técnico más
valioso después del 90Hz.

## SteamVR no levanta (y no es culpa nuestra)

El driver Monado para SteamVR carga OK (con el RPATH del patch 0002 + bundle de libs),
pero `vrmonitor` de Valve crashea por `libQt5Multimedia.so.5` faltante **dentro del
runtime container de Valve**. Camino recomendado: **OpenComposite** (OpenVR→OpenXR directo
contra Monado, saltea SteamVR entero) — no probado aún.

## 90Hz — los parches del 595-open NO lo arreglan (2026-08-04, 18:55)

Se creía: bug del driver NVIDIA (5923212), no de hardware ni de Monado; sin fix upstream
hasta 610.x inclusive; el lab con el 595-open parcheado era el plan activo.

**Medido: no alcanza.** Con los tres parches de Project-VR instalados vía DKMS y el módulo
parcheado confirmado en memoria, los dos modos de 90Hz siguen dejando el panel apagado con
el logo de HP — idéntico al baseline sin parches. Verificación física, seis casos, tabla
completa en el cap. 04. El control a 60Hz corrido después dio imagen perfecta, así que el
setup estaba sano.

### DESCARTADO: "falta un comando HID que le pida el modo al casco" (2026-08-04, 21:00)

Se creía, y se escribió como hipótesis viva en el cap. 04 y en `CLAUDE.md`: el driver WMR de
Monado manda la misma secuencia HID de activación para 60 y para 90Hz (`wmr_hmd.c:767`), y el
"parche 90Hz" sólo setea `nominal_frame_interval_ns` para el pacing (`wmr_hmd.c:1992`) — no
toca el panel. De ahí salió todo el `docs/07` (capturar el HID de Windows).

**Es falso, y hay dos evidencias independientes:**

1. **Por argumento (19:30):** Project-VR llega a `4320x2160@90` con parches al driver de
   video y sin ningún comando propietario.
2. **Por lectura del binario (21:00):** se montaron read-only las NTFS del disco de Windows y
   se desensambló el **Oasis Driver de HP** — el driver standalone que corre el G2 a 90Hz y
   que habla con el casco directo, sin pasar por el runtime WMR del SO. Su **único** comando
   de panel es *Display Enable* (HID Usage Page `0x03` VR Controls, Usage `0x21`), que es
   exactamente el `{0x04, 0x01}` que Monado ya manda. No existe comando de refresh rate.
   Procedimiento y falsos positivos en **`docs/09-oasis-driver-re.md`**.

Los dos falsos positivos que hay que no volver a perseguir: `HmdDriver_SetFrameRate` es de
las cámaras (`IspFrameRate`/`SensorFrameRate`, igual que `OV7251SetFrameRate`), y
`Detected change of refresh rate` es contabilidad interna de SteamVR sobre
`Prop_DisplayFrequency_Float`.

**Conclusión: la secuencia HID de Monado es correcta y suficiente. El panel adopta el refresh
del video que le llega.** `docs/07-captura-hid-windows.md` queda archivado — no hace falta
bootear Windows.

Nota de proceso: esta hipótesis murió dos veces porque entre la primera y la segunda
`CLAUDE.md` quedó desactualizado dándola por viva, y se la volvió a citar como "la única que
explica los resultados". Al cerrar una línea, actualizar `CLAUDE.md` **en el mismo commit**.

### CUIDADO: Project-VR NO es un caso positivo verificado (2026-08-04, 23:00)

Todo el plan del lab se apoyaba en que [Project-VR](https://github.com/AshishKumar4/Project-VR)
tenia el G2 andando a `4320x2160@90` en Linux. **Ese claim no resiste.**

- 0 estrellas, 0 forks, 0 issues, 0 PRs. Cero menciones externas en toda la web.
- **Cero imagenes o video en sus 177 archivos.** Un solo commit de volcado inicial (2026-07-03).
- Validado en Ada (RTX 4080), nunca en Ampere.
- Y lo decisivo: su evidencia de "90Hz funcionando" es **una sesion Vulkan/OpenXR exitosa y
  sus logs** — exactamente la clase de evidencia que este proyecto ya demostro nueve veces
  que es **compatible con el panel muerto**. La API reporta 90.0 fps felices con el logo de HP.

Seria el cuarto falso positivo de la misma familia que el cable, la fuente y el audio: una
conclusion dada por buena sin que un humano haya mirado.

**No invertir mas tiempo en sus parches tal como estan.** La unica forma de rehabilitarlo es
pedirle al autor una foto o un video del panel encendido a 90Hz.

Corolario incomodo: **no hay UN SOLO caso humano confirmado de G2 a 90Hz en Linux, con ninguna
GPU** — tampoco AMD. Veniamos preguntandonos por que a nosotros no nos andaba lo que a otros
si; puede que no le haya andado a nadie.

### El bug de NVIDIA es transversal y esta abierto (2026-08-04)

Del hilo del foro (bug interno **5923212**): NVIDIA **admitio y reprodujo** el bug el
2026-03-20, y sigue sin resolucion al 2026-07-19. Falla igual en **Turing, Ampere y
Blackwell** (2070 SUPER, 3090, A5000, 5070 Ti) y de la serie 590.x a la 610.x.

Esto explica por que los 3 parches de Project-VR no cambiaron nada: si el bug vive en el
firmware GSP o en el blob cerrado de userspace, ningun parche a los *open kernel modules*
puede alcanzarlo. Y cambia el objetivo: de "encontrar el parche correcto" a "confirmar en que
capa vive y aportar evidencia al bug".

### DESCARTADO: DSC como causa (2026-08-04, 21:30) — la cuarta teoría de bandwidth que cae

Muerto lo del HID, el sospechoso era DSC: el parche 0001 de Project-VR dice arreglar el
*"90 Hz handshake"* de DSC 1.1. Pero los números del EDID del casco no lo sostienen:

| modo | pixel clock | 24 bpp | ¿anda? |
|---|---|---|---|
| 2880x1440@90 | 428.6 MHz | **10.29 Gbps** | NO |
| 4320x2160@60 | 709.1 MHz | 17.02 Gbps | SÍ |
| 4320x2160@90 | 905.4 MHz | 21.73 Gbps | NO |

Enlace: 4 lanes HBR3 = **25.92 Gbps** útiles. El modo `2880x1440@90` pide menos de la mitad
que el `4320x2160@60` que funciona: **no puede necesitar compresión**, y falla igual. DSC
explicaría a lo sumo el modo de 4320@90 a 30 bpp, no el otro. Tabla completa y el test que
falta correr, en el cap. 04.

### Descartado: contención de displays / dominios de reloj de la GPU

Distinto del bandwidth del cable DP (más abajo): esto era sobre el display engine con
varios heads activos. Se probó con un solo monitor y con **cero** — el casco como único
display del sistema — y el panel sigue apagado. Además el modo 90Hz que falla consume menos
pixel clock (428 MHz) que el modo 60Hz que anda (709 MHz). No es esto.

## Controllers: solo 3DoF

Límite de código del driver WMR upstream (posición hardcodeada). Roadmap constellation en
cap. 03. La confiabilidad de conexión ya la arreglamos (patches/monado/0004-0006).

## Cuelgue total 2026-08-04 (resuelto por diseño)

Disco raíz USB compartiendo xHCI con el casco + autosuspend. Cap. 00 tiene el análisis y
los procedimientos. Los .mp4 truncados de esa mañana (marsa*, sin moov atom) no son
recuperables — re-descargar.

## Hardware roto conocido

- 16GB RAM (upgrade a 32 planeado); zram configurado al 100% con zstd.
- NVMe 1.8TB enteramente NTFS (Windows) — el futuro setup ideal debería darle una
  partición nativa a Linux para media/scratch de Resolve.
