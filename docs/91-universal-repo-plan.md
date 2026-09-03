# 91 — Making this repo universal: privacy, i18n, and a layered install

Goal (2026-09-03): turn this from one lab's working tree into a project a stranger can clone
and run on their own machine, without leaking this rig's identity and without assuming this
rig's layout. Three workstreams, below. An audit (partial, one pass) produced the concrete
worklists; this chapter is the durable plan. **No private values appear in this file** — the
actual identifiers live only in the gitignored `scripts/.private-patterns` and in the
maintainer's local `replace-text`/`mailmap` files, never in a tracked blob.

## 1. Privacy — stop shipping this rig's identity

The repo is already public, so everything in `origin/main` history is already exposed; this
plan both redacts HEAD and rewrites history so the exposure stops growing and can be cleaned.

**What the audit found** (categories, not values). The project's own
`scripts/check-publishable.py` only knew 5 literals; the audit added the rest, and the
checker now flags ~50 HEAD files / 161 history blobs:

- **Bluetooth addresses** — both motion controllers, the headset's own embedded radio, and a
  captured pairing link-key fragment. In `docs/03-controllers.md`, in **two notations**
  (colon-separated and space-separated hex bytes); a colon-only regex misses the second.
- **Per-unit hardware serials/UUIDs** — the headset presence-device serial (already a known
  pattern, still un-redacted in HEAD), the panel EDID serial (in every `.edid`/`.bin` and in
  the bug-report `.gz`), the active-cable hub chip serial + its Windows ContainerID GUID, the
  camera module serial, the GPU UUID and PDI, the SMBIOS system UUID, two filesystem UUIDs,
  and three **attached-monitor** EDID serials embedded in the bug-report log.
- **Network / host identity** — the rig's Ethernet MAC (a known pattern, still in HEAD), its
  live LAN IP and prior lease, the home-router gateways, the residential ISP/carrier names and
  ASN, and (with the pervasive `-03` timestamps) the country. Internal hostnames: the lab host
  and its `.internal` FQDN, the pmadminka hub host, a self-hosted Gitea name, and the
  **dual-boot Windows computer name** — the last one **UTF-16LE encoded**, invisible to a
  plain-ASCII `git grep`, so a naive text scrub skips it.
- **Accounts** — the Linux account name (pervasive), the Windows account name, and the
  maintainer's **public Steam ID64 hardcoded** in `scripts/steam-library-vr-map.py` and a doc.
- **Incidental personal leak** — a Windows directory listing of personal video-editing project
  filenames captured inside a hardware-diagnostic transcript (`windows-kit/captures/...`).
- **Patch author headers** — 31 patch files carry `From: <lab-user>@<lab-host>` in their body;
  a git mailmap rewrites commit metadata but **not** patch-file text, so these need the
  replace-text pass too.

**Two pervasive terms are deliberately NOT blocklisted**: the bare lab hostname and Linux
username appear in ~400 commits and as UI strings and `User=` unit directives. A literal
blocklist match on them would make the checker fail on nearly everything and stop being
useful. They are handled by **editorial rename** (a config value + a search-replace in docs),
not by the redaction pass.

**Remediation, in order** (the maintainer drives the history rewrite — it is destructive and
force-pushes):

1. **HEAD redaction** — replace each identifier in the current files with its placeholder
   (`<HMD-SERIAL>`, `<CTRL-LEFT-BDA>`, `<LAB-HOST>`, …). Re-run `check-publishable.py` until
   HEAD is clean. The EDID `.bin`/`.edid` files need their 4-byte serial at base-block offset
   `0x0C–0x0F` zeroed (keep ManufID/ProductID — the NVIDIA WAR patch matches on those), then
   regenerate the decoded text; the bug-report `.gz` needs the headset **and** the three
   monitor EDID blocks scrubbed before it is shippable, or it should be dropped from the tree.
2. **History rewrite** — `git filter-repo --replace-text <maintainer replace-text>` plus
   `--mailmap` to unify the commit author name, then force-push. Old procedure and file
   formats are in `docs/17`. Keep the UTF-16 Windows-hostname blob and the `.gz` in the
   replace-text explicitly, since a text pass alone misses them.
3. **Strengthen the checker** — `check-publishable.py` matches literals only. Add regex
   *classes* so a new unit's identifiers are caught without being pre-listed: MAC
   (`([0-9a-f]{2}[:\- ]){5}[0-9a-f]{2}`), IPv4 in RFC1918 ranges, SteamID64 (`7656119\d{10}`),
   GPU-UUID, generic UUID, and a decode-then-scan of UTF-16 and of `.gz`/`.zip` blobs (the
   current binary scan already reads compressed blobs, but not UTF-16 re-encoding).

## 2. Frontend i18n — three languages now, a fourth as data

**Rule enforced**: everything in the repo is English **except end-user frontends**, which are
multilingual (EN/ES/RU today, extensible). The audit inventoried every user-facing surface:

- **The only surface that does i18n right** is the booth dashboard (`status-dashboard.py` +
  `scripts/vr_i18n.py`): a `data-i18n="key"` table with EN/ES/RU and a persisted per-user
  language. Even it has three bypasses — the Python-side action-button labels, the demo
  "note" fields, and the live telemetry text — all English-only, rendered without translation.
- **Every other surface is single-language and hardcoded**: the voice cues
  (`voice-guide.py`, `yaw-protocol-voice.py`), `power-on.py` verdicts, `playlist-runner.py`,
  `vr-launcher-console.sh`, `vr-boot-selector.sh`, and `web/index.html` — most Spanish-only,
  `web/index.html` English-only, none sharing a mechanism. `vr_i18n.py` already contains dead
  EN/ES translations for `vr-boot-selector`'s exact prompts, unused.
- **A cross-language duplication** proves the point: `power-on.py` (Python) and
  `windows-kit/power-on.ps1` (PowerShell) hand-maintain the same ~50 messages twice. A
  Python-only i18n module can never reach the PowerShell one.

**Design**: one **language-neutral strings store** — `i18n/<lang>.json`, flat `key → string`
— read by a tiny loader in each runtime (Python `vr_i18n.py`, a bash helper as
`usb-port-map.sh` already does, a JS fetch for the web page, a PowerShell reader for the
Windows gate). Adding a 4th language = drop one `i18n/xx.json` file, zero code. Migrate each
hardcoded surface onto it; fold the dashboard's three bypasses in as keys. The **non-frontend**
scripts (installer, preflight, checks) stay English by rule — today they are English only by
luck, and even that is inconsistent (`install-*.sh` and `publicar.sh` are Spanish); normalize
them to English.

## 3. Install layers + config

Today install is one `bootstrap-lab.sh` plus manual steps. Split by audience:

| Layer | Contents | For |
|---|---|---|
| **docs-only** | the manual, nothing installed | reading how the G2 works on Linux |
| **runtime** | NVIDIA 595-open + the 4 patches, Monado, udev rules, `jack-in`, config | actually driving a headset at 90 Hz |
| **booth** | dashboard, kiosk, power watchdog, playlist, voice cues | running a guest-facing showcase |
| **dev-tools** | build deps, diagnostics, benchmarks (`decode-bench`, `gpu-pacing-baseline`), replay/soak tools | developing/measuring |
| **optional** | 360/VR180 player, Basalt SLAM, OpenComposite, per-title Steam tuning | content and extras |

**One config file** (`config/rig.conf.example` → `~/.config/reverb-g2/rig.conf`) replaces the
machine-specific literals the audit found hardcoded across `scripts/**`: paths (`VR_BASE`,
Steam library, `/mnt/...`), the target user, the DRM connector (now `DP-3` after the GPU swap,
was `DP-1` — see docs/90), the GPU power ceiling (this rig's new card caps at 210 W, not 250),
LAN host/IP, dashboard port, and the display stack. Auto-detect where possible (`gui_env.py`
already does the Wayland env; `machine-specs.sh` already dumps the hardware profile) and fall
back to the config value. Several knobs already exist (`VR_BASE`, `HMD_OUTPUT`, `TARGET_USER`,
`power.conf`) — unify them into the one file instead of scattering them.

**Docs & licensing**: the ~65 dated session logs (`docs/24`+, plus root `NEXT-STEP.md` and
`CLAUDE.md`) are a lab notebook, not a manual, and none are indexed. Move them under
`docs/journal/` (or a maintainers area), keep `docs/00–23` as the manual, and add an index.
Rename the Spanish-named files (`docs/pruebas.jsonl`, `docs/17-publicacion.md`,
`scripts/publicar.sh`, root `power-on-stats.jsonl`). The top-level `LICENSE` is MIT but
unscoped: add a NOTICE stating `patches/**` are diffs against upstreams under their own
licenses (Monado BSL-1.0, Basalt, xrizer, NVIDIA MIT/GPL) — the patches are ours, the code
they apply to is not.

## Status

Audit was one partial pass (the personal-identifier and history-rewrite-plan finders and the
adversarial verifiers did not finish; findings above are from the network, hardware, language,
and install finders and are worth re-verifying before the history rewrite). The privacy
worklist and the extended blocklist are done and live in `scripts/.private-patterns`; the
HEAD redaction, the i18n migration, and the installer split are not yet started.
