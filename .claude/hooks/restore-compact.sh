#!/usr/bin/env bash
# SessionStart hook (matcher: compact) — inject saved state after compaction
# Reads the recovery file written by pre-compact.sh and injects it into context.
# Also emits session_start event with source=compact to governance-log.jsonl
# (observability v2 gap #1 fix 2026-04-19).

# Read stdin payload FIRST for telemetry (before heredoc output)
PAYLOAD=$(cat)

RECOVERY_FILE="$HOME/.claude/pre-compact-recovery.md"

if [ -f "$RECOVERY_FILE" ]; then
  # Read recovery content, escape for JSON
  RAW=$(cat "$RECOVERY_FILE" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g' | sed ':a;N;$!ba;s/\n/\\n/g')

  # ECC-LEARN-A1 (2026-05-05): wrap recovered content with HISTORICAL REFERENCE ONLY guard.
  # Direct fix to feedback_compaction_loses_attribution.md — model must treat restored
  # content as a snapshot, not live state. Verify specifics against current files before acting.
  PREFIX="=== HISTORICAL REFERENCE ONLY (PRE-COMPACTION SNAPSHOT) ===\\n\\nThis content was saved before the previous session compacted. It is a snapshot in time — current state may have changed. Verify specific facts (file paths, IDs, status, decisions, line numbers) against the live system before acting on them. Do NOT cite this snapshot as authoritative for current state. Read Projects/[active project]/STATE.md and the live files first.\\n\\n=== BEGIN SNAPSHOT ===\\n\\n"
  SUFFIX="\\n\\n=== END SNAPSHOT ===\\n\\nReminder: the snapshot above is historical, not live. If you are about to act on a fact from the snapshot, verify it against the current file or live system first."
  CONTENT="${PREFIX}${RAW}${SUFFIX}"

  cat << HOOKJSON
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "$CONTENT"
  }
}
HOOKJSON
fi

# Emit session_start with source=compact (telemetry — mirrors session-start.sh pattern)
echo "$PAYLOAD" | "C:/Program Files/Python314/python.exe" "$(dirname "$0")/session-start-log.py" 2>/dev/null || true

exit 0
