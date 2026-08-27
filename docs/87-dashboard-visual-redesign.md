# 87 — status-dashboard.py visual redesign: "Night Panel" (2026-08-27)

User installed the `frontend-design` plugin (marketplace `claude-plugins-official`) and asked for
the dashboard (`scripts/status-dashboard.py`, the :8765 booth console) to be "emprolijado" using
its design guidance. Scope: visual/CSS/HTML only — zero changes to any Python backend function or
API route (confirmed by diff: every hunk falls inside the `PAGE = """..."""` template string,
lines 561+).

## Method: independent design panel, not a single pass

Per the skill's own process (brainstorm → critique → build), ran a 3-way parallel design-panel
workflow (`wf_4fab2726-043`) instead of picking one direction alone: three agents each produced a
full token system (colors/type/layout/signature) from a different angle —
**instrument/flight-deck**, **field-kit/operator-manual**, **observatory/control-room** — grounded
in a written brief (real content inventory, hard constraints, the project's own dim-room and
offline-only facts). Each proposal was then critiqued by an independent agent scored against the
brief and against reading as one of the three well-known AI-generic looks (cream+serif,
near-black+neon, broadsheet).

**Winner: "Night Panel" (field-kit angle)** — scored highest on both distinctiveness (4/5) and
subject-fit (5/5), verdict "keep" with one concrete fix applied (see below). Runner-up
"Annunciator Deck" (instrument angle) had a real internal contradiction (its own wireframe lit the
GOLD tile the same as APPROVED, violating the brief's own safety rule) — not used. "Night Bridge"
(control-room angle) had an accent-vs-ok-green hue proximity problem under low light — not used.
Full proposal/critique JSON: `wf_4fab2726-043`'s journal (or ask to re-run — the workflow script's
one-line bug, `a` referenced out of scope in the critique stage, is fixed in the transcript's
second run).

## The system, as built

Two visual registers, matching the brief's own two real jobs:

- **Operator tray** (always visible, generous spacing, 14-18px type): alert banner → wordmark +
  4-dot status strip (SESSION/AUDIO/HARDWARE/HUB, folding USB+DRM+coredump faults into one HW dot)
  → compositor toggle + action row → a glance-grid (headset preview, largest element, beside the
  relocated Session card + audio outputs) → command centre → demo round/playlist → demo launch →
  operator guide (styled as a distinct dashed-border "laminated card").
- **Access panel** (collapsed `<details>`, closed by default, dense mono 11-12px type): USB
  census, display connectors, monado-service+coredumps, GPU+driver string, git head, system specs,
  Sunshine, uptime — everything that's read rarely, only when something's actually wrong. Its
  `<summary>` carries a small fault-dot (hidden unless `hwFault` is true) so a real problem is
  discoverable without opening it.
- **Demo grid = switch-plates**, the signature element: every (title × tracking) tile is always
  fully clickable, but only `status=approved` gets a lit green border + tinted background via
  `.demo:has(.st.approved)` — gold/testing/untested/broken stay visibly neutral/held-back. Pure
  CSS, no JS change needed (`:has()`, safe in any 2026 evergreen browser).

Tokens: bg `#17181a`, surface `#212327`/`#262a30`, ink `#eae5d8`, one non-status accent (steel-blue
`#7c93a6`, interactive-only, never status), ok/bad/warn unchanged in *meaning* from the old build
(green/red/amber) but re-picked so none of them read as neon. Three font roles, **all real fonts
already on this Debian/GNOME box** — no web fonts, since the venue may have zero internet:
`Liberation Sans Narrow` (display/eyebrows), `Cantarell` (body), `DejaVu Sans Mono` (every
diagnostic/data readout). The critique flagged the proposal's own `dim` token as failing WCAG AA
(~3.4:1) when reused for secondary body text in the diagnostics tier — split into `--ink-dim`
(~5:1, secondary text) and `--ink-inactive` (the original, kept for genuinely-inactive/disabled
states only).

Small gap found and fixed while building: `.st` had no rule for `status="testing"` (used by
Cyberpilot in `DEMO_LAUNCHES`) — pre-existing, not something the redesign introduced, but since
the CSS was already open it now maps to the same warn/amber treatment as `gold`.

Dead CSS removed (verified unreferenced by any element/JS first): `.badge`/`.badge.ok`/`.badge.bad`,
`#audio-toggle.on/.off`, `#vol-wrap`/`#vol`/`#vol-val` — leftover from an earlier build, no matching
markup anywhere in the file.

## Verification (the docs/86 lesson, applied on purpose)

The previous dashboard change (86) shipped a Python-escaping bug that silently broke every dynamic
panel, caught only because the user saw it live — source-text regex extraction and `curl` status
checks both passed while the real served JS was broken. This time, before calling it done:

1. `ast.parse()` the whole file (catches Python syntax errors).
2. Extract `PAGE`'s actual value via `ast.literal_eval` on the AST (not a source-text regex) —
   this is what makes Python's own `\"` → `"` collapse visible if it's wrong.
3. `node --check` on the extracted `<script>` body — catches JS syntax errors in what will
   actually be served.
4. Restarted the real running dashboard process (PID from `pgrep`, plain `python3
   status-dashboard.py` — it's still "run by hand," no systemd unit) and hit it with headless
   Chrome (`google-chrome --headless=new --dump-dom` / `--screenshot`), reading the **post-JS**
   DOM and stderr — confirms zero console errors, no leftover `"loading..."` placeholders (i.e.
   every async render function actually completed against the live backend), and gives real
   screenshots for the visual critique the skill itself asks for. Checked at both desktop
   (1400px) and mobile (420px) widths — the `@media (max-width:960px/720px)` breakpoints collapse
   cleanly, no horizontal overflow.

Confirmed live and coincidentally: `monado-service` was genuinely running during this session
(real PID, not stale) — restarting the dashboard script never touches it (it's read-only by its
own docstring), so this redesign work didn't risk whatever session was live at the time.

## Follow-up same session: grouping (user feedback "faltan grupos más prolijos")

Two places were still flat, undifferentiated lists after the tiering pass above:

- **Action row**: `activate-panel`/`stop-games` (system) and the 4 `voz-*` spoken booth cues were
  one unlabeled row of 6 buttons. Split into two labeled clusters, `#actions-system` /
  `#actions-voice`, with a left-border divider. The split rule in `loadActions()` is generic
  (`id.startsWith('voz-')`), not a hardcoded id list — a future voice cue groups correctly with no
  code change.
- **Demo grid**: all 7 (title × tracking) tiles were one grid regardless of status, relying only
  on the switch-plate color to communicate "only approved is real." Split into two literal
  sections, `#demos-approved` / `#demos-other` (`d.status === 'approved'` is the only condition),
  each with its own `data-i18n` group label. `.demo-group:empty` / a `:has(+ .demo-group:empty)`
  rule on the label hide either section cleanly if it's ever empty (e.g. a night with zero
  approved titles, or — hopefully someday — zero titles still in testing).

Same verification method as the main pass: `ast.literal_eval` → `node --check` → live restart →
headless Chrome dump/screenshot, confirmed both groups populate with the right members (2
approved: Aircar·3dof, Dreams of Dalí·6dof; 5 other: Aircar·6dof, Cyberpilot, Hellblade, The Night
Café, Anne Frank House). One process-management note for next time — **bitten twice the same
night, second time with the "fix" from the first**: `kill $(pgrep -f "status-dashboard.py")` can
match the *calling shell wrapper's own* command line (which contains that literal string as text)
and kill the shell itself (exit 144). The bracket trick (`[s]tatus-dashboard`) is **not enough**
when the same chained command also contains the plain string elsewhere (e.g. the `nohup python3
status-dashboard.py` that restarts it) — the wrapper still self-matches on that. The robust rule:
**anchor the pattern at the start of the command line, `pgrep -f "^python3 status-dashboard.py"`**
— the wrapper's cmdline begins with `/bin/bash -c`, so it can never match, regardless of what
else the same command contains. Verified live: the anchored form returned exactly the one real
PID (or none) both times it was used afterwards.

## Same night, later: the deploy-drift class of bug got its own instrument

Three times in one session an edit in the repo did not reach what actually runs, because
`~/vr/` holds **copies** of `scripts/`, not symlinks: `vr-launcher.py` (a headset test ran the
stale profile), `basalt-g2-config.json`, and — worst — `demo-recorder.py`, which had crashed on
every launch since it was born (2026-08-26) because the modules it imports (`rig_telemetry.py`,
`gui_env.py`, `wmr_usb_ids.py`, later `reseat_audio.py`) were never copied beside it, so a
whole night of "auto-recorded" variant sessions never existed. A full sweep found 11 of 55
shared scripts drifted (repo newer in every case — the 18.5 V PSU corrections, the
English-strings rule, `vr-power-setup.sh`'s `hmd_usb_no_autosuspend()` refactor). All
deployed after diffing each one for local-only lines (none found).

**`scripts/deploy-check.py`** (new): lists shared files that differ (and which side is newer),
modules imported by any `~/vr/*.py` that are missing there, and repo scripts with no deployed
copy; exits 1 on drift/missing so a session script can gate on it. It deliberately does not
deploy — a `~/vr` copy *can* carry an uncommitted local fix, and diff-then-copy is the safe
habit. Symlinking `~/vr` to the repo would end the class of bug outright but changes a
project-wide convention (CLAUDE.md's "sync `scripts/` with the copy in `~/vr/`") — flagged,
not done.

## Not done / open

- The heavily-dynamic per-tick telemetry strings (session state text, audio labels, etc.) are
  still English-only, same scope line docs/86 already drew — untouched here too.
- No visual regression pass against a real guest/operator using it live yet — screenshots only.
  Worth a look next time someone's actually running the booth.
