#!/usr/bin/env python3
"""PostToolUse hook: periodic save checkpoint reminder."""
import json
import os
import time

CHECKPOINT_FILE = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), ".claude", "last-checkpoint")

now = int(time.time())

# Initialize if missing
if not os.path.exists(CHECKPOINT_FILE):
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(str(now))

try:
    with open(CHECKPOINT_FILE, "r") as f:
        last = int(f.read().strip())
except (ValueError, FileNotFoundError):
    last = now

diff = now - last

# Silent if fired too recently
if diff < 60:
    print("{}")
    raise SystemExit(0)

# Update timestamp
with open(CHECKPOINT_FILE, "w") as f:
    f.write(str(now))

KNOWLEDGE_REMINDER = (
    "[SAVE CHECK] Scan BOTH tool output AND recent conversation for persistable changes. "
    "Route: task completed/discovered->task_plan.md | blocker/decision/project state->Projects/[Name]/STATE.md "
    "| user correction/preference/standing directive->.claude/agent-memory/planner/+MEMORY.md "
    "| durable fact (ID,URL,limit,API behavior)->STATE.md or owning spec file | default->STATE.md. "
    "SKIP if: (1) read-only op with no new findings, (2) info already in target file, (3) nothing actionable changed. "
    "If saving: do it NOW inline, then continue."
)

if diff >= 300:
    context = f"[CHECKPOINT] 5min since last save. Write current status to STATE.md NOW. {KNOWLEDGE_REMINDER}"
else:
    context = KNOWLEDGE_REMINDER

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": context,
    }
}))
