# 17 — Publicar el repo

Objetivo: que cualquiera con un Reverb G2 pueda seguir desarrollando esto. Destino
`github.com/Wintch/reverb-g2`.

**La limpieza del historial ya se hizo** (2026-08-05, desde el sistema principal con el SSD
del lab montado). Lo que sigue documenta qué había, qué se hizo y cómo verificarlo antes de
cada push.

---

## Qué bloqueaba la publicación

### 1. Blobs por encima del límite de GitHub

Las dos capturas de USB estaban **en el historial de git**, no sólo en el árbol de trabajo:

```
858.1 MB  docs/dump90hz.pcapng
428.9 MB  docs/dump60hz.pcapng
```

GitHub rechaza cualquier blob de más de 100 MB, así que el push fallaba de entrada, y
borrarlas del árbol no alcanzaba. Git LFS tampoco servía: el tier gratis es 1 GB y esto
eran 1.29 GB.

Se sacaron del historial. No hubo pérdida real: el valor está en el análisis
(`docs/12-g2-protocol.md`, `scripts/parse-usbpcap.py`), no en los dumps crudos. También
salió `nv-report-*/build/hmd-vk`, un binario compilado que nunca debió estar trackeado.

`.git` pasó de **412 MB a 8.8 MB**.

### 2. Identidad e identificadores de hardware

- Tres identidades distintas en los commits, unificadas a una sola.
- El serial USB del casco aparecía en 6 archivos, redactado.
- El `nvidia-bug-report` adjunto al foro llevaba además la MAC de la placa de red (dos
  veces, directa y al revés como PCI Device Serial) y el serial del motherboard. Se
  regeneró redactado: mismas 42787 líneas, sólo esas cuatro modificadas.

---

## Cómo se hizo

Con `git filter-repo`, en dos pasadas. **Hace falta las dos** — la primera sola no alcanza,
y esa fue la trampa:

```bash
# 1. blobs + identidad de los commits
git filter-repo --force \
    --path docs/dump90hz.pcapng --path docs/dump60hz.pcapng \
    --path nv-report-20260804-223535/build/hmd-vk --invert-paths \
    --mailmap /tmp/mailmap

# 2. el CONTENIDO de los archivos
git filter-repo --force --replace-text /tmp/redacciones
```

`--mailmap` reescribe **autor y committer**, que es metadata. No toca lo que hay adentro de
los archivos. Acá había dos parches de `patches/hello_xr-player/` con la dirección vieja en
su línea `From:`, y sobrevivieron enteros a la primera pasada. Hay que buscar en el
contenido de todos los commits, no sólo en los autores:

```bash
git grep -lI "<patrón>" $(git rev-list --all)
```

Los archivos `/tmp/mailmap` y `/tmp/redacciones` llevan literales que no deben publicarse,
por eso van fuera del repo. Formatos:

```
# mailmap
Nombre Nuevo <nuevo@ejemplo.com> <viejo@ejemplo.com>

# redacciones (replace-text)
LITERAL_VIEJO==>REEMPLAZO
```

### La trampa que sí nos mordió

La primera versión de esto era un script `publicar.sh` que llevaba **adentro** el serial y
la dirección que estaba redactando, porque los necesitaba como patrón de búsqueda. Al
correr la limpieza se redactó a sí mismo, quedando con `SERIAL="REDACTED"` y un chequeo que
buscaba la palabra `REDACTED`. Inservible, y peor: si se hubiera publicado antes de la
limpieza, habría publicado exactamente lo que intentaba ocultar.

Por eso ahora los patrones viven en `scripts/.private-patterns`, que está en `.gitignore`.

---

## Antes de cada push

```bash
./scripts/check-publishable.py
```

Chequea que haya una sola identidad en los commits, que ningún blob supere los 100 MB, y
que ninguno de los patrones de `scripts/.private-patterns` aparezca en el historial. No
modifica nada. Devuelve distinto de cero si algo falla.

Ese archivo de patrones **no está en el repo** (a propósito). Si clonás esto en otra
máquina, creá el tuyo: un patrón por línea, y las líneas con `#` se ignoran.

## Publicar

```bash
git remote add origin git@github.com:Wintch/reverb-g2.git
git push -u origin main
```

`git filter-repo` borra el remote a propósito después de reescribir, por eso el
`remote add` va después de la limpieza y no antes.

El repo se creó **privado**. Conviene pushear privado, revisar en la web que quedó como se
espera, y recién ahí pasarlo a público desde Settings. Un force-push posterior no saca de
forma confiable lo que ya se indexó.

---

## Lo que la redacción no arregla

El `nvidia-bug-report` original **sigue en el servidor de NVIDIA** en su URL actual, aunque
se reemplace el adjunto del hilo: Discourse no purga los uploads huérfanos al instante. Y
quien lo haya bajado tiene el original. Al momento de redactarlo el post tenía 7 vistas y 0
respuestas, así que la exposición real es baja — pero la redacción sirve para adelante, que
es cuando el hilo va a tener tráfico si NVIDIA contesta.

---

## Estructura: un solo repo

Se evaluó separar player / herramientas / drivers en tres repos y **se descartó**. Lo que
hay en `patches/` no son forks: son series de parches contra upstream. Un parche sin el doc
que explica por qué existe no sirve, y el doc sin el parche tampoco.

```
docs/          17 capítulos, del USB al bug de NVIDIA
patches/nvidia/            3 de Project-VR + el nuestro (0004, ver PR #1275)
patches/monado/            7 nuestros
patches/hello_xr-player/   3, el player 360/VR180
scripts/       34 herramientas
experiments/   los EDID del experimento del vblank (docs/16)
```

Lo único que sale del repo es el fix de NVIDIA, y ya salió:
https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1275

Los árboles de código no se versionan: `bootstrap-lab.sh` los clona de upstream en los SHA
exactos contra los que se generaron los parches. Por eso el bundle pesa kilobytes y se ve
exactamente qué es nuestro.

## Lo que faltaba antes de hacerlo público

- [x] **Un README de entrada** (`README.md`, en inglés). Actualizado 2026-08-05 (noche)
      para reflejar que el factorial de `docs/16` ya se corrió (no queda como tarea
      pendiente para un tercero) y que el canal USB/HID también se cerró del lado Windows.
- [x] **Los PDFs de la FCC** (6.8 MB, `docs/*.pdf`) se linkean, no se versionan —
      `.gitignore` los excluye a todos (`*.[Pp][Dd][Ff]`), coherente con el mismo criterio
      ya aplicado al datasheet del ANX7530.

Antes de pasar el repo de privado a público, además de correr `check-publishable.py`:
revisar en la web de GitHub que el README rinda bien, y que ningún archivo de
`windows-kit2/` (binarios de terceros, capturas propias) haya quedado trackeado por error
— esa carpeta es intencionalmente local, ver `.gitignore`.

---

## Acceso git desde el lab

Resuelto. Hay una clave **propia del lab** (no se copió la del sistema principal, así se
puede revocar una máquina sin tocar la otra), en `~/.ssh/id_ed25519`, con su entrada
`Host github.com` en `~/.ssh/config`. La pública ya está cargada en la cuenta.

Verificar con `ssh -T git@github.com` — tiene que responder `Hi Wintch!`.
