# Workflows Reference

**Audience:** Operators deploying or adapting the framework.
**Mode:** Reference: attributes tables, no tutorial prose. **Code is the source of truth**: if a field here disagrees with the `.js` file, the code wins.

A workflow script is a Claude Code Workflow tool script (`export const meta = {...}`) that encodes the dispatch sequence for one process skill by construction. Each script in `workflows/` corresponds to a core process skill. The prose SKILL.md is the spec-of-record and explicit fallback; the workflow script is the authoritative runtime for operators who use the Workflow tool.

For setup instructions, see `INSTALL.md §Workflows`. For the design rationale, see `docs/adr/0006-full-procedure-layer-migration.md`.

---

## Summary table

| Script | Corresponding skill | Phases | HALT paths | Registered in |
|---|---|---|---|---|
| `process-research.js` | `process-research` | Scope → Research → Synthesis → Report → Quality | `ralph-loop-hand-back`, `halted-malformed-args` | Operator installs to `.claude/workflows/` |
| `process-analysis.js` | `process-analysis` | Scope → Analyze → Synthesis → Report → Quality | `decomposition-hand-back`, `halted-malformed-args` | Operator installs to `.claude/workflows/` |
| `process-build.js` | `process-build` | Scope → Plan → Build → Review → Quality | `halted-malformed-args` | Operator installs to `.claude/workflows/` |
| `process-planning.js` | `process-planning` | Scope → Research (optional) → Plan → Review → Quality | `halted-malformed-args` | Operator installs to `.claude/workflows/` |
| `process-qa.js` | `process-qa` | Scope → Execute → Report → Quality | `halted-malformed-args` | Operator installs to `.claude/workflows/` |
| `process-pentest.js` | `process-pentest` | Scope → Attack-enum → Execute → Report → Quality | `halted-malformed-args` | Operator installs to `.claude/workflows/` |

---

## `process-research.js`

| Attribute | Value |
|---|---|
| **Script** | `workflows/process-research.js` |
| **Skill** | `process-research` |
| **Invocation** | `Workflow({scriptPath: "{{VAULT_ROOT}}/.claude/workflows/process-research.js", args: {project, question, sources?, constraints?}})` |
| **Phases** | 1. Scope (query-clarifier or inline) → 2. Research (research-orchestrator pipeline: analyst + technical-researcher in parallel) → 3. Synthesis (research-synthesizer, mandatory when ≥2 agent findings) → 4. Report (report-generator) → 5. Quality (architect-reviewer) |
| **HALT: ralph-loop-hand-back** | When scope agent returns `ralph_loop_indicated: true`: script returns `{status: "ralph-loop-hand-back", scope_block_for_loop: ...}` and stops. Caller (main session) must initiate the ralph loop manually. |
| **HALT: halted-malformed-args** | When `args.project` or `args.question` is missing: script returns `{status: "halted-malformed-args", message: ...}` before spawning any agents. |
| **Typed schemas** | SCOPE_SCHEMA, FINDINGS_SCHEMA, SYNTHESIS_SCHEMA, REPORT_SCHEMA, QUALITY_SCHEMA |
| **Returns** | `{status: "complete", research_report_text: string, quality_verdict: string}` |
| **DISPATCHES.json** | `skills/core/process-research/DISPATCHES.json`: retained as H11 read-only audit artifact |
| **Hook preconditions** | None specific to this script |

---

## `process-analysis.js`

| Attribute | Value |
|---|---|
| **Script** | `workflows/process-analysis.js` |
| **Skill** | `process-analysis` |
| **Invocation** | `Workflow({scriptPath: "{{VAULT_ROOT}}/.claude/workflows/process-analysis.js", args: {project, subject, mode?, rubric?, constraints?}})` |
| **Phases** | 1. Scope (mode detection: evaluation / diagnosis / decomposition / synthesis) → 2. Analyze (specialists in parallel via `parallel()`) → 3. Synthesis → 4. Report (conditional on `scope.complex`) → 5. Quality |
| **HALT: decomposition-hand-back** | When scope returns `mode: "decomposition"`: script returns `{status: "decomposition-hand-back", decomposition_subtasks: [...]}` and stops. Caller decomposes the task list manually. |
| **HALT: halted-malformed-args** | When `args.project` or `args.subject` is missing. |
| **Evaluation mode guard** | When `mode === "evaluation"`, script hard-fails if `args.rubric` is empty: prevents unanchored evaluation. |
| **Typed schemas** | SCOPE_SCHEMA, ANALYSIS_SCHEMA, SYNTHESIS_SCHEMA, REPORT_SCHEMA, QUALITY_SCHEMA |
| **Returns** | `{status: "complete", analysis_report_text: string, quality_verdict: string}` |
| **DISPATCHES.json** | `skills/core/process-analysis/DISPATCHES.json`: retained as H11 read-only audit artifact |

---

## `process-build.js`

| Attribute | Value |
|---|---|
| **Script** | `workflows/process-build.js` |
| **Skill** | `process-build` |
| **Invocation** | `Workflow({scriptPath: "{{VAULT_ROOT}}/.claude/workflows/process-build.js", args: {project, spec, constraints?, llm_prompts?, n8n_domain?}})` |
| **Phases** | 1. Scope → 2. Plan (implementation-plan) → 3. Build (blueprint-mode) → 4. Review (architect-reviewer + adversarial-reviewer in parallel; prompt-engineer added when `args.llm_prompts`) → 5. Quality (process-qa via nested agent) |
| **HALT: halted-malformed-args** | When `args.project` or `args.spec` is missing. |
| **FILE CONTRACT** | Build agent receives an explicit FILE CONTRACT specifying the expected output file path; Quality gate reads the file to confirm delivery. |
| **Review cap** | Adversarial review is capped at 2 rounds (per vault doctrine: `feedback_adversarial_loop_ratchets_past_necessity.md`). |
| **Typed schemas** | SCOPE_SCHEMA, PLAN_SCHEMA, BUILD_SCHEMA, REVIEW_SCHEMA, QUALITY_SCHEMA |
| **Returns** | `{status: "complete", build_report_text: string, quality_verdict: string}` |
| **DISPATCHES.json** | `skills/core/process-build/DISPATCHES.json`: retained as H11 read-only audit artifact |

---

## `process-planning.js`

| Attribute | Value |
|---|---|
| **Script** | `workflows/process-planning.js` |
| **Skill** | `process-planning` |
| **Invocation** | `Workflow({scriptPath: "{{VAULT_ROOT}}/.claude/workflows/process-planning.js", args: {project, task_brief, classification_block?}})` |
| **Phases** | 1. Scope → 2. Research (optional, only when scope indicates unknowns) → 3. Plan (implementation-plan) → 4. Review (mandatory parallel: architect-reviewer + adversarial-reviewer [+ prompt-engineer when LLM prompts present]) → 5. Quality |
| **HALT: halted-malformed-args** | When `args.project` or `args.task_brief` is missing. |
| **Review mandatory** | Unlike process-build, architect-review is unconditionally mandatory in process-planning: not conditional on any scope flag. |
| **Typed schemas** | SCOPE_SCHEMA, PLAN_SCHEMA, REVIEW_SCHEMA, QUALITY_SCHEMA |
| **Returns** | `{status: "complete", plan_text: string, quality_verdict: string}` |
| **DISPATCHES.json** | `skills/core/process-planning/DISPATCHES.json`: retained as H11 read-only audit artifact |

---

## `process-qa.js`

| Attribute | Value |
|---|---|
| **Script** | `workflows/process-qa.js` |
| **Skill** | `process-qa` |
| **Invocation** | `Workflow({scriptPath: "{{VAULT_ROOT}}/.claude/workflows/process-qa.js", args: {project, claims: [...], source?, constraints?}})` |
| **Phases** | 1. Scope (N claims in → N results out contract) → 2. Execute (per-claim execution agents with raw tool output) → 3. Report (QA REPORT block with PASS/FAIL per claim + Untested Surface) → 4. Quality |
| **HALT: halted-malformed-args** | When `args.project` is missing or `args.claims` is empty or not an array. |
| **AUTO-FAIL rule** | Any claim where the execute-agent used only Read/Grep (no Bash or MCP) to verify a behavioral assertion → automatically downgraded to FAIL. Encoded in the typed schema evaluation, not in prose agent judgment. |
| **Coverage rule** | N claims in → N results out. If results count mismatches claims count, missing results are padded with FAIL. |
| **TRANSCRIPT RELAY CONTRACT** | Script returns `qa_scope_text` + `qa_report_text` as plain strings. After the Workflow tool returns, the main session MUST relay both verbatim as plain unfenced text: `process-step-check.py` matches these strings after fence-stripping; fenced relay is invisible to the hook. |
| **Hook preconditions** | `process-step-check.py` B-1a/B-1b (Workflow-aware SCOPE detection) and `work-verification-check.py` B-2/B-3 (Workflow-path execution suppression) must be on disk. |
| **Typed schemas** | SCOPE_SCHEMA, EXECUTE_SCHEMA, REPORT_SCHEMA, QUALITY_SCHEMA |
| **Returns** | `{status: "complete", qa_scope_text: string, qa_report_text: string}` |
| **DISPATCHES.json** | `skills/core/process-qa/DISPATCHES.json`: retained as H11 read-only audit artifact |

---

## `process-pentest.js`

| Attribute | Value |
|---|---|
| **Script** | `workflows/process-pentest.js` |
| **Skill** | `process-pentest` |
| **Invocation** | `Workflow({scriptPath: "{{VAULT_ROOT}}/.claude/workflows/process-pentest.js", args: {project, increment_summary, artifacts: [...], constraints?}})` |
| **Phases** | 1. Scope → 2. Attack enumeration (threat-model agent produces ranked attack list) → 3. Execute (per-attack agents in parallel, each returning raw tool output) → 4. Synthesis (pentest-synthesizer) → 5. Report (PENTEST REPORT with per-finding verdict + Untested Surface + overall recommendation) |
| **HALT: halted-malformed-args** | When `args.project` or `args.increment_summary` is missing. |
| **Evidence-only gate** | Per-attack execute agents must return raw tool output in `evidence_raw` field. If `evidence_raw` is empty, the attack result is auto-downgraded to INCONCLUSIVE. |
| **Recommendation values** | `SHIP` / `FIX` / `ESCALATE`: derived in code from finding severities, not from prose agent verdict. |
| **Typed schemas** | SCOPE_SCHEMA, THREAT_SCHEMA, ATTACK_SCHEMA, SYNTHESIS_SCHEMA, REPORT_SCHEMA |
| **Returns** | `{status: "complete", pentest_report_text: string, recommendation: "SHIP"|"FIX"|"ESCALATE"}` |
| **DISPATCHES.json** | `skills/core/process-pentest/DISPATCHES.json`: retained as H11 read-only audit artifact |

---

## Shared invariants (all six scripts)

| Invariant | Description |
|---|---|
| Parse-if-string + HALT | `args` may arrive as a JSON string (session-cached invocation). All scripts parse-if-string and halt before any agent spawn if required fields are missing. |
| Typed schemas | Every `agent()` call receives a typed schema. PASS/FAIL logic evaluates typed sub-fields, never prose self-report. |
| FILE CONTRACT | Agents that must produce files receive an explicit FILE CONTRACT block in their prompt. Quality gates read the file to confirm delivery. |
| PASS/FAIL in code | Pass conditions are evaluated by the script, not delegated to an agent's self-assessment. |
| DISPATCHES.json untouched | Workflow scripts never modify `DISPATCHES.json`. It remains the H11 read-only audit artifact. |
| HALT paths return | All HALT conditions return a structured object (`{status, ...}`). They do not throw. The caller can inspect the result and decide how to proceed. |
| Session-cache gotcha | After editing a workflow script mid-session, invoke it by `scriptPath` (absolute path), not by `name`. The Workflow tool caches scripts by name at session start; a mid-session edit is only visible via `scriptPath`. |
