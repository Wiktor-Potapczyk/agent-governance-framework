# Hook Registry

This framework uses 35 active enforcement hooks across 8 event types, plus four shared libraries (`sidecar_loader.py`, `_governance_logger.py`, `_wiki_citation_logic.py`, `_subagent_quality_logic.py`). Two further hooks ship **opt-in**: present but not registered in the default config: `prose-slop-check.py` and `registry-staleness-check.py` (listed at the foot of the table). The deferred stub `context-fill-log.py` has been moved to `_archived/hooks/` (it was never registered and its module docstring says "DO NOT REGISTER"). Five additional hook scripts (4 Python + 1 PowerShell) live in `hooks/disabled/`: some disabled after an instructive failure, some shipping opt-in/unregistered (e.g. `routing-table-validation.py`): see `disabled/README.md` for each.

## Active Hooks

| Hook | Event | Matcher | Purpose | Blocks? |
|------|-------|---------|---------|---------|
| user-prompt-submit.py | UserPromptSubmit | (all) | Displays context usage bar; injects task-classifier reminder when no classifier output is detected in recent transcript | No |
| skill-routing-check.py | PreToolUse | Skill | Validates that the process skill being invoked matches the TYPE field declared by the task-classifier | Yes |
| bash-safety-guard.py | PreToolUse | Bash | Blocks dangerous shell commands (rm -rf, force-push, sudo, credential exposure patterns) | Yes |
| skill-step-reminder.py | PostToolUse | Skill | After a process skill loads, injects mandatory step reminders so the model does not skip required steps | No |
| subagent-governance.py | SubagentStart | (all) | Injects behavioral guidance into every spawned subagent: cite evidence, use multiple perspectives, apply blind analysis rule | No (additionalContext) |
| subagent-quality-check.py | SubagentStop | (all) | L2 exit gate: checks subagent output for: empty response (<5 chars); error/refusal (short + refusal keyword, **exempted when a result-signal token co-occurs** so a short negative finding passes); missing structure (long output with no list/heading markup **and** no `Label: value` lines or known REPORT header) | Yes (on failure) |
| classifier-field-check.py | Stop | (all) | L1 exit gate: verifies all required classifier fields are present when task-classifier was invoked; self-logs blocks | Yes |
| dispatch-compliance-check.py | Stop | (all) | Verifies that items declared in MUST DISPATCH were actually dispatched during the session; self-logs blocks | Yes |
| governance-log.py | Stop | (all) | Logging only: writes JSONL governance record including IMPLIES text extracted from classifier output | No |
| process-step-check.py | Stop | (all) | L1 exit gate: hard blocks on missing SCOPE or missing QA REPORT; soft logs synthesis gaps and architect-review gaps | Yes (on hard failures) |
| dark-zone-check.py | Stop | (all) | Monitoring only: detects citation patterns and scores severity; never blocks | No |
| agent-dispatch-check.py | PreToolUse | Agent | Advisory governance: logs agent dispatches, registry-exempts process-* skill dispatches, and warns on off-contract dispatches without blocking | No (warns only) |
| memory-dedup-check.py | PreToolUse | Write | Detects near-duplicate memory entries and surfaces an advisory warning when a candidate write overlaps significantly with an existing memory file | No (additionalContext advisory) |
| memory-schema-check.py | PostToolUse | Write\|Edit | Validates memory frontmatter after writes (required fields: name, description, type, confidence, last_verified, expires); logs schema violations | No (logs only) |
| epistemic-check.py | Stop | (all) | Sends Claude's response to Haiku for external evaluation of overconfidence. Adapted from the Trail of Bits anti-rationalization pattern. Blocks when the Haiku evaluator returns a block verdict | Yes |
| session-start-log.py | SessionStart | (all) | Writes a `session_start` event to `governance-log.jsonl` so analytics scripts can detect session boundaries cleanly instead of inferring from first classification entry | No (logging only) |
| work-verification-check.py | Stop | (all) | L1 exit gate: blocks QA/pentest reports filed with zero execution tool uses; also catches inline QA/PENTEST REPORT blocks filed without invoking the corresponding process skill | Yes |
| verifier-gate-check.py | Stop | (all) | Enforces the contract of the `verification-gated-research` skill: if that skill was invoked, blocks completion until a separate verifier agent was dispatched | Yes |
| task-plan-auto-sync.py | Stop | (all) | On Stop events with an OVERALL PASS QA REPORT, locates the matching open task_plan.md item and marks it `[x]` with a summary line | No (logging + edit) |
| session-start-orientation.py | SessionStart | (all) | Reads the active project's STATE.md and open task_plan.md items; emits a plain-English orientation summary as additionalContext | No (additionalContext) |
| wiki-citation-check.py | PostToolUse | Write\|Edit | M2 Layer 2 fabrication mitigation: validates that any Write to a wiki-layer file carries a valid `source:` field with SHA-256 hash matching the cited source file | No (advisory in v1) |
| inbox-auto-ingest.py | PostToolUse | Write\|Edit | Auto-trigger for the Karpathy LLM-Wiki ingest operation: when a file is written or edited in `Inbox/`, emits additionalContext signaling that `process-ingest` should run | No (additionalContext) |
| checkpoint.py | PostToolUse | (all) | Periodic save checkpoint reminder: fires when >30 minutes have elapsed since the last STATE.md save reminder | No (additionalContext) |
| user-prompt-state-inject.py | UserPromptSubmit | (all) | Throttled re-orientation reminder for long-running sessions: re-injects active project STATE.md context when >30 min elapsed or STATE.md changed | No (additionalContext) |
| bias-guard.py | SubagentStart | (all) | Injects the Blind Analysis Rule reminder into evaluator agents to prevent anchoring on delegating-session hypotheses | No (additionalContext) |
| pre-compact.py | PreCompact | (all) | Comprehensive state save before compaction: writes a recovery file containing STATE.md content, open task plans, and recent transcript context | No (state save) |
| prose-slop-check.py | PostToolUse | Write\|Edit | **Opt-in (not default-registered)**: flags LLM-slop vocabulary (delve, tapestry, multifaceted, furthermore, foster…) in generated prose; corpus-calibrated to 0 false-positives; scoped to prose, not code | No (warns only) |
| registry-staleness-check.py | SessionStart | (all) | **Opt-in (not default-registered)**: warns when `registry.json` is older than a threshold, naming the regen command; silent when fresh | No (additionalContext) |

## Helper Scripts (not hooks)

| Script | Purpose |
|--------|---------|
| `mine_governance.py` | Pure-stdlib governance-log failure miner: imported by the `process-governance-mine` skill. Scans `governance-log.jsonl` for recurring failure patterns keyed by (event_label, agent_type, hook, normalized_reason); returns flagged sig records sorted severity-high-first. Also runnable standalone via `python mine_governance.py`. Not a hook: never registered in settings. |

## Opt-in / Unregistered Hooks

These hooks ship in `hooks/disabled/` and are **not registered by default**. Copy to your active `hooks/` directory and add to `settings.json` / `settings.local.json` to arm.

| Hook | Event | Purpose | Blocks? |
|------|-------|---------|---------|
| `routing-table-validation.py` | PreToolUse Edit\|Write\|MultiEdit | Denies edits to `CLAUDE.md` or any `SKILL.md` that introduce a broken dispatch-name reference: an agent name in a MUST DISPATCH line, `subagent_type:` field, or routing-table row that does not resolve in `registry.json`. Four-gate design: target-file check, dispatch-position detection, agent-name shape check, registry lookup. Fail-open on any parse error or unreadable registry. Add retired names to `DEPRECATED_ALLOWLIST` in the script to prevent false positives after renames. | Yes (on gate hit) |

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

Stop hooks fire when Claude is about to end its turn. A Stop hook can block the turn from ending by outputting `{"continue": true}`: this forces Claude to keep working (e.g., to complete a missing QA report). Exit with code 0 and no blocking output to let the turn end normally.

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
- **Self-log all blocks.** Write a JSONL record when a hook blocks something: you need this data to tune the hook over time.
- **Hardcode a transcript window** (e.g., 200KB). Don't read unbounded transcripts.
- **Strip code fences** before scanning transcript text. The model's output is often wrapped in markdown.

## Observability

The governance hooks emit structured JSONL events that can be visualized locally.

**Governance log:** `governance-log.py` (Stop hook) writes one line per session end to `.claude/hooks/governance-log.jsonl`. Records include the IMPLIES text from the task-classifier, task type, dispatched agents/skills, and QA outcome.

**Dashboard:** a reference observability dashboard lives at `.claude/observability-dashboard/`:

- `server.py`: minimal HTTP server exposing `/api/events` (raw governance-log stream) and `/api/query` (aggregations)
- `app.js`: front-end renderer
- `index.html`: layout
- `styles.css`: presentation
- `vendor/chart.umd.min.js`: vendored Chart.js (pinned, offline-capable)

Run locally from the dashboard directory:

```bash
python server.py
```

The dashboard surfaces per-session classifier output (IMPLIES, TASK TYPE, MUST DISPATCH), dispatch compliance outcomes (what was declared vs what was invoked), QA FAIL counts from `qa_fail_reported` events, and turn-level token breakdown. It is a read-only reporting layer over the governance log: no hook behavior depends on it.
