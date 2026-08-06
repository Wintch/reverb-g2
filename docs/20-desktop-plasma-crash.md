# 20 — El casco conectado rompe el escritorio KDE (X11), no solo el 90Hz

**Encontrado el 2026-08-06, sesión con el agente.** Esto es un problema nuevo, distinto del
bug del bpc (`docs/13`): no es que el panel del casco no encienda a 90Hz, es que **con el
casco conectado, todo el escritorio Plasma puede volverse inestable**, hasta el punto de
quedar solo con el wallpaper (sin panel, sin iconos) o con la pantalla de bloqueo rota (solo
el reloj, sin campo de contraseña).

---

## El síntoma

Arranque limpio (reboot completo, no solo relogin). Sesión KDE Plasma X11 vía SDDM. Todos
los procesos esperables están corriendo (`Xorg`, `kwin_x11`, `plasmashell`, `kded6`) pero
**la interfaz nunca se dibuja**: se ve el fondo de pantalla y nada más — sin panel, sin
iconos de escritorio, sin barra de tareas.

`journalctl -b` muestra, repetido en ráfagas de 4-8 líneas cada vez:

```
plasmashell[PID]: QRhiGles2: Context is lost.
plasmashell[PID]: Graphics device lost, cleaning up scenegraph and releasing RHI
kwin_x11[PID]: kwin_scene_opengl: Could not delete framebuffer because no context is current
```

Sin ningún Xid en dmesg/journalctl -k (o sea: no es un reset de GPU al nivel del kernel; el
`nvidia.ko` y `nvidia-drm` no ven nada raro). El fallo está en la capa de Qt/RHI/EGL que usa
`plasmashell` para su scenegraph — se cae y se reconstruye, y mientras se reconstruye no hay
UI. A veces se recupera después de varios ciclos (queda un escritorio funcional pero con
notificaciones rotas — ver el binding loop de `DelegatePopup.qml` en el log), a veces queda
en el loop permanentemente.

## La causa raíz identificada: DP-0 (el casco) guardado como monitor de escritorio a 90Hz

`xrandr` mostraba `DP-0 connected primary 2880x1440+0+0` corriendo `2880x1440@90.00` —
**exactamente el modo nativo del G2** que `docs/13-bug-6bpc.md` documenta como el modo con
el link DisplayPort inestable (panel que no enciende o parpadea sin color).

Confirmado con los perfiles guardados de KDE en `~/.local/share/kscreen/`: el `fullname` de
`DP-0` es literalmente `xrandr-HP Inc.-3958133002` — el EDID del casco. El perfil activo en
el boot de esta mañana (`b1daa19a6590a34be81df4a5d763a943`, timestamp del boot) lo tenía
`enabled: true` a 90Hz. Un perfil más viejo (`92b2326774024e554276dd6dba98d565`, de ayer
19:46) lo tenía `enabled: false` — en algún momento del lab quedó prendido por accidente
(probablemente al guardar la config de pantallas mientras el casco estaba conectado para
alguna prueba) y KDE lo siguió arrancando así en cada boot siguiente.

**Con el casco tratado como un monitor de escritorio normal, cualquier hiccup del link DP a
90Hz (que ya sabemos que es inestable — es el bug central de `docs/13`) se lleva puesto todo
el compositor**, no solo la salida del casco. Encaja con que el crash-loop empieza apenas
arranca la sesión: KDE intenta componer sobre las 4 salidas, una de ellas es un link DP
crónicamente inestable a 90Hz, y `plasmashell`/`kwin` pierden el contexto GL entero.

### El fix aplicado

```bash
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
export XAUTHORITY=/run/sddm/xauth_HAltUI   # o el que corresponda a la sesión activa
export DISPLAY=:0
kscreen-doctor output.DP-0.disable
```

Esto para la sesión viva. **Persiste solo mientras KDE no vuelva a guardar un perfil con
DP-0 habilitado** — que es justo lo que causó el problema la primera vez. No hay (todavía)
un mecanismo a prueba de esto; ver "Qué falta" más abajo.

Tras el fix, dejaron de aparecer nuevos `Context is lost` durante varios minutos, y
`plasmashell`/`kwin_x11` quedaron estables en el escritorio normal.

## Lo que el fix NO explica: recurrió en la pantalla de bloqueo, con DP-0 ya apagado

A las 00:16:39 (más de 6 minutos después de deshabilitar DP-0, y ~2.5 minutos después de que
arrancara `kscreenlocker_greet` a las 00:14:08) **volvió a aparecer el mismo patrón exacto de
`QRhiGles2: Context is lost`**, esta vez en el proceso del lock screen. Resultado visible:
pantalla de bloqueo mostrando solo el reloj, sin el campo de usuario/contraseña. Un intento
de contraseña a las 00:16:47 falló (`pam_unix(kde:auth): authentication failure`), consistente
con que el campo no tenía foco o no se estaba dibujando.

`journalctl -k` en la ventana 00:13–00:17 no muestra ningún hotplug ni evento de
reconexión — nada que explique por qué se disparó justo ahí. `kscreen-doctor -o` confirmó que
DP-0 seguía deshabilitado en ese momento.

**Conclusión: DP-0 a 90Hz como monitor de escritorio es UNA causa confirmada del crash, pero
no la única.** Hay algo más amplio — probablemente un bug conocido de Plasma 6 + NVIDIA
(driver 550.163.01, el paquete estándar de Debian, **no** el 595-open parcheado del lab, que
no está cargado — confirmado con `dkms status` y `nvidia-smi`) donde el backend QRhiGles2 de
Qt Quick pierde el contexto EGL/GLES ante ciertos eventos de recomposición (como que arranque
el lock screen, que también crea su propia superficie GL). Esto no está resuelto — ver "Qué
falta".

## Nota al margen: config de debug del GSP quedó residual

`/etc/modprobe.d/99-nvidia-gsp-logs.conf` (`NVreg_EnableGpuFirmwareLogs=1`) sigue puesto
desde la investigación del 2026-08-05 (ver `docs/13`, sección "Habilitando los logs del
firmware GSP"). Se confirmó ahí mismo que **no hace nada** en este sistema —
`gsp_log_ga10x.bin` no existe en ningún lado, el driver lo reporta como fallo no-fatal y
sigue andando normal. No parece relacionado a este bug (no hay mensajes de GSP en los logs
del crash), pero es config de debug abandonada que ya cumplió su propósito. Candidato a
borrar con `sudo rm /etc/modprobe.d/99-nvidia-gsp-logs.conf` la próxima vez que se reconstruya
el módulo, para no arrastrar parámetros de debug sin motivo.

## Qué falta

- [ ] **Evitar que KDE vuelva a guardar/arrancar DP-0 habilitado.** Ideas, sin probar
      todavía: (a) un script de autostart de Plasma que corra `kscreen-doctor
      output.DP-0.disable` al iniciar sesión, incondicional; (b) investigar si KDE tiene
      forma de "recordar siempre deshabilitado" un output por EDID en vez de por
      geometría/sesión. La opción (a) es la más simple y la que más se parece a lo que ya
      hace este repo (scripts idempotentes, ver `scripts/`).
- [ ] **El segundo crash (lock screen, DP-0 ya apagado) queda sin explicar.** Si vuelve a
      pasar sin el casco conectado en absoluto, es un bug de Plasma/NVIDIA genérico, no
      específico de este proyecto — buscar en bugs.kde.org por "QRhiGles2 Context is lost"
      antes de asumir que es otra manifestación del mismo problema del casco.
- [ ] **Confirmar si pasa igual con el casco físicamente desconectado.** Es la prueba que
      discrimina entre "es 100% el casco" y "hay un segundo bug independiente". No se hizo
      todavía porque la sesión quedó bloqueada antes de poder probarlo.

## Regla práctica para sesiones futuras

**Si el escritorio KDE se ve raro (solo wallpaper, panel roto, lock screen sin campo de
contraseña) y el casco está conectado: correr `kscreen-doctor -o` y revisar si `DP-0`
(o el output con `fullname` que contenga `HP Inc.`) está `enabled` antes de investigar
cualquier otra cosa.** Es el primer sospechoso y ya se confirmó una vez.

## Continuación (2026-08-06, misma noche): DP-0 no se puede apagar en caliente, y "arrastra" ventanas

Después del reboot sugerido en la sesión anterior, el escritorio volvió (panel e iconos
normales), pero **DP-0 había vuelto a `enabled` a 90Hz** — confirma la sospecha de "Qué
falta" de más arriba: el perfil que KDE carga en el boot lo trae prendido de nuevo. No hizo
falta que nadie lo reconectara a mano; solo con el reboot ya volvió.

Efecto colateral no documentado antes: **como DP-0 ocupa el rectángulo (0,0)-(2880,1440) del
escritorio virtual, algunas apps nuevas abren su ventana ahí** — literalmente en el panel del
casco, invisible para el usuario sin ponérselo. Pasó con Telegram, una ventana de Chrome, y
la vista de escritorio/iconos de esa pantalla.

### Intento de apagar DP-0 en caliente: falló por las tres vías

1. `kscreen-doctor output.DP-0.disable` — el comando devuelve éxito, pero **no aplica**:
   `kscreen-doctor -o` lo sigue mostrando `enabled` inmediatamente después, y `xrandr`
   confirma que el modo 90Hz sigue activo (`2880x1440 90.00*+`). Ya había pasado una vez en
   la sesión anterior (por eso "recurrió" el crash con DP-0 "ya deshabilitado" — probablemente
   nunca se deshabilitó de verdad a nivel del servidor X, solo a nivel de la config que
   reporta KWin).
2. `xrandr --output DP-0 --off` directo (bypaseando KWin/KScreen) — falla con:
   ```
   xrandr: Configure crtc 0 failed
   X Error of failed request:  BadMatch (invalid parameter attributes)
   Minor opcode of failed request:  7 (RRSetScreenSize)
   ```
   Mismo error con un comando combinado que reafirma las otras 3 salidas a la vez. El driver
   NVIDIA rechaza el resize del framebuffer virtual mientras el casco sigue eléctricamente
   conectado a ese conector.
3. `nvidia-settings --assign CurrentMetaMode=...` con un MetaMode nuevo que omite DPY-1
   (=DP-0) por completo, tanto con `DPY-1: NULL` explícito como omitiéndolo — falla con
   `Attribute not available` en los dos casos, con o sin `--ctrl-display=:0` explícito.

**Conclusión: mientras el casco esté físicamente conectado, no encontramos ninguna forma de
sacar a DP-0 del escritorio en caliente — ni por KWin/KScreen, ni por RandR crudo, ni por el
mecanismo nativo de NVIDIA.** Sospecha (sin confirmar): puede ser un `DynamicTwinView`
efectivamente `off` para esta combinación de salidas, o una restricción del driver 550.163.01
específica para paneles marcados non-desktop/HMD. **No probado todavía: si desconectar el
cable DP físicamente (hotplug real) sí permite que X reprobe sin DP-0** — es la prueba más
obvia para la próxima sesión, y explicaría por qué `DP-1`/`DP-2` (genuinamente desconectados)
sí muestran `disconnected` limpio en xrandr mientras que DP-0 nunca lo hace por más que se le
pida apagarse en software.

### Workaround que sí funcionó: mover las ventanas con un script de KWin, sin tocar la pantalla

En vez de sacar DP-0 del layout, se dejaron las ventanas atrapadas ahí y se las movió a mano
por scripting de KWin (D-Bus, `org.kde.kwin.Scripting`):

```js
var outs = workspace.screens;
var target = null;
for (var i = 0; i < outs.length; i++) {
    if (outs[i].name !== "DP-0") { target = outs[i]; break; }
}
var wins = workspace.windowList();
var moved = [];
if (target) {
    var tg = target.geometry;
    var offset = 0;
    for (var j = 0; j < wins.length; j++) {
        var w = wins[j];
        if (w.output && w.output.name === "DP-0") {
            var g = w.frameGeometry;
            w.frameGeometry = { x: tg.x + 40 + offset, y: tg.y + 40 + offset, width: g.width, height: g.height };
            offset += 30;
            moved.push(w.caption);
        }
    }
}
print("MOVED:" + JSON.stringify(moved) + " TARGET:" + (target ? target.name : "none"));
```

Cargado y corrido así (el `print()` va a `journalctl`, no a stdout):

```bash
qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript /ruta/al/script.js "algún-nombre"
qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.start
journalctl -b --since "1 minute ago" | grep 'kwin_scripting\|js:'
```

Notas de la API de scripting de KWin 6 (costó tantear esto, dejarlo anotado):

- `w.output = target` **falla** — `output` es de solo lectura (`Cannot assign to read-only
  property "output"`). Hay que mover por geometría (`frameGeometry`), no por asignación
  directa de output.
- `Qt.rect(...)` **no existe** en este engine (`Qt is not defined`) — hay que pasar un
  objeto plano `{x, y, width, height}` a `frameGeometry`, no un `QRect` construido a mano.
- `qdbus6 .../Scripting/<id> .../Script.run` con el path que devuelve `loadScript` **no
  funciona** (`UnknownObject`) — el flujo correcto es `Scripting.start()` a secas, que corre
  todos los scripts cargados.
- `workspace.windowList()` incluye la vista de escritorio/iconos como una "ventana" más
  (`"Desktop @ QRect(...)"`) — no es un error, es esperable que aparezca en el listado.

Con esto, Chrome volvió a aparecer. **Falta confirmar si Telegram (y la vista de escritorio
de DP-0) también quedaron visibles** — no se verificó explícitamente antes de cortar la
sesión.

### Qué retomar mañana

- [ ] Probar si desconectar físicamente el DP del casco permite que X reprobe sin DP-0 (y si
      al reconectarlo después, con la sesión ya arrancada, NO se vuelve a agregar como
      desktop output — sería la señal de que el problema es sólo al probing inicial de X).
- [ ] Armar el script de autostart de Plasma (`kscreen-doctor output.DP-0.disable` al
      iniciar sesión) que quedó pendiente de la sesión anterior — aunque con el hallazgo de
      hoy (que el disable no aplica de verdad) puede no alcanzar por sí solo; evaluar si
      conviene en cambio automatizar el script de mover-ventanas como red de seguridad,
      corriéndolo también al reconectar el casco.
- [ ] Confirmar visualmente que Telegram y el resto de lo que estaba en DP-0 son visibles
      ahora en una pantalla real.
- [ ] Seguía pendiente de la sesión anterior: probar si el crash de `QRhiGles2: Context is
      lost` recurre con el casco desconectado del todo (para saber si hay un segundo bug de
      Plasma/NVIDIA genérico, no específico de este proyecto).

## Continuación (2026-08-06, sesión posterior con Claude Code): compositor de KWin apagado, hipótesis nueva sin confirmar

En una sesión distinta, sin relación aparente con el 90Hz, el usuario pidió arreglar el
**cursor del mouse invisible** en todo el escritorio (bug separado, no documentado acá antes).
El fix que terminó funcionando fue forzar `GLPlatformInterface=egl` en `kwinrc`
(`[Compositing]`) — eso hace que KWin **falle** al iniciar el compositor OpenGL
(`kwin_scene_opengl: Creating the OpenGL rendering failed: "Invalid QOpenGLContext::
globalShareContext()"`) y, como en este host `platformRequiresCompositing=false`, sigue
corriendo **sin compositor** en vez de crashear. Con eso el cursor se ve (lo dibuja Xorg
directo, ya que `HWCursor false` sigue puesto desde antes).

El usuario notó después que el casco aparecía "como una pantalla más" y preguntó si tenía que
ver con el bug de este documento. **Es una hipótesis razonable, sin confirmar todavía:**

- Con el compositor apagado, `DP-0` sigue `enabled`/`connected` a `2880x1440@90` en
  `kscreen-doctor -o` y `xrandr`, igual que lo documentado arriba — eso no cambió.
- `kscreen-doctor output.DP-0.disable` se comportó **igual que antes**: KScreen pasó a
  reportar `disabled`, pero `xrandr` siguió mostrando `2880x1440 90.00 +` como modo activo.
  Mismo desync ya documentado, no se investigó más porque los caminos alternativos (`xrandr
  --off`, MetaMode de NVIDIA) ya están descartados arriba y no hace sentido repetirlos.
- Se chequeó con el mismo mecanismo de scripting de KWin (D-Bus) si había ventanas atrapadas
  en `DP-0`: **ninguna** en el momento del chequeo.
- **No se observó ningún `QRhiGles2: Context is lost` en lo que va de esta sesión** con el
  compositor apagado y `DP-0` activo. Ventana de observación corta, no es concluyente.

**Por qué podría ser relevante:** el log de crash original citaba tanto `plasmashell` como
`kwin_x11` perdiendo el contexto GL. Si el compositor de KWin está completamente apagado, la
mitad del mecanismo de falla documentado arriba (`kwin_scene_opengl: Could not delete
framebuffer because no context is current`) no tiene contexto que perder — no existe. **Pero
`plasmashell` mantiene su propio `QRhiGles2`/RHI independiente del compositor**, así que esto
NO explica ni descarta el segundo crash (el de la pantalla de bloqueo, con DP-0 ya
deshabilitado) que quedó sin explicar más arriba.

**No verificado, no asumir:** no se dejó el sistema corriendo un tiempo largo con compositor
apagado + casco conectado para confirmar si el crash-loop reaparece o no. Si en una futura
sesión el crash NO vuelve a pasar con esta config, es evidencia fuerte de que el compositor de
KWin (no Plasma/NVIDIA en general) era el mecanismo. Si SÍ vuelve a pasar, confirma que el
problema vive en otro lado (probablemente `plasmashell`) y que apagar el compositor no
resuelve nada de fondo, sólo cambió el síntoma visible (cursor sí, pero desktop con casco
"pegado" como 4ta pantalla).

**Efecto secundario a monitorear:** al no haber compositor, no hay efectos visuales,
transparencias, ni la lógica de KWin que aparentemente antes hacía menos visible a `DP-0` en
el escritorio compuesto. Puede ser la explicación de por qué el usuario dice "nunca se vio
así" — con compositor activo, aunque `DP-0` estuviera técnicamente `enabled`, el rendering
compuesto podía estar ocultándolo o presentándolo distinto. No confirmado, es la lectura más
simple de la evidencia disponible ahora.
