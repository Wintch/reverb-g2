#!/bin/bash
# steam-prefix-guard.sh - keep Proton prefixes (steamapps/compatdata/<appid>) off NTFS Steam libraries.
#
#   steam-prefix-guard.sh check            read-only; exit 0 = clean, 1 = problems found
#   steam-prefix-guard.sh fix [--apply]    move offending prefixes to ext4 and symlink them back;
#                                          DRY RUN unless --apply is given
#   steam-prefix-guard.sh preseed [--apply]  for every INSTALLED app on an NTFS library that has no
#                                          compatdata entry yet, create an empty ext4 directory under
#                                          the store and symlink it in, so its FIRST launch already works
#                                          (a first launch on NTFS creates the prefix and dies with Errno 22)
#
# Why (docs/70, docs/139 F5): a library on NTFS (fuseblk/ntfs3, here /mnt/videos and /mnt/win5)
# cannot hold the relative symlinks Proton creates inside a prefix; a NEW prefix there dies in about
# one second with  OSError: [Errno 22] Invalid argument: '../drive_c'  (creating dosdevices/c:).
# The cure is to keep compatdata/<appid> on ext4 and leave a symlink in the library.
#
# A compatdata entry is a PROBLEM when, inside an NTFS library, it is
#   - a real directory (a prefix that lives on NTFS), or
#   - a symlink whose target is missing, or whose target is itself on NTFS.
# Symlinks to any other filesystem are fine, whatever the target is called (the repo has e.g.
# 108800-ge-proton11-5). 'fix' never touches an appid whose game or driver is running, skips an
# existing destination, and never deletes anything it did not just copy successfully (it uses mv).
#
# Environment: PREFIX_STORE (default ~/proton-prefixes-external), STEAM_ROOT.

set -u
STEAM_ROOT="${STEAM_ROOT:-$HOME/.steam/debian-installation}"
PREFIX_STORE="${PREFIX_STORE:-$HOME/proton-prefixes-external}"
NTFS_RE="${PREFIX_GUARD_NTFS_RE:-^(fuseblk|ntfs|ntfs3|ntfs-3g)$}"   # override only for tests

fstype_of() { stat -f -c %T -- "$1" 2>/dev/null; }   # 'fuseblk' / 'ext2/ext3' (ext4) ...
is_ntfs_fs() {   # stat -f reports fuseblk for ntfs-3g and 'ntfs' / 'ntfs3' otherwise
	local t; t=$(fstype_of "$1"); t="${t,,}"
	[[ "$t" =~ $NTFS_RE ]] && return 0
	t=$(findmnt -no FSTYPE -T "$1" 2>/dev/null)
	[[ "${t,,}" =~ $NTFS_RE ]]
}

libraries() {
	local vdf="$STEAM_ROOT/steamapps/libraryfolders.vdf"
	if [ -r "$vdf" ]; then sed -n 's/^[[:space:]]*"path"[[:space:]]*"\(.*\)"/\1/p' "$vdf"; else echo "$STEAM_ROOT"; fi
}

# appids that currently have a live process using that compatdata (STEAM_COMPAT_DATA_PATH in environ)
running_appids() {
	local p
	for p in /proc/[0-9]*; do
		[ -O "$p" ] && [ -r "$p/environ" ] || continue
		{ tr '\0' '\n' < "$p/environ"; } 2>/dev/null | sed -n 's|^STEAM_COMPAT_DATA_PATH=.*/compatdata/\([0-9]*\)/*$|\1|p'
	done | sort -u
}

human() { du -sh --apparent-size -- "$1" 2>/dev/null | cut -f1; }

scan() {   # prints "<lib>\t<appid>\t<kind>\t<detail>" for every problem
	local lib cd e id tgt
	while IFS= read -r lib; do
		cd="$lib/steamapps/compatdata"
		[ -d "$cd" ] || continue
		is_ntfs_fs "$cd" || continue
		for e in "$cd"/*; do
			[ -e "$e" ] || [ -L "$e" ] || continue
			id=$(basename "$e")
			if [ -L "$e" ]; then
				tgt=$(readlink -f -- "$e" 2>/dev/null)
				if [ ! -d "$tgt" ]; then printf '%s\t%s\tBROKEN-LINK\t%s\n' "$lib" "$id" "$(readlink "$e")"
				elif is_ntfs_fs "$tgt"; then printf '%s\t%s\tLINK-ON-NTFS\t%s\n' "$lib" "$id" "$tgt"; fi
			elif [ -d "$e" ]; then
				printf '%s\t%s\tREAL-DIR-ON-NTFS\t%s\n' "$lib" "$id" "$(human "$e")"
			fi
		done
	done < <(libraries)
}

do_check() {
	local n=0 total=0 lib id kind detail
	while IFS=$'\t' read -r lib id kind detail; do
		[ -n "$id" ] || continue
		n=$((n + 1))
		echo "PROBLEM  appid $id  $kind  ($detail)  in $lib/steamapps/compatdata"
	done < <(scan)
	for lib in $(libraries); do
		[ -d "$lib/steamapps/compatdata" ] && total=$((total + $(find "$lib/steamapps/compatdata" -mindepth 1 -maxdepth 1 | wc -l)))
	done
	echo "prefix guard: $n problem(s) among $total compatdata entries; store $PREFIX_STORE: $(human "$PREFIX_STORE" || echo 'absent') ($(df -P / | awk 'NR==2{print $5}') used on /)"
	[ "$n" = 0 ]
}

do_fix() {
	local apply=0 lib id kind detail running moved=0 skipped=0 src dst need avail
	[ "${1:-}" = "--apply" ] && apply=1
	[ "$apply" = 1 ] || echo "DRY RUN (nothing will be changed; pass --apply to do it)"
	running=" $(running_appids | tr '\n' ' ') "
	mkdir -p "$PREFIX_STORE" 2>/dev/null || { [ "$apply" = 0 ] || { echo "cannot create $PREFIX_STORE"; return 2; }; }
	while IFS=$'\t' read -r lib id kind detail; do
		[ -n "$id" ] || continue
		src="$lib/steamapps/compatdata/$id"; dst="$PREFIX_STORE/$id"
		case "$kind" in
			REAL-DIR-ON-NTFS) ;;
			*) echo "SKIP     appid $id: $kind ($detail) needs a manual look, not a move"; skipped=$((skipped + 1)); continue ;;
		esac
		case "$running" in
			*" $id "*) echo "REFUSE   appid $id: a process is using this prefix right now; close the game/driver first"; skipped=$((skipped + 1)); continue ;;
		esac
		if [ -e "$dst" ] || [ -L "$dst" ]; then
			echo "SKIP     appid $id: destination $dst already exists (resolve by hand)"; skipped=$((skipped + 1)); continue
		fi
		need=$(du -sk --apparent-size -- "$src" 2>/dev/null | cut -f1)
		avail=$(df -Pk "$PREFIX_STORE" 2>/dev/null | awk 'NR==2{print $4}')
		if [ -n "$need" ] && [ -n "$avail" ] && [ "$avail" -lt $((need * 12 / 10 + 1048576)) ]; then
			echo "REFUSE   appid $id: not enough free space for $(human "$src") (need ~$((need / 1024)) MB + 1 GB headroom)"; skipped=$((skipped + 1)); continue
		fi
		if [ "$apply" = 0 ]; then
			echo "WOULD    move $src ($(human "$src")) -> $dst and symlink back"; continue
		fi
		echo "MOVING   $src -> $dst"
		if mv -- "$src" "$dst" && ln -s "$dst" "$src"; then
			echo "DONE     appid $id: $src -> $dst"; moved=$((moved + 1))
		else
			echo "FAILED   appid $id: left as is (check $src and $dst by hand)"; return 3
		fi
	done < <(scan)
	echo "fix: moved=$moved skipped/refused=$skipped$([ "$apply" = 0 ] && echo ' (dry run)')"
}

do_preseed() {
	local apply=0 lib f id n=0
	[ "${1:-}" = "--apply" ] && apply=1
	[ "$apply" = 1 ] || echo "DRY RUN (nothing will be changed; pass --apply to do it)"
	while IFS= read -r lib; do
		[ -d "$lib/steamapps" ] || continue
		is_ntfs_fs "$lib/steamapps" || continue
		mkdir -p "$lib/steamapps/compatdata" 2>/dev/null
		for f in "$lib"/steamapps/appmanifest_*.acf; do
			[ -f "$f" ] || continue
			id=${f##*appmanifest_}; id=${id%.acf}
			case "$id" in ''|*[!0-9]*) continue ;; esac
			if [ -e "$lib/steamapps/compatdata/$id" ] || [ -L "$lib/steamapps/compatdata/$id" ]; then continue; fi
			if [ "$apply" = 0 ]; then echo "WOULD    preseed appid $id in $lib"; n=$((n + 1)); continue; fi
			mkdir -p -- "$PREFIX_STORE/$id" && ln -s "$PREFIX_STORE/$id" "$lib/steamapps/compatdata/$id" \
				&& { echo "PRESEED  appid $id -> $PREFIX_STORE/$id"; n=$((n + 1)); } || echo "FAILED   preseed appid $id"
		done
	done < <(libraries)
	echo "preseed: $n app(s)$([ "$apply" = 0 ] && echo ' (dry run)')"
}

case "${1:-}" in
	check) do_check ;;
	fix) shift; do_fix "$@" ;;
	preseed) shift; do_preseed "$@" ;;
	*) echo "usage: $(basename "$0") check | fix [--apply] | preseed [--apply]" >&2; exit 2 ;;
esac
