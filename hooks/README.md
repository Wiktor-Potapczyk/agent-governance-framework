# Hook Registry

This framework uses 11 active hooks across 6 event types. Two additional hooks are disabled — see `disabled/README.md` for why.

## Active Hooks

| Hook | Event | Matcher | Purpose | Blocks? |
|------|-------|---------|---------|---------|
| user-prompt-submit.py | UserPromptSubmit | (all) | Displays context usage bar; injects task-classifier reminder when no classifier output is detected in recent transcript | No |
| skill-routing-check.py | PreToolUse | Skill | Validates that the process skill being invoked matches the TYPE field declared by the task-classifier | Yes |
| bash-safety-guard.py | PreToolUse | Bash | Blocks dangerous shell commands (rm -rf, force-push, sudo, credential exposure patterns) | Yes |
| skill-step-reminder.py | PostToolUse | Skill | After a process skill loads, injects mandatory step reminders so the model does not skip required steps | No |
| subagent-governance.py | SubagentStart | (all) | Injects behavioral guidance into every spawned subagent: cite evidence, use multiple perspectives, apply blind analysis rule | No (additionalContext) |
| subagent-quality-check.py | SubagentStop | (all) | L2 exit gate — checks subagent output for: empty response (<5 chars), error/refusal (<100 chars + refusal keywords), wall-of-text (>500 chars with no structure) | Yes (on failure) |
| classifier-field-check.py | Stop | (all) | L1 exit gate — verifies all required classifier fields are present when task-classifier was invoked; self-logs blocks | Yes |
| dispatch-compliance-check.py | Stop | (all) | Verifies that items declared in MUST DISPATCH were actually dispatched during the session; self-logs blocks | Yes |
| governance-log.py | Stop | (all) | Logging only — writes JSONL governance record including IMPLIES text extracted from classifier output | No |
| process-step-check.py | Stop | (all) | L1 exit gate — hard blocks on missing SCOPE or missing QA REPORT; soft logs synthesis gaps and architect-review gaps | Yes (on hard failures) |
| dark-zone-check.py | Stop | (all) | Monitoring only — detects citation patterns and scores severity; never blocks | No |

## How Hooks Work

### The Basics

Claude Code hooks are shell commands that fire at specific lifecycle events. Each hook receives a JSON payload on stdin and can respond via stdout.

The hook runner passes context as JSON. For example, a `PreToolUse` hook for `Bash` receives:

```json
{
  "tool_name": "Bash",
  "tool_input": {
    "command": "rm -rf /tmp/test"
  },
  "session_id": "abc123"
}
```

### The Three Response Types

**1. Allow (default)**
Exit with code 0 and no output, or output `{"continue": true}`. The tool call proceeds.

**2. Block**
Output JSON with `"continue": false` and a `"reason"` field. The tool call is cancelled and the reason is shown to the model.

```json
{"continue": false, "reason": "Dangerous command blocked: rm -rf detected"}
```

**3. additionalContext (SubagentStart only)**
Output JSON with an `"additionalContext"` field. The text is injected into the subagent's context as a `<system-reminder>`.

```json
{"additionalContext": "Always cite evidence. Use multiple analytical perspectives."}
```

### Stop Hook Behavior

Stop hooks fire when Claude is about to end its turn. A Stop hook can block the turn from ending by outputting `{"continue": true}` — this forces Claude to keep working (e.g., to complete a missing QA report). Exit with code 0 and no blocking output to let the turn end normally.

### Reading the Transcript

Many hooks in this framework read the session transcript to detect what happened (e.g., was the task-classifier invoked? were agents dispatched?). The transcript is available at a path provided in the hook payload under `transcript_path`. Read the last 200KB to avoid memory issues on long sessions.

Example pattern:
```python
import json, sys

payload = json.load(sys.stdin)
transcript_path = payload.get("transcript_path", "")

with open(transcript_path, "r", encoding="utf-8") as f:
    transcript = f.read()[-200000:]  # last 200KB

if "task-classifier" not in transcript.lower():
    print(json.dumps({"continue": False, "reason": "task-classifier not invoked"}))
    sys.exit(0)
```

## Adding Your Own Hooks

1. Create a Python script in `hooks/` that reads JSON from stdin and writes JSON to stdout.
2. Register it in `.claude/settings.json` (global) or `.claude/settings.local.json` (project-level). See `settings/settings.json.example` for the full registration format.
3. Test it by triggering the relevant event and checking Claude Code's hook output in the terminal.

**Design principles learned from this framework:**

- Hooks should verify **process compliance**, not judge output quality. Compliance is binary and detectable; quality is semantic and requires understanding.
- Hooks are **floors** (minimum standards), not ceilings. Blocking legitimate actions because they don't match a narrow allowlist destroys trust.
- **Self-log all blocks.** Write a JSONL record when a hook blocks something — you need this data to tune the hook over time.
- **Hardcode a transcript window** (e.g., 200KB). Don't read unbounded transcripts.
- **Strip code fences** before scanning transcript text. The model's output is often wrapped in markdown.
