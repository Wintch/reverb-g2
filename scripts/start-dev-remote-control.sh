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
# Absolute path -- a non-interactive SSH/systemd shell doesn't source the
# .bashrc bits that put ~/.local/bin on PATH for an interactive shell
# (confirmed 2026-08-21: `claude` alone silently failed under tmux's
# non-interactive pane, which tears the whole session down on exit).
CLAUDE_BIN="$HOME/.local/bin/claude"

cd "$REPO_DIR" || { echo "cannot cd to $REPO_DIR" >&2; exit 1; }

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux session '$SESSION' already running -- not starting a second one."
    echo "kill it first with: tmux kill-session -t $SESSION"
    exit 1
fi

if [ ! -x "$CLAUDE_BIN" ]; then
    echo "claude binary not found at $CLAUDE_BIN -- check the install path" >&2
    exit 1
fi

# `claude --model haiku remote-control --name X` errors "unknown option
# '--name'" on 2.1.239 -- a real CLI parsing bug combining the global
# --model flag with the remote-control subcommand's own flags (confirmed
# 2026-08-21, reproduced on two machines, same version). ANTHROPIC_MODEL as
# an env var sidesteps it cleanly.
tmux new-session -d -s "$SESSION" -c "$REPO_DIR" \
    "ANTHROPIC_MODEL=claude-haiku-4-5-20251001 $CLAUDE_BIN remote-control --name reverb-g2-dev --permission-mode $PERMISSION_MODE"

echo "Started tmux session '$SESSION' running claude remote-control (fresh, $PERMISSION_MODE)."
echo "Attach with: tmux attach -t $SESSION   (detach again with Ctrl+B D)"
