#!/usr/bin/env bash
#
# extract-wmr-dlls.sh - Copy WMR-related binaries out of a mounted Windows
# install for later Ghidra/ILSpy reverse engineering (see
# docs/11-wmr-decompilation-plan.md).
#
# WARNING: DO NOT RUN THIS SCRIPT YET.
# It assumes the Windows NTFS partition is already mounted read-only, e.g.:
#
#     sudo mount -o ro /dev/nvme0n1p3 /mnt/win
#
# That mount step is privileged and is done separately by the user - this
# script never mounts, unmounts, or uses sudo itself. It only reads from an
# already-mounted path and writes to a local output directory.
#
# Usage:
#     ./extract-wmr-dlls.sh <mount-point> [output-dir]
#
#   <mount-point>  Root of the mounted read-only Windows partition
#                  (e.g. /mnt/win). Must already be mounted.
#   [output-dir]   Where to copy matched files (default:
#                  ./wmr-extracted-<timestamp> in the current directory).
#
# What it does:
#   1. Validates the mount point exists and is actually a mount (not an
#      empty/missing directory - refuses to silently "succeed" against a
#      bare dir).
#   2. Searches (read-only, case-insensitive) for the PRIORITY target group
#      (real WMR/holographic tracking stack) and the SECONDARY target group
#      (Perception Simulation - synthetic input only) as documented in
#      docs/11-wmr-decompilation-plan.md section 2.
#   3. Prints everything it found and lets the user review before copying
#      (unless -y/--yes is passed).
#   4. Copies matches into <output-dir>/priority/ and <output-dir>/secondary/,
#      preserving the relative source path to avoid filename collisions.
#   5. Writes a manifest (TSV: relative_source_path, dest_path, size_bytes,
#      sha256) to <output-dir>/manifest.tsv for provenance tracking, so any
#      later re-extraction (e.g. after a Windows Update) can be diffed.
#
# NDA / IP CAUTION: everything this script copies is proprietary Microsoft
# (and possibly NVIDIA) binary code. Keep the output directory local, out of
# git, and never circulate raw extracted binaries or later decompiler output
# outside this machine. See docs/11-wmr-decompilation-plan.md section 5.

set -euo pipefail

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

ASSUME_YES=0
ARGS=()
for arg in "$@"; do
    case "$arg" in
        -y|--yes)
            ASSUME_YES=1
            ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^#//; s/^ //'
            exit 0
            ;;
        *)
            ARGS+=("$arg")
            ;;
    esac
done

MOUNT_POINT="${ARGS[0]:-}"
OUTPUT_DIR="${ARGS[1]:-./wmr-extracted-$(date +%Y%m%d-%H%M%S)}"

if [[ -z "$MOUNT_POINT" ]]; then
    echo "Usage: $0 <mount-point> [output-dir] [-y|--yes]" >&2
    echo "  <mount-point> must already be mounted read-only, e.g.:" >&2
    echo "    sudo mount -o ro /dev/nvme0n1p3 /mnt/win" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------

if [[ ! -d "$MOUNT_POINT" ]]; then
    echo "ERROR: mount point '$MOUNT_POINT' does not exist or is not a directory." >&2
    exit 1
fi

# Refuse to operate on a path that isn't actually a mounted filesystem -
# this avoids accidentally "extracting" nothing from an empty local dir and
# reporting false success.
if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "ERROR: '$MOUNT_POINT' is not a mount point." >&2
    echo "Mount the Windows partition read-only first, e.g.:" >&2
    echo "    sudo mount -o ro /dev/nvme0n1p3 /mnt/win" >&2
    exit 1
fi

# Sanity check it actually looks like a Windows root (has a Windows dir,
# any case). Warn but don't hard-fail, in case of a nonstandard layout.
if ! find "$MOUNT_POINT" -maxdepth 1 -iname "Windows" -type d | grep -q .; then
    echo "WARNING: no top-level 'Windows' directory found under '$MOUNT_POINT'." >&2
    echo "Continuing anyway, but double-check this is really a Windows partition root." >&2
fi

mkdir -p "$OUTPUT_DIR/priority" "$OUTPUT_DIR/secondary"
MANIFEST="$OUTPUT_DIR/manifest.tsv"

echo "Mount point : $MOUNT_POINT"
echo "Output dir  : $OUTPUT_DIR"
echo

# ---------------------------------------------------------------------------
# Search patterns
# ---------------------------------------------------------------------------
# All patterns are case-insensitive (-iname). Search is read-only: find only,
# no writes under $MOUNT_POINT at any point.

# 2a. PRIORITY - real device tracking / runtime stack
# (see docs/11-wmr-decompilation-plan.md section 2a)
PRIORITY_NAME_PATTERNS=(
    "Windows.Perception*"
    "*HolographicDevice*"
    "*HolographicRuntime*"
    "Windows.Graphics.Holographic*"
    "*MixedReality*"
    "*WMR*"
)

# 2b. SECONDARY - Perception Simulation (synthetic input simulator only,
# NOT the real tracking stack - see docs/11-wmr-decompilation-plan.md
# section 2b)
SECONDARY_NAME_PATTERNS=(
    "PerceptionSimulation*"
    "SimulationStream.Interop.dll"
)

# Roots to search. System32 covers most target DLLs directly. DriverStore
# is searched separately below (by directory name, not just filename) since
# WMR driver packages there use hashed/versioned folder names that don't
# match simple filename globs.
SYSTEM32_CANDIDATES=(
    "$MOUNT_POINT/Windows/System32"
    "$MOUNT_POINT/windows/system32"
)

SYSTEM32_DIR=""
for cand in "${SYSTEM32_CANDIDATES[@]}"; do
    if [[ -d "$cand" ]]; then
        SYSTEM32_DIR="$cand"
        break
    fi
done

if [[ -z "$SYSTEM32_DIR" ]]; then
    # Fall back to a case-insensitive find, in case of unusual casing.
    SYSTEM32_DIR="$(find "$MOUNT_POINT/Windows" -maxdepth 1 -iname "System32" -type d 2>/dev/null | head -n1)"
fi

if [[ -z "$SYSTEM32_DIR" ]]; then
    echo "ERROR: could not locate a System32 directory under '$MOUNT_POINT/Windows'." >&2
    exit 1
fi

echo "Using System32 dir: $SYSTEM32_DIR"

DRIVERSTORE_DIR="$SYSTEM32_DIR/DriverStore/FileRepository"
if [[ ! -d "$DRIVERSTORE_DIR" ]]; then
    DRIVERSTORE_DIR="$(find "$SYSTEM32_DIR" -maxdepth 1 -iname "DriverStore" -type d 2>/dev/null | head -n1)"
    [[ -n "$DRIVERSTORE_DIR" ]] && DRIVERSTORE_DIR="$DRIVERSTORE_DIR/FileRepository"
fi

# ---------------------------------------------------------------------------
# Build find expressions
# ---------------------------------------------------------------------------

build_iname_expr() {
    # Prints a `find` -iname OR-expression for the given patterns array name.
    local -n patterns_ref=$1
    local expr=()
    local first=1
    for pat in "${patterns_ref[@]}"; do
        if [[ $first -eq 0 ]]; then
            expr+=("-o")
        fi
        expr+=("-iname" "$pat")
        first=0
    done
    printf '%s\n' "${expr[@]}"
}

echo "=== Searching PRIORITY targets (real WMR/holographic tracking stack) ==="
mapfile -t PRIORITY_EXPR < <(build_iname_expr PRIORITY_NAME_PATTERNS)
mapfile -t PRIORITY_MATCHES < <(
    find "$MOUNT_POINT/Windows" \( -iname "*.dll" -o -iname "*.exe" -o -iname "*.sys" -o -iname "*.winmd" \) \
        -a \( "${PRIORITY_EXPR[@]}" \) -type f 2>/dev/null | sort -u
)
printf '%s\n' "${PRIORITY_MATCHES[@]}"
echo "PRIORITY matches: ${#PRIORITY_MATCHES[@]}"
echo

echo "=== Searching SECONDARY targets (Perception Simulation - synthetic input only) ==="
mapfile -t SECONDARY_EXPR < <(build_iname_expr SECONDARY_NAME_PATTERNS)
mapfile -t SECONDARY_MATCHES < <(
    find "$MOUNT_POINT/Windows" \( -iname "*.dll" -o -iname "*.exe" \) \
        -a \( "${SECONDARY_EXPR[@]}" \) -type f 2>/dev/null | sort -u
)
printf '%s\n' "${SECONDARY_MATCHES[@]}"
echo "SECONDARY matches: ${#SECONDARY_MATCHES[@]}"
echo

echo "=== Scanning DriverStore for likely WMR driver packages ==="
DRIVERSTORE_MATCHES=()
if [[ -n "$DRIVERSTORE_DIR" && -d "$DRIVERSTORE_DIR" ]]; then
    mapfile -t DRIVERSTORE_PKG_DIRS < <(
        find "$DRIVERSTORE_DIR" -maxdepth 1 -type d \( \
            -iname "*holographic*" -o -iname "*hololens*" -o \
            -iname "*mixedreality*" -o -iname "*wmr*" -o \
            -iname "*perception*" -o -iname "*spatial*" \
        \) 2>/dev/null | sort -u
    )
    for pkgdir in "${DRIVERSTORE_PKG_DIRS[@]}"; do
        echo "  package dir: $pkgdir"
        mapfile -t pkg_files < <(find "$pkgdir" -type f \( -iname "*.dll" -o -iname "*.sys" -o -iname "*.inf" -o -iname "*.cat" \) 2>/dev/null)
        DRIVERSTORE_MATCHES+=("${pkg_files[@]}")
    done
else
    echo "  (no DriverStore/FileRepository directory found - skipping)"
fi
echo "DriverStore matches: ${#DRIVERSTORE_MATCHES[@]}"
echo

TOTAL=$(( ${#PRIORITY_MATCHES[@]} + ${#SECONDARY_MATCHES[@]} + ${#DRIVERSTORE_MATCHES[@]} ))
if [[ $TOTAL -eq 0 ]]; then
    echo "No matching files found. Nothing to copy. Check that the mount point"
    echo "actually contains a Windows install with WMR/Mixed Reality Portal"
    echo "installed (it may have been removed, or the build may name things"
    echo "differently - adjust the patterns in this script and re-run)."
    exit 0
fi

echo "Total candidate files: $TOTAL"
echo

if [[ $ASSUME_YES -ne 1 ]]; then
    read -r -p "Copy these ${TOTAL} files into '$OUTPUT_DIR'? [y/N] " reply
    case "$reply" in
        [yY]|[yY][eE][sS]) ;;
        *) echo "Aborted, nothing copied."; exit 0 ;;
    esac
fi

# ---------------------------------------------------------------------------
# Copy + manifest
# ---------------------------------------------------------------------------

echo "relative_source_path	dest_path	size_bytes	sha256" > "$MANIFEST"

copy_and_log() {
    local src="$1"
    local dest_subdir="$2"   # "priority" or "secondary"
    local rel_path="${src#"$MOUNT_POINT"/}"
    # Flatten into dest_subdir, preserving relative path structure to avoid
    # filename collisions between e.g. System32 and DriverStore copies of
    # a same-named DLL.
    local dest_path="$OUTPUT_DIR/$dest_subdir/$rel_path"
    mkdir -p "$(dirname "$dest_path")"
    cp --no-preserve=mode -- "$src" "$dest_path"
    local size sha
    size=$(stat -c%s -- "$dest_path")
    sha=$(sha256sum -- "$dest_path" | cut -d' ' -f1)
    printf '%s\t%s\t%s\t%s\n' "$rel_path" "$dest_path" "$size" "$sha" >> "$MANIFEST"
    echo "  copied: $rel_path"
}

echo "Copying PRIORITY files..."
for f in "${PRIORITY_MATCHES[@]}"; do
    [[ -n "$f" ]] && copy_and_log "$f" "priority"
done

echo "Copying DriverStore files (grouped under priority/)..."
for f in "${DRIVERSTORE_MATCHES[@]}"; do
    [[ -n "$f" ]] && copy_and_log "$f" "priority"
done

echo "Copying SECONDARY files..."
for f in "${SECONDARY_MATCHES[@]}"; do
    [[ -n "$f" ]] && copy_and_log "$f" "secondary"
done

echo
echo "Done. Manifest written to: $MANIFEST"
echo "Remember: keep '$OUTPUT_DIR' out of git and off any public host."
echo "See docs/11-wmr-decompilation-plan.md section 5 (NDA / IP caution)."
