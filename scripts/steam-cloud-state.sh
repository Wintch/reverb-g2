#!/bin/bash
# steam-cloud-state.sh -- READ-ONLY Steam Cloud sync-state detector for one AppID.
#
#   ./steam-cloud-state.sh <appid>
#
# Prints exactly one word to stdout: clean | pending | conflict | unknown
# Prints a one-line reason to stderr.
# Exit code: 0=clean, 1=pending, 2=conflict, 3=unknown (i.e. ALWAYS nonzero when
# not clean -- callers that just want "ok to launch?" can test the exit status
# alone; callers that want the class can read stdout).
#
# THIS SCRIPT NEVER TOUCHES A STEAM CLOUD DIALOG. It never clicks, force-syncs,
# uploads, downloads, or sends any input to Steam. It only reads local files and
# (optionally) an X11 window title via xdotool. Forcing a Steam Cloud resolution
# programmatically risks corrupting configs/saves -- if a conflict is detected,
# the fix is for a human to cancel the dialog and use Steam's own "force sync"
# button, never anything this script does. Do not add force/resolve/click logic
# here. See docs/91 / MEMORY project_demo_day_prep and reference_lab notes on
# why: this repo's hard rule is manual resolution only.
#
# ---------------------------------------------------------------------------
# THREE SIGNALS, combined (highest-confidence first):
#
#  1. logs/cloud_log.txt (append-only, per-AppID lines, grows ~KB/session).
#     We take the LAST line for the given AppID that contains a terminal-state
#     keyword (fail/conflict/successfully synced/upload complete/download
#     complete/autocloud complete) -- earlier lines for the same appid are
#     noise from previous launches/exits and are ignored.
#     Empirically verified 2026-09-03 against a currently-bad appid (Q2RTX,
#     1089130) and a currently-good one (241100):
#       bad:  "...BYieldingBuildFileListToSync Failed for 'up,AC Exit,'"
#             "...Failed sync for 'AC Launch,down,' [login=false][offlineMode=false]"
#       good: "...AutoCloud complete" / "...Upload complete in build list" /
#             "...Download complete in build list" / "...Successfully synced
#             to ChangeNumber N"
#     -> last line matching /fail|conflict/i = conflict, else = clean.
#
#  2. userdata/<steamid>/<appid>/remotecache.vdf -- per-file "syncstate".
#     EMPIRICAL FINDING (2026-09-03, compared 1089130 [bad] vs 241100 [good]):
#       syncstate "1" = fully synced (localtime == time == remotetime, real
#                        sha1, real size) -- this is what every entry in the
#                        known-good 241100 cache shows (30/30 entries).
#       syncstate "2" = NOT yet synced / pending -- this is what every entry
#                        in the known-bad 1089130 cache shows (24/24 entries,
#                        all size 0, sha all-zero -- i.e. it never got past
#                        this state because BYieldingBuildFileListToSync keeps
#                        failing).
#     No syncstate value other than 1 or 2 has been observed live, so a
#     "conflict" verdict is never derived from this file alone -- only
#     clean (all entries == 1) or pending (any entry != 1). A missing file
#     (Steam deletes it when there's nothing to sync -- "empty vector,
#     deleting" in cloud_log.txt) is "unknown" from this signal, not "clean".
#
#  3. xdotool window title (DISPLAY/XAUTHORITY permitting) for an actual
#     Steam Cloud dialog. No such dialog was open during development/testing
#     (2026-09-03) even with 1089130 sitting in a Failed state, so this
#     signal was NOT observed live -- UNCERTAIN, best-effort only. The title
#     strings below are NOT guessed: they are the literal English strings
#     Steam's own client ships, pulled from
#     ~/.steam/debian-installation/public/steamui_english.txt on this
#     machine:
#       Steam_CloudConflict_Title          = "Steam - Cloud Sync Conflict"
#       Steam_CloudPendingSessions_Title    = "Steam - Pending Cloud Uploads"
#       Steam_WaitingForCloudSyncTitle       = "Steam Cloud - Syncing"
#       SteamUI_JoinDialog_CloudSyncFailed_Title = "Steam - Warning" (too
#         generic to use alone -- shared with unrelated warnings -- not used).
#     If Steam ever renders these with different casing/wording in practice,
#     this signal will simply miss and the verdict falls back to signals 1+2.
#     DISPLAY note: live on 2026-09-03 Xwayland was on :0 (auth file
#     /run/user/<uid>/.mutter-Xwaylandauth.*), not :1 -- this script
#     auto-detects both DISPLAY and the Xwayland auth file rather than
#     hard-coding either, and env DISPLAY/XAUTHORITY override if already set.
# ---------------------------------------------------------------------------

set -u

STEAM_BASE="$HOME/.steam/debian-installation"
CLOUD_LOG="$STEAM_BASE/logs/cloud_log.txt"

usage() {
    cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") <appid>

Read-only Steam Cloud sync-state detector. Prints one of:
  clean | pending | conflict | unknown
to stdout, a short reason to stderr, and exits 0/1/2/3 respectively.
Never forces, resolves, uploads, downloads, or clicks anything.

Env overrides (optional): STEAM_ID, DISPLAY, XAUTHORITY.
EOF
}

APPID="${1:-}"
case "$APPID" in
    ''|*[!0-9]*)
        usage >&2
        exit 3
        ;;
esac

# ---------------------------------------------------------------------------
# Signal 1: cloud_log.txt
# ---------------------------------------------------------------------------
log_state="unknown"
log_line=""
if [ -r "$CLOUD_LOG" ]; then
    log_line="$(grep -F "[AppID $APPID]" "$CLOUD_LOG" 2>/dev/null \
        | grep -Ei 'fail|conflict|successfully synced|upload complete|download complete|autocloud complete' \
        | tail -1)"
    if [ -n "$log_line" ]; then
        if echo "$log_line" | grep -qEi 'fail|conflict'; then
            log_state="conflict"
        else
            log_state="clean"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Signal 2: remotecache.vdf syncstate
# ---------------------------------------------------------------------------
vdf_state="unknown"
steamid="${STEAM_ID:-}"
if [ -z "$steamid" ] && [ -d "$STEAM_BASE/userdata" ]; then
    mapfile -t _ids < <(ls "$STEAM_BASE/userdata" 2>/dev/null)
    [ "${#_ids[@]}" -eq 1 ] && steamid="${_ids[0]}"
fi

vdf_path=""
if [ -n "$steamid" ]; then
    vdf_path="$STEAM_BASE/userdata/$steamid/$APPID/remotecache.vdf"
    if [ -r "$vdf_path" ]; then
        _values="$(grep -oP '"syncstate"\s+"\K[0-9]+' "$vdf_path" 2>/dev/null)"
        if [ -n "$_values" ]; then
            if echo "$_values" | grep -qv '^1$'; then
                vdf_state="pending"
            else
                vdf_state="clean"
            fi
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Signal 3: xdotool window title (best-effort, see header)
# ---------------------------------------------------------------------------
win_state="none"
win_title=""
if command -v xdotool >/dev/null 2>&1; then
    _disp="${DISPLAY:-}"
    _xauth="${XAUTHORITY:-}"
    if [ -z "$_disp" ]; then
        _disp=":0"
    fi
    if [ -z "$_xauth" ]; then
        for _f in "/run/user/$(id -u)"/.mutter-Xwaylandauth.*; do
            [ -e "$_f" ] && { _xauth="$_f"; break; }
        done
    fi
    if [ -n "$_xauth" ] && [ -e "$_xauth" ]; then
        _wids="$(DISPLAY="$_disp" XAUTHORITY="$_xauth" xdotool search --name '.' 2>/dev/null)"
        for _wid in $_wids; do
            _title="$(DISPLAY="$_disp" XAUTHORITY="$_xauth" xdotool getwindowname "$_wid" 2>/dev/null)"
            case "$_title" in
                *"Cloud Sync Conflict"*|*"Sync Conflict"*)
                    win_state="conflict"; win_title="$_title"; break ;;
                *"Pending Cloud Uploads"*|*"Cloud - Syncing"*|*"Synchronizing Steam Cloud"*)
                    win_state="pending"; win_title="$_title"; break ;;
            esac
        done
    fi
fi

# ---------------------------------------------------------------------------
# Combine (highest confidence first)
# ---------------------------------------------------------------------------
state="unknown"
reason=""

if [ "$win_state" = "conflict" ]; then
    state="conflict"
    reason="Cloud Sync Conflict dialog is open: window title '$win_title'"
elif [ "$win_state" = "pending" ]; then
    state="pending"
    reason="Cloud syncing/pending-upload dialog is open: window title '$win_title'"
elif [ "$log_state" = "conflict" ]; then
    state="conflict"
    reason="cloud_log.txt last status for AppID $APPID: $log_line"
elif [ "$vdf_state" = "pending" ]; then
    state="pending"
    reason="remotecache.vdf has syncstate != 1 (unsynced) entries for AppID $APPID (${vdf_path:-n/a})"
elif [ "$log_state" = "clean" ] && [ "$vdf_state" != "pending" ]; then
    state="clean"
    reason="cloud_log.txt last status for AppID $APPID: $log_line"
elif [ "$log_state" = "unknown" ] && [ "$vdf_state" = "clean" ]; then
    state="clean"
    reason="remotecache.vdf: all entries syncstate=1 for AppID $APPID (no cloud_log.txt record to cross-check)"
else
    state="unknown"
    reason="insufficient signal for AppID $APPID -- log=$log_state vdf=$vdf_state window=$win_state"
fi

echo "$state"
echo "steam-cloud-state: appid=$APPID state=$state -- $reason" >&2

case "$state" in
    clean)    exit 0 ;;
    pending)  exit 1 ;;
    conflict) exit 2 ;;
    *)        exit 3 ;;
esac
