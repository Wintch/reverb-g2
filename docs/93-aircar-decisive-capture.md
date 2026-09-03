# 93 — Aircar dead-wand: the decisive one-session capture (supersedes docs/89 §14's open ends)

A four-way re-investigation (2026-09-03) of the Aircar VR-controller regression, run against
the real xrizer/Monado source and every prior conclusion in `docs/89`. It settles the bisect,
kills three dead theories, leaves **two** live hypotheses, and specifies a single ~2-minute
worn capture that distinguishes them. It also corrects a stale operational claim in §14.

## Bisect result

Working T161 (2026-08-12), broken T243 (2026-08-20/21). The window contains **exactly two
xrizer patches that touch any input file, both dated 2026-08-18**: `0003` (XR_EXT_user_presence)
and `0004` (`input: legacy state coexists with action manifests`). Patches 0001-0002 predate
T161; 0005+ postdate T243 or are compositor/openxr_data-only. **No Monado `oxr` patch and no
Proton bump falls in the window.** So the regression is a change xrizer `0003`/`0004` introduced.

## What is now ruled OUT (do not chase these again)

- **Patch 0004's "unconditional per-frame sync race"** (the docs/89 §11 story that patch 0011
  tried to fix). The 0004 diff scopes its only new per-frame-capable call *inside* the
  pre-existing "no controllers connected" branch, which the §12 live log shows fires once at
  startup and never again. Patch 0011 fixed exactly that branch and **changed nothing live
  (§12 A/B)** — the decisive already-run fact every surviving theory must fit.
- **A second `xrAttachSessionActionSets` as a silent failure** — it is a loud
  `XR_ERROR_ACTIONSETS_ALREADY_ATTACHED`, not silent.
- **Naive interaction-profile fallback-mismatch** — both G2 hands correctly resolve to
  `oculus/touch_controller`, the same profile Aircar's manifest binds.

## The two surviving hypotheses

**(1) Binding-table double-suggest clobber — code-confirmed, not yet observed live. Leading.**
Patch 0004 made xrizer's `load_action_manifest()` suggest Aircar's manifest bindings for
`oculus/touch_controller`, then **unconditionally** call `get_or_create_legacy_actions()`,
which re-suggests bindings for the *same* profile — **before** the single attach. Per the
OpenXR spec and Monado's `oxr_binding.c` (`reset_all_keys()`), a second
`xrSuggestInteractionProfileBindings` for the same profile **discards, not merges**, the prior
call. So Aircar's trigger/grip/A end with `cache->input_count == 0`, `oxr_action_cache_update`
never sets `.active`, and `isActive` reads false **permanently from the first `xrSyncActions`**,
with no error and no default-verbosity log. Deterministic — best matches the literal
"0 true samples across 9.5 minutes, both hands, both action types" signature, and is
independent of patch 0011's per-frame fix. **Caveat: this predicts breakage for every
manifest title resolving to a profile the legacy layer also touches, not just Aircar** — cross-
check `docs/23` for other post-08-18 wand regressions before trusting it; if other manifest
titles still work wand-only, this hypothesis is weakened.

**(2) Session drops/never holds `XR_SESSION_STATE_FOCUSED` — new, never checked in docs/89.**
`oxr_action_sync_data` returns `XR_SESSION_NOT_FOCUSED` (a success-class code) and does nothing
if the session is not focused; `oxr_action_cache_update` zeroes `is_active` unless focused. Both
are swallowed by xrizer's `.unwrap()` (non-negative result, no panic, no log) — exactly the
"legitimate Ok(is_active=false), no error anywhere" that §14(d) observed. §14 only ever proved
the session reached FOCUSED *once, early*; it never greps the session-state sequence across the
steady-state window. Uniform across all actions/hands by construction (the gate is whole-sync
level). Checkable for free: xrizer already logs every state transition unconditionally at
`info!` (`openxr_data.rs`, `"OpenXR session state changed: {:?}"`).

## Correction to docs/89 §14: the instrumentation is ALREADY deployed

§14 said patch 0012's `DEBUGPROFILE`/`DEBUGBOOL*` instrumentation was "not installed". **Stale.**
Verified live 2026-09-03: `~/vr/xrizer` is at commit `ba7828a` (patch 0012), clean tree; the
live `target/release/libxrizer.so` has the markers compiled in (`strings` confirms
`DEBUGPROFILE(analog/bool)`, `DEBUGBOOLFINAL`, `DEBUGVEC1EXPLICIT`). Deployment is the build
path itself: `openvrpaths.vrpath`'s single runtime entry points at `.../xrizer/target/release`,
whose `bin/linux64/vrclient.so` is a **permanent symlink to `libxrizer.so`** (made once by
`build.rs`). Whatever `cargo build --release` last wrote is what Steam loads next launch — same
mechanism §12 confirmed via `/proc/<pid>/maps`. **No rebuild is needed before the capture.**

## The decisive capture — ONE worn session, both hypotheses from the same two logs

Controllers-on-first is mandatory (no hotplug). Launch env (exported in the shell, not edited
into scripts — `vr-launcher.py` inherits ambient env):

```bash
export RUST_LOG=xrizer=debug OXR_DEBUG_BINDINGS=1 XRT_LOG=debug VR_LAUNCH_APPID=1073390
cd ~/vr && python3 vr-launcher.py
```

Worn: ~10s to settle, then deliberately pull right trigger, left trigger, press right A, ~1-2s
apart, repeat 2-3× over ~40s, doff. Under 2 minutes.

Pull and read (same run, three checks):

```bash
cp ~/.local/state/xrizer/xrizer.txt ~/aircar-capture-xrizer.txt
cp ~/vr/jack-in-wayland.log ~/aircar-capture-monado.log
# (A) binding resolution — Monado's OXR_DEBUG_BINDINGS trace:
grep -n -A6 '^: Binding main/' ~/aircar-capture-monado.log
# (B) session focus sequence — xrizer's own state log:
grep -n 'OpenXR session state changed' ~/aircar-capture-xrizer.txt
# (C) tie back to the failure — patch 0012's own is_active reads:
grep -n 'DEBUGBOOLFINAL\|DEBUGPROFILE\|DEBUGVEC1EXPLICIT' ~/aircar-capture-xrizer.txt | grep -v 'is_active=true'
```

- **(A) PASS (binding is the cause):** for thrust/reverse/menu, no `Bound to:` follows, or the
  only candidate is `Rejected! (NO TRANSFORM)`, or `input_count` 0.
- **(B) PASS (focus is the cause):** `Focused` once early, then a `Visible`/`Synchronized` line
  during the press window with no later `Focused` (a one-way drop), or Focused↔Visible flapping.
- **(C)** should be a quiet run (zero `is_active=true`), confirming this is the same failure;
  its `session_state` field lines up against (A)/(B) timestamps to say which mechanism fired.
- If BOTH (A) and (B) come back clean while (C) is still false, the next trace (out of this
  capture's scope) is `oxr_input_combine_input`'s `input->active` on the raw `xrt_input` vs.
  `wmr_controller_hp.c`'s driver input array.

## Fix

Candidate fixes exist for both hypotheses (for (1): don't re-suggest legacy bindings for a
profile the manifest already covers, or merge instead of clobber; for (2): find and fix why the
session leaves FOCUSED) — **but they are flagged needs-live-confirmation and not written yet.**
Patch 0011 is the standing precedent for why theorizing a fix before the capture is a trap: run
the capture, let it name the mechanism, then fix that one.
