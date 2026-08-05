#!/usr/bin/env bash
# Verifica que el repo se pueda publicar sin filtrar nada ni chocar con los límites
# de GitHub. No modifica nada. Correr antes de cada push a un remoto público.
#
#   ./scripts/verificar-publicable.sh
#
# Los patrones a buscar NO viven acá: se leen de scripts/.patrones-privados, que está
# en .gitignore. Así el propio verificador no publica lo que busca — que es el error
# que cometimos la primera vez, cuando el script llevaba adentro la dirección y el
# serial que estaba redactando.
#
# Formato de .patrones-privados: un patrón por línea, las que empiezan con # se ignoran.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
PATRONES="scripts/.patrones-privados"
LIMITE=$((100 * 1024 * 1024))   # GitHub rechaza blobs de más de 100 MB
FALLAS=0

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
bad() { printf '   \033[31mFALLA\033[0m %s\n' "$*"; FALLAS=1; }
ok()  { printf '   ok    %s\n' "$*"; }

say "identidad de los commits"
AUTORES=$(git log --format='%an <%ae>' | sort -u)
echo "$AUTORES" | sed 's/^/        /'
[ "$(echo "$AUTORES" | wc -l)" -eq 1 ] \
    && ok "una sola identidad" \
    || bad "hay más de una identidad en el historial"

say "tamaño de los blobs"
GRANDES=$(git rev-list --objects --all \
    | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
    | awk -v lim="$LIMITE" '$1=="blob" && $3>lim {printf "%.1f MB  %s\n", $3/1048576, $4}')
if [ -n "$GRANDES" ]; then
    bad "hay blobs sobre el límite de 100 MB de GitHub:"
    echo "$GRANDES" | sed 's/^/        /'
else
    ok "ningún blob supera los 100 MB"
fi
printf '   %-38s %s\n' ".git" "$(du -sh .git | cut -f1)"

say "patrones privados"
if [ ! -f "$PATRONES" ]; then
    echo "   (no hay $PATRONES, salteado)"
    echo "   Creá ese archivo con un patrón por línea para chequear direcciones,"
    echo "   seriales, MACs o lo que no deba salir. Está en .gitignore."
else
    if git check-ignore -q "$PATRONES"; then
        ok "$PATRONES está gitignoreado, como corresponde"
    else
        bad "$PATRONES NO está gitignoreado — se publicaría junto con el repo"
    fi
    TODOS=$(git rev-list --all)
    while IFS= read -r pat; do
        [ -z "$pat" ] && continue
        case "$pat" in \#*) continue ;; esac
        HITS=$(git grep -lI "$pat" $TODOS 2>/dev/null | head -5)
        if [ -n "$HITS" ]; then
            bad "aparece en el historial:"
            echo "$HITS" | sed 's/^/        /'
        else
            ok "ausente del historial"
        fi
    done < "$PATRONES"
fi

say "resultado"
if [ "$FALLAS" -eq 0 ]; then
    echo "   Publicable."
else
    echo "   NO publicar hasta resolver lo de arriba. El procedimiento de limpieza"
    echo "   está en docs/17-publicacion.md."
fi
exit "$FALLAS"
