# 70 — Two Steam/NTFS gotchas: unregistered secondary library, Proton prefix on NTFS

Two real Steam configuration traps found when a game installed on an NTFS library shared with
Windows would not launch under Proton on Linux. Both fixes were applied and confirmed working.

## 1. A second Steam library (NTFS, shared with Windows) is not registered

A second library on NTFS partitions (mounted via `fuseblk`/ntfs-3g) can be genuinely shared with
a Windows install: the library's own `libraryfolder.vdf` marker contains `"launcher"
"C:\\Program Files (x86)\\Steam\\steam.exe"`, proof it was created by Windows Steam. A game
already fully installed there is still unknown to the Linux Steam client until the library
folder is added to `~/.steam/debian-installation/steamapps/libraryfolders.vdf` (which only
lists the primary library). Launching the game then offers to **install it fresh**, not because
anything is broken, purely because Steam does not know the library exists.

**Fix**: with Steam shut down, add an entry to `libraryfolders.vdf` for the path, using the
`contentid` already present in that library's own `libraryfolder.vdf` marker (leave `"apps": {}`
empty; Steam scans and populates it itself on next start):

```
"1"
{
	"path"		"/mnt/videos/SteamLibrary"
	"label"		""
	"contentid"		"<contentid>"   // from that library's own libraryfolder.vdf
	"totalsize"		"0"
	"update_clean_bytes_tally"		"0"
	"time_last_update_verified"		"0"
	"apps"
	{
	}
}
```

Confirmed: Steam's next start scanned the whole library and populated every appid's exact
installed size, with no download and no re-verify, just recognition.

## 2. Proton's own prefix cannot be created on NTFS

Even with the library recognised, the first Proton launch crashes within ~2 seconds:

```
OSError: [Errno 22] Invalid argument: '../drive_c' -> '.../compatdata/1091500/pfx//dosdevices/c:'
```

`ntfs-3g` refuses the symlink Proton creates inside every prefix (`dosdevices/c:` ->
`../drive_c`). **The game files are never touched**; only the small Linux-only
`compatdata/<appid>` metadata folder is affected, and Windows Steam does not read it.

**Fix**: do not put the prefix on NTFS. Relocate just `compatdata/<appid>` to a local ext4 disk
(real symlink support) via a plain symlink, leaving the game on NTFS:

```bash
rm -rf /mnt/videos/SteamLibrary/steamapps/compatdata/1091500   # was a broken partial prefix, not game data
mkdir -p ~/proton-prefixes-external/1091500
ln -s ~/proton-prefixes-external/1091500 /mnt/videos/SteamLibrary/steamapps/compatdata/1091500
```

Confirmed: after this the prefix builds and the game launches normally. **General lesson: any
title installed on the NTFS library hits this exact crash on first Proton launch**; apply the
same symlink relocation before assuming a title is broken.

Two related notes:

- Reusing one prefix across two different Proton major builds (different Wine versions) risks
  subtle breakage; use a separate prefix directory per Proton build when comparing builds.
- Edit `libraryfolders.vdf`, `config.vdf` and `localconfig.vdf` only with Steam fully shut down
  (take a timestamped `.bak` first); the client rewrites them on exit.
