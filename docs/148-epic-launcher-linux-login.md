# Epic Games Launcher on Linux: VR/Linux compatibility check, login blocked

Date: 2026-10-15. Machine: local box (Debian 13, Ryzen 5 3600, 31 GB). Status: **not working yet, stuck at login.**

## Goal

Check whether Epic Games Store titles can be used for VR on Linux (OpenXR via Monado, OpenVR via xrizer).

## What is installed

- `~/Downloads/EpicGamesLauncher-x86_64.AppImage` (176 MB, downloaded from https://launcher.epicgames.com/).
- This is **Epic's native Linux launcher** (Tauri/Rust + WebKitGTK), not Heroic/Legendary. Version `0.95.2+gfa9ad49`
  (the log says "UPDATED FROM 0.96.0", so the AppImage self-updated to an older stable target).
- Web search on 2026-10-15 still said "native launcher in development, no date"; that is out of date, the AppImage exists.
  Treat web claims about Linux support with suspicion.
- Data: `~/.local/share/com.epicgames.eglv2/` (logs in `logs/`, settings in `settings/app-settings.json`),
  cache in `~/.cache/com.epicgames.eglv2/`. Default install dir: `~/Games`.
- Build platforms resolved at startup: `["Linux", "Windows"]`, so the store knows about Windows builds too.
- Default browser on this box: Brave (`brave-browser.desktop`).

## Login flow (from the logs)

1. Launcher starts, finds no stored refresh token (`Auth.Credentials.NoRefreshToken`), shows the SISU sign-in surface.
2. "Sign in" calls `auth_sign_in_browser`: binds a loopback listener on `127.0.0.1:<random port>` and opens
   `https://www.epicgames.com/id/authorize` in the system browser.
3. It then waits for the browser to redirect back to that loopback port (`Auth.Sisu.AwaitingCallback`).
4. Attempt 1 (05:08:43 UTC): waited 69 s, ended `reason="user_cancelled"` (the user closed it / retried).
5. Attempt 2 (05:09:54 UTC): listener on `127.0.0.1:37505` confirmed open with `ss -ltnp`, still waiting, no callback logged.

So the launcher side is healthy (listener up, no TLS/keyring/DPoP errors). **The callback never reaches it.**
Everything else in the log (`AUTH_ERROR not_authenticated`, `Library.BundleAuthTimedOut`, `RefreshSkippedSignedOut`)
is a downstream effect of not being logged in.

## Not yet checked (next steps, in order)

1. Does the browser actually open the authorize page, and does it finish at a `http://127.0.0.1:<port>/...` redirect?
   Look at the final URL in Brave. If the page loads but the redirect shows a connection error, copy the URL.
2. Brave Shields / extensions blocking the localhost redirect or the Epic captcha (try a private window, shields down).
3. Try another browser (Firefox) via `xdg-settings set default-web-browser`, then retry sign-in.
4. Port-per-attempt: the port changes every attempt, so a page left open from attempt 1 will redirect to a dead port.
   Always sign in from the page opened by the **latest** attempt.
5. Check for a deep-link/protocol handler (`xdg-mime query default x-scheme-handler/com.epicgames.launcher`).
6. Re-run with `RUST_LOG`/debug logging (`debug_logging=false` in the log header) if the above shows nothing.

## VR compatibility: still unknown

Nothing can be tested until login works. The questions to answer per title once the library loads:

- Does the Linux build exist, or is it a Windows build under Proton? (Launcher advertises both platforms.)
- OpenXR title (should work on Monado) or OpenVR title (needs xrizer/OpenComposite)?
- Uses Easy Anti-Cheat? EAC works under Wine/Proton only if the developer enabled it; kernel-level EAC is unsupported.
- Does the launcher's EOS overlay/bootstrapper start under our Monado session? (Log shows `Overlay loaded` and
  `Anti-cheat client not available` at idle, which is expected without a game.)

## Reference

- Web research (2026-10-15, partly outdated): Epic Linux launcher news, EAC-on-Linux 2021 announcement, Heroic as workaround.
  No source covered VR/OpenXR for Epic titles.
