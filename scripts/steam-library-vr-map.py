#!/usr/bin/env python3
"""Build a VR-capability map of the whole Steam library (owned, not just installed).

Usage:
    python3 scripts/steam-library-vr-map.py [--cache-dir DIR] [--time-budget SECONDS]
                                             [--limit N] [--sleep SECONDS]

Regenerates docs/steam-library-vr-map.json and docs/steam-library-vr-map.md.
Safe to re-run: appdetails responses are cached to disk (one JSON file per appid)
under --cache-dir, so a re-run only fetches appids that were missing or marked
"not fetched" last time, unless --refresh is passed.

Data sources, in the order actually used this run:
  1. Steam Community profile XML (games?tab=all&xml=1) for the owned-games list.
     Only works if the account's "game details" privacy is Public. On this
     account it is NOT (the profile itself is public but this sub-setting
     redirects to login) -- see the report in docs/steam-library-vr-map.md.
  2. IPlayerService/GetOwnedGames Web API -- needs STEAM_API_KEY in the
     environment. Skipped silently if unset.
  3. Fallback (what actually ran): the "apps" block of the local user's
     localconfig.vdf, which Steam populates for every owned app (not just
     installed ones), cross-checked against installed appmanifest_*.acf.
     This does NOT touch or modify localconfig.vdf -- read-only.

Per-appid detail comes from the public Store API
(https://store.steampowered.com/api/appdetails), one appid per request --
that endpoint does not support batching. Requests are paced (~1.6s apart)
and cached so reruns are free for already-fetched appids.

Does not touch hardware, does not run Steam or Monado, does not modify any
Steam config file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
LOCALCONFIG_PATH = Path(
    "/home/iam/.steam/steam/userdata/27072718/config/localconfig.vdf"
)
STEAMAPPS_DIR = Path("/home/iam/.steam/steam/steamapps")
STEAMID64 = "76561197987338446"
# Store API responses, one JSON per appid -- reruns are free. Override with --cache-dir.
DEFAULT_CACHE_DIR = Path(os.environ.get("STEAM_VR_MAP_CACHE", "~/.cache/reverb-g2/steam-store")).expanduser()
DOCS23_PATH = DOCS_DIR / "23-game-compatibility.md"
JSON_OUT = DOCS_DIR / "steam-library-vr-map.json"
MD_OUT = DOCS_DIR / "steam-library-vr-map.md"

USER_AGENT = "reverb-g2-lab-vr-map/1.0 (+https://github.com/, read-only research script)"

# Category descriptions (as literally returned by the Store API for this
# catalog snapshot) that count as "VR-relevant". Do NOT trust category IDs --
# they do not match the ids named in some older documentation (e.g. this
# catalog returns id 54 for "VR Only", not 403). Match by the description
# string the API actually sends, and keep the raw id+description pairs too.
VR_ONLY_DESCRIPTIONS = {"VR Only"}
VR_SUPPORTED_DESCRIPTIONS = {"VR Support", "VR Supported"}
TRACKED_CONTROLLER_DESCRIPTIONS = {
    "Tracked Controller Support",
    "Tracked Motion Controller Support",
}
FULL_CONTROLLER_DESCRIPTIONS = {"Full controller support"}
PARTIAL_CONTROLLER_DESCRIPTIONS = {"Partial Controller Support"}


# --------------------------------------------------------------------------
# Owned-games list
# --------------------------------------------------------------------------


def try_profile_xml() -> tuple[list[dict], str] | None:
    """Route (a): Steam Community profile XML games list. Returns None on failure."""
    import xml.etree.ElementTree as ET

    urls = [
        f"https://steamcommunity.com/profiles/{STEAMID64}/games?tab=all&xml=1",
        "https://steamcommunity.com/id/wintch/games?tab=all&xml=1",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status != 200:
                    continue
                body = resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            continue
        text = body.decode("utf-8", errors="replace")
        if "<html" in text.lower() or "login" in text.lower()[:200]:
            # redirected to login (private "game details" setting) -- not XML
            continue
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            continue
        games_el = root.find("games")
        if games_el is None:
            continue
        games = []
        for g in games_el.findall("game"):
            appid_el = g.find("appID")
            name_el = g.find("name")
            hours_el = g.find("hoursOnRecord")
            if appid_el is None or not (appid_el.text or "").strip():
                continue
            games.append(
                {
                    "appid": int(appid_el.text.strip()),
                    "name": (name_el.text or "").strip() if name_el is not None else "",
                    "hours_on_record": (hours_el.text or "").strip()
                    if hours_el is not None
                    else None,
                }
            )
        if games:
            return games, url
    return None


def try_web_api() -> tuple[list[dict], str] | None:
    """Route (b): IPlayerService/GetOwnedGames. Needs STEAM_API_KEY in env."""
    key = os.environ.get("STEAM_API_KEY")
    if not key:
        return None
    url = (
        "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
        f"?key={key}&steamid={STEAMID64}&format=json&include_appinfo=1"
        "&include_played_free_games=1"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    games_raw = data.get("response", {}).get("games", [])
    if not games_raw:
        return None
    games = [
        {
            "appid": g["appid"],
            "name": g.get("name", ""),
            "hours_on_record": round(g.get("playtime_forever", 0) / 60, 1),
        }
        for g in games_raw
    ]
    return games, "IPlayerService/GetOwnedGames (Web API)"


def parse_localconfig_appids(path: Path) -> list[int]:
    """Route (c) fallback: top-level appid keys under Software/Valve/Steam/apps.

    Read-only. Does not modify localconfig.vdf. Steam writes an entry here
    (playtime/cloud-sync state) for every app the account owns that the
    client has ever touched or synced, not only installed ones -- this is
    a reasonable proxy for "owned" when the profile's game-details privacy
    blocks the official XML/API routes, as it does on this account.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    idx = text.find('"apps"')
    if idx == -1:
        return []
    start = text.find("{", idx)
    depth = 0
    pos = start
    while pos < len(text):
        c = text[pos]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        pos += 1
    block = text[start : pos + 1]

    ids: list[int] = []
    depth = 0
    i = 0
    n = len(block)
    while i < n:
        c = block[i]
        if c == '"':
            j = block.find('"', i + 1)
            if j == -1:
                break
            token = block[i + 1 : j]
            k = j + 1
            while k < n and block[k] in " \t\r\n":
                k += 1
            if depth == 1 and token.isdigit() and k < n and block[k] == "{":
                ids.append(int(token))
            i = j + 1
        elif c == "{":
            depth += 1
            i += 1
        elif c == "}":
            depth -= 1
            i += 1
        else:
            i += 1
    # appid "0" is a real artifact in this file (LastPlayed/Playtime block
    # with no game behind it -- not a valid Steam appid) -- drop it.
    return sorted(set(ids) - {0})


def parse_installed_manifests(steamapps_dir: Path) -> dict[int, str]:
    """appid -> name, read-only, from appmanifest_*.acf. Does not modify anything."""
    installed = {}
    if not steamapps_dir.is_dir():
        return installed
    for f in steamapps_dir.glob("appmanifest_*.acf"):
        try:
            appid = int(f.stem.replace("appmanifest_", ""))
        except ValueError:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'"name"\s*"([^"]*)"', text)
        installed[appid] = m.group(1) if m else ""
    return installed


# --------------------------------------------------------------------------
# docs/23 cross-reference
# --------------------------------------------------------------------------

ROW_RE = re.compile(
    r"^\|\s*(.+?)\s*\|\s*\[(\d+)\]\(https://steamdb\.info/app/\d+/?\)\s*\|"
    r"\s*([^|]*?)\s*\|\s*(.*?)\s*\|\s*$"
)
SECTION_RE = re.compile(r"^##\s+(.*)$")


def parse_docs23(path: Path) -> dict[int, dict]:
    """appid -> {title, mark, notes (first ~120 chars), section, occurrences}."""
    if not path.exists():
        return {}
    entries: dict[int, dict] = {}
    section = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        sm = SECTION_RE.match(line)
        if sm:
            section = sm.group(1).strip()
            continue
        rm = ROW_RE.match(line)
        if not rm:
            continue
        title, appid_s, mark, notes = rm.groups()
        appid = int(appid_s)
        notes_trimmed = notes.strip()
        if len(notes_trimmed) > 120:
            notes_trimmed = notes_trimmed[:120].rstrip() + "..."
        if appid not in entries:
            entries[appid] = {
                "title": title.strip(),
                "mark": mark.strip(),
                "notes": notes_trimmed,
                "section": section,
                "occurrences": 1,
            }
        else:
            entries[appid]["occurrences"] += 1
    return entries


# --------------------------------------------------------------------------
# Store API fetch (cached, paced)
# --------------------------------------------------------------------------


def cache_path(cache_dir: Path, appid: int) -> Path:
    return cache_dir / f"appdetails_{appid}.json"


def fetch_appdetails(appid: int) -> dict:
    """Single request. Returns the raw {"<appid>": {...}} dict from the API,
    or a synthetic {"<appid>": {"success": false, "_fetch_error": "..."}}."""
    url = (
        f"https://store.steampowered.com/api/appdetails"
        f"?appids={appid}&cc=ar&l=english"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.status
            body = resp.read()
    except urllib.error.HTTPError as e:
        return {str(appid): {"success": False, "_fetch_error": f"HTTP {e.code}"}}
    except Exception as e:  # noqa: BLE001
        return {str(appid): {"success": False, "_fetch_error": f"{type(e).__name__}: {e}"}}
    if status == 429:
        return {str(appid): {"success": False, "_fetch_error": "HTTP 429 rate-limited"}}
    if not body:
        return {str(appid): {"success": False, "_fetch_error": "empty response body"}}
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {str(appid): {"success": False, "_fetch_error": "invalid JSON"}}
    return data


def get_appdetails(
    appid: int,
    cache_dir: Path,
    sleep_s: float,
    refresh: bool,
    stats: dict,
) -> tuple[dict | None, bool]:
    """Returns (data_for_appid_or_None, was_network_fetch)."""
    cp = cache_path(cache_dir, appid)
    if cp.exists() and not refresh:
        try:
            cached = json.loads(cp.read_text(encoding="utf-8"))
            entry = cached.get(str(appid))
            if entry is not None:
                stats["cache_hits"] += 1
                return entry, False
        except (json.JSONDecodeError, OSError):
            pass  # fall through and refetch

    backoff = 5.0
    for attempt in range(4):
        raw = fetch_appdetails(appid)
        entry = raw.get(str(appid))
        err = (entry or {}).get("_fetch_error", "")
        if entry is not None and "429" not in err and "empty response" not in err:
            cp.write_text(json.dumps(raw), encoding="utf-8")
            stats["network_fetches"] += 1
            return entry, True
        # back off and retry
        stats["retries"] += 1
        time.sleep(backoff)
        backoff = min(backoff * 2, 40)
    stats["hard_failures"] += 1
    return None, True


# --------------------------------------------------------------------------
# VR-flag derivation
# --------------------------------------------------------------------------


def derive_vr_flags(categories: list[dict]) -> dict:
    descs = {c.get("description", "") for c in categories}
    return {
        "vr_only": bool(descs & VR_ONLY_DESCRIPTIONS),
        "vr_supported": bool(descs & VR_SUPPORTED_DESCRIPTIONS),
        "tracked_controller_support": bool(descs & TRACKED_CONTROLLER_DESCRIPTIONS),
        "full_controller_support": bool(descs & FULL_CONTROLLER_DESCRIPTIONS),
        "partial_controller_support": bool(descs & PARTIAL_CONTROLLER_DESCRIPTIONS),
    }


def is_vr_capable(vr_flags: dict) -> bool:
    return vr_flags["vr_only"] or vr_flags["vr_supported"] or vr_flags["tracked_controller_support"]


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def build_records(
    owned: list[dict],
    installed: dict[int, str],
    docs23: dict[int, dict],
    cache_dir: Path,
    sleep_s: float,
    time_budget_s: float,
    limit: int | None,
    refresh: bool,
) -> tuple[list[dict], dict]:
    start = time.time()
    stats = {
        "cache_hits": 0,
        "network_fetches": 0,
        "retries": 0,
        "hard_failures": 0,
        "not_fetched_time_budget": 0,
    }
    records = []
    owned_by_id = {g["appid"]: g for g in owned}
    all_ids = sorted(set(owned_by_id) | set(installed) | set(docs23))
    if limit:
        all_ids = all_ids[:limit]

    for idx, appid in enumerate(all_ids):
        elapsed = time.time() - start
        timed_out = elapsed > time_budget_s
        cp = cache_path(cache_dir, appid)
        already_cached = cp.exists() and not refresh

        if timed_out and not already_cached:
            stats["not_fetched_time_budget"] += 1
            records.append(
                make_record(
                    appid, owned_by_id.get(appid), installed.get(appid),
                    docs23.get(appid), None, fetch_status="not_fetched_time_budget",
                )
            )
            continue

        entry, was_network = get_appdetails(appid, cache_dir, sleep_s, refresh, stats)
        if entry is None:
            fetch_status = "error"
        elif entry.get("success"):
            fetch_status = "ok"
        else:
            fetch_status = "not_found_or_unavailable"
        records.append(
            make_record(
                appid, owned_by_id.get(appid), installed.get(appid),
                docs23.get(appid), entry, fetch_status=fetch_status,
            )
        )
        if was_network:
            time.sleep(sleep_s)
        if (idx + 1) % 25 == 0:
            print(
                f"  [{idx + 1}/{len(all_ids)}] appid={appid} status={fetch_status} "
                f"elapsed={elapsed:.0f}s cache_hits={stats['cache_hits']} "
                f"net={stats['network_fetches']}",
                file=sys.stderr,
            )
    return records, stats


def make_record(appid, owned_info, installed_name, docs23_entry, api_entry, fetch_status):
    data = (api_entry or {}).get("data") if api_entry else None
    categories = (data or {}).get("categories") or []
    genres = (data or {}).get("genres") or []
    platforms = (data or {}).get("platforms") or {}
    vr_flags = derive_vr_flags(categories) if data else {
        "vr_only": False, "vr_supported": False, "tracked_controller_support": False,
        "full_controller_support": False, "partial_controller_support": False,
    }
    name = None
    if data and data.get("name"):
        name = data["name"]
    elif owned_info and owned_info.get("name"):
        name = owned_info["name"]
    elif installed_name:
        name = installed_name
    elif docs23_entry:
        name = docs23_entry["title"]

    return {
        "appid": appid,
        "name": name,
        "fetch_status": fetch_status,
        "type": (data or {}).get("type"),
        "is_free": (data or {}).get("is_free"),
        "release_date": (data or {}).get("release_date", {}).get("date") if data else None,
        "coming_soon": (data or {}).get("release_date", {}).get("coming_soon") if data else None,
        "developers": (data or {}).get("developers") or [],
        "publishers": (data or {}).get("publishers") or [],
        "genres": [g.get("description") for g in genres],
        "platforms": platforms,
        "metacritic_score": ((data or {}).get("metacritic") or {}).get("score"),
        "categories_raw": categories,
        "vr_flags": vr_flags,
        "vr_capable": is_vr_capable(vr_flags),
        "owned": owned_info is not None,
        "hours_on_record": (owned_info or {}).get("hours_on_record"),
        "installed": installed_name is not None,
        "docs23": docs23_entry,
    }


def steamdb_link(appid: int) -> str:
    return f"[{appid}](https://steamdb.info/app/{appid}/)"


def release_year(release_date: str | None) -> str:
    if not release_date:
        return "?"
    m = re.search(r"(\d{4})", release_date)
    return m.group(1) if m else "?"


def vr_flags_str(vr_flags: dict) -> str:
    parts = []
    if vr_flags["vr_only"]:
        parts.append("VR Only")
    if vr_flags["vr_supported"]:
        parts.append("VR Supported")
    if vr_flags["tracked_controller_support"]:
        parts.append("Tracked Controller")
    return ", ".join(parts) if parts else "-"


def write_outputs(records: list[dict], stats: dict, owned_route: str, owned_count: int):
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(
        json.dumps(
            {
                "generated_by": "scripts/steam-library-vr-map.py",
                "owned_list_source": owned_route,
                "owned_count": owned_count,
                "fetch_stats": stats,
                "apps": records,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    total = len(records)
    fetched_ok = [r for r in records if r["fetch_status"] == "ok"]
    vr_capable = [r for r in records if r["vr_capable"]]
    vr_only = [r for r in records if r["vr_flags"]["vr_only"]]
    vr_supported = [r for r in records if r["vr_flags"]["vr_supported"] and not r["vr_flags"]["vr_only"]]
    tracked_only = [
        r for r in records
        if r["vr_flags"]["tracked_controller_support"]
        and not r["vr_flags"]["vr_only"] and not r["vr_flags"]["vr_supported"]
    ]
    installed = [r for r in records if r["installed"]]
    in_docs23 = [r for r in records if r["docs23"]]
    not_fetched = [r for r in records if r["fetch_status"] != "ok"]

    def sort_key(r):
        return (0 if r["vr_flags"]["vr_only"] else 1, (r["name"] or "").lower())

    vr_table_rows = sorted(vr_capable, key=sort_key)

    mismatches = [
        r for r in records
        if r["docs23"] and not r["vr_capable"]
    ]

    lines = []
    lines.append("# Steam library VR-capability map")
    lines.append("")
    lines.append(
        "Generated by `scripts/steam-library-vr-map.py` (regenerate with "
        "`python3 scripts/steam-library-vr-map.py`). Re-running is safe and "
        "cheap: Store API responses are cached to disk, so only new/missing "
        "appids trigger network requests. Does not touch Steam, Monado, or "
        "any Steam config file -- read-only against the local Steam install "
        "and the public Store API."
    )
    lines.append("")
    lines.append(f"Snapshot date: {time.strftime('%Y-%m-%d')}.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Owned-list source: **{owned_route}**")
    lines.append(f"- Total apps in this map (owned ∪ installed ∪ docs/23-referenced): **{total}**")
    lines.append(f"- Owned (from the source above): **{owned_count}**")
    lines.append(f"- Store API detail fetched successfully: **{len(fetched_ok)}**")
    lines.append(f"- Not fetched / fetch failed: **{len(not_fetched)}**")
    lines.append(f"- VR-capable (any of VR Only / VR Supported / Tracked Controller Support): **{len(vr_capable)}**")
    lines.append(f"  - VR Only: **{len(vr_only)}**")
    lines.append(f"  - VR Supported (not VR Only): **{len(vr_supported)}**")
    lines.append(f"  - Tracked Controller Support only (neither VR flag set): **{len(tracked_only)}**")
    lines.append(f"- Currently installed (`appmanifest_*.acf`, live check): **{len(installed)}**")
    lines.append(f"- Already has a verdict row in `docs/23-game-compatibility.md`: **{len(in_docs23)}**")
    lines.append("")
    lines.append(
        "Category IDs returned by the Store API for this catalog snapshot do "
        "**not** match the ids named in some older internal notes (e.g. this "
        "snapshot uses id 54 for the description `\"VR Only\"`, not 403). This "
        "script matches on the literal `description` string the API returns, "
        "not on the id, and keeps the raw `categories` list per app in the "
        "JSON for anyone who wants to re-derive it differently."
    )
    lines.append("")

    lines.append("## VR-capable titles (any of VR Only / VR Supported / Tracked Controller Support)")
    lines.append("")
    lines.append("Sorted: VR Only first, then alphabetically.")
    lines.append("")
    lines.append("| Title | AppID | VR flags | Year | Linux native? | Installed? | docs/23 verdict | Developer |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in vr_table_rows:
        name = r["name"] or "?"
        appid_link = steamdb_link(r["appid"])
        flags = vr_flags_str(r["vr_flags"])
        year = release_year(r["release_date"])
        linux = "yes" if r["platforms"].get("linux") else "-"
        inst = "yes" if r["installed"] else "-"
        if r["docs23"]:
            verdict = f"{r['docs23']['mark']} — {r['docs23']['notes']}"
        else:
            verdict = "-"
        dev = ", ".join(r["developers"]) if r["developers"] else "-"
        # keep table cells single-line
        verdict = verdict.replace("|", "/").replace("\n", " ")
        name = name.replace("|", "/")
        lines.append(f"| {name} | {appid_link} | {flags} | {year} | {linux} | {inst} | {verdict} | {dev} |")
    lines.append("")

    lines.append("## In docs/23 but NOT flagged VR-capable by Steam's own catalog (possible mislabel or delisted flag)")
    lines.append("")
    if mismatches:
        lines.append("| Title | AppID | fetch_status | type | Notes from docs/23 |")
        lines.append("|---|---|---|---|---|")
        for r in sorted(mismatches, key=lambda x: (x["name"] or "").lower()):
            appid_link = steamdb_link(r["appid"])
            name = (r["name"] or "?").replace("|", "/")
            notes = r["docs23"]["notes"].replace("|", "/") if r["docs23"] else ""
            lines.append(f"| {name} | {appid_link} | {r['fetch_status']} | {r['type']} | {notes} |")
    else:
        lines.append("None -- every title with a docs/23 verdict is flagged VR-capable by Steam.")
    lines.append("")

    lines.append("## Fetch failures / not fetched")
    lines.append("")
    if not_fetched:
        lines.append("| AppID | Name | fetch_status |")
        lines.append("|---|---|---|")
        for r in sorted(not_fetched, key=lambda x: x["appid"]):
            name = (r["name"] or "?").replace("|", "/")
            lines.append(f"| {r['appid']} | {name} | {r['fetch_status']} |")
    else:
        lines.append("None -- every app in this map got a Store API response.")
    lines.append("")

    lines.append("## Fetch stats (this run)")
    lines.append("")
    for k, v in stats.items():
        lines.append(f"- {k}: {v}")
    lines.append("")

    MD_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    ap.add_argument("--time-budget", type=float, default=25 * 60, help="seconds")
    ap.add_argument("--sleep", type=float, default=1.6, help="seconds between network requests")
    ap.add_argument("--limit", type=int, default=None, help="only process first N appids (debug)")
    ap.add_argument("--refresh", action="store_true", help="ignore cache, refetch everything")
    args = ap.parse_args()

    args.cache_dir.mkdir(parents=True, exist_ok=True)

    owned_result = try_profile_xml()
    owned_route = None
    if owned_result:
        owned, owned_route = owned_result
        owned_route = f"Steam Community profile XML ({owned_route})"
    else:
        owned_result = try_web_api()
        if owned_result:
            owned, owned_route = owned_result
        else:
            ids = parse_localconfig_appids(LOCALCONFIG_PATH)
            owned = [{"appid": i, "name": "", "hours_on_record": None} for i in ids]
            owned_route = (
                f"FALLBACK: local localconfig.vdf 'apps' block ({LOCALCONFIG_PATH}) "
                "-- profile XML redirected to login (game-details privacy not "
                "public) and no STEAM_API_KEY was available"
            )

    print(f"Owned-list route: {owned_route}", file=sys.stderr)
    print(f"Owned count: {len(owned)}", file=sys.stderr)

    installed = parse_installed_manifests(STEAMAPPS_DIR)
    docs23 = parse_docs23(DOCS23_PATH)

    records, stats = build_records(
        owned, installed, docs23, args.cache_dir, args.sleep,
        args.time_budget, args.limit, args.refresh,
    )

    write_outputs(records, stats, owned_route, len(owned))
    print(f"Wrote {JSON_OUT} and {MD_OUT}", file=sys.stderr)
    print(json.dumps(stats), file=sys.stderr)


if __name__ == "__main__":
    main()
