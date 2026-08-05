# 17 — Publicar el repo

Objetivo: que cualquiera con un Reverb G2 pueda seguir desarrollando esto. Destino
`github.com/Wintch/reverb-g2-linux`.

Auditoría hecha 2026-08-05 desde el sistema principal, con el SSD del lab montado.

---

## Bloqueo 1: los pcapng no entran en GitHub

Las dos capturas de USB **están en el historial de git**, no sólo en el árbol de trabajo:

```
858.1 MB  docs/dump90hz.pcapng
428.9 MB  docs/dump60hz.pcapng
```

**GitHub rechaza cualquier blob de más de 100 MB.** El `git push` falla de entrada, y
borrarlos ahora no alcanza: quedan en la historia. Git LFS tampoco resuelve — el tier
gratis es 1 GB y esto son 1.29 GB.

Hay que sacarlos del historial. No es pérdida real: el valor está en el análisis
(`docs/12-protocolo-g2.md`, `scripts/parse-usbpcap.py`), no en los dumps crudos. Si algún
día hacen falta, se hostean aparte y se linkean.

`.git` pesa **410 MB** hoy; después de la limpieza debería quedar en pocos MB.

## Bloqueo 2: identidad y datos del equipo

En archivos **trackeados**:

| qué | archivos | decisión |
|---|---|---|
| `nikolai.viktorovich@gmail.com` | 2 + historial | **sacar** — es la dirección de trabajo, no va en nada público |
| `iam@iashur.internal` | historial | unificar a gmail, es ruido |
| serial `REDACTED` | 4 | **redactar** — es el serial de este casco |
| `nv-report-*/build/hmd-vk` | 1 | binario compilado, no debe estar trackeado |

Los cuatro PDFs de la FCC (6.8 MB) son documentos públicos y pueden quedarse, aunque
linkearlos sería más liviano.

---

## El procedimiento

```bash
pipx install git-filter-repo      # o apt install git-filter-repo

cd ~/Documents/reverb-g2-linux
git status                        # tiene que estar limpio antes de empezar
cp -a .git /tmp/git-backup        # red de seguridad

# 1. sacar del historial los pcapng y el binario de build
git filter-repo \
    --path docs/dump90hz.pcapng \
    --path docs/dump60hz.pcapng \
    --path nv-report-20260804-223535/build/hmd-vk \
    --invert-paths

# 2. unificar identidad
cat > /tmp/mailmap <<'EOF'
brunduk <nikolai.viktorovich@gmail.com> <nikolai.viktorovich@gmail.com>
brunduk <nikolai.viktorovich@gmail.com> <iam@iashur.internal>
EOF
git filter-repo --mailmap /tmp/mailmap

# 3. redactar el serial del contenido de los archivos
echo 'REDACTED==>REDACTED' > /tmp/redact
git filter-repo --replace-text /tmp/redact

# 4. verificar que no quedó nada
git log --format='%an <%ae>' | sort -u          # sólo gmail
git grep -lI -e REDACTED -e REDACTED $(git rev-list --all) | head   # vacío
du -sh .git                                      # pocos MB
git rev-list --objects --all | git cat-file --batch-check='%(objectsize) %(rest)' \
  | sort -rn | head -3                           # ningún blob > 100 MB

# 5. publicar
git remote add origin git@github.com:Wintch/reverb-g2-linux.git
git push -u origin main
```

`git filter-repo` borra el remote a propósito después de reescribir, por eso el `remote
add` va al final.

---

## Estructura: un solo repo

Se evaluó separar player / herramientas / drivers en tres repos y **se descartó**. Lo que
hay en `patches/` no son forks: son series de parches contra upstream. Un parche sin el doc
que explica por qué existe no sirve, y el doc sin el parche tampoco. La estructura actual
es la correcta:

```
docs/          17 capítulos, del USB al bug de NVIDIA
patches/nvidia/            3 de Project-VR + el nuestro (0004)
patches/monado/            7 nuestros
patches/hello_xr-player/   3, el player 360/VR180
scripts/       34 herramientas
experiments/   los EDID del experimento del vblank
```

Lo único que sale del repo es el fix de NVIDIA, y ya salió: PR #1275.

Los árboles de código no se versionan: `bootstrap-lab.sh` los clona de upstream en los SHA
exactos contra los que se generaron los parches. Por eso el bundle pesa kilobytes y se ve
exactamente qué es nuestro.

## Lo que falta antes de publicar

- **Un README de entrada.** El actual asume contexto. Un tercero necesita saber en diez
  líneas: qué funciona hoy, qué no, y cuál es el primer comando.
- Decidir si los cuatro PDFs de la FCC se quedan o se linkean.

---

## Acceso git desde el lab

Ya está resuelto. Se generó una clave **propia del lab** (no se copió la del sistema
principal, así se puede revocar una máquina sin tocar la otra):

```
~/.ssh/id_ed25519          clave del lab, sin passphrase
~/.ssh/config              entrada Host github.com
```

La pública hay que agregarla una vez en https://github.com/settings/ssh/new
(tipo **Authentication Key**):

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAII4MD3DYOMHUzRz2jLi/6KuNf+Bf+S1MiK3Y64b+BcTR reverb-g2-lab
```

Verificar con `ssh -T git@github.com` — tiene que responder `Hi Wintch!`.

La identidad de git de este repo ya quedó apuntando a gmail (`git config user.email`).
