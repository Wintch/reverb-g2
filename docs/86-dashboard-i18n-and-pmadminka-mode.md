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
