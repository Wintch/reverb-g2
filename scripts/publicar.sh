#!/usr/bin/env bash
# Prepara este repo para publicarlo: saca del historial los blobs que GitHub rechaza,
# unifica la identidad de los commits y redacta el serial del casco.
#
#   ./scripts/publicar.sh            revisa y muestra qué haría, sin tocar nada
#   ./scripts/publicar.sh --aplicar  reescribe el historial (hace backup antes)
#
# NO pushea. Después de aplicar, revisá y pusheás vos. Ver docs/17-publicacion.md.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
APLICAR=0
[ "${1:-}" = "--aplicar" ] && APLICAR=1

SERIAL="REDACTED"
BLOBS=(docs/dump90hz.pcapng docs/dump60hz.pcapng nv-report-20260804-223535/build/hmd-vk)
GMAIL="brunduk <nikolai.viktorovich@gmail.com>"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
bad() { printf '   \033[31mFALTA\033[0m %s\n' "$*"; }
ok()  { printf '   ok    %s\n' "$*"; }

say "1. chequeos previos"
[ -d .git ] || { bad "no es un repo git: $REPO"; exit 1; }
ok "repo: $REPO"

if [ -n "$(git status --porcelain)" ]; then
    bad "el working tree tiene cambios sin commitear."
    git status --short | sed 's/^/        /'
    echo "        Commiteá o descartá antes de reescribir el historial."
    exit 1
fi
ok "working tree limpio"

if ! command -v git-filter-repo >/dev/null 2>&1 && ! git filter-repo --version >/dev/null 2>&1; then
    bad "falta git-filter-repo.  sudo apt install git-filter-repo"
    exit 1
fi
ok "git-filter-repo disponible"

say "2. lo que hay hoy"
printf '   %-42s %s\n' "commits" "$(git rev-list --count HEAD)"
printf '   %-42s %s\n' ".git" "$(du -sh .git | cut -f1)"
echo "   autores:"
git log --format='%an <%ae>' | sort -u | sed 's/^/        /'
echo "   blobs más grandes del historial:"
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  | awk '$1=="blob"{print $3, $4}' | sort -rn | head -4 \
  | awk '{printf "        %8.1f MB  %s\n", $1/1048576, $2}'
echo "   archivos con el serial:"
git grep -lI "$SERIAL" HEAD 2>/dev/null | sed 's/^/        /' || echo "        (ninguno)"

if [ "$APLICAR" -eq 0 ]; then
    say "modo revisión"
    echo "   Se sacarían del historial:"
    printf '        %s\n' "${BLOBS[@]}"
    echo "   Se unificarían los autores a: $GMAIL"
    echo "   Se reemplazaría '$SERIAL' por 'REDACTED' en el contenido."
    echo
    echo "   Para aplicarlo:  ./scripts/publicar.sh --aplicar"
    exit 0
fi

say "3. backup"
BACKUP="../$(basename "$REPO")-git-backup-$(git rev-parse --short HEAD)"
rm -rf "$BACKUP"
cp -a .git "$BACKUP"
ok "copia de .git en $BACKUP"
echo "   (si algo sale mal:  rm -rf .git && cp -a $BACKUP .git && git checkout -- .)"

say "4. reescribiendo el historial"
MAILMAP=$(mktemp); REPLACE=$(mktemp)
trap 'rm -f "$MAILMAP" "$REPLACE"' EXIT
cat > "$MAILMAP" <<EOF
$GMAIL <nikolai.viktorovich@gmail.com>
$GMAIL <iam@iashur.internal>
EOF
echo "${SERIAL}==>REDACTED" > "$REPLACE"

PATHARGS=()
for b in "${BLOBS[@]}"; do PATHARGS+=(--path "$b"); done

git filter-repo --force \
    "${PATHARGS[@]}" --invert-paths \
    --mailmap "$MAILMAP" \
    --replace-text "$REPLACE"

say "5. verificación"
FALLAS=0
echo "   autores:"
git log --format='%an <%ae>' | sort -u | sed 's/^/        /'
if git log --format='%ae' | sort -u | grep -qvF "nikolai.viktorovich@gmail.com"; then
    bad "quedó algún autor que no es el gmail"; FALLAS=1
else ok "identidad unificada"; fi

BIG=$(git rev-list --objects --all \
      | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
      | awk '$1=="blob" && $3 > 100*1024*1024 {print $4}')
if [ -n "$BIG" ]; then
    bad "quedan blobs > 100 MB (GitHub los rechaza):"; echo "$BIG" | sed 's/^/        /'; FALLAS=1
else ok "ningún blob supera los 100 MB"; fi

if git grep -qI "$SERIAL" $(git rev-list --all) 2>/dev/null; then
    bad "el serial sigue apareciendo en el historial"; FALLAS=1
else ok "serial redactado"; fi

if git grep -qI "REDACTED" $(git rev-list --all) 2>/dev/null; then
    bad "'REDACTED' sigue apareciendo en el contenido de algún commit"; FALLAS=1
else ok "sin rastros de REDACTED"; fi

printf '   %-42s %s\n' ".git ahora" "$(du -sh .git | cut -f1)"

say "6. siguiente paso"
if [ "$FALLAS" -ne 0 ]; then
    echo "   Hay fallas arriba. NO pushees hasta resolverlas."
    echo "   Para volver atrás:  rm -rf .git && cp -a $BACKUP .git && git checkout -- ."
    exit 1
fi
cat <<'EOF'
   Todo limpio. filter-repo borra el remote a propósito, así que:

       git remote add origin git@github.com:Wintch/reverb-g2-linux.git
       git push -u origin main

   El repo está privado. Revisá en la web que quedó como esperabas y recién
   ahí pasalo a público desde Settings.
EOF
