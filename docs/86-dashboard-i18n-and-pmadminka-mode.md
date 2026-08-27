# 86 — Status dashboard: 3-language per-user preset, pmadminka attach/detach (2026-08-27)

Two additions to `scripts/status-dashboard.py`, both scoped to the static/command-centre chrome,
not the live telemetry loop.

## EN/ES/RU per-user language preset

Pattern adapted from an internal design guide (`tools/docs/GUIA_SITIOS.md`, unrelated project,
one relevant section): a client-side `I18N` object keyed by locale, `data-i18n="key"` on static
HTML for the header/guide/section titles, a `t(key)` helper for the JS-built command-centre and
playlist strings, `applyLang()`/`localStorage` for no-reload switching. Each user profile now
carries a `lang` field (`en`/`es`/`ru`); selecting a different active user re-applies that user's
saved language automatically (`refreshUserCenter()`'s `wantLang !== currentLang` guard), and the
command centre has its own language dropdown that saves the choice back to the active profile.
Existing profiles migrate to `lang: "es"` on load — this dashboard's actual daily-use language up
to now, so switching to per-user i18n doesn't silently change what today's real operator sees.

**Deliberately not localized this pass**: the heavily dynamic per-tick telemetry strings inside
`tick()` (session/USB/DRM/GPU/audio status labels) and `renderAudioDevices()` — left in English/
mixed as before, to limit regression risk on a live, guest-facing tool. Candidate for a later
pass.

## pmadminka attach/detach, surfaced in the Session card

`pmadminka-agent.py` (see the pmadminka memory / `project_machine_reservation_system`) runs as
its own `systemd --user` service and is what actually makes this box remotely rentable through
the hub — independent of this dashboard, which until now had no visibility into whether that
service was even running. Added:

- `pmadminka_status()` — `systemctl --user is-active pmadminka-agent.service`, cheap, in the same
  cached `build_status()` path as everything else.
- A row in the Session card: **attached** (warn-colored — a remote renter could queue/kill Steam
  titles on this rig) vs **standalone** (dim — dashboard-only, no hub involvement), with a button
  that flips it via two new POST endpoints, `/api/pmadminka/attach` / `/api/pmadminka/detach`
  (`systemctl --user start/stop` — no sudo needed, it's a `--user` unit).

Motivation, the user's own framing: the dashboard needs to work fully standalone, not degraded,
because **the demo venue very likely won't have pmadminka reachable at all** — and separately,
right before any live demo it should be one click to make sure nobody on the hub side can touch
Steam on this machine mid-session, without having to know or type a `systemctl` command by hand.

Verified live on iashur: reloaded process reports `{"attached": true, "state": "active"}`
correctly (the real agent was active/enabled at the time). Did not toggle the live service off/on
as part of this test — it's the actual production rental agent, and this box may have a real
renter attached; toggling it for real is a one-click action now, exercised for real the next time
it's actually needed rather than as a test.

## Correction, same day: the i18n change above shipped with the whole page broken

The `PAGE` HTML/JS template is a plain (non-raw) Python triple-quoted string. Several of the i18n
strings added above (`playlist_h2`, `demos_h2`, `pl_hint`, `guide_1`/`guide_2`/`guide_3`/`guide_5`,
EN+ES only — RU used «guillemets» instead of `"` and was unaffected) contain an embedded quote
mark, written as `\"` so the rendered JS would have a validly-escaped string. Python's own string
literal parser consumes that backslash on load — `\"` inside a non-raw `"""..."""` evaluates to a
bare `"`, not `\"` — so the JS actually served had unescaped quotes inside double-quoted string
literals. That's a JS syntax error, and a syntax error anywhere in a single inline `<script>` block
aborts the *entire* script: nothing after it runs, including every `tick()`/`loadActions()`/
`refreshUserCenter()` call at the bottom. Symptom: the static HTML shell rendered fine, every
dynamic panel stayed on "loading...", and it did not clear on reload — reported live by the user
("todo dice loading. recargo y hace lo mismo").

**Root cause of missing this in first-pass testing**: verification only checked `curl` status codes
and JSON payload shape (all fine — those never touch the JS content), and a syntax check that
extracted the JS from the raw `.py` *source text* with a regex, which faithfully preserved the
`\"` exactly as typed and therefore didn't reproduce Python's own escape processing — the check
validated code that was never actually going to be served. Re-diagnosed by running the real page
script (with `document`/`fetch`/`Image` stubs) against the live backend in Node, which surfaced a
`Cannot set properties of null` false lead first (a harness gap, not a real bug — fixed the stub),
and by diffing the *live-fetched* `<script>` content against the local source, which showed the
quotes silently missing. Fix: `\"` → `\\"` (32 occurrences, all confined to this i18n block) so the
backslash survives Python's own parse and reaches the JS as a real escape. Confirmed this time by
extracting `PAGE`'s value via `ast.literal_eval` on the actual Python AST (not a source-text regex)
and by re-fetching the live-served page after redeploying — both now pass `node --check`.

**Lesson**: a "syntax check" against the raw template source text is not equivalent to a syntax
check against what Python actually evaluates that string to, whenever the template contains
backslash sequences. Anywhere `PAGE`-style templates need a literal backslash to survive into the
rendered output, either double the backslash in the Python source or make the string `r"""`
(not usable here since existing `\n` styling isn't needed but would need auditing) — and validate
by fetching what the server actually returns, never by reading the `.py` source text back out.
