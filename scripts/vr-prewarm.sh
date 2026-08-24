#!/bin/bash
# vr-prewarm.sh - make sure a title's files are already hot before the wearer picks it,
# so the first minute of a demo never eats a storage hitch (a page fault to slow disk, a
# Proton/DXVK shader-cache read on first draw) on top of everything else already fighting
# for the frame budget.
#
#   ./vr-prewarm.sh 1073390                       cache-warm Aircar (appid)
#   ./vr-prewarm.sh aircar                        same, resolved by title substring
#   ./vr-prewarm.sh aircar --mode ram              hard guarantee: rsync to tmpfs + swap
#   ./vr-prewarm.sh aircar --mode ram --dry-run    print the plan, touch nothing
#   ./vr-prewarm.sh aircar --restore               undo a ram swap, put the SSD copy back
#   ./vr-prewarm.sh --status                       list active ram swaps + tmpfs usage
#
# WHY THIS EXISTS (NEXT-STEP.md's "ARkade storage line", user-directed 2026-08-18): VR
# demos on this machine must never lose a frame, and a cold page cache or an empty shader
# cache is a real, measured hitch source distinct from everything CLAUDE.md/NEXT-STEP.md's
# pacing work already covers (that's CPU/GPU once frames are already flowing -- this is
# about the FIRST touch of a file). The tty4 picker knows which title is about to launch
# before Monado ever starts (docs/23's per-title profile idea, same session) -- this script
# is the piece that runs in that gap.
#
# `ram` mode's actual benefit measured for the first time 2026-08-24 (T246 follow-up), not
# just assumed: Aircar, U_PACING_APP_LOG=debug, app-fps.sh in 2s windows from the moment
# Steam launched it. Cache mode's app-warming transition window landed at 24 fps before
# reaching steady 90; ram mode's landed at 51 fps and reached steady 90 one whole window
# (2s) sooner. Single A/B pair, not yet repeated 3x per this project's own variance
# discipline -- but the direction and rough size match the hypothesis (the map-load
# texture/shader stream-in is the hitch, and having the whole install already resident in
# RAM instead of read from NVMe measurably softens it) exactly.
#
# TWO MODES, deliberately different strength:
#
#   cache (default) -- page-cache warm. Reads every byte of the title's install dir, Proton
#   prefix, and shader cache so the kernel's page cache already holds them. Works from ANY
#   storage, including a mechanical disk (the cheap, universal path) -- but it is only ever
#   a HINT to the kernel. Under memory pressure (and this box runs full VR + SLAM + a game
#   at once) the cache can be evicted before the title even launches. No mlock here: mlock
#   needs root (CAP_IPC_LOCK) and pinning a multi-GB game tree would fight the SLAM/Basalt
#   working set for real RAM on a 31G box -- if a title needs the hard guarantee, that's
#   what `ram` mode is for, not a root-escalated cache mode.
#
#   ram -- hard guarantee. rsync's the install dir onto the 10G tmpfs at /mnt/vrtmp (see
#   jack-in-wayland.sh's "Ramdisk CSV lifecycle" section -- the same tmpfs already carries
#   session CSVs at its top level as /mnt/vrtmp/slam-<timestamp>; this script deliberately
#   nests games one level down at /mnt/vrtmp/games/<installdir> so the two never collide),
#   verifies the copy is byte-identical, then atomically swaps steamapps/common/<installdir>
#   for a symlink into the tmpfs copy -- Steam/Proton/the game binary itself never know the
#   difference. tmpfs is real RAM, so this can't be evicted; the tradeoff is it's real RAM,
#   hence the size caps below and the free-space check against what else already lives on
#   that tmpfs (the CSVs).
#
# SAFETY RAILS:
#   - ram mode refuses any title over 12G outright (--mode ram never even checks tmpfs
#     free space past that -- a flat no).
#   - ram mode refuses if (size + 15% margin) doesn't fit in tmpfs's CURRENT free space --
#     the margin covers rsync's transient double-write and leaves headroom for the CSVs
#     that already live on the same tmpfs.
#   - ram mode refuses to touch a title whose own process looks like it's running (checked
#     by every .exe basename under the install dir against `pgrep`, bracketed per CLAUDE.md's
#     pgrep-matches-itself trap) -- never rewrite a live title's directory under it.
#   - appid/title resolution that matches more than one installed title refuses to guess:
#     it lists every match (appid + name) and exits. Same for zero matches.
#   - every rm -rf in this script is guarded to a literal /mnt/vrtmp/games/* prefix; nothing
#     outside that tree is ever recursively removed.
#   - the compatdata (Proton) prefix NEVER moves, in either mode -- saves and per-game wine
#     config live there and this project has already been burned once by mixing save data
#     with disposable state (docs/*: compatdata is intentionally excluded from the swap).
#     ram mode still cache-warms it in place on the SSD, same as cache mode does.
#
# FAILURE STATE DISCIPLINE: every step that mutates anything says, on failure, exactly what
# state was left behind and how to recover by hand -- see ram_mode_swap/ram_mode_restore.
# Nothing here should ever need "just delete the whole install dir and reinstall" as the
# recovery plan.
#
# CLAUDE.md traps this script deliberately respects: pgrep -f matches this script's own
# argv unless the pattern is bracketed (bracket the exe basename's first char); pkill is
# blocked in the Claude Code environment entirely, so recovery here only ever uses
# `pgrep` + `kill` on real PIDs, never invoked automatically against a running title anyway
# (this script refuses instead of killing one).

set -u

STEAMAPPS_DIRS=()
TOTAL_BYTES_READ=0
DRY_RUN=0
MODE="cache"
ACTION="warm"
IDENT=""

APPID=""
NAME=""
STEAMAPPS_DIR=""
INSTALLDIR=""
GAME_DIR=""
COMPAT_DIR=""
SHADER_DIR=""

usage() {
	cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") <appid|title-substring> [--mode cache|ram] [--dry-run]
       $(basename "${BASH_SOURCE[0]}") <appid|title-substring> --restore
       $(basename "${BASH_SOURCE[0]}") --status [appid|title-substring]

  --mode cache|ram   cache (default): page-cache warm via vmtouch, or a plain read pass if
                     vmtouch isn't installed. ram: rsync the title onto /mnt/vrtmp and
                     symlink-swap it in, for titles that must never take a storage hitch.
  --dry-run          print the plan (sizes, paths, what would run) without touching
                     anything. Safe to run any time, including mid-session.
  --restore          reverse a --mode ram swap for this title: sync back any newer files,
                     remove the symlink, restore the SSD original.
  --status           list active ram swaps and /mnt/vrtmp usage. Read-only. An optional
                     appid/title after it filters to just that title's status.
  -h, --help         this help.

Title resolution: a pure-digit argument is treated as a Steam appid directly; anything else
is matched case-insensitively as a substring of the installed titles' names (from every
steamapps/appmanifest_*.acf this account has, across every library in libraryfolders.vdf).
Ambiguous or empty matches abort with the candidate list -- this script never guesses.

Examples:
  ./$(basename "${BASH_SOURCE[0]}") 1073390                     cache-warm Aircar by appid
  ./$(basename "${BASH_SOURCE[0]}") aircar --mode ram --dry-run   show the ram-mode plan
  ./$(basename "${BASH_SOURCE[0]}") aircar --restore               undo the ram swap
  ./$(basename "${BASH_SOURCE[0]}") --status                       what's currently swapped
EOF
}

# --- arg parsing -----------------------------------------------------------------------

while [ $# -gt 0 ]; do
	case "$1" in
		--mode)
			MODE="${2:-}"; shift 2 ;;
		--mode=*)
			MODE="${1#*=}"; shift ;;
		--status)
			ACTION="status"; shift ;;
		--restore)
			ACTION="restore"; shift ;;
		--dry-run)
			DRY_RUN=1; shift ;;
		-h|--help)
			usage; exit 0 ;;
		--)
			shift
			[ $# -gt 0 ] && [ -z "$IDENT" ] && { IDENT="$1"; shift; }
			;;
		-*)
			echo "vr-prewarm: unknown option '$1'" >&2; usage >&2; exit 2 ;;
		*)
			if [ -n "$IDENT" ]; then
				echo "vr-prewarm: unexpected extra argument '$1'" >&2; exit 2
			fi
			IDENT="$1"; shift ;;
	esac
done

case "$MODE" in
	cache|ram) ;;
	*) echo "vr-prewarm: --mode must be 'cache' or 'ram', got '$MODE'" >&2; exit 2 ;;
esac

# --- Steam library discovery ------------------------------------------------------------
# $HOME/.steam/steam is Steam's own stable symlink (-> .../debian-installation on this
# box, but that target is not assumed anywhere below). libraryfolders.vdf can list
# ADDITIONAL library roots (e.g. a second drive); each has its own steamapps/ with its
# own appmanifest_*.acf, compatdata/, shadercache/ and common/. Kept deliberately simple
# per spec: a "path" line per library, no VDF parser -- this account only has one library
# today, so this is unexercised beyond the primary path, but costs nothing to leave in.

build_steamapps_dirs() {
	STEAMAPPS_DIRS=()
	local -A seen=()
	local base="${STEAMAPPS_BASE:-$HOME/.steam/steam/steamapps}"
	local candidates=("$base")

	local vdf="$base/libraryfolders.vdf"
	if [ -f "$vdf" ]; then
		local path
		while IFS= read -r path; do
			[ -n "$path" ] && candidates+=("$path/steamapps")
		done < <(grep -oP '"path"\s+"\K[^"]+' "$vdf" 2>/dev/null)
	fi

	local d resolved
	for d in "${candidates[@]}"; do
		[ -d "$d" ] || continue
		resolved="$(cd "$d" && pwd -P)" || continue
		[ -n "${seen[$resolved]:-}" ] && continue
		seen[$resolved]=1
		STEAMAPPS_DIRS+=("$resolved")
	done

	if [ "${#STEAMAPPS_DIRS[@]}" -eq 0 ]; then
		echo "vr-prewarm: no steamapps directory found (looked at $base and its libraryfolders.vdf)" >&2
		exit 1
	fi
}

acf_field() {
	# Pull "key"   "value" out of a Steam .acf (its own flavor of VDF). Anchored on the
	# literal quoted key so e.g. "name" never matches "LastOwner"/"UserConfig"/etc.
	local file="$1" key="$2"
	grep -m1 "\"$key\"" "$file" 2>/dev/null | sed -E 's/^[[:space:]]*"'"$key"'"[[:space:]]+"([^"]*)".*/\1/'
}

resolve_ident() {
	local ident="$1"
	local -a matches=()
	local -A seen_appid=()
	local d f name appid

	if [[ "$ident" =~ ^[0-9]+$ ]]; then
		for d in "${STEAMAPPS_DIRS[@]}"; do
			f="$d/appmanifest_$ident.acf"
			[ -f "$f" ] || continue
			[ -n "${seen_appid[$ident]:-}" ] && continue
			seen_appid[$ident]=1
			matches+=("$ident|$(acf_field "$f" name)|$d")
		done
	else
		for d in "${STEAMAPPS_DIRS[@]}"; do
			[ -d "$d" ] || continue
			for f in "$d"/appmanifest_*.acf; do
				[ -f "$f" ] || continue
				name="$(acf_field "$f" name)"
				printf '%s\n' "$name" | grep -qi -- "$ident" || continue
				appid="$(acf_field "$f" appid)"
				[ -n "$appid" ] || continue
				[ -n "${seen_appid[$appid]:-}" ] && continue
				seen_appid[$appid]=1
				matches+=("$appid|$name|$d")
			done
		done
	fi

	if [ "${#matches[@]}" -eq 0 ]; then
		echo "vr-prewarm: no installed title matches '$ident'" >&2
		exit 1
	fi
	if [ "${#matches[@]}" -gt 1 ]; then
		echo "vr-prewarm: '$ident' is ambiguous -- ${#matches[@]} titles match, refusing to guess:" >&2
		local m
		for m in "${matches[@]}"; do
			echo "    appid=${m%%|*}  name=$(printf '%s' "$m" | cut -d'|' -f2)" >&2
		done
		exit 1
	fi

	local m="${matches[0]}" rest
	APPID="${m%%|*}"
	rest="${m#*|}"
	NAME="${rest%|*}"
	STEAMAPPS_DIR="${rest##*|}"

	local acf="$STEAMAPPS_DIR/appmanifest_$APPID.acf"
	INSTALLDIR="$(acf_field "$acf" installdir)"
	if [ -z "$INSTALLDIR" ]; then
		echo "vr-prewarm: could not read 'installdir' from $acf" >&2
		exit 1
	fi

	GAME_DIR="$STEAMAPPS_DIR/common/$INSTALLDIR"
	COMPAT_DIR="$STEAMAPPS_DIR/compatdata/$APPID"
	SHADER_DIR="$STEAMAPPS_DIR/shadercache/$APPID"

	if [ ! -e "$GAME_DIR" ]; then
		echo "vr-prewarm: appmanifest for '$NAME' ($APPID) found, but its install dir is missing: $GAME_DIR" >&2
		exit 1
	fi
}

# --- cache mode --------------------------------------------------------------------------

human() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "${1}B"; }

warm_cache() {
	local dir="$1" label="$2"
	if [ ! -d "$dir" ]; then
		echo "  [$label] not present, skipping ($dir)"
		return 0
	fi

	local size_bytes
	size_bytes="$(du -sb "$dir" 2>/dev/null | cut -f1)"
	size_bytes="${size_bytes:-0}"

	if [ "$DRY_RUN" -eq 1 ]; then
		echo "  [$label] would warm $dir ($(human "$size_bytes"))"
		if command -v vmtouch >/dev/null 2>&1; then
			echo "           via: vmtouch -t (vmtouch is installed)"
		else
			echo "           via: recursive cat >/dev/null fallback (vmtouch not installed)"
		fi
		return 0
	fi

	local t0=$SECONDS
	if command -v vmtouch >/dev/null 2>&1; then
		echo "  [$label] before:"
		vmtouch -v "$dir" 2>/dev/null | tail -n 4 | sed 's/^/      /'
		vmtouch -t "$dir" >/dev/null 2>&1
		echo "  [$label] after:"
		vmtouch -v "$dir" 2>/dev/null | tail -n 4 | sed 's/^/      /'
	else
		echo "  [$label] vmtouch not installed -- falling back to a plain read pass"
		local n=0 read_bytes=0 fsize
		while IFS= read -r -d '' f; do
			cat "$f" > /dev/null 2>&1
			fsize="$(stat -c%s "$f" 2>/dev/null || echo 0)"
			read_bytes=$((read_bytes + fsize))
			n=$((n + 1))
			if [ $((n % 200)) -eq 0 ]; then
				echo "      ...${n} files, $(human "$read_bytes") read so far"
			fi
		done < <(find "$dir" -type f -print0 2>/dev/null)
		echo "  [$label] read $n files, $(human "$read_bytes") total"
		TOTAL_BYTES_READ=$((TOTAL_BYTES_READ + read_bytes))
	fi
	echo "  [$label] elapsed: $((SECONDS - t0))s"
}

cache_mode_warm() {
	echo "=== cache warm: $NAME (appid $APPID) ==="
	echo "NOTE: this is a hint to the kernel's page cache, not a guarantee -- under memory"
	echo "      pressure (this box regularly runs VR + SLAM + a game at once) these pages"
	echo "      can be evicted before the title even launches. No mlock (needs root); use"
	echo "      --mode ram for a title that cannot tolerate that risk."
	local t0=$SECONDS
	TOTAL_BYTES_READ=0
	warm_cache "$GAME_DIR"   "game dir"
	warm_cache "$COMPAT_DIR" "compatdata"
	warm_cache "$SHADER_DIR" "shadercache"
	if [ "$DRY_RUN" -eq 0 ]; then
		if [ "$TOTAL_BYTES_READ" -gt 0 ]; then
			echo "=== total (fallback path only): $(human "$TOTAL_BYTES_READ") read in $((SECONDS - t0))s ==="
		else
			echo "=== done in $((SECONDS - t0))s (vmtouch path -- see per-path resident% above) ==="
		fi
	fi
}

# --- ram mode ------------------------------------------------------------------------

RAM_SIZE_LIMIT_BYTES=$((12 * 1024 * 1024 * 1024))

resolve_exe_basenames() {
	find "$1" -maxdepth 4 -iname "*.exe" -printf '%f\n' 2>/dev/null | sed -E 's/\.[Ee][Xx][Ee]$//'
}

title_is_running() {
	# CLAUDE.md's pgrep-matches-itself trap: bracket the exe basename's first character
	# so the pattern in THIS script's own argv/cmdline can never match the grep it runs.
	local dir="$1" exe pattern
	local found=0
	while IFS= read -r exe; do
		[ -n "$exe" ] || continue
		pattern="[${exe:0:1}]${exe:1}"
		if pgrep -f "$pattern" >/dev/null 2>&1; then
			echo "  process matching '$exe' looks like it's running" >&2
			found=1
		fi
	done < <(resolve_exe_basenames "$dir")
	[ "$found" -eq 0 ]
}

safe_rm_rf_tmpfs() {
	# Hard rail: never recurse a delete outside /mnt/vrtmp/games, no matter what a
	# variable resolved to upstream (empty INSTALLDIR, a stray "..", etc).
	local target
	target="$(readlink -f "$1" 2>/dev/null || echo "$1")"
	case "$target" in
		/mnt/vrtmp/games/?*)
			rm -rf "$target" ;;
		*)
			echo "  REFUSING rm -rf outside /mnt/vrtmp/games: '$target'" >&2
			return 1 ;;
	esac
}

ram_mode_swap() {
	local tmpfs_dir="/mnt/vrtmp/games/$INSTALLDIR"
	local ssd_backup="${GAME_DIR}.ssd"

	if ! mountpoint -q /mnt/vrtmp 2>/dev/null; then
		echo "vr-prewarm: /mnt/vrtmp is not mounted -- ram mode needs the tmpfs staging area." >&2
		echo "            Use --mode cache instead, or mount /mnt/vrtmp first." >&2
		exit 1
	fi

	local size_bytes
	size_bytes="$(du -sb "$GAME_DIR" 2>/dev/null | cut -f1)"
	size_bytes="${size_bytes:-0}"

	if [ "$size_bytes" -gt "$RAM_SIZE_LIMIT_BYTES" ]; then
		echo "vr-prewarm: '$NAME' is $(human "$size_bytes") -- over the 12G ram-mode safety limit. Refusing." >&2
		exit 1
	fi

	local need_bytes=$((size_bytes + size_bytes * 15 / 100))
	local avail_bytes
	avail_bytes="$(df --output=avail -B1 /mnt/vrtmp 2>/dev/null | tail -1 | tr -d ' ')"
	avail_bytes="${avail_bytes:-0}"

	if [ "$need_bytes" -gt "$avail_bytes" ]; then
		echo "vr-prewarm: '$NAME' needs $(human "$need_bytes") (size + 15% margin) but /mnt/vrtmp only has $(human "$avail_bytes") free." >&2
		echo "            Remember: session CSVs (SLAM_WRITE_CSVS etc.) also live on this tmpfs at" >&2
		echo "            /mnt/vrtmp/slam-* -- don't assume the whole 10G is available. Refusing." >&2
		exit 1
	fi

	if [ -e "$ssd_backup" ] || [ -L "$GAME_DIR" ]; then
		echo "vr-prewarm: '$NAME' already looks ram-swapped (found $ssd_backup and/or $GAME_DIR is already a symlink). Use --restore first." >&2
		exit 1
	fi

	if [ "$DRY_RUN" -eq 1 ]; then
		echo "=== [dry-run] ram swap: $NAME (appid $APPID) ==="
		echo "  game dir:   $GAME_DIR  ($(human "$size_bytes"))"
		echo "  tmpfs free: $(human "$avail_bytes"), need $(human "$need_bytes") (size + 15% margin)"
		echo "  would: rsync -a '$GAME_DIR/' '$tmpfs_dir/'"
		echo "  would: verify with 'rsync -anc --delete' (must print nothing)"
		echo "  would: mv '$GAME_DIR' '$ssd_backup'; ln -s '$tmpfs_dir' '$GAME_DIR'"
		echo "  would also cache-warm compatdata prefix (stays on SSD, never swapped): $COMPAT_DIR"
		return 0
	fi

	echo "==> checking '$NAME' isn't currently running"
	if ! title_is_running "$GAME_DIR"; then
		echo "vr-prewarm: refusing to ram-swap '$NAME' while it looks like it's running." >&2
		exit 1
	fi

	echo "==> rsync $GAME_DIR/ -> $tmpfs_dir/"
	mkdir -p "$(dirname "$tmpfs_dir")"
	if ! rsync -a "$GAME_DIR/" "$tmpfs_dir/"; then
		echo "vr-prewarm: rsync failed. State: SSD original untouched at $GAME_DIR;" >&2
		echo "            a partial copy may remain at $tmpfs_dir -- safe to delete and retry." >&2
		exit 1
	fi

	echo "==> verifying copy (rsync -anc --delete must print nothing)"
	local diff
	diff="$(rsync -anc --delete "$GAME_DIR/" "$tmpfs_dir/" 2>&1)"
	if [ -n "$diff" ]; then
		echo "vr-prewarm: verification found differences -- aborting BEFORE the swap." >&2
		echo "            State: SSD original untouched at $GAME_DIR." >&2
		echo "            The unverified tmpfs copy was left at $tmpfs_dir for inspection" >&2
		echo "            (not removed automatically); delete it by hand once you've looked." >&2
		echo "$diff" | sed 's/^/    /' >&2
		exit 1
	fi

	echo "==> swap: mv '$GAME_DIR' -> '$ssd_backup'"
	if ! mv "$GAME_DIR" "$ssd_backup"; then
		echo "vr-prewarm: mv to .ssd failed. State: original directory untouched at $GAME_DIR;" >&2
		echo "            verified tmpfs copy sits unused at $tmpfs_dir. Safe to retry." >&2
		exit 1
	fi

	if ! ln -s "$tmpfs_dir" "$GAME_DIR"; then
		echo "vr-prewarm: symlink creation FAILED after the original was already moved aside." >&2
		echo "            State: $GAME_DIR is MISSING. Your data is safe at $ssd_backup." >&2
		echo "            Recover by hand with:  mv '$ssd_backup' '$GAME_DIR'" >&2
		exit 1
	fi

	echo "==> ram swap complete: $GAME_DIR -> $tmpfs_dir  (SSD original preserved at $ssd_backup)"
	echo "==> cache-warming compatdata prefix (stays on SSD -- saves/config live there, never moved)"
	warm_cache "$COMPAT_DIR" "compatdata"
}

ram_mode_restore() {
	local tmpfs_dir="/mnt/vrtmp/games/$INSTALLDIR"
	local ssd_backup="${GAME_DIR}.ssd"

	if [ ! -L "$GAME_DIR" ] || [ ! -d "$ssd_backup" ]; then
		echo "vr-prewarm: no active ram swap found for '$NAME' (expected a symlink at" >&2
		echo "            $GAME_DIR and a backup at $ssd_backup)." >&2
		exit 1
	fi

	local link_target want_target
	link_target="$(readlink -f "$GAME_DIR" 2>/dev/null)"
	want_target="$(readlink -f "$tmpfs_dir" 2>/dev/null)"
	if [ -z "$want_target" ] || [ "$link_target" != "$want_target" ]; then
		echo "vr-prewarm: $GAME_DIR is a symlink but doesn't point at the expected tmpfs copy" >&2
		echo "            ($tmpfs_dir) -- refusing to touch it automatically. Investigate by hand." >&2
		exit 1
	fi

	if [ "$DRY_RUN" -eq 1 ]; then
		echo "=== [dry-run] restore: $NAME (appid $APPID) ==="
		echo "  would check for tmpfs-side files newer than the SSD backup (rsync -ani --update)"
		echo "  and sync any back first, then:"
		echo "  rm '$GAME_DIR'"
		echo "  mv '$ssd_backup' '$GAME_DIR'"
		echo "  rm -rf '$tmpfs_dir'   (freeing the tmpfs copy)"
		return 0
	fi

	echo "==> checking for tmpfs-side changes newer than the SSD backup"
	# Game saves usually live under compatdata (never touched by this script), but be
	# safe anyway: anything a title wrote into its own install dir while it ran off
	# tmpfs (some titles do keep config there) gets synced back before either copy is
	# destroyed.
	local newer
	newer="$(rsync -ani --update "$tmpfs_dir/" "$ssd_backup/" 2>/dev/null)"
	if [ -n "$newer" ]; then
		echo "    tmpfs copy has newer files -- syncing them back to the SSD backup first:"
		echo "$newer" | sed 's/^/      /'
		if ! rsync -au --update "$tmpfs_dir/" "$ssd_backup/"; then
			echo "vr-prewarm: sync-back failed -- nothing removed. tmpfs copy: $tmpfs_dir," >&2
			echo "            SSD backup: $ssd_backup. Fix the sync, then re-run --restore." >&2
			exit 1
		fi
	else
		echo "    none found"
	fi

	echo "==> removing symlink $GAME_DIR"
	if ! rm "$GAME_DIR"; then
		echo "vr-prewarm: couldn't remove symlink $GAME_DIR. State: swap still active, nothing else changed." >&2
		exit 1
	fi

	echo "==> restoring SSD copy: mv '$ssd_backup' -> '$GAME_DIR'"
	if ! mv "$ssd_backup" "$GAME_DIR"; then
		echo "vr-prewarm: mv back failed. State: $GAME_DIR is MISSING. Data is safe at $ssd_backup." >&2
		echo "            Recover by hand with:  mv '$ssd_backup' '$GAME_DIR'" >&2
		exit 1
	fi

	echo "==> freeing tmpfs copy: $tmpfs_dir"
	safe_rm_rf_tmpfs "$tmpfs_dir" || echo "    (left in place -- remove it by hand if that's wrong)" >&2

	echo "==> restore complete: $GAME_DIR is back on SSD"
}

# --- status ------------------------------------------------------------------------------

print_tmpfs_usage() {
	if mountpoint -q /mnt/vrtmp 2>/dev/null; then
		df -h /mnt/vrtmp | tail -1 | awk '{print "  tmpfs: " $3 " used / " $2 " total, " $4 " free (" $5 " used)"}'
		if [ -d /mnt/vrtmp/games ]; then
			echo "  /mnt/vrtmp/games contents:"
			local any=0
			local d
			for d in /mnt/vrtmp/games/*/; do
				[ -d "$d" ] || continue
				any=1
				echo "    $(du -sh "$d" 2>/dev/null | cut -f1)  $d"
			done
			[ "$any" -eq 1 ] || echo "    (empty)"
		fi
	else
		echo "  /mnt/vrtmp: not mounted"
	fi
}

status_all() {
	echo "=== vr-prewarm status ==="
	print_tmpfs_usage
	echo
	echo "  active ram swaps:"
	local found=0 d ssd base title
	for d in "${STEAMAPPS_DIRS[@]}"; do
		[ -d "$d/common" ] || continue
		for ssd in "$d"/common/*.ssd; do
			[ -d "$ssd" ] || continue
			found=1
			base="${ssd%.ssd}"
			title="$(basename "$base")"
			if [ -L "$base" ]; then
				echo "    $title  ($d)  ->  $(readlink -f "$base")  [$(du -sh "$(readlink -f "$base")" 2>/dev/null | cut -f1)]"
			else
				echo "    $title  ($d)  -- INCONSISTENT: SSD backup present but $base is not a symlink, needs a manual look"
			fi
		done
	done
	[ "$found" -eq 1 ] || echo "    (none)"
}

status_one() {
	echo "=== vr-prewarm status: $NAME (appid $APPID) ==="
	local tmpfs_dir="/mnt/vrtmp/games/$INSTALLDIR"
	local ssd_backup="${GAME_DIR}.ssd"
	if [ -L "$GAME_DIR" ] && [ -d "$ssd_backup" ]; then
		echo "  ram-swapped: $GAME_DIR -> $(readlink -f "$GAME_DIR") [$(du -sh "$(readlink -f "$GAME_DIR")" 2>/dev/null | cut -f1)]"
		echo "  SSD backup:  $ssd_backup"
	else
		echo "  not ram-swapped (install dir is a plain directory)"
	fi
	echo
	print_tmpfs_usage
}

# --- main ----------------------------------------------------------------------------

build_steamapps_dirs

case "$ACTION" in
	status)
		if [ -n "$IDENT" ]; then
			resolve_ident "$IDENT"
			status_one
		else
			status_all
		fi
		;;
	restore)
		if [ -z "$IDENT" ]; then
			echo "vr-prewarm: --restore needs an appid or title" >&2
			usage >&2
			exit 2
		fi
		resolve_ident "$IDENT"
		ram_mode_restore
		;;
	warm)
		if [ -z "$IDENT" ]; then
			echo "vr-prewarm: need an appid or title to warm" >&2
			usage >&2
			exit 2
		fi
		resolve_ident "$IDENT"
		if [ "$MODE" = "ram" ]; then
			ram_mode_swap
		else
			cache_mode_warm
		fi
		;;
esac
