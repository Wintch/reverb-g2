#!/usr/bin/env python3
"""Verifica que el repo se pueda publicar sin filtrar nada ni chocar con los límites de
GitHub. No modifica nada. Correr antes de cada push a un remoto público.

    ./scripts/verificar-publicable.py

Los patrones a buscar NO viven acá: se leen de `scripts/.patrones-privados`, que está en
.gitignore. Así el propio verificador no publica lo que busca — que es el error que
cometimos la primera vez, cuando el script llevaba adentro la dirección y el serial que
estaba redactando.

Formato de .patrones-privados: un patrón por línea, las que empiezan con # se ignoran.

Chequea, sobre TODOS los objetos del repo y no sólo sobre HEAD:

  1. que haya una sola identidad en los commits
  2. que ningún blob supere los 100 MB (GitHub los rechaza)
  3. que ningún patrón privado aparezca en el contenido de ningún blob,
     **incluidos los binarios y los comprimidos**

El punto 3 es el que importa. `git grep -I` saltea los binarios, así que un .gz con datos
privados adentro pasa un chequeo basado en git grep sin que nadie lo mire. Nos pasó
exactamente eso: un nvidia-bug-report viejo, con el serial del casco y la MAC de la placa
de red, sobrevivió a la limpieza y llegó al remoto dentro de un blob comprimido.

Sin dependencias: sólo stdlib.
"""

import gzip
import subprocess
import sys
from pathlib import Path

LIMITE = 100 * 1024 * 1024          # GitHub rechaza blobs de más de 100 MB
BOLD, RED, RESET = "\033[1m", "\033[31m", "\033[0m"

fallas = 0


def git(*args, binary=False):
    r = subprocess.run(["git", *args], capture_output=True)
    if r.returncode:
        sys.exit(f"git {' '.join(args)} falló: {r.stderr.decode(errors='replace')}")
    return r.stdout if binary else r.stdout.decode(errors="replace")


def say(t):
    print(f"\n{BOLD}== {t}{RESET}")


def ok(t):
    print(f"   ok    {t}")


def bad(t):
    global fallas
    fallas = 1
    print(f"   {RED}FALLA{RESET} {t}")


raiz = Path(git("rev-parse", "--show-toplevel").strip())

say("identidad de los commits")
autores = sorted(set(git("log", "--format=%an <%ae>").splitlines()))
for a in autores:
    print(f"        {a}")
ok("una sola identidad") if len(autores) == 1 else bad("hay más de una identidad")

# inventario de blobs: sha -> ruta (la primera que lo referencia)
inventario = {}
for linea in git("rev-list", "--objects", "--all").splitlines():
    sha, _, ruta = linea.partition(" ")
    inventario.setdefault(sha, ruta or "<sin ruta>")

tipos = git("cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
            "--batch-all-objects")
blobs = {}
for linea in tipos.splitlines():
    sha, tipo, tam = linea.split()
    if tipo == "blob":
        blobs[sha] = int(tam)

say("tamaño de los blobs")
grandes = [(s, t) for s, t in blobs.items() if t > LIMITE]
if grandes:
    bad("hay blobs sobre el límite de 100 MB de GitHub:")
    for s, t in sorted(grandes, key=lambda x: -x[1]):
        print(f"        {t / 1048576:8.1f} MB  {inventario.get(s, '?')}")
else:
    ok(f"ninguno de los {len(blobs)} blobs supera los 100 MB")
tam = next((l.split(": ", 1)[1] for l in git("count-objects", "-vH").splitlines()
            if l.startswith("size-pack:")), "?")
print(f"   {'.git (size-pack)':<38} {tam}")

say("patrones privados, en todos los blobs")
archivo = raiz / "scripts" / ".patrones-privados"
if not archivo.exists():
    print(f"   (no hay {archivo.relative_to(raiz)}, salteado)")
    print("   Creá ese archivo con un patrón por línea para chequear direcciones,")
    print("   seriales, MACs o lo que no deba salir. Está en .gitignore.")
else:
    ignorado = subprocess.run(["git", "check-ignore", "-q", str(archivo)]).returncode == 0
    ok("el archivo de patrones está gitignoreado") if ignorado else \
        bad("el archivo de patrones NO está gitignoreado — se publicaría con el repo")

    patrones = [l.strip().encode() for l in archivo.read_text().splitlines()
                if l.strip() and not l.startswith("#")]
    sucios = []
    for sha in blobs:
        crudo = git("cat-file", "blob", sha, binary=True)
        cuerpos = [crudo]
        if crudo[:2] == b"\x1f\x8b":                 # gzip
            try:
                cuerpos.append(gzip.decompress(crudo))
            except Exception:
                pass
        for pat in patrones:
            if any(pat in c for c in cuerpos):
                sucios.append((sha, inventario.get(sha, "?"), pat.decode()))

    if sucios:
        bad(f"{len(sucios)} blob(s) contienen patrones privados:")
        for sha, ruta, pat in sucios:
            print(f"        {sha[:12]}  {ruta}  <- {pat}")
        print("\n        Para sacarlos del historial:")
        unicos = sorted({s for s, _, _ in sucios})
        print("            printf '%s\\n' " + " ".join(u[:12] for u in unicos)
              + " > /tmp/shas")
        print("            git filter-repo --force --strip-blobs-with-ids /tmp/shas")
        print("        y después force-push, porque reescribe el historial.")
    else:
        ok(f"ningún patrón privado en los {len(blobs)} blobs (binarios y .gz incluidos)")

say("resultado")
if fallas:
    print("   NO publicar hasta resolver lo de arriba.")
    print("   El procedimiento de limpieza está en docs/17-publicacion.md.")
else:
    print("   Publicable.")
sys.exit(fallas)
