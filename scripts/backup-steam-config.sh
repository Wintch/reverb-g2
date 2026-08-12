#!/bin/bash
# backup-steam-config.sh - snapshot the Steam/VR configuration that is expensive to rebuild.
#
#   ./backup-steam-config.sh            write a timestamped snapshot
#   ./backup-steam-config.sh --list     show existing snapshots
#
# WHY (2026-08-12, T161). Reconstructing which titles have which launch options took a real
# chunk of a session, and getting it wrong is worse than not having it: three titles in
# docs/23 carry "broken" verdicts that were probably just missing launch options
# (Funhouse, InCell VR, InMind VR -- all three lacked the recipe, while CLAUDE.md recorded
# them as "three unrelated failures, not a shared bug"). This data is a few hundred KB and
# it protects every per-title verdict in docs/23 from being silently invalidated.
#
# WHERE IT GOES, and why not into git: localconfig.vdf carries account-specific data (the
# full library, playtimes, identifiers). THIS REPOSITORY IS PUBLIC. So the full snapshot
# stays outside git, under ~/vr/backups/, and only a sanitised appid -> launch-options
# table is written into the repo, where it is small, reviewable and safe.
#
# Steam rewrites localconfig.vdf from memory when it exits, so a snapshot taken while
# Steam is RUNNING can be stale relative to changes made in the UI this session. The
# script says so rather than pretending otherwise.

set -u

VR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$VR"
[ -d "$HOME/vr" ] && VR="$HOME/vr"
DEST_ROOT="$VR/backups"
STEAM="$HOME/.steam/debian-installation"

if [ "${1:-}" = "--list" ]; then
    if [ -d "$DEST_ROOT" ]; then
        du -sh "$DEST_ROOT"/steam-* 2>/dev/null | sort -k2 || echo "no snapshots yet"
    else
        echo "no snapshots yet ($DEST_ROOT does not exist)"
    fi
    exit 0
fi

[ -d "$STEAM" ] || { echo "No Steam install at $STEAM" >&2; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$DEST_ROOT/steam-$STAMP"
mkdir -p "$DEST" || exit 1

if pgrep -x steam >/dev/null 2>&1; then
    echo "NOTE: Steam is running. It rewrites localconfig.vdf on exit, so anything changed"
    echo "      in the UI this session may not be on disk yet. Close Steam first for a"
    echo "      guaranteed-current snapshot."
fi

copy() {  # copy() <src> <label>
    if [ -e "$1" ]; then
        mkdir -p "$DEST/$(dirname "$2")"
        cp -a "$1" "$DEST/$2" && echo "  + $2"
    else
        echo "  - $2 (absent)"
    fi
}

echo "Snapshot -> $DEST"

# Per-user config: launch options live here. This is the one that matters most.
for ud in "$STEAM"/userdata/*/; do
    [ -d "$ud" ] || continue
    uid="$(basename "$ud")"
    copy "$ud/config/localconfig.vdf" "userdata/$uid/localconfig.vdf"
    copy "$ud/config/shortcuts.vdf"   "userdata/$uid/shortcuts.vdf"
done

# Global Steam config: compat-tool (Proton version) mappings per title.
copy "$STEAM/config/config.vdf" "config/config.vdf"

# Which OpenVR runtime is registered -- Steam rewrites this and has re-added SteamVR
# behind our back before (docs/pruebas.jsonl T152).
copy "$HOME/.config/openvr/openvrpaths.vrpath" "openvr/openvrpaths.vrpath"

# Installed-title list: cheap, and it is what a verdict in docs/23 refers to.
mkdir -p "$DEST/appmanifests"
n=0
for f in "$STEAM"/steamapps/appmanifest_*.acf; do
    [ -e "$f" ] || break
    cp -a "$f" "$DEST/appmanifests/" && n=$((n+1))
done
echo "  + appmanifests/ ($n titles)"

# xrizer's custom bindings, if any are in use (XRIZER_CUSTOM_BINDINGS_DIR).
copy "$HOME/.local/share/xrizer" "xrizer"

# --- environment fingerprint ---------------------------------------------------------
# A pacing measurement is meaningless without knowing what it was measured against. The
# 2026-08-09 kernel + DKMS rebuild is the case in point: it sat between a session where
# games ran and one where they did not, and reconstructing that boundary afterwards took
# real work. Stamping every snapshot makes "did dropped frames change with the driver?"
# answerable instead of arguable.
{
    echo "# environment fingerprint -- $(date -Iseconds)"
    echo "kernel:            $(uname -r)"
    echo "os:                $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
    echo "nvidia:            $(sed -n '1p' /proc/driver/nvidia/version 2>/dev/null)"
    echo "nvidia_dkms_built: $(stat -c %y /lib/modules/$(uname -r)/updates/dkms/nvidia.ko.xz 2>/dev/null | cut -d. -f1)"
    echo "gpu:               $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -1)"
    echo "nvidia_patches:    $(ls /usr/src/nvidia-*/patches/ 2>/dev/null | tr '\n' ' ')"
    echo "monado_head:       $(git -C "$VR/monado" log --oneline -1 2>/dev/null)"
    echo "monado_branch:     $(git -C "$VR/monado" rev-parse --abbrev-ref HEAD 2>/dev/null)"
    echo "monado_built:      $(stat -c %y "$VR/monado/build/src/xrt/targets/service/monado-service" 2>/dev/null | cut -d. -f1)"
    echo "xrizer_built:      $(stat -c %y "$VR/xrizer/target/release/libxrizer.so" 2>/dev/null | cut -d. -f1)"
    echo "basalt_so:         $([ -e "$VR/basalt/build/libbasalt.so" ] && echo present || echo ABSENT)"
    echo "proton:            $(cat "$STEAM/steamapps/common/Proton - Experimental/version" 2>/dev/null | tr '\n' ' ')"
    echo "mesa:              $(dpkg-query -W -f='${Version}' libgl1-mesa-dri 2>/dev/null)"
} > "$DEST/environment.txt"
echo "  + environment.txt"

# --- sanitised, git-safe export: appid -> launch options only ------------------------
OUT="$REPO/docs/steam-launch-options.md"
python3 - "$STEAM" "$OUT" <<'PY'
import sys, re, os, glob, datetime
steam, out = sys.argv[1], sys.argv[2]
names = {}
for f in glob.glob(f"{steam}/steamapps/appmanifest_*.acf"):
    aid = os.path.basename(f).split("_")[1].split(".")[0]
    m = re.search(r'"name"\s*"([^"]*)"', open(f, encoding="utf-8", errors="replace").read())
    if m:
        names[aid] = m.group(1)

rows = []
for cfg in glob.glob(f"{steam}/userdata/*/config/localconfig.vdf"):
    t = open(cfg, encoding="utf-8", errors="replace").read()
    for aid, name in names.items():
        for mm in re.finditer(r'"%s"\s*\n\s*\{' % aid, t):
            s = mm.end(); d = 1; j = s
            while d and j < len(t):
                if t[j] == '{': d += 1
                elif t[j] == '}': d -= 1
                j += 1
            blk = t[s:j]
            if not re.search(r'"(LastPlayed|Playtime|BadgeData)"', blk):
                continue
            m = re.search(r'"LaunchOptions"\s*"([^"]*)"', blk)
            rows.append((name, aid, m.group(1) if m else ""))
            break

rows.sort(key=lambda r: r[0].lower())
BASE = "PRESSURE_VESSEL_FILESYSTEMS_RW"
with open(out, "w", encoding="utf-8") as f:
    f.write("# Steam launch options, per title\n\n")
    f.write("Generated by `scripts/backup-steam-config.sh` — **do not hand-edit**, it is overwritten.\n\n")
    f.write("Every OpenVR title needs the same three variables to reach Monado from inside Steam's\n")
    f.write("pressure-vessel container. They are not about the game: `XR_RUNTIME_JSON` picks the\n")
    f.write("runtime, `IPC_IGNORE_VERSION` skips the IPC version check, and\n")
    f.write("`PRESSURE_VESSEL_FILESYSTEMS_RW` exposes the Monado socket inside the sandbox.\n")
    f.write("Without them a title fails with `ERROR_RUNTIME_UNAVAILABLE` or a\n")
    f.write("\"VR HMD not found\" popup — which reads exactly like a compatibility problem and is not.\n\n")
    f.write("**Per-title tuning belongs here too**, not only the plumbing: engine cvars passed as\n")
    f.write("launch options can be worth a large fraction of the framerate (the user's own example:\n")
    f.write("Half-Life: Alyx, where forcing fog and LOD settings from the launcher is what made it\n")
    f.write("playable). A title can \"work\" and still be leaving half its performance unclaimed.\n\n")
    f.write(f"Snapshot: {datetime.date.today().isoformat()} — {len(rows)} installed titles.\n\n")
    f.write("| Title | AppID | Base recipe | Extra options |\n|---|---|---|---|\n")
    for name, aid, o in rows:
        if not o:
            base, extra = "**MISSING**", "—"
        else:
            base = "yes" if BASE in o else "**incomplete**"
            extra = o.replace("XR_RUNTIME_JSON=/home/iam/vr/monado/build/openxr_monado-dev.json", "") \
                     .replace("IPC_IGNORE_VERSION=1", "") \
                     .replace("PRESSURE_VESSEL_FILESYSTEMS_RW=/run/user/1000/monado_comp_ipc", "") \
                     .replace("%command%", "").strip()
            extra = f"`{extra}`" if extra else "—"
        f.write(f"| {name} | {aid} | {base} | {extra} |\n")
print(f"  + {os.path.relpath(out)} ({len(rows)} titles)")
PY

echo
echo "Snapshot size: $(du -sh "$DEST" | cut -f1)"
echo "Restore a file with:  cp $DEST/userdata/<uid>/localconfig.vdf <original path>   (Steam CLOSED)"
