# Hooks Reference

This is a Reference-mode document per the [documentation standard](../documentation-standard.md): attributes tables, no tutorial prose. **Code is the source of truth**: if a field here disagrees with the `.py` file, the code wins. Where a `test_<name>.py` file exists in `hooks/`, it is the authoritative enumeration of branches; the Logical-paths cell ends with a pointer to that file.

Every hook file in `hooks/` is listed below, whether or not it is registered by default. Library modules (`_`-prefixed), test files (`test_`-prefixed), and the `disabled/` subdirectory are excluded from the per-hook sections. An unregistered hook that still ships at the top level gets a full section with **Registered in** reading "opt-in": it is inert until you add it to your settings, and the section tells you what arming it would do. Files under `disabled/`, plus the standalone utilities that are not hooks at all, appear only in the [Disabled / opt-in hooks](#disabled--opt-in-hooks) table at the end.

---

## Summary table

| Hook file | Event | Action (brief) | Registered by default? |
|---|---|---|---|
| `session-start-log.py` | SessionStart | Log session_start to governance-log.jsonl | Yes: `settings.json.template` |
| `session-start-orientation.py` | SessionStart | Inject project STATE + task context as additionalContext | Yes: `settings.json.template` |
| `registry-staleness-check.py` | SessionStart | Warn if registry.json is >7 days old | No: opt-in |
| `user-prompt-submit.py` | UserPromptSubmit | Inject context bar + classifier enforcement reminder | Yes: `settings.json.template` |
| `user-prompt-state-inject.py` | UserPromptSubmit | Inject STATE.md orientation (throttled 30min) | Yes: `settings.json.template` |
| `skill-routing-check.py` | PreToolUse (Skill) | Deny process-skill if routing mismatches last TASK TYPE | Yes: `settings.json.template` |
| `bash-safety-guard.py` | PreToolUse (Bash) | Block dangerous shell commands | Yes: `settings.json.template` |
| `agent-dispatch-check.py` | PreToolUse (Agent) | Warn when dispatched agent not in MUST DISPATCH list | Yes: `settings.json.template` |
| `memory-dedup-check.py` | PreToolUse (Write) | Soft-warn on duplicate memory file (Jaccard ≥ 0.65) | Yes: `settings.json.template` |
| `reviewer-scope-violation-check.py` | PreToolUse (Write\|Edit\|MultiEdit) | Block reviewer agents from editing non-report files | Yes: `settings.json.template` |
| `mcp-circuit-breaker.py` | PreToolUse (mcp__.*) | Trip breaker after ≥3 MCP failures in 600s window | Yes: `settings.json.template` |
| `skill-step-reminder.py` | PostToolUse (Skill) | Inject mandatory process-step reminder for process-* skills | Yes: `settings.json.template` |
| `memory-schema-check.py` | PostToolUse (Write\|Edit) | Soft-warn on missing/invalid memory frontmatter fields | Yes: `settings.json.template` |
| `tag-variant-check.py` | PostToolUse (Write) | Advisory on non-canonical tags in .md frontmatter | Yes: `settings.json.template` |
| `mcp-circuit-breaker-record.py` | PostToolUse (mcp__.*) | Record MCP tool result as success/failure to breaker state | Yes: `settings.json.template` |
| `wiki-citation-check.py` | PostToolUse (Write\|Edit) | Validate source: field + SHA integrity on wiki-layer files | Yes: `settings.json.template` |
| `unicode-hygiene-check.py` | PostToolUse (Write\|Edit) | Warn on invisible/bidirectional Unicode in raw-layer arrivals | No: opt-in |
| `inbox-auto-ingest.py` | PostToolUse (Write\|Edit) | Trigger process-ingest when file written under Inbox/ | Yes: `settings.json.template` |
| `checkpoint.py` | PostToolUse (no matcher) | Inject knowledge reminder at ≥60s; CHECKPOINT notice at ≥300s | Yes: `settings.json.template` |
| `subagent-governance.py` | SubagentStart | Inject governance additionalContext; log agent_type | Yes: `settings.json.template` |
| `subagent-scope-check.py` | SubagentStart + SubagentStop | Capture/diff git status baseline per subagent | Yes: `settings.json.template` |
| `bias-guard.py` | SubagentStart | Inject Blind Analysis Rule for evaluator agents | Yes: `settings.json.template` |
| `subagent-quality-check.py` | SubagentStop | Block on structural quality violations in agent output | Yes: `settings.json.template` |
| `classifier-field-check.py` | Stop | Block when required classifier fields missing | Yes: `settings.json.template` |
| `dispatch-compliance-check.py` | Stop | Block when MUST DISPATCH items not fulfilled | Yes: `settings.json.template` |
| `governance-log.py` | Stop | Append turn_summary to governance-log.jsonl | Yes: `settings.json.template` |
| `process-step-check.py` | Stop | Block/log on missing process-skill steps | Yes: `settings.json.template` |
| `dark-zone-check.py` | Stop | Log dark-zone metric (agent citations vs dispatches) | Yes: `settings.json.template` |
| `work-verification-check.py` | Stop | Block lazy QA, premature escalation, fabrication claims | Yes: `settings.json.template` |
| `token-breakdown.py` | Stop | Log per-turn token breakdown telemetry | Yes: `settings.json.template` |
| `read-before-edit-check.py` | Stop | Log edit-without-read instrumentation | Yes: `settings.json.template` |
| `verifier-gate-check.py` | Stop | Block if verification-gated-research ran without verifier agent | Yes: `settings.json.template` |
| `task-plan-auto-sync.py` | Stop | Mark task_plan.md item done on QA PASS | Yes: `settings.json.template` |
| `pre-compact.py` | PreCompact | Write recovery snapshot before context compaction | Yes: `settings.json.template` |
| `post-compact.py` | PostCompact | Record the compaction event and write a staleness marker | No: opt-in |
| `lint-cadence-trigger.py` | SessionStart | Suggest overdue periodic sweeps from four cadence state files | No: opt-in |
| `mcp-qmd-health-probe.py` | SessionStart | Probe the qmd CLI and pre-seed the circuit breaker when it is dead | No: opt-in |
| `qmd-recall-nudge.py` | PreToolUse (Grep) | Remind to search via qmd when grepping a qmd-indexed corpus | No: opt-in |
| `raw-frontmatter-check.py` | PostToolUse (Write) | Advisory on missing date/tags/status in raw-layer Markdown | No: opt-in |
| `prose-slop-check.py` | PostToolUse (Write) | Warn on LLM-register slop words in wiki/work prose | No: dormant, not registered |
| `mcp-irreversible-guard.py` | PreToolUse (`mcp__.*`) | Gate-1 deny on enumerated destructive MCP tools | Yes: `settings.json.template` |
| `transition-gate-check.py` | PreToolUse (Write/Edit) | Gate phase transitions on recorded evidence | No: opt-in |
| `git-credential-scope-check.py` | SessionStart | Warn when git credential scope is broader than the repo needs | No: opt-in |
| `hook-write-regression-gate.py` | PostToolUse (Write/Edit) | Block hook edits that regress the test suite | No: opt-in |
| `session-work-orientation.py` | SessionStart | Report work/ file count, stale files, closed-track exhaust for the active project | Yes: `settings.json.template` |
| `memory-nudge.py` | SessionStart + Stop | Count turns since last memory write; nudge past the quiet-turn threshold | Yes: `settings.json.template` |
| `qmd-rerank-default-guard.py` | PreToolUse (`mcp__qmd__query`) | Deny a qmd query that omits `rerank: false` on CPU-only machines | Yes: `settings.json.template` |
| `aggregate-write-guard.py` | PreToolUse (Write\|Edit\|MultiEdit) | Deny wholesale-loss writes to the three singleton aggregate files | Yes: `settings.json.template` |
| `memory-context-guard.py` | PreToolUse (Write\|Edit\|MultiEdit) | Advisory on subagent-context writes into the memory folder | Yes: `settings.json.template` |
| `plain-language-guard.py` | PostToolUse (Write\|Edit) | Warn on plain-language rule violations in documentation surfaces | Yes: `settings.json.template` |
| `claude-md-provenance-check.py` | PostToolUse (Write\|Edit) | Warn when a rule-shaped CLAUDE.md change carries no origin citation | Yes: `settings.json.template` |
| `deferral-resurface.py` | PostToolUse (Write\|Edit) | Surface deferred items when a project is being closed out | Yes: `settings.json.template` |
| `state-reconcile-check.py` | PostToolUse (Write\|Edit) | Advisory when a STATE.md/task_plan.md write contradicts text left below it | Yes: `settings.json.template` |

---

## SessionStart hooks

### `session-start-log.py`

| Attribute | Value |
|---|---|
| **Event** | SessionStart |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Writes one `session_start` event to `hooks/governance-log.jsonl`. |
| **Inputs** | stdin JSON payload: `transcript_path`, `agent_type`, `session_id` (standard SessionStart fields). |
| **Outputs / Side-effects** | Appends one JSONL line to `hooks/governance-log.jsonl`. Fields: `ts`, `schema=2`, `event=session_start`, `session`, `source` (startup/resume/clear/compact). No stdout. |
| **Logical paths** | Parse payload → determine source value from session context → write JSONL entry → exit 0. All errors swallowed silently. |
| **Failure mode** | Fail-open: any exception is caught and discarded; exit 0 always. |
| **Rationale** | Provides session-boundary anchors in governance-log.jsonl so downstream analytics can compute per-session event sequences and duration. |

---

### `session-start-orientation.py`

| Attribute | Value |
|---|---|
| **Event** | SessionStart |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Injects a project-state orientation block as `additionalContext`: active project STATE.md summary + open task_plan items + recent decisions. |
| **Inputs** | stdin JSON payload. Reads: project override file, STATE.md of most-recently-modified project, task_plan.md, cost-summary.py output (best-effort). |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` JSON containing orientation block. No file writes. |
| **Logical paths** | Project detection: override file present → use it; else walk projects for most-recently-modified STATE.md; else fallback empty. Read STATE.md status + last_action → read task_plan.md open items (cap 10) → read recent decisions (cap 3) → call cost-summary.py (best-effort) → emit orientation block. Empty context path: any read failure → emit `{}`. |
| **Failure mode** | Fail-open: all read failures caught; emits empty context rather than blocking. |
| **Rationale** | Bootstraps each session with current project state so the model does not rely on stale memory or have to re-read STATE.md manually. |

---

### `registry-staleness-check.py`

| Attribute | Value |
|---|---|
| **Event** | SessionStart |
| **Matcher** | none |
| **Registered in** | Not registered by default: opt-in |
| **Action** | Reads `registry.json` age from `generated_at` field (or file mtime fallback). Emits advisory additionalContext when age >7 days. Silent when fresh. |
| **Inputs** | stdin JSON (consumed, not used). Reads `{{VAULT_ROOT}}/.claude/registry.json`. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` advisory string (only when stale or missing). No file writes. |
| **Logical paths** | Registry missing → emit gentle "generate it" note. Registry age ≤ 7 days → emit nothing (silent). Registry age > 7 days → emit advisory with day count and command. Parse/read failure → `age_days = None` → treats as missing → gentle note. |
| **Failure mode** | Fail-open: all exceptions caught; empty string → no stdout. |
| **Rationale** | Keeps the asset inventory (`registry.json`) from silently drifting stale without requiring a calendar-based reminder mechanism. |

---

### `lint-cadence-trigger.py`

| Attribute | Value |
|---|---|
| **Event** | SessionStart |
| **Matcher** | none |
| **Registered in** | Not registered by default: opt-in |
| **Action** | Reads four cadence state files and emits a "consider running" suggestion for each sweep whose last run is older than its cadence, or whose state file is absent. Cadences: lint 7 days, governance-mine 7 days, work-triage 7 days, setup-audit 30 days. Also surfaces an ingest backlog older than 48 hours and unclosed governance-mine proposals. |
| **Inputs** | stdin JSON payload (consumed). Reads `hooks/_state/lint-cadence.json`, `hooks/_state/governance-mine-cadence.json`, `hooks/_state/setup-audit-cadence.json`, `hooks/_state/work-triage-cadence.json`, the miner resolved ledger, and the most recent governance-mine proposal sheet. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` containing one line per overdue sweep. Bootstraps a missing state file so the first run establishes a baseline instead of nagging every session. |
| **Logical paths** | For each cadence: state file missing → bootstrap it and suggest; `last_iso` older than the cadence → suggest with a day count; otherwise silent. Ingest backlog and proposal-closure suggestions are computed independently and appended. All suggestions empty → no stdout. |
| **Failure mode** | Fail-open: every read is guarded; a parse error is treated as "no state" rather than an error. Never blocks. |
| **Rationale** | Periodic sweeps that depend on the operator remembering them do not happen. Deriving the reminder from a state file makes the cadence self-tracking, and bootstrapping on first sight avoids a permanent false alarm. |

---

### `mcp-qmd-health-probe.py`

| Attribute | Value |
|---|---|
| **Event** | SessionStart |
| **Matcher** | none |
| **Registered in** | Not registered by default: opt-in |
| **Action** | Runs the qmd CLI once (`status`) at session start. On failure, seeds the MCP circuit-breaker state and emits a loud warning so the session falls back to Grep/Read instead of burning turns on a dead recall layer. |
| **Inputs** | stdin JSON payload. Resolves the CLI dynamically from `.mcp.json` on every run: `mcpServers.qmd` → `command` plus the first `args` element ending in `.js`. Never hardcodes a path. Probe timeout 20 seconds. |
| **Outputs / Side-effects** | Writes `hooks/_state/mcp-circuit-breaker.json` (failure or success record for the `qmd` server key). stdout: `additionalContext` warning on failure or on unresolvable configuration. |
| **Logical paths** | `.mcp.json` missing, unparseable, no `qmd` entry, or no `.js` argument → emit "recall-layer health UNKNOWN" and exit 0. Probe exits non-zero or times out → record failure, warn. Probe succeeds → record success, silent. |
| **Failure mode** | Fail-open on the session, fail-loud on the configuration: an unresolvable config is reported rather than silently skipped, because a silent skip is indistinguishable from a healthy probe. |
| **Rationale** | The circuit breaker only observes calls the session already made, so a server that is dead before the first call stays invisible until a turn is wasted on it. This closes the cold-start gap. **Known limitation:** the CLI probe verifies the binary and the on-disk index, not the live MCP stdio transport; a transport that dies mid-session is still only caught by the PostToolUse breaker half. |

---

### `git-credential-scope-check.py`

| Attribute | Value |
|---|---|
| **Event** | SessionStart |
| **Matcher** | `startup`, `resume` |
| **Registered in** | not registered by default (opt-in) |
| **Action** | Warns when the configured git credential scope is broader than the current repository requires. |
| **Inputs** | git configuration for the active repository. |
| **Outputs / Side-effects** | stdout: `additionalContext` warning; never blocks. |
| **Logical paths** | Read the credential helper configuration and remote. Compare configured scope against what the repo needs. Broader than necessary, warn once per session. Otherwise silent. |
| **Failure mode** | Fail-open, advisory only. |
| **Rationale** | Credential scope is invisible until it leaks. Surfacing it at session start costs nothing and catches over-broad configuration before a push. |

---

### `session-work-orientation.py`

| Attribute | Value |
|---|---|
| **Event** | SessionStart |
| **Matcher** | (none) |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Emits one orientation line for the active project's `work/` directory: file count, files untouched over 30 days, and exhaust files belonging to closed tracks. |
| **Inputs** | stdin JSON payload: `cwd` (preferred project signal). Filesystem: `Projects/*/` scan when `cwd` does not resolve. |
| **Outputs / Side-effects** | stdout: `additionalContext` orientation line. No file writes. |
| **Logical paths** | `cwd` inside a real `Projects/<name>/` → direct match. Otherwise one `os.scandir` pass over `Projects/*/` picks the active project. No project resolvable → silent. Empty `work/` → silent. See `test_session_work_orientation.py`. |
| **Failure mode** | Fail-open: any exception exits silently. |
| **Rationale** | Close-out metabolism: stale `work/` files are invisible until a maintenance sweep; a one-line count at session start keeps the surface observable. |

---

### `memory-nudge.py`

| Attribute | Value |
|---|---|
| **Event** | SessionStart + Stop (one file, two registrations, branching on `hook_event_name`) |
| **Matcher** | (none) |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Stop: increments a turns-since-last-memory-write counter (skipping `stop_hook_active` continuations so Stop-chains do not double-count). SessionStart: reminds when the counter passes the quiet-turn threshold; "nothing to save" is a valid outcome. |
| **Inputs** | stdin JSON payload: `hook_event_name`, `stop_hook_active`. State file under `hooks/_state/`. |
| **Outputs / Side-effects** | Stop: state-file increment, prints nothing ever. SessionStart: `additionalContext` reminder past the threshold. |
| **Logical paths** | Stop with `stop_hook_active: true` → no increment. Memory write observed → counter reset. Counter below threshold → silent. See `test_memory_nudge.py`. |
| **Failure mode** | Fail-open: state I/O errors are swallowed; never blocks. |
| **Rationale** | Memory-persistence discipline: the main session owns the memory folder, and a quiet-turn counter surfaces drift toward never persisting anything. |

---

## UserPromptSubmit hooks

### `user-prompt-submit.py`

| Attribute | Value |
|---|---|
| **Event** | UserPromptSubmit |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Reads transcript for token counts + model, builds a context bar and injects classifier enforcement reminder; escalates at ≥50% context utilization. |
| **Inputs** | stdin JSON payload: `transcript_path`, `effort`. Reads transcript tail (100KB window) for token count and model fields. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` containing context bar (`CTX ▰▱▱ N% \| XK/YK \| model`) + classifier reminder text. At ≥50% adds `SAVE ENFORCEMENT` prefix. |
| **Logical paths** | Skip if subagent invocation or trivial/low-effort prompt. Parse transcript tail → compute token ratio → build context bar → scan for depth signals (regex) → escalate classifier reminder if depth signals found → emit. No depth signals → standard reminder. Subagent/trivial → emit nothing. authoritative branch set: `test_user_prompt_submit.py` |
| **Failure mode** | Fail-open: parse errors silently skipped; empty or no output on any exception. |
| **Rationale** | Provides per-prompt context budget awareness and keeps the task-classification requirement visible without relying on model memory across turns. |

---

### `user-prompt-state-inject.py`

| Attribute | Value |
|---|---|
| **Event** | UserPromptSubmit |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Injects a brief STATE.md orientation (status, last_action, top 5 open tasks) as additionalContext. Throttled: fires at most once per 30 minutes, or when STATE.md changes, or when the project changes. |
| **Inputs** | stdin JSON payload: `transcript_path`, `effort`, `agent_type`. Reads active project STATE.md and task_plan.md. Reads/writes atomic throttle state file. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` with STATE orientation block. Writes atomic throttle state file. |
| **Logical paths** | Skip if subagent invocation. Skip if effort.level == "low". Skip if prompt is trivial (heuristic). Throttle check: <30min since last fire AND STATE.md mtime unchanged AND same project → skip. Else: read STATE.md → extract status + last_action → read task_plan top 5 open items → emit orientation. Any read failure → emit empty (fail-open). |
| **Failure mode** | Fail-open: all file-read failures caught; throttle state write uses atomic temp-rename pattern to avoid corruption. |
| **Rationale** | Reduces the need for the model to proactively re-read STATE.md each turn while avoiding per-prompt noise via throttling. |

---

## PreToolUse hooks

### `skill-routing-check.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `Skill` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | For process-* skills: reads last TASK TYPE from transcript and denies invocation if the routing table maps the task type to a different process skill. Non-process skills always pass. **B-0 fix (2026-06-11):** a Workflow tool_use whose name/scriptPath basename maps to a process-* skill resets the routing context: any Skill invocation following a Workflow-dispatched process skill is not blocked by the stale pre-Workflow classification. |
| **Inputs** | stdin JSON payload: `tool_name`, `tool_input` (skill name, args), `transcript_path`. Reads 200KB transcript tail. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `permissionDecision: deny` + reason (on mismatch); nothing on allow. |
| **Logical paths** | Non-process skill → allow immediately. Process skill invoked → scan transcript for routing events (TASK TYPE assertions and Workflow tool_use blocks). Last routing event is a Workflow dispatch of a process-* skill → clear last_type (routing context consumed) → allow. Quick classification → allow. No classification → allow. Classification found → look up ROUTING table (research→process-research, analysis→process-analysis, content/build→process-build, planning→process-planning, compound→process-analysis) → skill matches expected → allow. Skill does not match → deny with explanation showing correct skill. authoritative branch set: `test_skill_routing_check.py` |
| **Failure mode** | Fail-open: parse errors, missing transcript → allow. |
| **Rationale** | Enforces that the model routes tasks to the correct process skill rather than calling a mismatched skill (e.g. calling process-build for a research task). B-0 prevents false denials when a process skill runs as a Workflow and a helper Skill follows. |

---

### `bash-safety-guard.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `Bash` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Blocks shell commands that match dangerous patterns before they execute. |
| **Inputs** | stdin JSON payload: `tool_input.command` (the shell command string). |
| **Outputs / Side-effects** | stdout: `{"decision": "block", "reason": "..."}` on match; nothing on allow. |
| **Logical paths** | Pre-process command through `strip_inert_contexts()` to remove string literals and reduce false positives. Match against `BLOCKED_PATTERNS`: `rm -rf`, `git push --force*`, `git reset --hard`, `git clean`, credential file reads (`cat ~/.ssh/id_rsa`, `cat ~/.aws/credentials`, etc.), `sudo`, `chmod 777`, `kill -9`, `n8n_delete_workflow`. Check for Windows reserved filenames (`CON`, `PRN`, `AUX`, `COM*`, `LPT*`). Any match → block. No match → allow. Parse error → allow (fail-open). |
| **Failure mode** | Fail-open: any exception exits 0 without blocking. |
| **Rationale** | Provides a last-resort gate against destructive or credential-exposing shell commands; complements the model's own judgment rather than replacing it. |

---

### `agent-dispatch-check.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `Agent` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Advisory warning (not block) when dispatched agent is not in the MUST DISPATCH list extracted from the transcript. |
| **Inputs** | stdin JSON payload: `tool_input` (agent description/type), `transcript_path`. Reads 200KB transcript tail. |
| **Outputs / Side-effects** | stderr: advisory warning text (warn-downgrade: surfaced, never a block JSON). Logs event to governance-log.jsonl. |
| **Logical paths** | Agent type in `ALWAYS_ALLOW` (general-purpose, explore, plan, bash) → allow silently. Transcript has no MUST DISPATCH block → allow. MUST DISPATCH block present → extract declared agent names via `extract_dispatch_names()` → expand aliases via `SKILL_AGENT_ALIASES` → dispatched agent in expanded set → allow + log exemption. process-* routing skill present in transcript → dispatched agent in registry → allow + log exemption. Otherwise → emit advisory warning to additionalContext + log event. authoritative branch set: `test_agent_dispatch_check.py` |
| **Failure mode** | Fail-open: parse errors, missing transcript → allow silently. |
| **Rationale** | Creates a soft signal when agents are dispatched outside declared MUST DISPATCH scope, supporting compliance measurement without blocking legitimate adaptive dispatches. |

---

### `memory-dedup-check.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `Write` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Soft-warns (never blocks) when a memory file being written has a description field with Jaccard similarity ≥ 0.65 to an existing file in the same memory directory. |
| **Inputs** | stdin JSON payload: `tool_input.file_path`, `tool_input.content`. |
| **Outputs / Side-effects** | stdout: flat `{"additionalContext": …}` advisory JSON (no `hookSpecificOutput` wrapper; only on duplicate detection). No file writes. |
| **Logical paths** | Target path is not under `.claude/projects/*/memory/` → skip silently. Target is MEMORY.md (the index) → skip. No `description:` field in incoming content → skip. Extract `description:` token set → iterate existing `.md` files in memory dir → compute Jaccard against each file's `description:` tokens → any score ≥ 0.65 → emit advisory with matching file name. No match → silent. |
| **Failure mode** | Fail-open: all I/O errors caught; emits nothing and continues. |
| **Rationale** | Reduces memory folder bloat by surfacing near-duplicate facts before they are written, without blocking legitimate closely-related entries. |

---

### `reviewer-scope-violation-check.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `Write\|Edit\|MultiEdit` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Blocks adversarial-reviewer, architect-reviewer, and code-reviewer agents from writing to any existing non-report file. |
| **Inputs** | stdin JSON payload: `tool_input.file_path`, `agent_type` (or transcript-derived agent name). |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `permissionDecision: deny` + reason (on violation); nothing on allow. |
| **Logical paths** | Current agent not a reviewer type → allow. Reviewer detected (primary: `agent_type` field; fallback: scan transcript for `name:` frontmatter line): Rule A: path matches `work/YYYY-MM-DD-*-review-*.md` → allow (review report). Rule C: file does not exist on disk (new file) → allow. All other existing non-report paths → deny with scope-violation message. |
| **Failure mode** | Fail-open: agent detection failures default to allow. |
| **Rationale** | Enforces the Blind Analysis Rule: reviewer agents should produce review documents, not edit the artifacts they are reviewing. |

---

### `mcp-circuit-breaker.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `mcp__.*` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Trips a per-server circuit breaker after ≥3 failures in a 600-second window; blocks further MCP calls during a 1800-second cooldown. |
| **Inputs** | stdin JSON payload: `tool_name` (format: `mcp__<server>__<tool>`). Reads/writes `hooks/_state/mcp-circuit-breaker.json`. Reads `MCP_HEALTH_FAIL_OPEN`, `MCP_BREAKER_RESET` environment variables. |
| **Outputs / Side-effects** | stdout: `{"decision": "block", "reason": "..."}` when breaker is open; nothing when allowing. Reads state file; writes are done by the companion `mcp-circuit-breaker-record.py` (PostToolUse). |
| **Logical paths** | `MCP_HEALTH_FAIL_OPEN=1` → allow all (fail-open override). `MCP_BREAKER_RESET=<server>` → clear state for that server → allow. Extract server name from tool_name. Read state file (missing → allow). Breaker open AND cooldown not elapsed → block with message. Breaker open AND cooldown elapsed → allow (auto-reset). Breaker closed → allow. State file corrupt/unreadable → allow (fail-open). |
| **Failure mode** | Fail-open: any I/O error → allow. |
| **Rationale** | Prevents runaway retry loops that hammer a failing MCP server, consuming budget without making progress. |

---

### `mcp-irreversible-guard.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `mcp__.*` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Denies MCP tool calls that fall on the canonical irreversible surface. The MCP arm of Gate 1; `bash-safety-guard.py` is the shell arm. |
| **Inputs** | stdin JSON payload: `tool_name` and `tool_input`. |
| **Outputs / Side-effects** | stdout: `{"permissionDecision": "deny", ...}` on match; nothing on allow. |
| **Logical paths** | Import the canonical surface from `_irreversible_surface.py`. Match `tool_name` against the **enumerated** destructive-tool list, never a blanket `mcp__.*` deny, which would block every MCP read and train the operator to bypass reflexively. On match, deny and emit the reason so the agent can surface a decision brief. No match, allow. Import failure or parse error, allow. |
| **Failure mode** | Fail-open: any exception exits 0 without blocking. |
| **Rationale** | Under universal `bypassPermissions` an `ask` decision is a no-op, so `deny` is the only decision that actually stops an irreversible MCP call. See ADR-0007 and `docs/concepts/two-gate-autonomy.md`. |

---

### `transition-gate-check.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `Write|Edit|MultiEdit` |
| **Registered in** | not registered by default (opt-in) |
| **Action** | Gates a declared phase transition on recorded evidence rather than assertion. |
| **Inputs** | stdin JSON payload: `tool_input.file_path` and content; project state files. |
| **Outputs / Side-effects** | stdout: warning or block payload when a transition is claimed without supporting evidence. |
| **Logical paths** | Detect a phase-transition edit to a state file. Look for the evidence the transition requires. Evidence present, allow. Absent, surface the gap. |
| **Failure mode** | Fail-open. |
| **Rationale** | Phase transitions are the point where unverified optimism enters project state and persists. |

---

### `qmd-recall-nudge.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `Grep` |
| **Registered in** | Not registered by default: opt-in |
| **Action** | When a `Grep` targets a qmd-indexed corpus (the memory folder or the KB wiki directory), injects a one-line reminder to search via `mcp__qmd__query` first. Warn-only: the Grep still runs. |
| **Inputs** | stdin JSON payload: `tool_name`, `tool_input.path`. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` reminder naming the matching collection. No file writes, no block. |
| **Logical paths** | Tool is not `Grep` → silent. Path does not resolve under the memory folder or the KB directory → silent. Path matches → emit the reminder naming the collection (`memory` or `agr-kb`). Deliberately does NOT fire on `Read`: fetching a known file by path is legitimate and qmd's `get` is optional there, not a correction. |
| **Failure mode** | Fail-open: exit 0 always, never blocks the Grep. |
| **Rationale** | A soft doctrine mention decays to roughly 25% adherence, so the session reaches for raw `Grep` over a corpus that has a purpose-built search index. Scoping the nudge to search intent over indexed paths only is what keeps it from becoming background noise, which is the failure mode that gets a nudge hook disabled. |

---

### `qmd-rerank-default-guard.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `mcp__qmd__query` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Denies a qmd MCP query whose input omits `rerank: false`, because the tool's server-side default (`rerank: true`) runs a local LLM reranking pass that never finishes on CPU-only machines and presents as a server crash. |
| **Inputs** | stdin JSON payload: `tool_input` of the `mcp__qmd__query` call. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `permissionDecision: deny` + corrective reason (on omission); nothing on pass. |
| **Logical paths** | `rerank: false` present → allow. `rerank` absent or `true` → deny with the exact parameter to add. See `test_qmd_rerank_default_guard.py`. |
| **Failure mode** | Fail-open: malformed payloads allow. |
| **Rationale** | The upstream package exposes no server-side rerank default, so the only reliable enforcement point is the call site; a guard beats a memory rule that must be re-remembered every session. |

---

### `aggregate-write-guard.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `Write\|Edit\|MultiEdit` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Denies wholesale-loss writes to three singleton aggregate files (the memory head index `MEMORY.md`, `governance-log.jsonl`, `hook-activity.jsonl`): full-file `Write` over an existing aggregate, or an edit that would shrink it past the loss threshold. |
| **Inputs** | stdin JSON payload: `tool_input.file_path`, `tool_input.content` / edit fields. Paths configurable via `AGGREGATE_WRITE_GUARD_MEMORY_PATH` / `_GOVLOG_PATH` / `_HOOKLOG_PATH` environment variables. |
| **Outputs / Side-effects** | stdout: `permissionDecision: deny` + reason on violation; a warn record to the governance log. Nothing on pass. |
| **Logical paths** | Target not one of the three exact paths → allow. Append-shaped change → allow. Wholesale replacement or destructive shrink → deny. See `test_aggregate_write_guard.py`. |
| **Failure mode** | Fail-open on I/O errors; the deny fires only on a positively identified loss write. |
| **Rationale** | Multi-session concurrency is the norm; a single wholesale write can destroy append-only history that no other copy holds. |

---

### `memory-context-guard.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `Write\|Edit\|MultiEdit` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Advisory (never blocks) when a write into the memory folder comes from a subagent context: subagents report memory-worthy findings back; the main session decides what persists. |
| **Inputs** | stdin JSON payload: `tool_input.file_path`, `agent_type` (present and named for subagents, absent for the main session: the empirically verified discriminator). |
| **Outputs / Side-effects** | Warning via `additionalContext` on subagent-context writes; every memory-folder write logged to `aggregates/memory-context-warnings.jsonl`. |
| **Logical paths** | Target outside the memory folder → silent. Main-session context → log only. Subagent context → warn + log. See `test_memory_context_guard.py`. |
| **Failure mode** | Fail-open: classification failures log as unknown and never block. |
| **Rationale** | Memory-folder ownership doctrine with an advisory wall: enforcement stays observational until the warning log proves the deny tier is warranted. |

---

## PostToolUse hooks

### `skill-step-reminder.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | `Skill` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | After a process-* skill invocation, injects a PROCESS REMINDER listing the skill's mandatory ordered steps as additionalContext. |
| **Inputs** | stdin JSON payload: `tool_name`, `tool_input` (skill name). |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` with numbered step list. Nothing for non-process skills. |
| **Logical paths** | Non-process skill → emit nothing. process-research → emit 5-step reminder. process-analysis → emit 4-step reminder. process-build → emit 5-step reminder. process-planning → emit 5-step reminder. process-qa → emit 5-step reminder. Unrecognized process skill → emit nothing. |
| **Failure mode** | Fail-open: parse error → emit nothing. |
| **Rationale** | Keeps the required process-skill step sequence visible immediately after skill invocation, reducing step-skip compliance failures. |

---

### `memory-schema-check.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | `Write\|Edit` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | After writing a memory file, validates required YAML frontmatter fields and emits a soft advisory (never blocks). |
| **Inputs** | stdin JSON payload: `tool_input.file_path`. Reads the written file from disk. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` advisory if validation fails; nothing on pass. |
| **Logical paths** | Target path is not under `.claude/projects/*/memory/*.md` → skip. Read written file → parse frontmatter → check required fields: `confidence`, `last_verified`, `expires`, `type`, `name`, `description`. Any missing field → warn. Validate `type` enum (fact/procedure/preference/reference/finding/decision/feedback). Validate `confidence` enum (high/medium/low). Validate date format on `last_verified` and `expires`. All pass → silent. Read or parse failure → skip (fail-open). |
| **Failure mode** | Fail-open: never blocks; read errors silently skipped. |
| **Rationale** | Enforces memory-file schema at write time (soft) so stale or malformed memory entries are caught early rather than silently corrupting the memory store. |

---

### `tag-variant-check.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | `Write` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | After writing an .md file, checks frontmatter tags against the canonical taxonomy and emits advisory additionalContext for non-canonical tags. |
| **Inputs** | stdin JSON payload: `tool_input.file_path`, `tool_input.content`. Reads `TAG_VARIANT_CHECK_DISABLED` env var. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` advisory listing non-canonical tags (only when violations found). |
| **Logical paths** | `TAG_VARIANT_CHECK_DISABLED=1` → skip. Target is not `.md` → skip. Target is under `.claude/`, `.obsidian/`, `.git/` → skip. Target is `CLAUDE.md` → skip. Parse frontmatter from content → extract tags (handles inline list, block list, comma-separated formats). Check each tag against `CANONICAL_TAGS` set → check `ALIASES` table → all canonical → silent. Any non-canonical tag → emit advisory with tag name and suggested canonical form. |
| **Failure mode** | Fail-open: parse errors silently skipped. |
| **Rationale** | Enforces tag taxonomy compliance (spec R4) at write time without blocking writes, keeping the vault tagging consistent for Dataview queries and MOC views. |

---

### `mcp-circuit-breaker-record.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | `mcp__.*` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Records each MCP tool call result (success or failure) to the circuit-breaker state file used by `mcp-circuit-breaker.py`. |
| **Inputs** | stdin JSON payload: `tool_name`, `tool_result` (content blocks, error fields, `is_error` flag). Reads/writes `hooks/_state/mcp-circuit-breaker.json`. |
| **Outputs / Side-effects** | Writes updated `_state/mcp-circuit-breaker.json`. No stdout. |
| **Logical paths** | Extract server name from tool_name. Determine success/failure: `is_error=True` → failure. Non-empty error fields → failure. Content starting with `"error"` or `"MCP error"` → failure. Missing response → failure. Unknown result → no state change. Success → reset failure list for server. Failure → append timestamp to failure list for server. Write updated state. Read/write errors → silently skip (fail-open). |
| **Failure mode** | Fail-open: all I/O errors caught; state unchanged on failure. |
| **Rationale** | Companion to `mcp-circuit-breaker.py`; maintains the failure-count state that the PreToolUse hook reads to decide whether to trip the breaker. |

---

### `wiki-citation-check.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | `Write\|Edit` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | After writing a wiki-layer file, validates the `source:` frontmatter field: path existence, SHA-256 integrity: and emits a soft advisory (hard block disabled in v1). |
| **Inputs** | stdin JSON payload: `tool_input.file_path`, `tool_input.content`. Reads source file bytes for SHA recomputation (via `_wiki_citation_logic.py`). |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` advisory on violation. Appends violation records to `hooks/aggregates/wiki-citation-violations.jsonl`. |
| **Logical paths** | Target not on wiki layer (not `Resources/KB/`; not `Notes/*.md` with `#wiki` tag; not `Projects/*/archive/*.md` with `#wiki` tag) → skip. Parse frontmatter → `source:` field absent or empty → advisory `MISSING_SOURCE`. For each source entry: check `path` field exists on disk → missing → advisory `ORPHAN_CITATION`. For entries without `type: generated` and `type: schema-doctrine`: recompute SHA-256 of file bytes → compare to `sha256` field → mismatch → advisory `SOURCE_DRIFT`. All pass → silent. authoritative branch set: `test_wiki_citation_logic.py` |
| **Failure mode** | Fail-open: parse errors, read errors → skip without blocking. |
| **Rationale** | Enforces wiki-layer citation integrity (Layer 2 of three-layer wiki invariant) at write time, catching source drift before it silently corrupts the knowledge base. |

---

### `inbox-auto-ingest.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | `Write\|Edit` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | When a file is written or edited under the vault's `Inbox/` directory, emits additionalContext instructing invocation of the `process-ingest` skill. |
| **Inputs** | stdin JSON payload: `tool_input.file_path`. Walks up from hook file to find vault root (CLAUDE.md sentinel). |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` with ingest instruction. Appends trigger record to `hooks/aggregates/inbox-ingest-triggers.jsonl`. |
| **Logical paths** | Target path is not under vault `Inbox/` → skip. Target is an excluded file (`.gitkeep`, `.DS_Store`, `Thumbs.db`, `desktop.ini`) → skip. Target is under `Inbox/` and not excluded → emit ingest instruction → append trigger log entry. Vault root detection fails → skip (fail-open). |
| **Failure mode** | Fail-open: vault root not found → skip; I/O errors → skip. |
| **Rationale** | Automates the Karpathy LLM-Wiki ingest trigger (Delta-4 of the architecture spec): research-grade items written to Inbox/ automatically surface for ingest without requiring manual invocation. |

---

### `checkpoint.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | none (all tool uses) |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Tracks time since last fire via `~/.claude/last-checkpoint`. At ≥60 seconds injects a KNOWLEDGE_REMINDER; at ≥300 seconds prepends a [CHECKPOINT] 5-minute save notice. |
| **Inputs** | stdin JSON payload (any PostToolUse payload). Reads/writes `{{HOME}}/.claude/last-checkpoint` timestamp file. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` (only when time thresholds met). Writes updated checkpoint timestamp. |
| **Logical paths** | Read last-checkpoint timestamp. Missing file → treat as epoch 0. Now - last < 60s → emit nothing (silent). 60s ≤ now - last < 300s → inject KNOWLEDGE_REMINDER. now - last ≥ 300s → inject [CHECKPOINT] save notice + KNOWLEDGE_REMINDER. Update last-checkpoint to now. |
| **Failure mode** | Fail-open: timestamp parse error or write error → continue without blocking. |
| **Rationale** | Provides a low-noise periodic reminder to save state during long sessions, reducing the risk of losing context or work across compaction. |

---

### `hook-write-regression-gate.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | `Write|Edit` |
| **Registered in** | not registered by default (opt-in) |
| **Action** | Blocks an edit to a hook when that edit regresses the hook test suite. |
| **Inputs** | stdin JSON payload: the edited hook path. |
| **Outputs / Side-effects** | stdout: block payload naming the failing tests. |
| **Logical paths** | Detect that the written path is a hook. Run the matching test module. Tests pass, allow. Tests fail, block and name them. |
| **Failure mode** | Fail-open if the suite cannot be run at all. |
| **Rationale** | Hooks are the enforcement layer. A silently broken hook removes a guarantee without removing the belief that the guarantee holds. |

---

### `raw-frontmatter-check.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | `Write` |
| **Registered in** | Not registered by default: opt-in |
| **Action** | Advisory check that raw-layer Markdown writes carry the three required frontmatter fields (`date`, `tags`, `status`). Reports what is missing; never blocks. |
| **Inputs** | stdin JSON payload: written file path and content. Environment: `VAULT_ROOT`, plus `RAW_FRONTMATTER_CHECK_DISABLED=1` to silence and `RAW_FRONTMATTER_CHECK_VERBOSE=1` to log passes as well as failures. |
| **Outputs / Side-effects** | stdout: `additionalContext` advisory naming the missing fields. Appends to `hooks/logs/raw-frontmatter-check.log`. |
| **Logical paths** | Path outside the raw layer → silent. Path in an excluded class (Inbox, Templates, Clippings, Daily Notes, dotfile directories, archive and source-data subtrees) or an excluded filename (STATE.md, PROJECT.md, task_plan.md, MEMORY.md, README.md, CLAUDE.md) → silent. Path in the wiki layer, meaning the KB directory or a note tagged `#wiki` → silent, since `wiki-citation-check.py` owns those. Otherwise parse frontmatter, and emit an advisory naming any of the three required fields that is absent. |
| **Failure mode** | Fail-open, advisory only: any exception is swallowed and the write stands. |
| **Rationale** | Deliberately narrower than the general structure check: this hook asserts only field presence on the raw layer. Tag canonicality belongs to `tag-variant-check.py` and the anti-orphan rule applies to the wiki layer, so keeping the three concerns in separate hooks means a false positive in one does not require disarming the others. |

---

### `unicode-hygiene-check.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | `Write\|Edit` |
| **Registered in** | Not registered by default: opt-in |
| **Action** | Scans tool-written content headed for `Inbox/` or `Clippings/` for invisible and bidirectional Unicode characters (the prompt-injection carrier classes: bidi overrides, bidi isolates, zero-width characters, a mid-file byte-order mark, a soft hyphen, and any other category-Cf character). Warns; never blocks. |
| **Inputs** | stdin JSON payload: `tool_name`, `tool_input.file_path`, `tool_input.content` (Write) or `tool_input.new_string` (Edit). Pure logic lives in `_unicode_hygiene.py`. |
| **Outputs / Side-effects** | On findings: stdout `hookSpecificOutput.additionalContext` warning; one stderr line; one JSONL record appended to `hooks/aggregates/unicode-hygiene.jsonl`. Clean or out-of-scope writes produce no output and no record. The written file itself is never modified: detection only. |
| **Logical paths** | Tool is not Write/Edit → skip. File path does not match `/inbox/` or `/clippings/` (case-insensitive, `_test_fixtures` excluded) → skip. Content scanned via `_unicode_hygiene.scan_text` → no findings → log allow, no output. Findings present → build per-class counts, emit advisory + JSONL record + log warn. |
| **Failure mode** | Fail-open: the entire hook body is wrapped in a top-level `try/except`; any internal exception → exit 0, no advisory. |
| **Rationale** | Closes the arrival-time gap for a specific, narrow attack class (Trojan-Source-style hidden characters) on the two directories a Karpathy LLM-Wiki-style raw layer treats as untrusted input. Ships opt-in rather than registered by default because its scope (two hardcoded directory names) needs adapting to your own raw-layer paths, and its paired test suite depends on committed glyph-level fixtures this repo has not yet adopted a shipping strategy for — see the 2026-08-22 `CHANGELOG.md` entry. |

---

### `plain-language-guard.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | `Write\|Edit` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Warn-only plain-language check (blocks OFF) over documentation surfaces: project `work/` files (minus `work/backups/`), the knowledge-base wiki, and this repository's README + `docs/`. Thin wrapper over `plain_language_check.py`; rules of record in [`plain-language-rules.md`](../../plain-language-rules.md). |
| **Inputs** | stdin JSON payload: `tool_input.file_path`, `tool_input.content` (Write) / `tool_input.new_string` (Edit: only the new text is visible, a documented limitation). |
| **Outputs / Side-effects** | Advisory `additionalContext` listing rule findings; per-write JSONL log entry. MM1-marked destructive-action/safety prose is exempt from length findings. |
| **Logical paths** | Path outside the three enforced surfaces → silent. In scope → run rule set → findings → advisory + log; clean → log only. See `test_plain_language_guard.py`. |
| **Failure mode** | Fail-open: checker exceptions are swallowed; never blocks. |
| **Rationale** | Advisory-first rollout of the plain-language standard: measure the finding rate before any blocking tier is considered. |

---

### `claude-md-provenance-check.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | `Write\|Edit` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Warn-only provenance guard for the workspace-root `CLAUDE.md`: a rule-shaped change with no inline origin citation gets a one-line warning. Nested `CLAUDE.md` files are out of scope. |
| **Inputs** | stdin JSON payload: `tool_input.file_path`, written/edited content. |
| **Outputs / Side-effects** | Advisory warning on uncited rule additions; nothing otherwise. |
| **Logical paths** | Path is not the workspace-root CLAUDE.md → silent. Change not rule-shaped → silent. Rule-shaped + citation present → silent. Rule-shaped + no citation → warn. See `test_claude_md_provenance_check.py`. |
| **Failure mode** | Fail-open. |
| **Rationale** | Wiki pages require a `source:` field; the constitution required nothing, and a rule survived four months after the pointer to its own origin died. This extends citation discipline to the constitution. |

---

### `deferral-resurface.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse (hook mode) + standalone CLI (`--project Projects/<Name>` sweep mode) |
| **Matcher** | `Write\|Edit` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Makes deferred items visible at project close: scans `task_plan.md`, `work/`, and `archive/` for deferral-class markers (Tier 3 / MEDIUM / DEFER(RED) / HOLD, unchecked deferral items) when a close-shaped status write happens. |
| **Inputs** | stdin JSON payload (hook mode) or `--project` path (sweep mode); project files on disk. |
| **Outputs / Side-effects** | Advisory listing of unresolved deferrals; no file writes. |
| **Logical paths** | Write is not close-shaped → silent. Close detected → sweep → deferral markers found → advisory list; none → silent. See `test_deferral_resurface.py`. |
| **Failure mode** | Fail-open. |
| **Rationale** | Deferred items died as tier-scoped markers no mechanism ever resurfaced, and a mechanical status sweep then certified unfinished business as done. |

---

### `state-reconcile-check.py`

| Attribute | Value |
|---|---|
| **Event** | PostToolUse |
| **Matcher** | `Write\|Edit` |
| **Registered in** | `settings/settings.json.template` (15s timeout: it re-reads the whole file) |
| **Action** | Advisory when a write to `STATE.md` or `task_plan.md` leaves older text below it that contradicts the newly written status: the file then says two things and which one a reader believes depends on where they stop reading. |
| **Inputs** | stdin JSON payload: `tool_input.file_path`, written content; the full post-write file from disk. |
| **Outputs / Side-effects** | Advisory naming the contradicting stale region; no file writes. |
| **Logical paths** | Target is not a state-class file → silent. New status consistent with the remainder → silent. Contradiction detected → advisory. See `test_state_reconcile_check.py`. |
| **Failure mode** | Fail-open. |
| **Rationale** | Measured defect: a PM checkpoint reading only the top of a state file reported work done that the bottom half still listed as pending, three times in one day. |

---

## SubagentStart hooks

### `subagent-governance.py`

| Attribute | Value |
|---|---|
| **Event** | SubagentStart |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Logs agent_type + agent_id to `subagent-governance.log` and injects a governance additionalContext block (multi-perspective analysis, evidence citation, structure, blind analysis rule). |
| **Inputs** | stdin JSON payload: `agent_type`, `agent_id`. |
| **Outputs / Side-effects** | Appends one line to `hooks/subagent-governance.log`. stdout: `hookSpecificOutput` → `additionalContext` governance block. |
| **Logical paths** | Parse payload → log to file → build governance context block → emit. Log write failure → continue to emit context (fail-open). |
| **Failure mode** | Fail-open: log write errors caught and ignored; context block always emitted on best-effort. |
| **Rationale** | Ensures every subagent receives baseline governance instructions (blind analysis, uncertainty flagging, evidence citation) regardless of what its dispatch prompt says. |

---

### `subagent-scope-check.py`

| Attribute | Value |
|---|---|
| **Event** | SubagentStart + SubagentStop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` (both SubagentStart and SubagentStop) |
| **Action** | At SubagentStart: captures `git status --porcelain` baseline keyed by agent_id. At SubagentStop: diffs current git status against baseline and logs new/resolved changes. Pure instrumentation: never blocks. |
| **Inputs** | stdin JSON payload: `agent_id`. Reads/writes `hooks/_state/subagent-scope-baselines.json`. Runs `git status --porcelain`. |
| **Outputs / Side-effects** | Start: writes baseline to `_state/subagent-scope-baselines.json`. Stop: appends diff record to `hooks/subagent-scope-log.jsonl`; emits stderr warning if new changes found. No stdout (no additionalContext). |
| **Logical paths** | Start: parse payload → run git status → store baseline under agent_id → exit. Stop: parse payload → run git status → load baseline for agent_id → compute diff (new files, resolved files) → log diff to JSONL → if new_changes non-empty → stderr warning. No baseline found for agent_id → log with empty baseline. git failure → log error, skip diff. |
| **Failure mode** | Fail-open: git errors, file I/O errors → logged and skipped; never blocks. |
| **Rationale** | Provides observability into what file changes each subagent introduces, enabling post-hoc attribution of vault changes to specific agent runs. |

---

### `bias-guard.py`

| Attribute | Value |
|---|---|
| **Event** | SubagentStart |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Injects the Blind Analysis Rule as additionalContext for evaluator-type agents. Non-evaluator agents receive an empty response. |
| **Inputs** | stdin JSON payload: `agent_type`. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` with Blind Analysis Rule (for evaluators); or `{}` (for non-evaluators). |
| **Logical paths** | Agent type in evaluator list (adversarial-reviewer, architect-reviewer, prompt-engineer, research-analyst, research-synthesizer, competitive-analyst, api-security-audit) → emit Blind Analysis Rule context. Agent type not in evaluator list → emit `{}`. |
| **Failure mode** | Fail-open: parse error → emit `{}`. |
| **Rationale** | Prevents evaluator agents from receiving proposed conclusions or hypotheses in their context, enforcing the blind-analysis constraint that keeps review outputs unanchored to the dispatcher's priors. |

---

## SubagentStop hooks

### `subagent-quality-check.py`

| Attribute | Value |
|---|---|
| **Event** | SubagentStop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Runs structural quality checks (CHECK 1/2/3 from `_subagent_quality_logic.py`) on the agent's output and blocks if violations found. |
| **Inputs** | stdin JSON payload: `agent_type`, `agent_id`, `last_assistant_message`, `transcript_path`, `stop_hook_active`. |
| **Outputs / Side-effects** | On violation: stdout `{"decision": "block", "reason": "..."}`. Appends record to both `hooks/subagent-quality.log` and `hooks/governance-log.jsonl` (with `violation_excerpt`, `block_reason`). |
| **Logical paths** | `stop_hook_active=True` → return immediately (prevent infinite loop). Parse payload → call `classify_subagent_output(message)` (pure logic in `_subagent_quality_logic.py`) → `blocked=True` → log to both files + emit block. `blocked=False` → log PASS to subagent-quality.log → exit. authoritative branch set: `test_subagent_quality_check.py` |
| **Failure mode** | Fail-open: parse/import errors → exit 0 without blocking. |
| **Rationale** | Provides a structural exit gate for agent output: catches agents that produce empty, malformed, or non-compliant output before it propagates into the main session. |

Note: `subagent-scope-check.py` also fires at SubagentStop: documented in the SubagentStart section above.

---

## Stop hooks

### `classifier-field-check.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Blocks completion when required classifier fields are absent from the last assistant turn. Emits a `classification_emitted` observability event on pass. |
| **Inputs** | stdin JSON payload: `transcript_path`, `stop_hook_active`. Reads 200KB transcript tail. |
| **Outputs / Side-effects** | On violation: stdout `{"decision": "block", "reason": "..."}`. Always: logs event to governance-log.jsonl via `_event_emit`. |
| **Logical paths** | `stop_hook_active=True` → return. Scan last assistant turn for: `IMPLIES` field (always required) → missing → block. `TASK TYPE:` field (always required) → missing → block. TASK TYPE = Quick → pass (no further fields required). TASK TYPE = non-Quick → require `APPROACH:`, `MISSED:`, `MUST DISPATCH:` (with `pm` present) → any missing → block. All present → pass → emit `classification_emitted` event. authoritative branch set: `test_classifier_field_check.py` |
| **Failure mode** | Fail-open: transcript read errors → pass. |
| **Rationale** | Makes task classification a structural contract enforced at turn-end rather than a suggestion; compliance data feeds the governance-log compliance rate metric. |

---

### `dispatch-compliance-check.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Blocks when MUST DISPATCH items declared in the last turn were not fulfilled by actual agent dispatches. |
| **Inputs** | stdin JSON payload: `transcript_path`, `stop_hook_active`. Reads 200KB transcript tail. Optionally reads H11 sidecar file for post-compaction fallback. |
| **Outputs / Side-effects** | On violation: stdout `{"decision": "block", "reason": "..."}`. On pass: logs pass event to governance-log.jsonl. |
| **Logical paths** | `stop_hook_active=True` → return. Extract MUST DISPATCH from last assistant text via `extract_dispatch_names()`. MUST DISPATCH = "none" or empty → H3 check: non-Quick task with empty MUST DISPATCH → block (missing declaration). MUST DISPATCH present → collect actual agent dispatches from transcript (with alias expansion via `SKILL_AGENT_ALIASES`) → all declared names fulfilled → pass. Any declared name not found in actual dispatches → block. H11 sidecar fallback: if post-compaction and one or more trackable skills were dispatched → enforce the UNION of their DISPATCHES.json contracts (merged_sidecar_contract, 2026-08-31; last-wins overwrite let a trailing pm dispatch replace the substantive skill's contract). `pm` and `task-classifier` are trackable alongside the process-* skills; `process-qa`/`process-pentest` stay terminal and never arm the fallback. authoritative branch set: `test_dispatch_compliance.py` |
| **Failure mode** | Fail-open: parse errors, missing transcript → pass. |
| **Rationale** | Enforces that MUST DISPATCH declarations are executable commitments, not suggestions: the primary driver of the 53% → target compliance-rate improvement. |

---

### `governance-log.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Appends one `turn_summary` JSONL entry to governance-log.jsonl per turn that contains a classification block. Pure logging: never blocks. |
| **Inputs** | stdin JSON payload: `transcript_path`. Reads 200KB transcript tail to extract classification fields. |
| **Outputs / Side-effects** | Appends one record to `hooks/governance-log.jsonl`. Fields: `ts`, `schema=2`, `event=turn_summary`, `session`, `type`, `effort_level`, `implies`, `domain`, `must_dispatch`, `agents` (list), `skills` (list), `agent_count`, `skill_count`, `wiki_queried`. No stdout. |
| **Logical paths** | No classification found in transcript → skip (no entry written). Classification found → extract fields → determine `wiki_queried` (was `mcp__qmd__query` used this turn?) → write JSONL. Write failure → swallow error. authoritative branch set: `test_governance_log.py` |
| **Failure mode** | Fail-open: all exceptions swallowed; never blocks. |
| **Rationale** | Provides the per-turn data feed for governance analytics, compliance measurement, and the governance-mine weekly sweep. |

---

### `process-step-check.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Hard-blocks on missing process-skill structural requirements (SCOPE block, QA REPORT, PENTEST REPORT, PM checkpoint); soft-logs on advisory gaps (missing synthesis, missing architect-review, zero agent dispatches). **B-1a fix (2026-06-11):** Workflow tool_use whose name/scriptPath maps to a process-* skill is detected as a skill invocation (not just Skill tool_use). **B-1b fix (2026-06-11):** tool_result wrapper user entries (entry 2 of the three-entry Workflow shape) do NOT reset scan state: only real user messages reset it. |
| **Inputs** | stdin JSON payload: `transcript_path`, `stop_hook_active`. Reads 200KB transcript tail. |
| **Outputs / Side-effects** | On hard violation: stdout `{"decision": "block", "reason": "..."}`. Soft violations: logged to governance-log.jsonl (no stdout). |
| **Logical paths** | `stop_hook_active=True` → return. Scan transcript: detect process skill via Skill tool_use OR Workflow tool_use (B-1a). Turn-boundary reset fires only on real user messages, not tool_result wrappers (B-1b). After process skill detection: collect relay text from subsequent assistant turns. Check: no SCOPE block in relay text → hard block. process-qa detected but no QA REPORT/PASS in relay text → hard block. process-pentest detected but no PENTEST REPORT → hard block. PM invoked but pm-orchestrator not dispatched (rubber-stamp guard) → hard block. Increment complete (2+ TaskCreate completed + pentest_seen: set by Skill or Workflow process-pentest) but no /pm → hard block. Missing synthesis (soft) → log. Missing architect-review (soft) → log. Zero agent dispatches (soft) → log. authoritative branch set: `test_process_step_check.py` |
| **Failure mode** | Fail-open: parse errors → exit without blocking. |
| **Rationale** | Enforces process-skill structural completeness at turn-end, catching abbreviated skill execution (e.g. invoking /process-qa but not producing a report) before it registers as a completed step. B-1a/B-1b ensure enforcement is not silently bypassed when process skills run as Workflow scripts. |

---

### `dark-zone-check.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Monitors the ratio of agent dispatches to citation patterns in the response. Logs a dark-zone observability event with severity. Never blocks. |
| **Inputs** | stdin JSON payload: `transcript_path`. Reads 200KB transcript tail. |
| **Outputs / Side-effects** | Appends one dark-zone event record to governance-log.jsonl. No stdout. |
| **Logical paths** | Count Agent dispatches in last turn. Count citation patterns (source references) in response text. Count file writes. Compute `effective_citations = citations + files_written`; severity: ≥1 agent dispatch + zero effective citations → `high`. Citation ratio < 0.5 → `medium`. Adequate citations → `low`. Write dark-zone event with severity, counts. |
| **Failure mode** | Fail-open: all exceptions swallowed; never blocks. |
| **Rationale** | Provides a signal for turns where agents were dispatched but the response cites no evidence: a pattern associated with fabricated inventory claims documented in `feedback_main_session_can_fabricate_inventory.md`. |

---

### `work-verification-check.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Four checks: (CHECK 1) Hard-blocks QA/pentest report filed with zero tool usage. (CHECK 1b) Hard-blocks inline QA report on non-Quick task without /process-qa invocation. (CHECK 2) Hard-blocks premature escalation (asks user for help after <3 tool uses). (CHECK 4) Soft-logs/warns fabricated Write claims (claimed to write path that doesn't exist and wasn't written). Also emits session_end and qa_fail_reported telemetry events. **B-2 fix (2026-06-11):** pre-scan from the real user boundary detects Workflow process-qa/pentest tool_use (which precedes the tool_result wrapper) and sets `qa_via_workflow` / `pentest_via_workflow` flags. **B-3 fix (2026-06-11):** CHECK 1's zero-execution-tools block is suppressed when the corresponding `*_via_workflow` flag is set: the execution evidence obligation moves into the workflow script's typed per-claim fields. |
| **Inputs** | stdin JSON payload: `transcript_path`, `stop_hook_active`. Reads 200KB transcript tail plus tool_result blocks. |
| **Outputs / Side-effects** | On CHECK 1/1b/2 violation: stdout `{"decision": "block", "reason": "..."}` + governance-log.jsonl entry. On CHECK 4 fabrication: stderr warning + governance-log.jsonl entry (non-blocking). Emits `session_end` heartbeat and `qa_fail_reported` events via `_event_emit`. |
| **Logical paths** | `stop_hook_active=True` → return. **B-2 pre-scan:** walk from real-last-user-idx boundary (skips tool_result wrappers) to find Workflow process-qa or process-pentest tool_use; set `qa_via_workflow` / `pentest_via_workflow` flags. Walk last turn collecting tool uses, text blocks, QA/pentest report markers, classification, skill invocations. Compute execution_tools (Bash + mcp__*), tool_count (all except Skill). CHECK 1: QA/pentest report present + process skill invoked + zero execution tools + zero Read tools + NOT via_workflow → hard block. **B-3:** `qa_via_workflow` / `pentest_via_workflow` set → suppress CHECK 1 zero-execution-tools block. CHECK 1b: non-Quick + QA report present + process-qa not invoked (Skill or Workflow) → hard block. CHECK 4: scan text for Write-claim regex patterns → claimed path not in Write trace AND not on disk → fabrication → stderr warn + log. CHECK 2: escalation patterns in response + non-Quick + tool_count < 3 → hard block. CHECK 3 (soft): non-Quick + zero tool_count → log warn. Emit session_end heartbeat. Emit qa_fail_reported if QA REPORT with FAIL: lines. Log pass for monitoring. authoritative branch set: `test_work_verification_check.py` |
| **Failure mode** | Fail-open: parse errors → return without blocking; all observability emits wrapped in try/except. |
| **Rationale** | Closes three distinct verification gaps: lazy QA (report without execution), rubber-stamp escalation (asking user before exhausting tools), and fabricated file-write claims. B-2/B-3 prevent false CHECK 1 blocks when QA/pentest runs inside a Workflow subagent whose Bash/MCP calls are invisible to the main transcript. |

---

### `token-breakdown.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Aggregates token usage for the turn (main session + per-subagent) and emits a `token_breakdown` event. Telemetry only: never blocks. |
| **Inputs** | stdin JSON payload: `transcript_path`. Reads transcript tail for `message.usage` fields and `toolUseResult.usage` fields (subagent). |
| **Outputs / Side-effects** | Emits `token_breakdown` event via `_event_emit` helper. Fields: `turn_total_tokens`, `main_session`, `by_subagent` (list: one entry per Agent tool call), `tool_calls`, `skill_names`, `task_type`. No stdout to CC. |
| **Logical paths** | Parse transcript → find last assistant turn → sum input/output tokens from `message.usage` → iterate tool_result blocks for subagent usage (`toolUseResult.usage`) → all-zero total → skip emit. Non-zero → emit event. Transcript read error → skip. |
| **Failure mode** | Fail-open: all exceptions swallowed; never blocks; silently skips if all-zero. |
| **Rationale** | Provides per-turn token accounting for cost attribution and the cost-summary dashboard, including per-subagent breakdown that the CC UI does not expose. |

---

### `read-before-edit-check.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Instrumentation layer: checks whether each Edit/MultiEdit in the last turn was preceded by a Read of the same file. Logs violations to governance-log.jsonl and emits stderr warnings. Never blocks. |
| **Inputs** | stdin JSON payload: `transcript_path`. Reads 200KB transcript tail. |
| **Outputs / Side-effects** | Logs `edit_without_read` events to governance-log.jsonl. Emits stderr warnings. No stdout. |
| **Logical paths** | Walk last assistant turn tool_use blocks. Collect all Read file paths and all Edit/MultiEdit file paths. For each Edit path: check if same path was Read earlier in this turn → yes → pass. No → log `edit_without_read` event + stderr warning. All edits had prior reads → no output. |
| **Failure mode** | Fail-open: parse errors → exit 0; never blocks. |
| **Rationale** | Enforces the vault's read-before-edit convention at the instrumentation layer; data feeds compliance measurement without blocking writes where the Read was done in a prior turn or via a different access pattern. |

---

### `verifier-gate-check.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Dormant unless `verification-gated-research` skill was invoked this session. If invoked, blocks completion unless an Agent with "verifier" in its description was dispatched AFTER the skill invocation. |
| **Inputs** | stdin JSON payload: `transcript_path`, `stop_hook_active`. Reads transcript tail. |
| **Outputs / Side-effects** | On violation: stdout `{"decision": "block", "reason": "..."}`. On pass: logs pass event to governance-log.jsonl. |
| **Logical paths** | `stop_hook_active=True` → return. Scan transcript for `verification-gated-research` skill invocation. Not found → pass silently (dormant path). Found → find invocation position. Scan assistant turns AFTER invocation position for Agent dispatch with "verifier" in description. Found verifier agent dispatch → pass + log. Not found → block with ordering-violation message. |
| **Failure mode** | Fail-open: parse errors → pass. |
| **Rationale** | Enforces the verification-gated-research skill's ordering contract: research work must be verified by a separate verifier agent before the session can complete. |

---

### `task-plan-auto-sync.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | When a QA PASS is detected in the last assistant response, finds the matching `task_plan.md` entry by TASK-ID and marks it `[x]` with a summary. |
| **Inputs** | stdin JSON payload: `transcript_path`, `stop_hook_active`. Reads last assistant text for `QA REPORT` block. Reads/writes `task_plan.md` in active project. Reads/writes dedup window state and undo log. Reads `DRY_RUN`, `H4_ENABLE_HAIKU` env vars. |
| **Outputs / Side-effects** | Writes updated `task_plan.md` (marks `[ ]` → `[x]`, appends summary). Writes undo log entry. Writes dedup window state. On `DRY_RUN=1`: no file writes, logs action instead. |
| **Logical paths** | `stop_hook_active=True` → return. Scan last assistant text for structural QA REPORT with PASS verdict (structural detection, not naive substring). No PASS → exit. Extract TASK-ID from SCOPE field (primary) then full QA REPORT text. TASK-ID found in dedup window (within 72h) → skip (already synced). Find matching `[ ]` entry in task_plan.md by TASK-ID. Match found → rewrite line as `[x]` with summary → post-write verification → mismatch → revert from undo log. Optional Haiku fallback (`H4_ENABLE_HAIKU=1`): if no TASK-ID found, call Haiku to extract it. Self-test: `--selftest` flag runs internal boundary test. |
| **Failure mode** | Fail-open: task_plan.md not found, TASK-ID not found, write failure → log and exit 0. Revert-on-failure ensures partial writes are not left behind. |
| **Rationale** | Automates the task-plan sync requirement from CLAUDE.md ("CRITICAL RULE: Task Plan Sync"), removing the need to manually update task_plan.md after each QA PASS. |

---

## PreCompact hooks

### `pre-compact.py`

| Attribute | Value |
|---|---|
| **Event** | PreCompact |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Before context compaction, writes a recovery snapshot file containing: STATE.md contents from all projects, active task_plan.md items, last 3 user messages, last classification, recently modified files. Resets checkpoint timer. |
| **Inputs** | stdin JSON payload (PreCompact fields). Reads transcript tail (50KB). Reads all `Projects/*/STATE.md` and `Projects/*/task_plan.md` files. |
| **Outputs / Side-effects** | Writes `{{HOME}}/.claude/pre-compact-recovery.md`. Resets `{{HOME}}/.claude/last-checkpoint` to epoch. **Produces no stdout**: PreCompact does not accept `additionalContext`. |
| **Logical paths** | Parse payload → read transcript tail → extract last 3 user messages → extract last classification block → list recently modified files → read all STATE.md files → extract In Progress / Shaped task_plan sections (cap) → write recovery file. Any individual read error → skip that section, continue. |
| **Failure mode** | Fail-open: individual file read errors skipped; write failure logged to stderr; exit 0 always. |
| **Rationale** | Provides a human-readable recovery point before each compaction so state can be restored if the compacted summary loses critical context (addresses the compaction-loses-attribution failure mode). |

---

## PostCompact hooks

### `post-compact.py`

| Attribute | Value |
|---|---|
| **Event** | PostCompact |
| **Matcher** | none |
| **Registered in** | Not registered by default: opt-in |
| **Action** | Fires after context compaction completes. Records the compaction event for instrumentation and writes a staleness marker so a later session or lint pass can tell that context was compacted and that the search index and STATE.md may be stale. |
| **Inputs** | stdin JSON payload (PostCompact fields). |
| **Outputs / Side-effects** | Writes `hooks/_state/last-compact.json`. Appends a compaction event to `hooks/governance-log.jsonl` and the hook-activity instrument. **Produces no stdout:** PostCompact, like PreCompact, rejects `hookSpecificOutput.additionalContext`. |
| **Logical paths** | Parse payload → write marker → append event → exit 0. Any write failure is swallowed. |
| **Failure mode** | Fail-open: exit 0 always; never crashes the session. |
| **Rationale** | Closes the loop that `pre-compact.py` opens on the other side. Compaction frequency is otherwise invisible, and the marker lets downstream consumers detect the staleness rather than assume freshness. This hook only flags: it does not re-index, because that is a heavier operation than a hook should perform. Post-compaction orientation stays the job of the SessionStart recovery-file mechanism. |

---

## Disabled / opt-in hooks

These files ship in `hooks/disabled/` or are present in `hooks/` but explicitly not registered. They have zero runtime effect unless manually armed.

| Hook file | Where | Reason unregistered | One-line description |
|---|---|---|---|
| `disabled/epistemic-check.py` | `hooks/disabled/` | Disabled after failure: never blocked in practice; cannot distinguish correct from incorrect confidence without semantic domain understanding | Sole surviving copy of the Stop-event Haiku evaluator; a duplicate that shipped registered in `settings/settings.json.template` (contradicting this entry) was removed 2026-08-22, see `disabled/README.md` |
| `disabled/agent-dispatch-check.py` | `hooks/disabled/` | Disabled after failure: allowlist model blocked legitimate ad-hoc dispatches; ceilings punish adaptation | PreToolUse (Agent) version that blocked (not warned) dispatches not in a pre-approved allowlist |
| `disabled/delegation-check.ps1` | `hooks/disabled/` | Disabled after failure: same rationale as agent-dispatch-check.py; PowerShell form | PowerShell PreToolUse hook that blocked undeclared agent dispatches |
| `disabled/routing-table-validation.py` | `hooks/disabled/` | Opt-in by design: correct and tested (26 tests); ships unregistered because arming a blocking hook on CLAUDE.md + SKILL.md is a deliberate decision requiring a complete registry | PreToolUse (Edit\|Write\|MultiEdit) hook that denies edits introducing broken agent-name references in CLAUDE.md or any SKILL.md |
| `disabled/config-protection.py` | `hooks/disabled/` | Retired from the maintainer's own deployment (2026-08-07): a hard PreToolUse deny on reversible, git-tracked config files cost a retry round-trip without moving any decision to a human; see `disabled/README.md` | PreToolUse (Write\|Edit\|MultiEdit) hook that hard-blocked writes to a local settings file, a registry file, and a persistent memory index |
| `disabled/agent-registry-check.py` | `hooks/disabled/` | Retired from the maintainer's own deployment alongside config-protection.py; no independent failure narrative recorded, kept as a correct reference implementation | SubagentStart hook that suggested specialist agents for generic/untyped dispatches via keyword overlap |
| `disabled/em-dash-guard.py` | `hooks/disabled/` | Opt-in by design: enforces a personal prose-style preference (no "fancy" dash glyphs), not a process-compliance check | Stop hook that blocks a response containing en/em dash, minus sign, or similar Unicode dash look-alikes in prose |
| `disabled/prose-codes-check.py` | `hooks/disabled/` | Opt-in by design: same reasoning as em-dash-guard.py; also ships with a placeholder ticket-key allow-list that needs editing before arming | Stop hook that blocks a response using invented internal shorthand codes instead of plain language |
| `_archived/hooks/weekly-usage.py` | `_archived/hooks/` | Archived: retired from the maintainer's active toolset; kept as a worked example of a non-hook maintenance script | Standalone CLI utility printing weekly token usage grouped by model and day since last Friday 8PM; requires the third-party `claude_monitor` package |
| `prose-slop-check.py` | `hooks/` (dormant) | Opt-in: built and calibrated (0 false positives on a 19-page prose corpus); ships unregistered until the maintainer arms it | PostToolUse (Write) hook that warns on LLM-register slop vocabulary in `Resources/KB/` and `Projects/*/work/` prose |
| `unicode-hygiene-check.py` | `hooks/` (dormant) | Opt-in: narrowly scoped by design (two hardcoded raw-layer directories) and its paired test suite needs a fixture-shipping decision this repo has not made yet | PostToolUse (Write\|Edit) hook that warns on invisible/bidirectional Unicode characters in content written under `Inbox/` or `Clippings/` |
| `disabled/pretooluse-payload-probe.py` | `hooks/disabled/` | Diagnostic, temporary by design: a metadata-only probe (payload key names, `agent_type` value, tool name: never content) used to verify which fields reach PreToolUse payloads; deregistered after its probe window and retained as a worked example of safe payload introspection | PreToolUse (Write\|Edit\|MultiEdit) probe appending one JSONL metadata record per matched call |
| `plain_language_check.py` | `hooks/` | Not a hook: the checker module `plain-language-guard.py` wraps; also runnable standalone against a file | Plain-language rule engine (rules of record in `plain-language-rules.md`) |
| `mine_governance.py` | `hooks/` | Not a hook: the miner module behind the weekly `process-governance-mine` skill; proposal-only, never edits config | Mines `governance-log.jsonl` for recurring failure/warn patterns (allowlist + per-agent sig_key + severity gate + resolved-ledger suppression) |
