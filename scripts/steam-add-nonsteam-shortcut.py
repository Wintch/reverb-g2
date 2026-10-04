#!/usr/bin/env python3
"""steam-add-nonsteam-shortcut.py - add a non-Steam game (with a Proton mapping) to Steam, with Steam CLOSED.

  steam-add-nonsteam-shortcut.py --name "Blade Runner 9732" --exe /mnt/videos/nonsteam/BR9732/BR9732.exe \
      [--startdir DIR] [--launch-options "PROTON_LOG=1 %command% -vrmode openvr"] [--proton proton_experimental] [--apply]

Why (docs/138, Blade Runner 9732): a Windows exe started with a bare `proton run` lacks the Steam client environment Proton's
vrclient shim expects; as a shortcut Steam starts it through pressure-vessel like any library title. Dry run unless --apply.
Writes <userdata>/<id>/config/shortcuts.vdf (binary VDF, round-trip checked) and the CompatToolMapping of config/config.vdf, backing
both up once under ~/vr/bak-<name-slug>/. Prints the gameid to launch with:  steam steam://rungameid/<gameid>
The appid is crc32(quoted exe + name) | 0x80000000 (Steam's own scheme); gameid = appid << 32 | 0x02000000.
Environment: STEAM_ROOT (default ~/.steam/debian-installation), STEAM_USERDATA_ID (default: the only/first userdata dir).
"""
import argparse, glob, os, re, shutil, struct, subprocess, sys, zlib


def parse(b, i=0):
    d = {}
    while i < len(b):
        t = b[i]; i += 1
        if t == 8:
            return d, i
        j = b.index(b"\0", i); k = b[i:j].decode("utf-8", "replace"); i = j + 1
        if t == 0:
            d[k], i = parse(b, i)
        elif t == 1:
            j = b.index(b"\0", i); d[k] = b[i:j].decode("utf-8", "replace"); i = j + 1
        elif t == 2:
            d[k] = struct.unpack("<I", b[i:i + 4])[0]; i += 4
        else:
            raise ValueError(f"unknown VDF type {t} at {i}")
    return d, i


def dump(d):
    out = b""
    for k, v in d.items():
        kb = k.encode() + b"\0"
        if isinstance(v, dict):
            out += b"\x00" + kb + dump(v)
        elif isinstance(v, str):
            out += b"\x01" + kb + v.encode() + b"\0"
        else:
            out += b"\x02" + kb + struct.pack("<I", v & 0xFFFFFFFF)
    return out + b"\x08"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True); ap.add_argument("--exe", required=True)
    ap.add_argument("--startdir"); ap.add_argument("--launch-options", default="")
    ap.add_argument("--proton", default="proton_experimental"); ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    home = os.path.expanduser("~"); root = os.environ.get("STEAM_ROOT", home + "/.steam/debian-installation")
    uid = os.environ.get("STEAM_USERDATA_ID") or os.path.basename(sorted(glob.glob(root + "/userdata/[0-9]*"))[0])
    sc_path = f"{root}/userdata/{uid}/config/shortcuts.vdf"; cfg_path = root + "/config/config.vdf"
    exe = '"%s"' % a.exe; startdir = '"%s"' % (a.startdir or os.path.dirname(a.exe) + "/")
    appid = (zlib.crc32((exe + a.name).encode()) & 0xFFFFFFFF) | 0x80000000; gameid = (appid << 32) | 0x02000000
    raw = open(sc_path, "rb").read() if os.path.exists(sc_path) else b"\x00shortcuts\x00\x08\x08"
    d, _ = parse(raw); assert dump(d) == raw, "shortcuts.vdf does not round-trip; refusing to touch it"
    sc = d.setdefault("shortcuts", {})
    print(f"appid {appid}  gameid {gameid}  userdata {uid}")
    if subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", "steam"], capture_output=True).returncode == 0:
        print("Steam is running: close it first (it rewrites these files on exit)"); return 2
    if any(v.get("AppName") == a.name for v in sc.values()):
        print("shortcut already present; nothing to do"); return 0
    entry = {"appid": appid, "AppName": a.name, "Exe": exe, "StartDir": startdir, "icon": "", "ShortcutPath": "",
             "LaunchOptions": a.launch_options, "IsHidden": 0, "AllowDesktopConfig": 1, "AllowOverlay": 1, "OpenVR": 1,
             "Devkit": 0, "DevkitGameID": "", "DevkitOverrideAppID": 0, "LastPlayTime": 0, "FlatpakAppID": "", "tags": {}}
    print("would add shortcut", len(sc), "and CompatToolMapping", a.proton, "(dry run)" if not a.apply else "")
    if not a.apply:
        return 0
    bak = home + "/vr/bak-" + re.sub(r"\W+", "-", a.name.lower()); os.makedirs(bak, exist_ok=True)
    for f in (sc_path, cfg_path):
        if os.path.exists(f) and not os.path.exists(bak + "/" + os.path.basename(f)):
            shutil.copy2(f, bak + "/" + os.path.basename(f))
    sc[str(len(sc))] = entry
    open(sc_path, "wb").write(dump(d))
    t = open(cfg_path, errors="surrogateescape").read()
    m = re.search(r'"CompatToolMapping"\s*\n\s*\{\n', t)
    if not m:
        print("CompatToolMapping not found in config.vdf: set the Proton version in the Steam UI"); return 3
    if f'"{appid}"' not in t:
        block = (f'\t\t\t\t\t"{appid}"\n\t\t\t\t\t{{\n\t\t\t\t\t\t"name"\t\t"{a.proton}"\n\t\t\t\t\t\t"config"\t\t""\n'
                 f'\t\t\t\t\t\t"priority"\t\t"250"\n\t\t\t\t\t}}\n')
        open(cfg_path, "w", errors="surrogateescape").write(t[:m.end()] + block + t[m.end():])
    print(f"done; launch with: steam steam://rungameid/{gameid}   (backups in {bak})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
