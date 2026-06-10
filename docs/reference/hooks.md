# Hooks Reference

This is a Reference-mode document per the [documentation standard](../documentation-standard.md): attributes tables, no tutorial prose. **Code is the source of truth** — if a field here disagrees with the `.py` file, the code wins. Where a `test_<name>.py` file exists in `hooks/`, it is the authoritative enumeration of branches; the Logical-paths cell ends with a pointer to that file.

Every production hook is listed below. Library modules (`_`-prefixed), test files (`test_`-prefixed), and the `disabled/` subdirectory are excluded from the per-hook sections; disabled and opt-in hooks appear in the [Disabled / opt-in hooks](#disabled--opt-in-hooks) section at the end.

---

## Summary table

| Hook file | Event | Action (brief) | Registered by default? |
|---|---|---|---|
| `session-start-log.py` | SessionStart | Log session_start to governance-log.jsonl | Yes — `settings.json.template` |
| `session-start-orientation.py` | SessionStart | Inject project STATE + task context as additionalContext | Yes — `settings.json.template` |
| `registry-staleness-check.py` | SessionStart | Warn if registry.json is >7 days old | No — opt-in |
| `user-prompt-submit.py` | UserPromptSubmit | Inject context bar + classifier enforcement reminder | Yes — `settings.json.template` |
| `user-prompt-state-inject.py` | UserPromptSubmit | Inject STATE.md orientation (throttled 30min) | Yes — `settings.json.template` |
| `skill-routing-check.py` | PreToolUse (Skill) | Deny process-skill if routing mismatches last TASK TYPE | Yes — `settings.json.template` |
| `bash-safety-guard.py` | PreToolUse (Bash) | Block dangerous shell commands | Yes — `settings.json.template` |
| `agent-dispatch-check.py` | PreToolUse (Agent) | Warn when dispatched agent not in MUST DISPATCH list | Yes — `settings.json.template` |
| `memory-dedup-check.py` | PreToolUse (Write) | Soft-warn on duplicate memory file (Jaccard ≥ 0.65) | Yes — `settings.json.template` |
| `reviewer-scope-violation-check.py` | PreToolUse (Write\|Edit\|MultiEdit) | Block reviewer agents from editing non-report files | Yes — `settings.json.template` |
| `config-protection.py` | PreToolUse (Write\|Edit\|MultiEdit) | Hard-block writes to protected config files | Yes — `settings.json.template` |
| `mcp-circuit-breaker.py` | PreToolUse (mcp__.*) | Trip breaker after ≥3 MCP failures in 600s window | Yes — `settings.json.template` |
| `skill-step-reminder.py` | PostToolUse (Skill) | Inject mandatory process-step reminder for process-* skills | Yes — `settings.json.template` |
| `memory-schema-check.py` | PostToolUse (Write\|Edit) | Soft-warn on missing/invalid memory frontmatter fields | Yes — `settings.json.template` |
| `tag-variant-check.py` | PostToolUse (Write) | Advisory on non-canonical tags in .md frontmatter | Yes — `settings.json.template` |
| `mcp-circuit-breaker-record.py` | PostToolUse (mcp__.*) | Record MCP tool result as success/failure to breaker state | Yes — `settings.json.template` |
| `wiki-citation-check.py` | PostToolUse (Write\|Edit) | Validate source: field + SHA integrity on wiki-layer files | Yes — `settings.json.template` |
| `inbox-auto-ingest.py` | PostToolUse (Write\|Edit) | Trigger process-ingest when file written under Inbox/ | Yes — `settings.json.template` |
| `checkpoint.py` | PostToolUse (no matcher) | Inject knowledge reminder at ≥60s; CHECKPOINT notice at ≥300s | Yes — `settings.json.template` |
| `subagent-governance.py` | SubagentStart | Inject governance additionalContext; log agent_type | Yes — `settings.json.template` |
| `agent-registry-check.py` | SubagentStart | Suggest specialist agents for generic dispatches | Yes — `settings.json.template` |
| `subagent-scope-check.py` | SubagentStart + SubagentStop | Capture/diff git status baseline per subagent | Yes — `settings.json.template` |
| `bias-guard.py` | SubagentStart | Inject Blind Analysis Rule for evaluator agents | Yes — `settings.json.template` |
| `subagent-quality-check.py` | SubagentStop | Block on structural quality violations in agent output | Yes — `settings.json.template` |
| `classifier-field-check.py` | Stop | Block when required classifier fields missing | Yes — `settings.json.template` |
| `dispatch-compliance-check.py` | Stop | Block when MUST DISPATCH items not fulfilled | Yes — `settings.json.template` |
| `governance-log.py` | Stop | Append turn_summary to governance-log.jsonl | Yes — `settings.json.template` |
| `process-step-check.py` | Stop | Block/log on missing process-skill steps | Yes — `settings.json.template` |
| `dark-zone-check.py` | Stop | Log dark-zone metric (agent citations vs dispatches) | Yes — `settings.json.template` |
| `work-verification-check.py` | Stop | Block lazy QA, premature escalation, fabrication claims | Yes — `settings.json.template` |
| `token-breakdown.py` | Stop | Log per-turn token breakdown telemetry | Yes — `settings.json.template` |
| `read-before-edit-check.py` | Stop | Log edit-without-read instrumentation | Yes — `settings.json.template` |
| `epistemic-check.py` | Stop | Spawn Haiku to evaluate overconfidence; block if flagged | Yes — `settings.json.template` |
| `verifier-gate-check.py` | Stop | Block if verification-gated-research ran without verifier agent | Yes — `settings.json.template` |
| `task-plan-auto-sync.py` | Stop | Mark task_plan.md item done on QA PASS | Yes — `settings.json.template` |
| `pre-compact.py` | PreCompact | Write recovery snapshot before context compaction | Yes — `settings.json.template` |
| `prose-slop-check.py` | PostToolUse (Write) | Warn on LLM-register slop words in wiki/work prose | No — dormant, not registered |

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
| **Action** | Injects a project-state orientation block as `additionalContext` — active project STATE.md summary + open task_plan items + recent decisions. |
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
| **Registered in** | Not registered by default — opt-in |
| **Action** | Reads `registry.json` age from `generated_at` field (or file mtime fallback). Emits advisory additionalContext when age >7 days. Silent when fresh. |
| **Inputs** | stdin JSON (consumed, not used). Reads `{{VAULT_ROOT}}/.claude/registry.json`. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` advisory string (only when stale or missing). No file writes. |
| **Logical paths** | Registry missing → emit gentle "generate it" note. Registry age ≤ 7 days → emit nothing (silent). Registry age > 7 days → emit advisory with day count and command. Parse/read failure → `age_days = None` → treats as missing → gentle note. |
| **Failure mode** | Fail-open: all exceptions caught; empty string → no stdout. |
| **Rationale** | Keeps the asset inventory (`registry.json`) from silently drifting stale without requiring a calendar-based reminder mechanism. |

---

## UserPromptSubmit hooks

### `user-prompt-submit.py`

| Attribute | Value |
|---|---|
| **Event** | UserPromptSubmit |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Reads transcript for token counts + model, builds a context bar and injects classifier enforcement reminder; escalates at ≥50% context utilization. |
| **Inputs** | stdin JSON payload: `transcript_path`, `effort`. Reads transcript tail (200KB window) for token count and model fields. |
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
| **Action** | For process-* skills: reads last TASK TYPE from transcript and denies invocation if the routing table maps the task type to a different process skill. Non-process skills always pass. |
| **Inputs** | stdin JSON payload: `tool_name`, `tool_input` (skill name, args), `transcript_path`. Reads 200KB transcript tail. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `permissionDecision: deny` + reason (on mismatch); nothing on allow. |
| **Logical paths** | Non-process skill → allow immediately. Process skill invoked → scan transcript for last `TASK TYPE:` line. Quick classification → allow. No classification → allow. Classification found → look up ROUTING table (research→process-research, analysis→process-analysis, content/build→process-build, planning→process-planning, compound→process-analysis) → skill matches expected → allow. Skill does not match → deny with explanation showing correct skill. |
| **Failure mode** | Fail-open: parse errors, missing transcript → allow. |
| **Rationale** | Enforces that the model routes tasks to the correct process skill rather than calling a mismatched skill (e.g. calling process-build for a research task). |

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
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` warning text (advisory only, never `{"decision": "block"}`). Logs event to governance-log.jsonl. |
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
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` advisory (only on duplicate detection). No file writes. |
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
| **Rationale** | Enforces the Blind Analysis Rule — reviewer agents should produce review documents, not edit the artifacts they are reviewing. |

---

### `config-protection.py`

| Attribute | Value |
|---|---|
| **Event** | PreToolUse |
| **Matcher** | `Write\|Edit\|MultiEdit` |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Hard-blocks writes to three protected files: `settings.local.json` (under `.claude/`), `registry.json` (under `.claude/`), and `MEMORY.md` (anywhere). |
| **Inputs** | stdin JSON payload: `tool_input.file_path`. Reads `CONFIG_PROTECTION_ALLOW` environment variable. |
| **Outputs / Side-effects** | stdout: `{"decision": "block", "reason": "..."}` on violation; nothing on allow. |
| **Logical paths** | `CONFIG_PROTECTION_ALLOW=1` env var set → allow all (session-scoped override). Target file is `settings.local.json` with parent directory `.claude` → block. Target file is `registry.json` with parent directory `.claude` → block. Target file is `MEMORY.md` (any path) → block. No match → allow. Parse error → allow (fail-open). |
| **Failure mode** | Fail-open: any unhandled exception exits 0 without blocking. |
| **Rationale** | Prevents accidental or hook-triggered overwrites of the three highest-consequence config files: the local settings that control hook registration, the asset registry, and the persistent memory index. |

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
| **Action** | After writing a wiki-layer file, validates the `source:` frontmatter field — path existence, SHA-256 integrity — and emits a soft advisory (hard block disabled in v1). |
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
| **Logical paths** | Read last-checkpoint timestamp. Missing file → treat as epoch 0. Now − last < 60s → emit nothing (silent). 60s ≤ now − last < 300s → inject KNOWLEDGE_REMINDER. now − last ≥ 300s → inject [CHECKPOINT] save notice + KNOWLEDGE_REMINDER. Update last-checkpoint to now. |
| **Failure mode** | Fail-open: timestamp parse error or write error → continue without blocking. |
| **Rationale** | Provides a low-noise periodic reminder to save state during long sessions, reducing the risk of losing context or work across compaction. |

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

### `agent-registry-check.py`

| Attribute | Value |
|---|---|
| **Event** | SubagentStart |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | When a generic/untyped agent is dispatched, scores prompt words against registry keyword lists and suggests specialist agents with overlap score ≥ 3. Advisory only — never blocks. |
| **Inputs** | stdin JSON payload: `subagent_type` / `agent_type`, `agent_id`, `prompt` / `description`. Reads `{{VAULT_ROOT}}/.claude/registry.json`. |
| **Outputs / Side-effects** | stdout: `hookSpecificOutput` → `additionalContext` with specialist suggestions (only when match found). Appends one line to `hooks/agent-registry-check.log`. |
| **Logical paths** | Agent type not in `GENERIC_TYPES` (general-purpose, explore, plan, "", unknown) → skip silently. No prompt text → skip. Registry unreadable → skip. Extract prompt word set → find specialist agents with keyword overlap ≥ `MIN_MATCH_SCORE` (3) → top 3 matches → emit suggestion text. No matches → log `no_match` silently. |
| **Failure mode** | Fail-open: any exception → exit without blocking. |
| **Rationale** | Nudges toward specialist agents when a generic dispatch is used, without enforcing it — addresses the advisory routing gap for domain-specific agents. |

---

### `subagent-scope-check.py`

| Attribute | Value |
|---|---|
| **Event** | SubagentStart + SubagentStop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` (both SubagentStart and SubagentStop) |
| **Action** | At SubagentStart: captures `git status --porcelain` baseline keyed by agent_id. At SubagentStop: diffs current git status against baseline and logs new/resolved changes. Pure instrumentation — never blocks. |
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
| **Rationale** | Provides a structural exit gate for agent output — catches agents that produce empty, malformed, or non-compliant output before it propagates into the main session. |

Note: `subagent-scope-check.py` also fires at SubagentStop — documented in the SubagentStart section above.

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
| **Logical paths** | `stop_hook_active=True` → return. Extract MUST DISPATCH from last assistant text via `extract_dispatch_names()`. MUST DISPATCH = "none" or empty → H3 check: non-Quick task with empty MUST DISPATCH → block (missing declaration). MUST DISPATCH present → collect actual agent dispatches from transcript (with alias expansion via `SKILL_AGENT_ALIASES`) → all declared names fulfilled → pass. Any declared name not found in actual dispatches → block. H11 sidecar fallback: if post-compaction and sidecar has dispatch record → use sidecar data. authoritative branch set: `test_dispatch_compliance.py` |
| **Failure mode** | Fail-open: parse errors, missing transcript → pass. |
| **Rationale** | Enforces that MUST DISPATCH declarations are executable commitments, not suggestions — the primary driver of the 53% → target compliance-rate improvement. |

---

### `governance-log.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Appends one `turn_summary` JSONL entry to governance-log.jsonl per turn that contains a classification block. Pure logging — never blocks. |
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
| **Action** | Hard-blocks on missing process-skill structural requirements (SCOPE block, QA REPORT, PENTEST REPORT, PM checkpoint); soft-logs on advisory gaps (missing synthesis, missing architect-review, zero agent dispatches). |
| **Inputs** | stdin JSON payload: `transcript_path`, `stop_hook_active`. Reads 200KB transcript tail. |
| **Outputs / Side-effects** | On hard violation: stdout `{"decision": "block", "reason": "..."}`. Soft violations: logged to governance-log.jsonl (no stdout). |
| **Logical paths** | `stop_hook_active=True` → return. Check: process skill invoked but no SCOPE block → hard block. process-qa invoked but no QA REPORT/PASS → hard block. process-pentest invoked but no PENTEST REPORT → hard block. PM invoked but pm-orchestrator not dispatched (rubber-stamp guard, B2 fix) → hard block. Increment complete but no /pm checkpoint → hard block. Missing synthesis (soft) → log. Missing architect-review (soft) → log. Zero agent dispatches (soft) → log. authoritative branch set: `test_process_step_check.py` |
| **Failure mode** | Fail-open: parse errors → exit without blocking. |
| **Rationale** | Enforces process-skill structural completeness at turn-end, catching abbreviated skill execution (e.g. invoking /process-qa but not producing a report) before it registers as a completed step. |

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
| **Logical paths** | Count Agent dispatches in last turn. Count citation patterns (wikilinks, source references) in response text. Count file writes. Compute severity: ≥1 agent dispatch + zero citations → `high`. Citation ratio < 0.5 → `medium`. Adequate citations → `low`. Write dark-zone event with severity, counts. |
| **Failure mode** | Fail-open: all exceptions swallowed; never blocks. |
| **Rationale** | Provides a signal for turns where agents were dispatched but the response cites no evidence — a pattern associated with fabricated inventory claims documented in `feedback_main_session_can_fabricate_inventory.md`. |

---

### `work-verification-check.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Four checks: (CHECK 1) Hard-blocks QA/pentest report filed with zero tool usage. (CHECK 1b) Hard-blocks inline QA report on non-Quick task without /process-qa invocation. (CHECK 2) Hard-blocks premature escalation (asks user for help after <3 tool uses). (CHECK 4) Soft-logs/warns fabricated Write claims (claimed to write path that doesn't exist and wasn't written). Also emits session_end and qa_fail_reported telemetry events. |
| **Inputs** | stdin JSON payload: `transcript_path`, `stop_hook_active`. Reads 200KB transcript tail plus tool_result blocks. |
| **Outputs / Side-effects** | On CHECK 1/1b/2 violation: stdout `{"decision": "block", "reason": "..."}` + governance-log.jsonl entry. On CHECK 4 fabrication: stderr warning + governance-log.jsonl entry (non-blocking). Emits `session_end` heartbeat and `qa_fail_reported` events via `_event_emit`. |
| **Logical paths** | `stop_hook_active=True` → return. Walk last turn collecting tool uses, text blocks, QA/pentest report markers, classification, skill invocations. Compute execution_tools (Bash + mcp__*), tool_count (all except Skill). CHECK 1: QA/pentest report present + process skill invoked + zero execution tools + zero Read tools → hard block. CHECK 1b: non-Quick + QA report present + process-qa not invoked → hard block. CHECK 4: scan text for Write-claim regex patterns → claimed path not in Write trace AND not on disk → fabrication → stderr warn + log. CHECK 2: escalation patterns in response + non-Quick + tool_count < 3 → hard block. CHECK 3 (soft): non-Quick + zero tool_count → log warn. Emit session_end heartbeat. Emit qa_fail_reported if QA REPORT with FAIL: lines. Log pass for monitoring. |
| **Failure mode** | Fail-open: parse errors → return without blocking; all observability emits wrapped in try/except. |
| **Rationale** | Closes three distinct verification gaps: lazy QA (report without execution), rubber-stamp escalation (asking user before exhausting tools), and fabricated file-write claims surfaced by the SA-4 sprint. |

---

### `token-breakdown.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Aggregates token usage for the turn (main session + per-subagent) and emits a `token_breakdown` event. Telemetry only — never blocks. |
| **Inputs** | stdin JSON payload: `transcript_path`. Reads transcript tail for `message.usage` fields and `toolUseResult.usage` fields (subagent). |
| **Outputs / Side-effects** | Emits `token_breakdown` event via `_event_emit` helper. Fields: `turn_total_tokens`, `main_session`, `by_subagent` (dict), `tool_calls`, `skill_names`, `task_type`. No stdout to CC. |
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

### `epistemic-check.py`

| Attribute | Value |
|---|---|
| **Event** | Stop |
| **Matcher** | none |
| **Registered in** | `settings/settings.json.template` |
| **Action** | Spawns a `claude -p --model haiku` subprocess to evaluate the last response for overconfidence. Blocks if Haiku returns `{"decision": "block"}`. |
| **Inputs** | stdin JSON payload: `transcript_path`, `stop_hook_active`. Reads last assistant message from transcript. |
| **Outputs / Side-effects** | On Haiku block verdict: stdout `{"decision": "block", "reason": "..."}`. On pass or timeout: nothing. |
| **Logical paths** | `stop_hook_active=True` → return. Extract last assistant message from transcript. Build evaluation prompt → spawn `claude -p --model haiku` subprocess with 15s timeout. Parse stdout → `{"decision": "block"}` → emit block. Any other response → pass. Timeout → fail-open (pass). Subprocess error → fail-open (pass). Parse error → fail-open (pass). |
| **Failure mode** | Fail-open: all subprocess errors, timeouts, and parse failures → exit 0 without blocking. |
| **Rationale** | Provides an external evaluator gate for epistemic honesty using a fresh model context. Note: the disabled/ version of this hook was found to never block in practice (see `hooks/disabled/README.md`); the registered version preserves the circuit but its real-world block rate is low. |

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
| **Inputs** | stdin JSON payload (PreCompact fields). Reads transcript tail (200KB). Reads all `Projects/*/STATE.md` and `Projects/*/task_plan.md` files. |
| **Outputs / Side-effects** | Writes `{{HOME}}/.claude/pre-compact-recovery.md`. Resets `{{HOME}}/.claude/last-checkpoint` to epoch. **Produces no stdout** — PreCompact does not accept `additionalContext`. |
| **Logical paths** | Parse payload → read transcript tail → extract last 3 user messages → extract last classification block → list recently modified files → read all STATE.md files → extract In Progress / Shaped task_plan sections (cap) → write recovery file. Any individual read error → skip that section, continue. |
| **Failure mode** | Fail-open: individual file read errors skipped; write failure logged to stderr; exit 0 always. |
| **Rationale** | Provides a human-readable recovery point before each compaction so state can be restored if the compacted summary loses critical context (addresses the compaction-loses-attribution failure mode). |

---

## Disabled / opt-in hooks

These files ship in `hooks/disabled/` or are present in `hooks/` but explicitly not registered. They have zero runtime effect unless manually armed.

| Hook file | Where | Reason unregistered | One-line description |
|---|---|---|---|
| `disabled/epistemic-check.py` | `hooks/disabled/` | Disabled after failure — never blocked in practice; cannot distinguish correct from incorrect confidence without semantic domain understanding | Earlier version of the Stop-event Haiku evaluator; disabled per `disabled/README.md` lessons |
| `disabled/agent-dispatch-check.py` | `hooks/disabled/` | Disabled after failure — allowlist model blocked legitimate ad-hoc dispatches; ceilings punish adaptation | PreToolUse (Agent) version that blocked (not warned) dispatches not in a pre-approved allowlist |
| `disabled/delegation-check.ps1` | `hooks/disabled/` | Disabled after failure — same rationale as agent-dispatch-check.py; PowerShell form | PowerShell PreToolUse hook that blocked undeclared agent dispatches |
| `disabled/routing-table-validation.py` | `hooks/disabled/` | Opt-in by design — correct and tested (26 tests); ships unregistered because arming a blocking hook on CLAUDE.md + SKILL.md is a deliberate decision requiring a complete registry | PreToolUse (Edit\|Write\|MultiEdit) hook that denies edits introducing broken agent-name references in CLAUDE.md or any SKILL.md |
| `disabled/weekly-usage.py` | `hooks/disabled/` | Opt-in — standalone script, not a hook; requires `claude_monitor` package | CLI utility printing weekly token usage grouped by model and day since last Friday 8PM |
| `prose-slop-check.py` | `hooks/` (dormant) | Opt-in — built and calibrated (0 false positives on a 19-page prose corpus); ships unregistered until the maintainer arms it | PostToolUse (Write) hook that warns on LLM-register slop vocabulary in `Resources/KB/` and `Projects/*/work/` prose |
