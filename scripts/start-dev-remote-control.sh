#!/bin/bash
# Starts a FRESH (never resumed) Claude Code Remote Control session for this
# repo, inside a detached tmux session so it survives disconnects/reboots
# without a human terminal attached. Run by hand first; only installed into
# systemd as a deliberate, separate step -- see the matching .service file's
# own header for why (same convention as vr-boot-selector.service).
#
# "Fresh every time" is deliberate: no -c/--continue. Each boot starts a
# clean conversation with no memory of the previous one -- state that needs
# to survive belongs in NEXT-STEP.md / the memory system / the dashboard,
# not in an assumed-resumed session.
set -u

SESSION="dev-remote-control"
REPO_DIR="$HOME/Documents/reverb-g2"
PERMISSION_MODE="acceptEdits"
MODEL="haiku"

cd "$REPO_DIR" || { echo "cannot cd to $REPO_DIR" >&2; exit 1; }

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux session '$SESSION' already running -- not starting a second one."
    echo "kill it first with: tmux kill-session -t $SESSION"
    exit 1
fi

# --model must come BEFORE the remote-control subcommand -- it errors as an
# "Unknown argument" if placed after (tested 2026-08-21).
tmux new-session -d -s "$SESSION" -c "$REPO_DIR" \
    "claude --model $MODEL remote-control --name reverb-g2-dev --permission-mode $PERMISSION_MODE"

echo "Started tmux session '$SESSION' running claude remote-control (fresh, $PERMISSION_MODE)."
echo "Attach with: tmux attach -t $SESSION   (detach again with Ctrl+B D)"
