# Next step

## LEER PRIMERO — estado al 2026-08-06, madrugada

Escrito desde el sistema everyday con el SSD del lab montado read-write en `/mnt/lab`, antes
de que el usuario reinicie a la instalación del lab para probar físicamente. **Esto es lo que
hay que hacer al volver — el resto del archivo, más abajo, es historial del 90Hz, no leer
primero.**

Repo ya público (`github.com/Wintch/reverb-g2`), update de anoche posteado en el hilo de
NVIDIA (379240), y las 4 MRs de Monado abiertas contra upstream (`monado/monado` #2967,
#2968, #2969, #2971) — nada de eso necesita al lab, ya está resuelto.

**Lo que sí necesita al lab, en orden:**

1. **Controllers** (los 4 patches de input/conexión ya están en `patches/monado/0001-0008`,
   aplicados vía `bootstrap-lab.sh sources`; también ya están subidos a upstream como MR, ver
   arriba, pero eso no cambia nada localmente):
   ```bash
   ./jack-in.sh 3dof     # prender los controllers antes o después, ya no importa
   grep -E "left:|right:" ~/Documents/reverb-g2/jack-in.log
   # debe decir: left: HP Reverb G2 Left Controller / right: HP Reverb G2 Right Controller
   ```
   Diagnóstico en vivo (sticks, batería, IMU por controller): `XRT_DEBUG_GUI=1` antes de
   arrancar el servicio, mirar los paneles de cada controller. Sticks quietos deben leer
   exactamente (0,0) — si drifean, algo no cargó bien el patch de deadzone. Test de estrés:
   10 ciclos de arranque con los controllers prendidos, deben conectar 10/10 (ver `docs/03`).

2. **Player / VR180:**
   ```bash
   ./play360.sh ~/Documents/reverb-g2/photo360/vr180_berlin_8k60.mp4   # 8K60 estéreo, el bueno
   ./play360.sh ~/Documents/reverb-g2/playlist_test/                   # feature de playlist, nunca probado interactivo
   ```
   Con el casco puesto: confirmar imagen estéreo real (no aplanada), sin starves a 8K60, y que
   las teclas de transporte (espacio pausa, `[`/`]` velocidad, `n` siguiente, `q` salir)
   respondan. Si el terminal queda mudo después: `stty sane`.

3. **NO instrumentar el reset del hub USB2 todavía** — investigado por código (sin hardware)
   2026-08-06: el autosuspend ya está descartado (regla `71-usb-no-autosuspend.rules` cubre
   `04b4` desde el bootstrap), y la hipótesis de keepalive mal manejado tampoco se sostiene
   leyendo `wmr_hmd.c` (poll no bloqueante, sin writes periódicos). Si en 1-2 hace falta
   retomarlo: agregar logging con timestamps a `control_read_packets`/
   `hololens_sensors_read_packets` y correr bajo carga hasta que resetee — es la única forma
   de ver qué pasa justo antes, ese dato no existe todavía. Detalle en `docs/06-known-issues.md`.

4. **Constellation tracking (6DoF de controllers) — en pausa a propósito.** Hay un merge de
   prueba ya hecho (rama descartable, ya borrada) contra `gitlab.freedesktop.org/thaytan/monado`
   rama `dev-constellation-controller-tracking`: 8 conflictos, todos mecánicos (CMake +
   reconciliar la lista de hand-tracking devices), ninguno toca los archivos de nuestros 4
   patches. **No retomar todavía** — esperando que los reviewers de Monado respondan algo en
   las 4 MRs antes de terminar ese merge, para no reescribir código que puede cambiar por
   feedback. Ver `docs/03-controllers.md`, sección "Tracking posicional (6DoF)".

Nada de esto es urgente — el usuario pidió pacing explícito ("lo acomodamos con tiempo"). El
único motivo del reboot ahora es que tiene el casco físicamente en frente y ganas de probar.

---

State as of 2026-08-05, late. Written from the everyday system with the lab SSD mounted
read-write at `/mnt/lab`, right before rebooting into the lab OS to resume physically.

Same physical machine, two separate Debian 13 installs on separate disks (see
`docs/17-publishing.md` history / the repo's own notes) — the headset does not need to be
unplugged to switch between them, just reboot and pick the lab SSD at the boot menu, log in
as `iam`.

## EN CURSO (2026-08-05, noche): el factorial corrió — CTRL falla, y apunta a la resolución, no al vblank

**La vía de carga (opción 2, `nvidia_modeset.config_file` con la clave `DP-0`) quedó
confirmada de punta a punta**: reboot hecho, `dmesg` sin warning, `/sys/class/drm/card0-DP-1/edid`
byte-idéntico a `g2-vblank-test.edid`, y DRM pasó de ver 3 modos a 6. Detalle completo y la
cadena de código que explica el off-by-one `DP-0`/`DP-1` está más abajo en este archivo
("Lo anterior de esta misma sesión"), sin tocar.

**Se corrió el factorial completo: CTRL → B → A. Los tres fallan** (logo HP, sin video),
con el casco puesto. Pero con un dato nuevo que la tabla de `docs/16` no anticipaba: el HID
del casco (`DEVICE_STATUS`) confirma, en los tres casos, un timing **byte a byte idéntico**
al inyectado (htotal/vtotal/refresh/bpc exactos) — así que el override llegó perfecto hasta
el link físico. Eso descarta "el override no llegó" como explicación de la falla.

**Lo que queda como explicación más probable: los tres modos inyectados son 2880x1440, y
esa resolución nunca mostró nada en toda la historia del proyecto**, a ningún refresh
(el modo nativo 2880x1440@90 ya fallaba de antes). El único caso que alguna vez funcionó es
4320x2160@60. La resolución explica el 100% de los resultados sin necesitar invocar el
vblank ni el refresh — lo cual **no cierra la hipótesis del vblank, la deja sin probar
todavía**: hay que repetir el factorial inyectando en los descriptores DisplayID Type I
(4320x2160) en vez del bloque base, como ya preveía `docs/16` ("Si hace falta repetirlo a
4320x2160"). El decoder de esos descriptores ya existe y está validado byte a byte contra el
EDID real; falta escribir el encoder (`inject-did`) — la capa de bytes está documentada en
esa misma sección con los offsets exactos.

**Detalle completo, con las tablas de HID y la anomalía sin explicar (byte 1 de A, ver
abajo), en `docs/16-lab-vblank.md`, sección "Corrido (2026-08-05): CTRL falla".**

**`inject-did` ya está escrito, probado y usado.** Encoder simétrico de `decode_did_type1`
en `scripts/edid-tool.py`, con round-trip verificado por el decoder completo y los dos
checksums (sección DisplayID + bloque de extensión) correctos. Ya generó los tres EDID de
la segunda ronda: `experiments/vblank/g2-vblank-4k-{ctrl,b,a}.edid`, cada uno con el
descriptor #1 (el que fallaba a 90 Hz) reemplazado por `CTRL4K`/`B4K`/`A4K` y el
descriptor #2 (@60, el que anda) intacto como control. Detalle y por qué `B4K` usa vblank
240 y no 514 (ancho de banda a 4320 de ancho) en `docs/16`, sección "Segunda ronda".

**`CTRL4K` corrido y confirmado (T012): ANDA.** Colores alternando (azul/blanco/verde) con
el casco puesto, HID confirma 60Hz exacto y el bit de backlight prendido. El descriptor #1
no es la causa del fallo — clonar ahí un timing sano funciona igual que en su posición
original. Detalle en `docs/16`, sección "`CTRL4K` corrido". Se armó
`scripts/verify-override.sh` (corre como root, junta dmesg + detect + md5 en un solo
`sudo`) para no pedir la contraseña comando por comando en cada ronda.

**`B4K` corrido y confirmado (T013): FALLA.** Sólo logo de HP, casco puesto. Mismo
descriptor #1 que acababa de probarse sano con `CTRL4K` a 60 Hz — ahora a 90 Hz con vblank
corto (240) no engancha. Dato nuevo sin explicar todavía: el HID (`panel-status.py`) ni
siquiera llegó a reportar 90 Hz — se quedó mostrando el último estado conocido (60, de
`CTRL4K`) y el companion re-enumeró sin más mensajes. Distinto de la ronda anterior, donde
el HID sí confirmaba el timing inyectado byte a byte pese a fallar visualmente. Detalle
completo en `docs/16`, sección "`B4K` corrido".

**`A4K` corrido y confirmado (T014): FALLA también — esto cierra el factorial 2x2.**
`CTRL4K` (60Hz, vblank514) anda; `A4K` (60Hz, vblank116) y `B4K` (90Hz, vblank240) fallan
los dos. **No es el refresh — es el vblank corto**, y tampoco es ancho de banda: `A4K` corre
a apenas 603.6 MHz, muy por debajo del techo HBR3, y falla exactamente igual que `B4K` a
954.72 MHz. El límite real es una duración mínima de blanking vertical, no bits/segundo.
Detalle completo en `docs/16`, sección "`A4K` corrido — y esto cierra el factorial".

**Esto reabre 90 Hz como alcanzable.** Si el mínimo de vblank que hace falta es compatible
con 90 Hz dentro de HBR3, no hace falta bajar el refresh. Ya se generó el candidato más
directo: `experiments/vblank/g2-vblank-4k-90long.edid` — 4320x2160@90 con el mismo vblank
514 que sí anda a 60 Hz (`./scripts/edid-tool.py inject-did ... 514@90:1`). Pixel clock
1063.72 MHz → 25.53 Gbps @24bpp, dentro del techo HBR3 (25.92, ~1.5% de margen). El `.conf`
ya apunta ahí.

**`90long` corrido y confirmado (T015): FALLA.** Sólo logo HP, casco puesto. Esta vez el HID
sí confirmó 90Hz y timing exacto (a diferencia de `B4K`, que se había quedado en el estado
viejo) — así que el modo llegó completo y aun así no engancha. Los cuatro resultados hasta
acá (`A4K` 0.849ms FALLA, `B4K` 1.111ms FALLA, `90long` 2.136ms FALLA, `CTRL4K` 3.204ms
ANDA) ordenan limpio por **tiempo de blanking vertical en ms**
(`vblank/((vact+vblank)·rate)`), no por líneas — `90long` y `CTRL4K` tienen el mismo número
de líneas (514) y sólo el refresh distinto ya alcanza para que uno falle y el otro no.
Detalle y la tabla completa en `docs/16`, sección "`90long` corrido".

**Esto es un problema serio para 90 Hz:** el techo de HBR3 limita el vblank a ~555 líneas a
90 Hz, o sea **~2.27 ms como máximo posible** — por debajo de los 3.204 ms que ya sabemos
que andan. Si el umbral real de tiempo está más cerca de 3.2 que de 2.27, 90 Hz puede ser
sencillamente imposible dentro de HBR3, sin importar el vblank.

Antes de gastar otro reboot cerca del límite de banda a 90 Hz, se armó un candidato para
acotar el umbral real **a 60 Hz** (sin presión de bandwidth):
`experiments/vblank/g2-vblank-4k-bisect1.edid` — vblank=340 líneas a 60Hz, el mismo 2.27 ms
que sería el máximo posible a 90 Hz. El `.conf` ya apunta ahí.

**`bisect1` corrido y confirmado (T016): FALLA.** Sólo logo HP, HID confirma timing exacto
(60Hz, vtotal 2500) entregado perfecto. vblank=340@60Hz da 2.27ms — el mismo tiempo que
sería el máximo posible a 90Hz dentro de HBR3 — y falla. **Esto descarta 90 Hz como
alcanzable dentro de este enlace DisplayPort HBR3**, sin importar qué vblank se use: el
umbral real de tiempo está por encima de 2.27ms, y el techo de banda a 90Hz no permite
superar ese valor bajo ninguna combinación.

**Decisión con el usuario (2026-08-05): en vez de seguir bisectando el umbral exacto a
60Hz, ir directo a un refresh intermedio con margen real.** A 80Hz el techo de banda
permite hasta 3.66ms (vs los 3.204ms conocidos que andan) — mucho más margen que a 90Hz.
Se generó `experiments/vblank/g2-vblank-4k-80hz.edid`: vblank=775 líneas a 80Hz, 1037.82
MHz, 3.301ms, 24.91 de 25.92 Gbps (~4% de margen, no al límite como los intentos a 90Hz). El
`.conf` ya apunta ahí. **Esto redefine el objetivo**: `CLAUDE.md` asume que "la única cura"
del parpadeo es 90Hz, pero eso nunca se probó a un refresh intermedio — si 80Hz reduce o
elimina el parpadeo perceptible, cambia el criterio de éxito. Detalle en `docs/16`, sección
"`bisect1` corrido".

**`80hz` corrido y confirmado (T017): FALLA.** Sin imagen, sólo logo. HID confirmó refresh
80 exacto y timing exacto entregado. **Esto refuta la hipótesis del umbral de tiempo de
vblank**: `80hz` tiene 3.301 ms de blanking — más que los 3.204 ms de `CTRL4K`, que sí
anda — y aun así falla. El patrón que sí sobrevive a los 7 puntos: el único pixel clock que
alguna vez mostró imagen es **≈709.15 MHz** (el nativo 4320x2160@60 y su clon `CTRL4K`);
todo lo demás falló, sin importar bandwidth, vblank en líneas o en tiempo. Detalle completo
y la tabla en `docs/16`, sección "`80hz` corrido".

**Pivot grande (2026-08-05, noche):** en vez de seguir bisectando a ciegas, se investigó el
hardware. El usuario acercó el datasheet real del puente **ANX7530** (Product Brief oficial
de Analogix, AA-004263-PB-7 — no versionado acá, tiene aviso de copyright; ver `docs/10`
para el link público): declara el techo de link en **HBR2.5 (6.75 Gbps/lane,
no HBR3)** y una línea de spec explícita — **"DisplayPort Receiver Input Bandwidth supports
up to 4K x 2K x 60Hz"** — que es un techo de refresh declarado por el fabricante, no sólo
una cuenta de bandwidth. Coincide con que `2880x1440@90` (bandwidth total MENOR que el
4320x2160@60 que anda) también falló siempre.

Un research aparte confirmó que esto **ya es un bug reconocido por NVIDIA**: hilo
`forums.developer.nvidia.com/t/.../337744`, bug interno **5923212**, reproducido en
RTX 2070S/3090/5070Ti/A5000 en drivers 590–610.43.02, siempre la misma firma (60Hz anda,
90Hz no, incluso a menor resolución). Sin respuesta de NVIDIA desde 2026-03-20.

**Decisión con el usuario: sumar esta evidencia al hilo de NVIDIA en vez de seguir con más
EDIDs a ciegas.** Borrador completo del post (en inglés, listo para copiar/pegar o editar)
en `docs/19-nvidia-bug-5923212-followup.md` — incluye la tabla de los 7 puntos del
factorial, la identificación del chip (nueva para ese hilo, nadie lo había nombrado ahí
todavía) y la pregunta abierta para quien tenga visibilidad de DPCD/MSA o del driver de
Windows. **No lo posteé yo** — necesita la cuenta del usuario en el foro.

**Pendiente de decidir después de postear:** si sigue el camino empírico (queda listo
`edid-tool.py` extendido con `HBP:VBLANK@RATE` para separar pixel-clock-exacto de
refresh/vblank, sin usar todavía) o si se espera respuesta de NVIDIA antes de seguir
gastando reboots.

---

### Instrucciones originales para el reboot de `80hz` (ya ejecutado, dejadas por historial)

**FALTA EL REBOOT que carga `g2-vblank-4k-80hz.edid`.** Al volver:

1. `sudo ./scripts/verify-override.sh` — confirma carga (dmesg + md5).
2. PREFLIGHT completo (`docs/16`, arriba de todo), incluyendo `Notify Attach Begin` (root) —
   debería decir `pclk 1037820000 raster 4420x2935 24 bpp`.
3. `hmd-vk list` — `[1]` debería reportar `80.000 Hz` (distinto de `[2]` a 60.000, esta vez
   sin ambigüedad de índice).
4. Presentar `[1]` con `hmd-vk native 1`, casco puesto, HID (`panel-status.py`) en paralelo,
   `testlog.py` para anotar.
5. **Si `80hz` ANDA:** además de "¿hay imagen?", preguntar específicamente **si el
   parpadeo mejoró o desapareció** respecto de 60Hz — es la pregunta que en realidad
   importa ahora que 90Hz está descartado. Si el parpadeo sigue igual pese a andar la
   imagen, el objetivo del lab necesita replantearse desde cero (¿el strobe del backlight
   está atado específicamente a 90Hz por firmware, no a "cualquier refresh alto"?).
   **Si `80hz` FALLA:** el umbral de vblank/tiempo es más alto de lo estimado; volver a
   bisectar (a 60Hz, sin presión de banda) entre 340 (falla) y 514 (anda) para acotarlo
   antes de probar otro refresh intermedio.

### Lo anterior de esta misma sesión: la clave era `DP-0`, no `DP-1`

Reboot hecho. `dmesg` confirmó `nvidia-modeset: Successfully read
/home/iam/Documents/reverb-g2/experiments/vblank/nvkms-override-candidates.conf` — sin
warning, la sintaxis con corchetes de la sección anterior (abajo, sin tocar) era correcta.
Pero el EDID de `/sys/class/drm/card0-DP-1/edid` seguía siendo el `hmd.edid` original.

Se probó primero la hipótesis de timing (que faltaba un `detect()` fresco desde que cargó
el override) leyendo `cat /sys/class/drm/card0-DP-1/status` — eso SÍ dispara
`connector->funcs->detect()` real (confirmado en `nvidia-drm-connector.c:274-283`, el
callback `.force`/`.detect` cae los dos en `__nv_drm_connector_detect_internal`). Se
recorrió a mano toda la cadena de código para confirmar que el plumbing existe de punta a
punta: `nvDpyGetDynamicData` (`nvkms-dpy.c:3088`) → `GetEdidOverride` (`nvkms-dpy.c:195`,
la usa `nvDpyReadAndParseEdidEvo` con prioridad sobre `ReadEdidFromDP`) → de vuelta en
`nvkms-kapi.c:1544` el EDID overrideado sí se copia a `params->edid` porque el flag
`overrideEdid` que compara ahí es el de DRM (`connector->override_edid`, el de la opción 1,
en `FALSE`) — no el interno de NVKMS → `nvidia-drm-connector.c:136` copia ese EDID a
`nv_connector->edid` → línea 301 llama `nv_drm_connector_update_edid_property`. Todo el
camino existe y debería funcionar. Pero el status leyó `connected` con el EDID viejo de
todos modos.

**La causa real: un off-by-one entre NVKMS y DRM en la numeración de conectores.**
`nvkms-rm.c:880` — `AllocConnectorDispDataRec allocConnectorDispData = { };` — confirma que
`typeIndices` arranca en 0. El primer conector DP tiene `typeIndex = 0`, así que su nombre
interno en NVKMS es **`DP-0`**. DRM, en cambio, numera desde 1 (por eso el listado real de
`/sys/class/drm/` es `card0-DP-1`, `card0-DP-2` — nunca aparece un `DP-0`). Mismo conector
físico, dos nombres distintos según la capa. `DPY_OVERRIDE_MATCHES`
(`nvkms-dpy-override.c:37-39`, `nvDpyEvoGetOverride` línea 210) compara la clave del
`.conf` contra el nombre **interno** de NVKMS (`pConnectorEvo->name`), no contra el de DRM
— así que la clave `DP-1` nunca hizo match. El archivo se leyó sin error porque el parser
no valida que el nombre de display corresponda a un conector real; sólo lo guarda en la
tabla de overrides a la espera de que algún conector algún día se llame así.

`experiments/vblank/nvkms-override-candidates.conf` ya tiene la clave corregida:
`override.[0000:05:00.0].DP-0 = .../g2-vblank-test.edid`.

**Falta el reboot que prueba la corrección.** Al volver:
```
sudo dmesg -T | grep -iE 'nvkms|override|Error in|Syntax error|Successfully read'
cat /sys/class/drm/card0-DP-1/status          # dispara un detect() fresco
sudo cat /sys/class/drm/card0-DP-1/edid | md5sum
md5sum experiments/vblank/g2-vblank-test.edid  # deberían coincidir
```
Si coinciden, el override quedó cargado — seguir con el factorial de `docs/16`. Si NO
coinciden pero tampoco hay warning en dmesg, el problema puede estar en el número de PCI
function (`0000:05:00.0` vs `.1`, la GPU tiene dos functions — VGA en `.0`, audio en `.1`;
ya está bien puesta la `.0`) o en que el `debug=1` no está realmente habilitando el log
`nvEvoLogDebug` de `nvDpyEvoGetOverride` línea 212 — revisar si aparece
`NVDpyOverrideRec found: DP-0` en dmesg, que confirmaría el match sin ambigüedad.

### Lo anterior de esta misma sesión (histórico, sin tocar)

Opción 1 (`debugfs edid_override`) quedó descartada con evidencia — ver `docs/16`, sección
bajo el PENDIENTE. El driver NVIDIA no pasa por el helper genérico de DRM para el EDID de
este conector; lo lee por su propio canal, y el override queda ignorado.

Se pasó a la opción 2 (`nvidia_modeset.config_file`). El primer intento (RE por disassembly,
sin fuente) falló: `dmesg` dio un solo warning —
`Syntax error in override entry: Unknown GPU designator: 0000:05:00` — y `nvKmsReadConf`
aborta el archivo entero en el primer error, así que ni los otros dos candidatos se llegaron
a probar.

**Se encontró algo mejor que RE: `/usr/src/nvidia-595.71.05/src/nvidia-modeset/src/nvkms-conf.c`
es fuente real (parte abierta del 595, MIT).** Ahí está la gramática exacta, sin
reconstruirla a ciegas:

- La clave separa `keyhead` (`override`) de `keytail` en el PRIMER `.` — todo lo demás va
  entero a `Subparser_override`. Ese parser sólo activa el branch de dirección PCI cuando
  `key[0] == '['` (`nvkms-conf.c:126`). **Los corchetes son obligatorios**, no notación
  opcional — sin ellos busca el primer `.` suelto, que cae en medio de la dirección PCI, y
  tira justo el error que vimos.
- Formato real: `override.[<dominio>:<bus>.<slot>.<función>].<nombre-dpy> = <valor>`
  (los `:` y `.` dentro de los corchetes son los delimitadores hex de 4 campos, igual que
  `lspci`/DRM: `0000:05:00.0`).
- Valor: ruta absoluta sin comillas ni `<angulos>` — el branch de archivo sólo se activa si
  `value[0]=='/'` tras pelar comillas; los `<angulos>` del primer intento NO se pelan, quedan
  como parte literal del valor (por eso ese candidato tampoco habría andado aunque la clave
  estuviera bien).

`experiments/vblank/nvkms-override-candidates.conf` ya tiene la línea corregida:
`override.[0000:05:00.0].DP-1 = .../g2-vblank-test.edid`.

**El nombre de display `DP-1` se confirmó por lectura de código, no por suposición:**
`nvkms-rm.c:616-623` arma `pConnectorEvo->name` como `"%s-%u"` con un contador `typeIndex`
por tipo (0-based, orden de enumeración de RM). `nvidia-drm-connector.c:562` llama
`drm_connector_init()` sin `type_id` explícito, así que DRM asigna el suyo incrementando en
el mismo orden en que NVKMS ya enumeró — mismo contador, misma lista física, mismo orden →
el `DP-1` de DRM (`card0-DP-1`, donde el `edid_override` de la opción 1 ya había confirmado
que cuelga el casco) y el `DP-1` interno de NVKMS son el mismo conector. No hace falta
cambiar el nombre.

`/etc/modprobe.d/99-nvkms-override-test.conf` (`config_file=... debug=1`) sigue apuntando al
mismo `.conf`, así que sólo hace falta que el módulo lo vuelva a leer — es de sólo lectura en
caliente, sólo se lee una vez al cargar el módulo.

**Falta disparar el reboot.** Al volver, primero:
```
sudo dmesg -T | grep -iE 'nvkms|override|Error in|Syntax error|Successfully read'
```
Si esta vez no hay warning (o dice `Successfully read...`), el override quedó cargado.
Recién ahí verificar físicamente: `/sys/class/drm/card0-DP-1/edid` debería leer
`g2-vblank-test.edid` en vez de `hmd.edid`, y seguir con el factorial de `docs/16`.

---

## Two independent tracks right now

1. **The vblank experiment** (`docs/16-lab-vblank.md`) — needs the lab OS booted natively.
   Blocked on an open question, see below.
2. **Monado upstreaming** (`docs/18-monado-upstreaming.md`) — needs nothing from the lab
   machine at all. Blocked on a GitLab account-verification issue on the everyday system's
   side. Do not waste lab time on this.

---

## Track 1 — vblank experiment: what to do first

**Before running PREFLIGHT, read the "PENDIENTE" block near the top of
`docs/16-lab-vblank.md`.** While documenting this session I found and fixed a real error in
that doc: it claimed the EDID-override loading mechanism was "already proven in this lab".
It is not. The 6 bpc bug was closed with a *driver source patch* (0004), which sidestepped
ever needing NVIDIA to accept a fake EDID — so that claim was simply wrong, and following it
would have wasted lab time discovering there is no confirmed way to load the modified EDID.

**So the actual first task on the lab machine is resolving that**, trying in this order
(full detail now in `docs/16`, background in `docs/13`):

1. `/sys/kernel/debug/dri/*/DP-1/edid_override` (debugfs) — cheapest to try. Unconfirmed
   whether NVKMS's closed logic reads EDID through the generic DRM helper (would see this)
   or its own AUX channel (would not). Writing the file does not trigger hotplug — disconnect
   and reconnect the connector after.
2. `nvidia_modeset.config_file` — NVKMS's own mechanism, parameter exists and is compiled in,
   but the dpy-name syntax is undocumented. Discover it with `nvidia_modeset.debug=1` and
   reading dmesg as root during a real modeset.
3. Patching the EDID the headset itself reports over the cable, if there's an injection point
   between the Analogix bridge and the host — unexplored.

If none of the three works, the experiment is inconclusive by this route and needs a
different injection strategy before the factorial itself means anything.

### Once loading works: PREFLIGHT (5 checks, `docs/16`)

1. `grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' /proc/driver/nvidia/version` → must say `595.71.05`
2. `modinfo nvidia | grep -i license` → must include "Dual MIT/GPL"
3. `./scripts/verify-bpc.sh` → patch present
4. `lsusb | grep -E '04b4:6506|0bda:4c15|03f0:0580|04b4:6504|045e:0659' | wc -l` → must be 5
5. `dmesg | grep 'Notify Attach Begin' | tail -1` → must say `24 bpp`, not `18`

If any of the five fails, stop — measuring on the wrong driver gives a result that looks
good and points at the wrong thing.

### Then the experiment itself

Order: **CTRL → B → A**. If B works, that's the answer and A is just confirmation.
Verification is physical — put the headset on and look; the API reports 90.0 fps success
even with a black panel. For each mode: does the backlight come on, is there color or just
white/flicker, does `dmesg`'s `Notify Attach Begin` line say `24 bpp`, and the HID status
byte 18 (`scripts/decode-status.sh`).

The read-the-result table and the refresh-sweep follow-up are both in `docs/16`.

---

## Track 2 — Monado upstreaming: status

Four MR branches are ready (rebased on Monado `main` `735e29e4e`, adversarially reviewed,
three real defects found and fixed, zero warnings, DCO-signed, no AI co-author trailer per
the standing decision below). They live in the **everyday system's** clone
`~/Documents/linux_vr_base/monado`, refs `wmr-hid-resilience`, `wmr-controller-input-fixes`,
`wmr-camera-stream-toggle`, `steamvr-drv-origin-rpath`. Same content as
`patches/monado/0001–0010` in this repo.

**Blocked on GitLab account verification.** freedesktop.org's GitLab restricts new accounts
(anti-spam): they can't fork or create projects until an admin approves a request.
Filed as **issue #3736**
(`https://gitlab.freedesktop.org/freedesktop/freedesktop/-/work_items/3736`), open, no fixed
SLA. Check for a notification email, or ask to have it checked.

**Once approved:**
1. Add an SSH key to the GitLab account (can generate one in advance, same pattern as the
   lab machine's deploy key).
2. Fork `monado/monado`.
3. Push the four branches from `~/Documents/linux_vr_base/monado` to the fork.
4. Open four MRs against `main`. Titles and bodies are ready to paste, in
   `docs/18-monado-upstreaming.md`.
5. After each MR gets a number, add its `doc/changes/.../mr.<N>.md` changelog fragment as a
   final commit (path convention explained in docs/18).

---

## Idea a pensar (2026-08-05, parqueada): sudo acotado + autoarranque de la sesión

Surgió mientras se corría el factorial del vblank: el ciclo reboot → "volví" → PREFLIGHT →
presentar → mirar con el casco tiene fricción real de copy-paste en los pasos que necesitan
sudo (ya causó un glitch de expansión de historial de bash al pegar la salida). Se acordó
pedir un `sudoers.d` acotado con `NOPASSWD` sólo para los comandos de sólo-lectura
(`verify-override.sh`, `dmesg`, el `cat` del EDID de sysfs, `modinfo`) — sin sudo en blanco
y sin automatizar el `reboot` en sí, porque la verificación es física: el usuario tiene que
estar presente apenas vuelve la máquina de todos modos, así que automatizar el reboot no
ahorra tiempo real, y esta es una sola máquina física sin recuperación remota si algo cuelga
el boot. Después de eso, el usuario propuso ir un paso más allá: que la sesión de Claude
Code arranque sola al bootear la máquina, para poder interactuar apenas vuelve sin el paso
de "volví". **Quedó explícitamente pendiente de pensar, no decidido ni implementado** —
retomarlo después de correr `g2-vblank-4k-90long.edid`. Detalle completo en memoria
(`idea_agent_autostart_lab.md`, tipo `project`).

## Pendiente adicional (2026-08-05): perfil de power de la GPU

Hipótesis del usuario, todavía sin correr: en Windows siempre se recomienda forzar el panel
de NVIDIA a **"Prefer Maximum Performance"** para VR — dejarlo en el default ("Adaptive",
reloj dinámico) puede causar problemas. En Linux el 595-open también arranca en PowerMizer
adaptativo por default. Si el firmware GSP cerrado que decide el enganche a 90Hz (ver
`docs/13-bug-6bpc.md`) es sensible al estado de reloj en el momento del modeset, un
downclock en el momento equivocado podría explicar por qué el panel no llega a sincronizar.

No se investigó todavía. Cuando se retome: revisar con `nvidia-smi -q -d PERFORMANCE` o
`nvidia-settings` el P-state real durante el intento de modeset a 90Hz, y probar forzando
máximo rendimiento (`nvidia-settings -a '[gpu:0]/GPUPowerMizerMode=1'` o el mecanismo
equivalente en el 595-open) antes de correr el experimento del vblank o en paralelo con él.

---

## Standing convention decided this session

**No `Co-Authored-By: Claude` trailer on commits, and no repo-level AI disclaimer either.**
The `Signed-off-by` already certifies the content for publication; a tool-attribution note
adds nothing on top of that. Applies going forward to both this repo and the Monado series
(already applied there — the 10 patches and the reverb-g2 history were both rewritten to
drop it, and reverb-g2's rewritten history is already force-pushed to GitHub).

## Repo state

- Renamed `reverb-g2-linux` → **`reverb-g2`** (README explains why: the headset has no
  supported platform left on any OS, not just Linux). Working directory here is already the
  renamed one; GitHub remote is `Wintch/reverb-g2` (private).
- `main` @ `301eaee`, matches GitHub, gate (`scripts/check-publishable.py`) passes clean.
- FCC PDFs dropped from the tree (linked to fccid.io instead); Oasis driver attribution fixed
  (it's Matthieu Bucchianeri's, not HP's); HP Omnicept noted as a related test target in
  `docs/10-resources.md` (same WMR display path per Monado's prober — a 90 Hz result there
  would show whether this is G2-wide or unit-specific) but not being pursued (no hardware).
