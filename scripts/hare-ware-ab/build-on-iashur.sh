#!/usr/bin/env bash
# build-on-iashur.sh - build both A/B variants of hare_ware's wmr-new-constellation-tracking.
#
# RUN ON iashur (not on the everyday box). Idempotent; safe to re-run.
#
#   A (fix)   ~/vr/monado-hw          branch hw-timesync-fix-v2 = 10a23daab + 783cf6ae5 (clock fix) + 8 x !2967/!3004
#   B (nofix) ~/vr/monado-hw-nofix    branch hw-ab-nofix        = 10a23daab + the same 8 commits, WITHOUT 783cf6ae5
#
# Input : ~/vr/tmp/hw-ab.bundle (scp'd from the everyday box beforehand)
# Output: the two monado-service paths + git shas, printed at the end.
#
# What it never does: touch the working tree, branches or build of ~/vr/monado (production).
# NOTE: ~/vr/monado-hw may be a worktree of the production repo's object store. In that case
# fetching the bundle adds objects, refs/ab/* and the new branch hw-ab-nofix to that shared .git
# (and `git worktree add` registers monado-hw-nofix there); nothing existing is moved or checked out.
#
# Env overrides (all optional):
#   VR_DIR=~/vr          root of the lab tree
#   BUNDLE=...           bundle path (default $VR_DIR/tmp/hw-ab.bundle)
#   NINJA_TARGETS=...    ninja targets (default: all); used for the local dry run only
#   JOBS=N               ninja -j (default: ninja's own, run under nice -n 10)

set -euo pipefail

VR_DIR="${VR_DIR:-$HOME/vr}"
BUNDLE="${BUNDLE:-$VR_DIR/tmp/hw-ab.bundle}"
HW="$VR_DIR/monado-hw"
NF="$VR_DIR/monado-hw-nofix"
PROD="$VR_DIR/monado"
BR_FIX=hw-timesync-fix-v2
BR_NOFIX=hw-ab-nofix
NINJA_TARGETS="${NINJA_TARGETS:-}"
JOBS_ARGS=()
[ -n "${JOBS:-}" ] && JOBS_ARGS=(-j "$JOBS")

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "== $*"; }
real() { readlink -f -- "$1"; }

# ---- guards -----------------------------------------------------------------
[ -f "$BUNDLE" ] || die "bundle not found: $BUNDLE"
[ -d "$HW" ] || die "$HW does not exist (expected the existing worktree at $BR_FIX)"
[ -f "$HW/build/CMakeCache.txt" ] || die "$HW/build/CMakeCache.txt missing; build monado-hw first"
[ "$(real "$HW")" != "$(real "$PROD")" ] || die "VR_DIR layout wrong: monado-hw resolves to production"
[ "$(real "$NF")" != "$(real "$PROD")" ] || die "nofix path resolves to production"

# one run at a time
mkdir -p "$VR_DIR/tmp"
exec 9>"$VR_DIR/tmp/.build-ab.lock"
flock -n 9 || die "another build-on-iashur.sh is running"

G() { git -C "$HW" "$@"; }   # all repo operations go through monado-hw's worktree

COMMON="$(real "$(G rev-parse --path-format=absolute --git-common-dir)")"
case "$COMMON" in
  "$(real "$PROD")"/.git) info "note: monado-hw shares the production repo's .git ($COMMON); only adding refs/objects/worktree entries" ;;
esac

# ---- 1. fetch the bundle into private refs (never into a checked-out branch) --
info "verify + fetch bundle"
G bundle verify "$BUNDLE" >/dev/null
# gc.auto=0 / maintenance.auto=false: a fetch must not trigger a gc/prune of the (possibly shared
# production) object store as a side effect.
G -c gc.auto=0 -c maintenance.auto=false fetch --quiet "$BUNDLE" \
  "+refs/heads/$BR_FIX:refs/ab/$BR_FIX" \
  "+refs/heads/$BR_NOFIX:refs/ab/$BR_NOFIX"
SHA_FIX="$(G rev-parse "refs/ab/$BR_FIX^{commit}")"
SHA_NOFIX="$(G rev-parse "refs/ab/$BR_NOFIX^{commit}")"
echo "bundle: $BR_FIX=$SHA_FIX  $BR_NOFIX=$SHA_NOFIX"

# sanity: the two trees must differ by exactly the clock-fix commit's 3 files
DIFFSTAT="$(G diff --stat "$SHA_NOFIX" "$SHA_FIX" | tail -n +1)"
echo "$DIFFSTAT"
G diff --name-only "$SHA_NOFIX" "$SHA_FIX" | sort | tr '\n' ' ' | \
  grep -qx 'src/xrt/drivers/wmr/wmr_camera.c src/xrt/drivers/wmr/wmr_camera.h src/xrt/drivers/wmr/wmr_source.c ' \
  || die "A/B diff is not exactly the 3 expected wmr files"

# ---- 2. worktrees -------------------------------------------------------------
# sync_wt DIR BRANCH WANT_SHA : make DIR a worktree of BRANCH at WANT_SHA without clobbering
sync_wt() {
  local dir="$1" br="$2" want="$3" have
  if [ ! -e "$dir" ]; then
    if G show-ref --verify --quiet "refs/heads/$br"; then
      have="$(G rev-parse "refs/heads/$br")"
      [ "$have" = "$want" ] || die "branch $br exists at $have, bundle has $want; refusing to move it"
    else
      G branch "$br" "$want"
    fi
    info "creating worktree $dir at $br"
    G worktree add "$dir" "$br" >/dev/null
    return
  fi
  [ "$(real "$(git -C "$dir" rev-parse --path-format=absolute --git-common-dir)")" = "$COMMON" ] \
    || die "$dir is not a worktree of $COMMON"
  have="$(git -C "$dir" rev-parse HEAD)"
  if [ "$have" = "$want" ]; then
    echo "worktree $dir already at $want"
    return
  fi
  [ -z "$(git -C "$dir" status --porcelain --untracked-files=no)" ] \
    || die "$dir is at $have (want $want) and has local modifications; resolve by hand"
  git -C "$dir" merge-base --is-ancestor "$have" "$want" \
    || die "$dir is at $have, not an ancestor of $want; resolve by hand (local commits there would be lost)"
  info "fast-forwarding $dir $have -> $want"
  git -C "$dir" merge --ff-only "$want" >/dev/null
}

sync_wt "$HW" "$BR_FIX"   "$SHA_FIX"
sync_wt "$NF" "$BR_NOFIX" "$SHA_NOFIX"

# ---- 3. cmake: same cache options as monado-hw/build -----------------------------
CACHE_HW="$HW/build/CMakeCache.txt"
GEN="$(sed -n 's/^CMAKE_GENERATOR:INTERNAL=//p' "$CACHE_HW")"
GEN="${GEN:-Ninja}"

# user-facing options worth replicating (BOOL/STRING/FILEPATH/PATH; never values pointing into a source tree)
KEYRE='^(CMAKE_BUILD_TYPE|BUILD_TESTING|CMAKE_(C|CXX)_COMPILER|CMAKE_(C|CXX)_FLAGS|CMAKE_(C|CXX)_FLAGS_[A-Z_]+|CMAKE_INSTALL_PREFIX|CMAKE_PREFIX_PATH|CMAKE_EXPORT_COMPILE_COMMANDS|CMAKE_POLICY_VERSION_MINIMUM|BUILD_[A-Z0-9_]+|XRT_[A-Z0-9_]+)$'
# extract CACHE SRCDIR [notype] : with "notype" prints KEY=VALUE (cmake may re-type compiler entries)
extract() {
  grep -E '^[A-Za-z0-9_]+:(BOOL|STRING|FILEPATH|PATH)=' "$1" \
    | awk -F'[:=]' -v re="$KEYRE" -v src="$2" -v nt="${3:-}" '
        { key=$1; type=$2; val=substr($0, index($0,"=")+1) }
        key ~ re && index(val, src)==0 && val !~ /-NOTFOUND$/ { print (nt=="notype" ? key : key ":" type) "=" val }' \
    | sort
}
mapfile -t OPTS < <(extract "$CACHE_HW" "$HW")
[ "${#OPTS[@]}" -gt 0 ] || die "no cmake options extracted from $CACHE_HW"
CBT="$(printf '%s\n' "${OPTS[@]}" | sed -n 's/^CMAKE_BUILD_TYPE:STRING=//p')"
BT="$(printf '%s\n' "${OPTS[@]}" | sed -n 's/^BUILD_TESTING:BOOL=//p')"
echo "reference cache: generator=$GEN CMAKE_BUILD_TYPE=${CBT:-<unset>} BUILD_TESTING=${BT:-<unset>} (${#OPTS[@]} options replicated)"
[ "$BT" = "OFF" ] || die "reference BUILD_TESTING is '$BT', expected OFF"

DARGS=()
for o in "${OPTS[@]}"; do DARGS+=("-D$o"); done

if [ ! -f "$NF/build/CMakeCache.txt" ]; then
  info "configuring $NF/build"
  cmake -S "$NF" -B "$NF/build" -G "$GEN" "${DARGS[@]}" >"$NF/build.configure.log" 2>&1 \
    || { tail -30 "$NF/build.configure.log" >&2; die "cmake configure failed (see $NF/build.configure.log)"; }
else
  echo "nofix build dir already configured"
fi

# parity check: same options in both caches (after configure)
if ! diff <(extract "$CACHE_HW" "$HW" notype) <(extract "$NF/build/CMakeCache.txt" "$NF" notype) >"$VR_DIR/tmp/.ab-cache.diff"; then
  echo "WARNING: cmake option mismatch between the two build dirs (< monado-hw, > monado-hw-nofix):" >&2
  cat "$VR_DIR/tmp/.ab-cache.diff" >&2
  die "build configs differ; the A/B would not be like-for-like"
fi
echo "cmake option parity: OK"

# ---- 4. build both, low priority ------------------------------------------------
for d in "$HW" "$NF"; do
  info "building $d/build (nice -n 10 ninja ${NINJA_TARGETS:-all})"
  # shellcheck disable=SC2086
  nice -n 10 ninja -C "$d/build" "${JOBS_ARGS[@]}" $NINJA_TARGETS
done

# ---- 5. report --------------------------------------------------------------------
echo
info "RESULT"
SVC_REL=build/src/xrt/targets/service/monado-service
JSON_REL=build/openxr_monado-dev.json
for pair in "A-fix:$HW" "B-nofix:$NF"; do
  tag="${pair%%:*}"; d="${pair#*:}"
  sha="$(git -C "$d" rev-parse HEAD)"
  br="$(git -C "$d" rev-parse --abbrev-ref HEAD)"
  dirty="$(git -C "$d" status --porcelain --untracked-files=no | wc -l)"
  if [ -x "$d/$SVC_REL" ]; then
    bin="$d/$SVC_REL"; binsha="$(sha256sum "$bin" | cut -c1-16)"
  else
    bin="$d/$SVC_REL (NOT BUILT)"; binsha="-"
  fi
  printf '%-8s branch=%s sha=%s dirty_files=%s\n         service=%s\n         service_sha256=%s\n         openxr_json=%s\n' \
    "$tag" "$br" "$sha" "$dirty" "$bin" "$binsha" "$d/$JSON_REL"
done
if [ -x "$HW/$SVC_REL" ] && [ -x "$NF/$SVC_REL" ] && [ -z "$NINJA_TARGETS" ]; then
  cmp -s "$HW/$SVC_REL" "$NF/$SVC_REL" && echo "WARNING: the two service binaries are byte-identical" >&2 || true
fi
echo "production $PROD untouched: HEAD $(git -C "$PROD" rev-parse --short HEAD 2>/dev/null || echo '?') ($(git -C "$PROD" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?'))"
