#!/usr/bin/env bash
# SessionStart hook (matcher: startup) — remind Claude to read STATE.md on fresh sessions
# P1-B (2026-04-09): Also writes session_start event to governance-log.jsonl for session boundary detection

# Read stdin payload FIRST (before heredoc output)
PAYLOAD=$(cat)

# Emit hook response
cat << 'HOOKJSON'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "[SESSION START] Read Projects/[active project]/STATE.md before doing anything. It contains current status, last actions, and next steps. Do not rely on memory — fetch current state from files."
  }
}
HOOKJSON

# Initialize checkpoint timer
date +%s > "$HOME/.claude/last-checkpoint"

# P1-B: Write session_start event to governance-log.jsonl
echo "$PAYLOAD" | "/c/Program Files/Python314/python.exe" "$(dirname "$0")/session-start-log.py" 2>/dev/null || true

exit 0
