# 66 — Steam automation and VR-store survey (for the ARkade compatibility sweep)

Research-only pass, 2026-08-21. No hardware touched, no Steam/Monado/game process run, no
Steam config modified. Goal: scope what can be **automated** in testing all ~109 owned
VR-capable titles (`docs/steam-library-vr-map.md`), across Steam and other stores, for the
"ARkade" commercial-showcase project (`docs/23-game-compatibility.md`).

**How to read this doc**: every claim is tagged **[verified]** (fetched/read live during
this research pass), **[verified-locally]** (confirmed by reading a real file on this
machine), **[from docs]** (found in official/authoritative or well-sourced community
documentation, not independently re-verified), or **[unverified]** (plausible but not
confirmed — treat as a lead, not a fact).

---

## 0. What was actually verified live in this pass

Using the existing `STEAM_API_KEY` (read from `~/.config/reverb-g2/steam.env`, never
printed — see `docs/steam-library-vr-map.md` for the same convention) and
`steamid=76561197987338446`:

| Endpoint | Result |
|---|---|
| `IPlayerService/GetOwnedGames/v1` | **[verified]** Per-game fields present: `appid`, `name`, `playtime_2weeks`, `playtime_forever`, `img_icon_url`, `has_community_visible_stats`, `playtime_windows_forever`, `playtime_mac_forever`, `playtime_linux_forever`, `playtime_deck_forever`, `rtime_last_played` (unix ts), `playtime_disconnected`. `appids_filter[N]=` did **not** reliably restrict results in our test (3 requested appids → 1 returned) — untrusted until the correct filter syntax is confirmed (see §1.2). |
| `IPlayerService/GetRecentlyPlayedGames/v1` | **[verified]** Same per-game shape minus `rtime_last_played`, plus `total_count`. Returned 69 total recently-played apps, first page showed real data (Aircar, SteamVR, Vampyr, "Oasis Driver for Windows Mixed Reality", fpsVR, SUPERHOT VR). |
| `ISteamUserStats/GetPlayerAchievements/v0001` | **[verified]** Works when the app has an achievement schema (SUPERHOT VR: real per-achievement `achieved`/`unlocktime`). Fails cleanly with `{"error":"Requested app has no stats","success":false}` when it doesn't (Aircar — confirmed on this account). |
| `store.steampowered.com/appreviews/{appid}?json=1` | **[verified]** No key required. Returns `query_summary` (`review_score`, `review_score_desc`, `total_positive`, `total_negative`, `num_reviews`). Aircar currently has 0 reviews. |
| `www.protondb.com/api/v1/reports/summaries/{appid}.json` | **[verified]** No key/auth required. Returns `bestReportedTier`, `confidence`, `score`, `tier`, `total`, `trendingTier`. Half-Life: Alyx → `tier: gold`, `total: 153` reports. Aircar → `tier: platinum`, `total: 8` reports, `confidence: moderate`. |

Everything else below layers on top of this with either fresh live checks (marked) or
research from the three parallel research passes this task ran.

---

## 0a. Local findings already on file in this repo — don't re-discover these

Two load-bearing facts already established and documented in `docs/23-game-compatibility.md`,
worth restating here because they change the automation design in §5:

- **[verified-locally] Editing `userdata/<id>/config/localconfig.vdf`'s per-app
  `LaunchOptions` directly on disk while Steam is running does nothing and is actively
  dangerous.** The running client only reads it at startup; a hand-edit gets silently
  overwritten when Steam next exits. Confirmed by the project by reading `/proc/<pid>/environ`
  on the whole launch chain (`docs/23`, "Trap: Steam launch options edited on disk don't
  exist"). This matches what the research below found from Valve/community sources
  independently (§2, item 4) — always set Launch Options through the Steam UI, or use the
  trick below.
- **[verified-locally] There is a documented, live-tested alternative that skips per-title
  Launch Options entirely: export the three required env vars (`XR_RUNTIME_JSON`,
  `IPC_IGNORE_VERSION`, `PRESSURE_VESSEL_FILESYSTEMS_RW`) in the shell *before starting the
  `steam` client itself*.** Verified by this project by reading `/proc/<pid>/environ` on
  every process in the launch chain (`reaper` → `pressure-vessel`/`srt-bwrap` → `pv-adverb`
  → Proton → the game's Windows `.exe` under Wine) for a title that had never been
  configured before (VersaillesVR) — all three vars were inherited with zero manual Steam
  UI steps, and the game reached a real `FOCUSED` OpenXR session on the first try
  (`docs/23`, "Update 2026-08-09"). **This is the actual automation lever**: a test harness
  that launches `steam` itself (rather than expecting per-title Launch Options to already
  be set) gets every current and future title wired for free, with no VDF editing at all.
  Caveat found the same day and still open: Steam silently re-adds `.../SteamVR` to the
  front of `openvrpaths.vrpath`'s `runtime` array on every Steam startup even with xrizer
  configured — only edit that file after Steam is already running and stable, and check
  the per-title prefix-local copy at
  `compatdata/<appid>/pfx/drive_c/users/steamuser/AppData/Local/openvr/openvrpaths.vrpath`
  if a fresh runtime change doesn't seem to take for one specific title.

---

## 1. Steam Web API + Steamworks Web API

### 1.1 Table per API family

| Family / endpoint | Auth | What it gives us | VR-relevant? | Status |
|---|---|---|---|---|
| `IPlayerService/GetOwnedGames/v1` | key | Full library + `playtime_windows/mac/linux/deck_forever`, `rtime_last_played`, `playtime_2weeks` | Yes — `playtime_linux_forever` is a real, cheap "played on Linux" signal per title | **[verified]** (see §0). `appids_filter[N]=` did not reliably filter — needs the correct syntax confirmed (possibly `input_json=`, not confirmed either way) before scripting against it. |
| `IPlayerService/GetRecentlyPlayedGames/v1` | key | Same shape, sorted by recency, `total_count` | Same as above, narrower window | **[verified]** |
| `ISteamUserStats/GetSchemaForGame/v2` | key | Per-game achievement/stat definitions: `achievements[]` (`name`, `displayName`, `hidden`, `description`, icon URLs), `stats[]` | Usable as a coarse "reached real gameplay" proxy when combined with `GetPlayerAchievements` — cross-reference low-ordinal/tutorial-sounding, non-hidden achievements against `achieved:1` | **[from docs]** — no field explicitly flags "this is the tutorial achievement"; the heuristic is inference, not a documented feature. |
| `ISteamUserStats/GetPlayerAchievements/v0001` | key | Per-achievement `achieved` + `unlocktime` | Same proxy as above | **[verified]** (see §0) — cleanly fails with `"Requested app has no stats"` for titles with no schema (confirmed on Aircar, this account). |
| `ISteamApps/GetAppList` (legacy) vs `IStoreService/GetAppList/v1` | keyless vs key | Full appid↔name catalog, ~108k (legacy, all types) vs ~49k games-only (IStoreService, `max_results` cap 50,000, `include_games/dlc/software/videos/hardware` filters) | No VR flags in either | **[from docs]** legacy is explicitly called out as deprecated/non-scaling by Valve; IStoreService is the recommended replacement. |
| `store.steampowered.com/api/appdetails` | keyless | `categories[]` (VR Only/VR Supported/Tracked Controller Support by **description string**, not stable numeric id — matches this project's own prior finding), `platforms.linux` (plain bool), genres, release date | **The** VR-capability source already powering `steam-library-vr-map.py` | **[verified]** live against SUPERHOT VR (617830): categories included "Tracked Controller Support" + "VR Supported"; `platforms.linux` was `false` for this title even though it runs here via Proton — confirms Linux-native flag is separate from "runs on Linux via Proton". No `controller_support` field was present despite the VR categories — don't rely on it. |
| `ISteamNews/GetNewsForApp` | keyless | Patch-note text, `title/contents/date/feedname/tags` | Weak — no structured "compatibility fixed" field, would need text-matching | **[verified]** live (appid 440, keyless) — real fields confirmed, but low value for this project without NLP-grade text matching. |
| SteamSpy (`steamspy.com/api.php`) | keyless | Owner-count band, tag weights, `positive/negative` | Weak/none for VR specifically | **[verified]** live (Beat Saber, 620980) responds with a real owner band and tags, **but** `average_forever/median_forever/average_2weeks/median_2weeks` all returned `0` — a known, ongoing playtime-field degradation per a tracked GitHub issue (woctezuma/steamspypi #10), not full API death. Don't trust its playtime numbers. |
| SteamDB | — | Proton/Deck compatibility badges, sale history | No public API — scraping is against their stated policy | **[from docs]** — no official API; their Deck/Proton badges are believed (not confirmed by SteamDB directly) to source substantially from ProtonDB + Valve's own Deck-Verified data rather than independent crowdsourcing. |
| ProtonDB summaries (`protondb.com/api/v1/reports/summaries/{appid}.json`) | keyless | `tier`, `bestReportedTier`, `trendingTier`, `confidence`, `score`, `total` | Pre-test expectation, NOT VR-aware — a `platinum` overall tier says nothing about whether VR specifically works, only that Proton ran the binary | **[verified]** (see §0). |
| ProtonDB individual reports | keyless (via unofficial mirror) | Per-report `id, timestamp, rating, notes, os, gpuDriver, specs, protonVersion` — i.e. the actual Proton version a reporter used | Can suggest a Proton version to try per title before a manual pass | **[from docs]** — via `protondb.max-p.me` (built from `github.com/bdefore/protondb-data`, itself synced from ProtonDB's real export) and a second wrapper `github.com/Trsnaqe/protondb-community-api`. Not independently fetched live in this pass; treat the mirror's freshness as unconfirmed. |
| Steam Input / VR bindings | — | Per-app controller config | Lives in local VDF (`controller_config`), NOT exposed via any Web API endpoint found | **[from docs / by absence]** |
| Frame-timing / FPS telemetry | — | — | **Confirmed absent.** No Web API surface exposes runtime performance data, per this pass's dedicated search. | **[verified by absence]** — real alternatives: this project's own `frame-pacing.sh` (`U_PACING_APP_LOG=debug` "Delivered frame" count, already the ground truth per `docs/23`'s T244 resolution), MangoHud (CSV logging via `MANGOHUD_CONFIG=output_folder=...`, column semantics explicitly undocumented upstream — flightlessmango/MangoHud#287), Gamescope (frame-pacing compositor, no logging API). Windows' PresentMon has no structured Linux equivalent. |

### 1.2 Notes

- The `appids_filter[N]=` query-array syntax for `GetOwnedGames` should be re-tested with
  `input_json=` (the modern Steamworks Web API convention for structured params) before
  being relied on in a script — this pass could not confirm the correct syntax, only that
  the naive form under-returned.
- `GetSchemaForGame` + `GetPlayerAchievements` as a "reached gameplay" proxy is a real,
  usable idea but only covers titles with `has_community_visible_stats: true` — many VR
  titles in this library (Aircar confirmed) have none at all, so this signal is partial
  coverage, not universal, and should be one input among several in §5's data model, never
  the sole gate.
- `appreviews` (§0) is near-useless for this specific library — Aircar (this rig's
  reference title, 764 minutes played) has **zero** Steam reviews, so review counts will be
  thin-to-empty for most of this niche VR catalog; don't design anything load-bearing on it.

---

## 2. Local Steam client automation on Linux

Local install found this pass at `~/.steam/debian-installation` (symlinked from
`~/.steam/root`/`~/.steam/steam`) — **[verified-locally]** `~/.local/share/Steam` does not
exist on this box, everything hangs off that one path. Account-identifying strings
(accountid, exact appid-to-option mapping) are redacted below per this project's own
public-repo convention (`backup-steam-config.sh`'s header).

| Mechanism | What it does | Safe to automate? | Status |
|---|---|---|---|
| `steam -applaunch <appid>` | Launches a title. **[verified-locally]** already used by this project's own `scripts/triage-sweep.sh:68` and `scripts/vr-launcher.py:327`. Returns control to the shell quickly — does **not** block until the game exits. No documented exit-code semantics for pass/fail. | Yes, for launching | **[verified-locally]** in-repo prior art + **[from docs]** non-blocking behavior (Steam Discussions / steam-for-linux issue threads — Valve's own Command-line-options wiki page 403'd on fetch, so cited via search index, not read directly). |
| `steam steam://rungameid/<id>` | Same launch effect via URL scheme. **[verified-locally]** already used in `docs/23-game-compatibility.md`'s own troubleshooting notes (the overlapping-launch trap). Other useful `steam://` routes: `install/<id>`, `uninstall/<id>` (community-observed — Valve's doc snippet actually surfaces `removeaddon/<name>` for workshop content, not the same thing), `validate/<id>`, `open/console`, `open/games`, `forceinputappid/<id>`/`0` (locks/frees Steam Input's foreground-app tracking — meant for controller-config debugging). | Yes | **[from docs]** — Valve Dev Wiki "Steam browser protocol" page + Steamworks partner docs on Steam Input, both fetch-blocked (403) this pass, cited via search snippets only. |
| `steamcmd` | Headless install/update/validate (`+login`, `+app_update`, `+quit`). `+login anonymous` only works for free/server content — every owned VR title needs a real `+login <user> <pass> [guard_code]`. First run with 2FA is interactive; caches a token for later automated runs. **It is a separate client identity from desktop Steam** — no documented way to reuse an already-authenticated desktop session's token. | Partial — real-account login friction makes it a poor fit for a fully unattended fleet-test loop; better suited to one-time install/update, not repeated auth | **[from docs]** (Valve Dev Wiki 403'd, cited via search; `Weilbyte/steamcmd-2fa` exists as a community 2FA helper). |
| `userdata/<accountid>/config/localconfig.vdf` → per-app `LaunchOptions` | **[verified-locally]** Real structure confirmed on this machine: `"apps" { "<appid>" { "LaunchOptions" "XR_RUNTIME_JSON=... IPC_IGNORE_VERSION=1 PRESSURE_VESSEL_FILESYSTEMS_RW=... %command%" "LastPlayed" "..." } }`. This project already has the 3-var recipe written for roughly a dozen-plus appids here. | **No — confirmed unsafe to hand-edit live**, both by this project's own prior incident (`docs/23`'s "trap": edits are silently overwritten when Steam next exits, and don't take effect while it's running) and by **[from docs]** community corroboration (Steam Discussions, a "declare your Steam launch options" blog) — not a Valve-official statement, but consistent and widely repeated. **Real automation lever instead: export the 3 vars into the shell before starting `steam` itself** — already verified working project-wide, see §0a. |
| `config/config.vdf` → `CompatToolMapping` | **[verified-locally]** Real structure confirmed: `"CompatToolMapping" { "<appid>" { "name" "proton_experimental" "config" "" "priority" "250" } }` — only one appid mapped on this box currently. `name` is the tool's short id, `priority` a sort weight. Separate file from `localconfig.vdf`. | **Unverified whether safer than LaunchOptions** — no source found claiming so; treat under the same Steam-must-be-closed caution until proven otherwise | **[verified-locally]** structure, **[from docs]** general caution (`sonic2kk/steamtinkerlaunch` wiki, which itself edits this file with Steam closed as standard practice). |
| `steamapps/appmanifest_<id>.acf` | **[verified-locally]** Sample read (SteamVR, 250820): fields present are `StateFlags`, `installdir`, `LastUpdated`, `SizeOnDisk`, `buildid`, `BytesToDownload/Downloaded`. `StateFlags "4"` = fully installed is well-corroborated **[from docs]** (multiple community forum threads) but **Valve has never published an authoritative bitmask table** — no canonical `EAppState` enum could be located even in SteamKit's own `enums.steamd` on GitHub. Treat any fuller bitmask table (e.g. `6`/`1026`/`1042` as various update-required states) as **[unverified inference]** from scattered reports, not a citable source. | Read-only use (install-state detection) is safe | Good "is it installed and idle" signal for §5's pipeline; not reliable beyond that. |
| `config/libraryfolders.vdf` | **[verified-locally]** One `"0"` block per library: `path`, `label`, `contentid`, `totalsize`, an `apps` map of `appid→size`. Only one library configured on this box. | Read-only, safe | Trivial to parse for multi-library setups. |
| `steamapps/compatdata/<appid>/pfx` | **[verified-locally]** Real Proton prefix structure present (`system.reg`, `user.reg`, `drive_c/...`) for at least one appid. **No `proton_log` file found in any checked prefix** — `PROTON_LOG=1` has never actually been exercised in this project despite `vr-launcher.py` wiring `PROTON_LOG=1`/`PROTON_LOG_DIR` into the launch env (worth confirming it's landing where expected on the next real run). | Read-only, safe | Per Proton's own env var doc, when active it writes `steamapps/compatdata/<appid>/proton_log`. |
| `steamwebhelper` / CEF remote debug | CEF remote debugging exists (`127.0.0.1:8080` locally, e.g. via SteamOS/Bazzite's "Allow Remote CEF Debugging") — but it exposes the Steam **UI's own** web views (store/community pages rendered inside the client), not a documented API for "is game X's session running." | No usable signal found | **[from docs, honest negative]** (Deckbrew CEF-debugging wiki, a Bazzite GitHub issue) — nothing here helps detect a running game session. |
| Detecting "reached main loop" from outside | No Steam-side API, D-Bus service, or CEF endpoint exposes per-title session state — confirmed by dedicated search, nothing found. | — | **[verified by absence]** — the realistic signal set stays exactly what this project already uses: Wine/Proton child-process presence in the process tree + Monado's own log (`client_connected`/`BEGIN_SESSION`). `appmanifest_<id>.acf`'s `StateFlags` only ever tells you install/update state, never "running." |

## 3. Trying newer/other Protons

| Tool / mechanism | What it is | Status this pass |
|---|---|---|
| `protonup-rs` (`auyer/Protonup-rs`) | Rust CLI (+lib, WIP GUI) that downloads Proton-GE/Luxtorpeda/Boxtron releases into `compatibilitytools.d`. Scriptable flags: `--tool`, `--version`, `--for <path>`, `-q` quick-download. | **[from docs]**. `compatibilitytools.d` **does not exist yet on this box** — only Valve's own official builds are present under `steamapps/common/` (`Proton - Experimental`, `Proton Hotfix`, both **[verified-locally]**). |
| `compatibilitytools.d` layout | Expected: one subdirectory per custom tool version, each containing its own `proton` script plus a `compatibilitytool.vdf`/`toolmanifest.vdf` for Steam to recognize it. | **[from docs]**, not locally confirmed since the directory is absent here. |
| `CompatToolMapping` (per-app selection) | See §2 — the actual switch once a custom tool is installed. | **[verified-locally]** structure, mapping mechanism only. |
| `STEAM_COMPAT_DATA_PATH` / `STEAM_COMPAT_CLIENT_INSTALL_PATH` + running Proton standalone | `STEAM_COMPAT_DATA_PATH=<compatdata dir> STEAM_COMPAT_CLIENT_INSTALL_PATH=<steam root> <ProtonDir>/proton run <exe>` runs a title fully outside the Steam client. Multiple independent write-ups agree on the pattern; no single canonical Valve page was fetchable this pass (403s throughout) — treat as strong community consensus, not Valve-primary. | **[from docs]** |
| `umu-launcher` (`Open-Wine-Components/umu-launcher`, `umu-run`) | Repackages Steam Linux Runtime/Proton tooling for use **outside Steam** — consumed by Heroic/Lutris/Bottles/Rare to run GOG/Epic/itch/standalone Windows builds through Proton + `protonfixes`. **Directly relevant to §4's non-Steam-store titles**: same container model, same env-var injection point — `XR_RUNTIME_JSON`/`IPC_IGNORE_VERSION`/`PRESSURE_VESSEL_FILESYSTEMS_RW` should be settable the same way as Steam Launch Options, unverified but structurally consistent. | **[from docs]**, not tested this pass. |
| wineopenxr / `wineopenvr` | **This project's own path is native-Linux Monado+xrizer — wineopenxr is NOT needed for it.** It matters for a different, adjacent case: a Proton-run Windows binary escaping its Wine prefix to reach the host's real OpenXR runtime, which is exactly the mechanism `XR_RUNTIME_JSON` in this project's Launch Options already exploits (Proton's built-in "point Wine's OpenXR loader at a host manifest" trick). Separately, GE-Proton (not stock Proton) carries `wineopenvr` patches specifically so **non-Steam** PCVR titles launched via Heroic/Lutris can find a runtime — relevant to the umu path above, irrelevant to Steam-launched titles that already get xrizer for free. | **[from docs]** (`CachyOS/proton-cachyos` issue #114) |
| Confirmed VR-relevant Proton/GE-Proton changelog activity | Proton Experimental added OpenXR 1.1.36 support and a Beat Saber/NVIDIA fix; GE-Proton added `wineopenvr` for non-Steam titles (named examples: Overload, Project Wingman, Star Citizen). No VR-specific DXVK-pinning note found (DXVK-per-release pinning is standard GE-Proton practice generally, nothing VR-specific). | **[from docs]** (GamingOnLinux article, `GloriousEggroll/proton-ge-custom` release notes) |
| `PROTON_USE_WINED3D` | Forces D3D→OpenGL translation instead of DXVK (D3D→Vulkan) — no VR-specific rationale found for using it here; flagged only because the task asked, no evidence it helps or is needed on this stack. | **[unverified / likely not applicable]** |

---

## 4. Other stores with PC-VR content

### 4.1 Cross-cutting finding — read this before the table

**[from docs]** The real gate for ANY non-Steam Windows VR binary is **OpenVR-under-Wine**.
GE-Proton (not stock Valve Proton) carries `wineopenvr` patches, and a title's
`openvr_api.dll` can be swapped for OpenComposite or xrizer itself to forward OpenVR calls
to the OpenXR runtime (Monado) without SteamVR installed — this works identically
regardless of which launcher started the binary (Heroic, `legendary`, `lgogdownloader`, or
Steam), so it's launcher-agnostic. Sources: GE-Proton/OpenComposite docs, a CachyOS
`proton-cachyos` GitHub issue on `wineopenvr` (github.com/CachyOS/proton-cachyos/issues/114),
xrizer's own README noting it is "currently immature" versus OpenComposite's greater
maturity (github.com/Supreeeme/xrizer), and the Linux VR Adventures wiki page "VR without
Steam" (lvra.gitlab.io/docs/games/vr-no-steam/). **Not independently validated on this
rig** — the first real step for stores 1, 2, and 5 below should be proving this path once,
on one simple non-Steam title, before investing further per-store effort.

### 4.2 Table per store

| Store | Catalog / examples | DRM-free & Linux-runnable? | API / CLI | Feasible today | First step |
|---|---|---|---|---|---|
| **GOG** | Small, uncurated VR list (No Man's Sky, Zed, Mind: Path to Thalamus, P.O.L.L.E.N, The Solus Project — **[from docs]**, no authoritative catalog count found) | DRM-free installers, but still Windows OpenVR/OpenXR binaries → needs the OpenVR-under-Wine path above | `lgogdownloader` **[from docs, verified-exists]** (unofficial, actively maintained, github.com/Sude-/lgogdownloader, auth via email/password, no Windows client needed). Official GOG Galaxy API is **Windows/macOS client-only** per docs.gog.com/galaxyapi **[from docs]**. Heroic uses its own `gogdl` downloader, not the Galaxy API **[from docs]**. | **Partial** | Install `lgogdownloader`, pull one DRM-free VR title (e.g. Zed), test via GE-Proton + OpenComposite/xrizer DLL swap. |
| **Epic Games Store** | EGS-exclusive VR titles are genuinely rare — only Tetris Effect turned up by name **[from docs, low confidence]**, no authoritative "VR exclusives" list exists | Same OpenVR-under-Wine caveat as GOG | `legendary` **[verified-exists, from docs behavior]** — open-source, uses Epic's real client API, actively maintained (v0.21.0 shipped 2026-08-04, moved to a community org after a maintenance gap — gamingonlinux.com/2026/04). Heroic wraps `legendary` directly. | **Partial** | `legendary` login + list library, cross-check against Steam ownership before chasing anything EGS-exclusive. |
| **itch.io** | Multiple overlapping tags (`tag-virtual-reality`, `tag-vr-game`, `tag-oculus-quest`), skews heavily toward small/free/jam titles, most standalone-Quest-first rather than genuine PCVR **[verified]** | Mostly small/free indie scope — be honest this is a minor source | Official API (`itch.io/docs/api/serverside.md`) exposes `profile/owned-keys` under OAuth scope `profile:owned-keys` + a download route — real programmatic ownership+download **[verified from docs, real repo]**. `butler` is **upload/dev-side only**, no player-side download function **[verified]**. | **Yes (small scope)** | Generate an API key, hit `/profile/owned-keys`, script downloads for the handful of real PCVR items. |
| **Humble Bundle** | VR content scattered inside general bundles, not curated | Bundle keys are frequently just Steam keys anyway | No official API for owned keys. Trove's 2026 status **unresolved** — moved behind the Windows-only Humble App per older forum discussion, no definitive 2026 shutdown notice found **[unverified]**. Unofficial scraping tools exist and work against a real logged-in session (`humble-bundle-keys`, `humblebundle-python` on GitHub/PyPI) **[verified-exists, functionality from-docs]**. | **Partial** | Run `humble-bundle-keys` to export a CSV, cross-reference against the Steam library (most VR titles there are Steam keys anyway). |
| **Meta/Oculus PC store (Rift titles)** | Many Rift-store titles are dual-owned on Steam | Revive (Oculus→OpenVR shim) is Windows-only, no Linux port found **[verified negative search]** | Running Revive + the target game simultaneously under Wine, on top of the still-unproven OpenVR-under-Wine path — high risk, low payoff | **No** | Check the Steam library for the same title before touching an Oculus-store copy at all — this is almost always the real path. |
| **Viveport** | Subscription-based; overlapping titles commonly exist on Steam instead | Windows 8.1/10 client only, confirmed via the official Viveport Help Center **[verified]** — no Linux compatibility layer found | — | **No** | None — check Steam for overlapping titles instead. |
| **Pico store / other headset-vendor stores** | PC content is exclusively via PICO Business/Enterprise Streaming — a WiFi/USB relay to an existing Windows+SteamVR PC, not a separate binary catalog **[verified]** | N/A | — | **No** | None — confirmed dead end, don't revisit without new information. |
| **Direct-download / standalone demos** | VRChat and Google Earth VR are both confirmed on Steam already **[verified]**; broader standalone-demo landscape has no strong centralized registry — closest is `github.com/drjenkin/VR-Demos`, a curated link-list (not an API), old/legacy-leaning, pointing to Wayback Machine for dead links **[verified-exists]** | Case-by-case, whatever the dev shipped | None found beyond that one link-list | **Partial** | Hand-check `drjenkin/VR-Demos` for anything relevant, then build our own small YAML registry for the rest — nothing better exists to adopt instead of building it. |

---

## 5. A concrete plan: "works today vs. what blocks it", per title

One page, as requested. This is project synthesis, not research — written from
`docs/23-game-compatibility.md`'s existing verdict table, `docs/steam-library-vr-map.md`'s
109-title map, `docs/32-measurement-toolkit.md`'s instrument index, and the parked
"error message database" idea (`idea_error_message_database.md`).

### 5.1 Data model

One row per (title, test-session), append-only (never overwrite — `docs/23` already lost
information once by treating verdicts as mutable; T243-night's re-tests are only useful
*because* the old rows were kept). Proposed fields, all cheap to populate from what already
exists:

| Field | Source |
|---|---|
| `appid`, `title`, `store` | `steam-library-vr-map.json` / a future multi-store registry |
| `vr_flags` (VR Only / VR Supported / Tracked Controller) | Store `appdetails` categories, already in the map |
| `installed`, `size_on_disk` | `appmanifest_<id>.acf` (§2) |
| `launch_recipe_present` (bool) | whether the 3-var recipe reached the process — check `/proc/<pid>/environ`, or trust the "export before `steam`" global fix (§0a) and mark true unless an override exists |
| `last_played_linux` (`playtime_linux_forever`, `rtime_last_played`) | `IPlayerService/GetOwnedGames` (§1) — a real, cheap signal of "was this actually played on this OS", distinct from install state |
| `achievement_progress` (bool/partial, if schema exists) | `GetPlayerAchievements` + `GetSchemaForGame` (§1) — a coarse "did the user get past the tutorial" proxy, only for titles that have any schema at all |
| `protondb_tier`, `protondb_total_reports` | protondb API (§1) — a pre-test expectation, not a verdict; note this project already knows ProtonDB tiers are Proton-general, not VR-aware, so a `platinum` title can still fail specifically in VR |
| `monado_session_reached` (bool) | grep Monado log for `client_connected` / `BEGIN_SESSION` without immediate `END_SESSION` |
| `builder_used` (`wmr` vs `legacy`/Simulated HMD) | grep `Using builder` — CLAUDE.md's known false-positive trap |
| `fps_delivered`, `late_frame_pct`, `median_lateness` | `frame-pacing.sh` / `U_PACING_APP_LOG=debug` "Delivered frame" count (docs/32, docs/23 T244 resolution) |
| `gpu_power_w`, `gpu_util_pct` | `nvidia-smi` sample during the window |
| `proton_exit_code`, `first_error_string` | Proton log (`PROTON_LOG_DIR`, already wired in `vr-launcher.py`) — feeds the parked error-message-database idea |
| `problem_category` | one of `docs/23`'s "Final problem categories" (SLAM/CPU starvation, xrizer swapchain bug, no presence detection, chaperone stub, no overlay support, GPU/CPU baseline, or "new/unclassified") — this taxonomy already exists and should be the controlled vocabulary, not free text |
| `wearer_verdict` | **always manual, see §5.3** |

### 5.2 An automated test pass, per title (what it CAN do unattended)

1. Ensure `monado-service` running fresh (kill -9 + clear `/run/user/1000/monado_comp_ipc`
   per CLAUDE.md's known startup sequence) — restart between titles, not just at session
   start, since `docs/23`'s T243-night data shows session-accumulated CPU load measurably
   changes tracking behavior (confounds a fleet sweep if not controlled for).
2. Launch via `steam steam://rungameid/<appid>` (§2) with the 3-var recipe already
   exported into the parent shell before Steam started (§0a) — no per-title Launch Options
   editing needed, so this scales to all 109 titles without touching `localconfig.vdf`.
3. Poll Monado's log for `client_connected` and `Using builder wmr` (not `legacy`) —
   timeout at some bound (60-90s, generous for the DXVK-shader-compile warm-up already
   measured to distort first-minute numbers).
4. On success: run `frame-pacing.sh` for a fixed window (30-60s) with the game window
   focused (pacing is meaningfully different unfocused — `docs/23`), sample `nvidia-smi`
   in parallel, then use `U_PACING_APP_LOG=debug`'s "Delivered frame" count as the
   ground-truth fps per the T244 resolution (Steam's own overlay counter was shown to
   diverge from real compositor delivery on at least two titles — don't trust it alone).
5. Capture Proton's log tail for the first ERROR/exception line if the session never
   reaches `client_connected`, or on any abnormal exit code — this is the raw material for
   the error-message-database idea, and should be stored per-title even on failure.
6. Kill the game process tree cleanly (bracket the process-name pattern, e.g.
   `pgrep -f "Aircar[-]Win64"` per CLAUDE.md's own `pkill`/`pgrep` traps), confirm
   `client_disconnected` in Monado's log, THEN restart Monado for the next title — never
   assume a `pgrep` process-gone check alone means the OpenXR session tore down cleanly
   (the overlapping-launch trap in `docs/23`).
7. Write one row to the data model above; move to the next title.

### 5.3 What MUST stay manual (the project's own core rule)

CLAUDE.md is explicit and this plan does not try to route around it: **"Verifying 90 Hz is
PHYSICAL. You have to look inside the headset. Any conclusion based on logs, on `xrandr`,
or on the reported framerate is invalid."** The same rule is stated project-wide, not just
for the 90Hz chapter. So the automated pass above produces a strong *pre-screen* — it can
confidently say "this title never even reaches a session" or "this title has a
`problem_category` match to an already-diagnosed bug" — but it cannot certify a title as
genuinely working. Concretely, kept manual:

- **Position correctness** — is the wearer where they should be in the world (T243-night's
  whole broken-family signature — "flying away", spawning 10-30m off — is invisible to any
  log-based check; Monado reports a happy session while the wearer is somewhere else
  entirely).
- **Hand/controller feel** — pointing direction, grab responsiveness, the
  ~95%-parked-hands gap noted on Google Earth VR was a *feel* finding, not a log finding.
- **Comfort / nausea** — the frame-pacing tool's own documented blind spot: it caught a
  13x pacing improvement while the wearer saw a brand-new ghosting artefact it could not
  measure (`docs/32`).
- **Final "works" verdict** — per CLAUDE.md's rule, a title is not "working" until a human
  wore the headset and said so, full stop. The automated pass's job is to make manual
  sessions efficient (pre-filter obvious failures, obvious `problem_category` matches, and
  titles that need a fresh look) — not to replace the wearer.

### 5.4 First concrete step

Nothing here requires new infrastructure beyond what already exists
(`frame-pacing.sh`, `vr-launcher.py`, `jack-in-wayland.sh`, Monado's log,
`steam-library-vr-map.py`). The smallest real next step is a thin orchestration script that
does steps 1-7 above for ONE already-known-working title (Aircar) end-to-end and writes one
row, to validate the harness before pointing it at all 109 — not built in this pass
(explicitly out of scope: no code changes, no Steam/game runs).

---
