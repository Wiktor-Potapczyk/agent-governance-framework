# Changelog

## 2026-04-13 — Alignment Fix Implementation (11/14 findings)

Comprehensive alignment analysis (8 routes, 14 findings) revealed that hooks enforce format, not correctness. This release fixes 11 of 14 findings across 4 phases.

### Phase 1: Structural Correctness

- **B4 fix:** Multiline MUST DISPATCH regex in `classifier-field-check.py` and `agent-dispatch-check.py`. Both now use `re.DOTALL` with FIELD_LABELS delimiter, matching `dispatch-compliance-check.py` pattern.
- **B5 fix:** `architect-review` vs `architect-reviewer` naming contract documented in all KNOWN_DISPATCH_NAMES copies.

### Phase 2: Alias Expansion (S3/B1)

- **SKILL_AGENT_ALIASES expanded** in `agent-dispatch-check.py` and `dispatch-compliance-check.py`:
  - `process-research`: +research-synthesizer, +report-generator (fixes B1: direct-dispatch path Step 4-5 was blocked)
  - `process-analysis`: expanded from 2 to 10 agents (all Step 2 specialists)
  - `process-planning`: expanded from 2 to 9 agents (Steps 2-4)
  - `process-build`: +prompt-engineer, +debugger
- **Canonical SKILL_AGENT_ALIASES** added to `scripts/shared/known_names.py`
- **Drift guard test** extended to cover SKILL_AGENT_ALIASES consistency across hooks + canonical

### Phase 3: Enforcement Uplift

- **S1 fix:** `classifier-field-check.py` now requires JUSTIFICATION field for Quick classifications (blocks if missing)
- **M1 fix:** `user-prompt-submit.py` adds 9 depth-signal patterns ("are you sure?", "analyze this", "why did", etc.) that inject stronger classifier warnings via additionalContext
- **B2 fix:** `process-step-check.py` `check_pm_checkpoint_report()` now verifies pm-orchestrator agent was dispatched, not just that a PM CHECKPOINT REPORT text block exists (prevents rubber-stamping)

### Phase 4: Independent Fixes

- **B3 fix:** Scheduled tasks (`daily-memory-update`, `weekly-memory-update`) corrected to reference actual `score-memory.py` path
- **M4 fix:** 4 process skill docs corrected from "caught by the Stop hook" to "logged by the Stop hook — soft enforcement"
- **M6 fix:** `governance-log.py` no longer skips blocked turns; logs with `blocked_turn: true` field

### Deferred (3/14)

- **S2** (TaskCreate enforcement hook) — requires new hook architecture, deferred to next iteration
- **M3** (shared checkpoint timer) — low impact, fix complexity not justified
- **M5** (dark-zone enforcement) — needs 30 days of log data before hardening

### Test Progression

87 → 120 tests. 3 new test files: `test_classifier_field_check.py`, `test_user_prompt_submit.py`, `test_process_step_check.py`.

---

## 2026-04-06 — Quality Enforcement + PM Simplification

Major evolution from compliance-only to compliance + quality enforcement. Hooks now check tool usage during QA, not just format. PM trigger simplified from "2+ compounds" to "every non-Quick."

### New: work-verification-check.py (Stop hook #12)

Three checks forcing actual execution and autonomous exhaustion:
1. **QA/Pentest Execution (HARD):** QA REPORT filed with zero execution tools → block
2. **Premature Escalation (HARD):** Asking user for help with <3 tools used → block
3. **Zero-Work Non-Quick (SOFT):** Non-Quick + zero tools → governance log warning

### Rewritten: process-qa/SKILL.md

- Step 3 split into 3a (run test) / 3b (show raw output) / 3c (judge PASS/FAIL)
- Step 4 NEW — Coverage Check (mandatory before reporting)
- Evidence rules: "Looks correct" without specific output = INVALID
- Scope check: if N artifacts built, N must be tested
- Hook warning at bottom

### Rewritten: process-pentest/SKILL.md

- Step 3 split into 3a-3d matching process-qa pattern: State → Execute → Show raw → Judge

### Simplified: PM enforcement (every non-Quick)

Previous trigger (2+ compounds) was circular — depended on Claude's own classification behavior. Simplified to: every non-Quick task → pm in MUST DISPATCH. No compound counting.

Files updated:
- `skills/core/task-classifier/SKILL.md` — mandatory compounds table, PM enforcement text, PM SELF-CHECK, Step 6
- `hooks/classifier-field-check.py` — compound counting regex → simple non-Quick + pm check
- `settings/settings.local.json.example` — work-verification-check.py added to Stop hooks

### Updated: CLAUDE.md

- "Exhaust before asking" rule (4 steps: Execute, Read, Retry, Delegate)
- "Test what you build" rule (work-verification hook enforces)
- PM enforcement line: every non-Quick gets PM oversight
- Model cost rule phrasing tightened
- PreCompact hook auto-saves noted

---

## 2026-03-26 — Monitoring Coverage Extension

Added governance-log.jsonl writes to 4 enforcement hooks that were previously silent. All enforcement events (block/deny) now flow to the central governance log.

### Hooks updated

| Hook | Type | Event logged |
|------|------|-------------|
| `agent-dispatch-check.py` | PreToolUse:Agent | `deny` — undeclared agent dispatch |
| `subagent-quality-check.py` | SubagentStop | `block` — empty/error/unstructured agent output |
| `epistemic-check.py` | Stop | `block` — overconfident response (Haiku-evaluated) |
| `delegation-check.ps1` | Stop | `block` — APPROACH said delegate but no Agent tool used |

### Coverage: 11/16 hooks now log to governance-log.jsonl (was 7)

All enforcement hooks centrally logged. Remaining 5 are context-injection only.

---

## 2026-03-26 — PM Enforcement Hardening

Prompt-based PM enforcement was unreliable (LLM skipped pm in MUST DISPATCH despite 2+ compounds). Added hook-level enforcement + inline self-check.

### Changes

**task-classifier/SKILL.md**
- Added PM SELF-CHECK inline in the MUST DISPATCH template field — LLM reads it while writing the field, cannot miss it
- Text: "count the yes answers above. If 2 or more → pm MUST be in this list. The Stop hook will block you if it's missing."

**hooks/classifier-field-check.py**
- Added compound-counting logic after existing field checks
- Parses APPROACH section, counts compounds marked "yes", blocks if 2+ and pm not in MUST DISPATCH
- Fires on Stop event — post-hoc catch, forces re-classification

### Enforcement Architecture (updated)

| Layer | When | Type |
|-------|------|------|
| PM SELF-CHECK in template | During classification | Prompt (inline) |
| classifier-field-check.py | Stop (post-response) | Hook (hard block) |
| dispatch-compliance-check.py | Stop (post-response) | Hook (contract check) |
| check_pm_after_increment | Stop (post-response) | Hook (TaskCreate safety net) |
| check_pm_checkpoint_report | Stop (post-response) | Hook (artifact check) |

---

## 2026-03-26 — PM Integration Fix (Systemic)

PM lifecycle management elevated from optional overlay to enforced infrastructure, achieving parity with QA enforcement.

### Problem

PM (project management checkpoints) was weakly integrated into the governance system:
- Not in the classifier's mandatory compounds table
- process-planning had zero PM references (no STATE.md, appetite, or lifecycle awareness)
- No machine-checkable output artifact (QA had QA REPORT; PM had nothing)
- pm skill made a false trust assumption about pentest ordering
- Hook enforcement contained dead code (`pm_seen` variable never set to True)
- No reactive PM triggers for mid-session state changes

### Changes

**task-classifier/SKILL.md**
- Added PM to mandatory compounds table: 2+ compounds detected triggers PM
- Added PM reactive triggers: scope change, blocker reported, new workstream, phase transition
- Updated MUST DISPATCH rules to cover both floor rule and reactive triggers
- Updated Step 6 execution rules for consistency
- Reactive triggers escalate Quick to Analysis (state changes are never Quick)

**process-planning/SKILL.md**
- Step 1 now reads STATE.md and PROJECT.md if they exist (optional, graceful degradation)
- Appetite imported from PROJECT.md into Constraints
- Scope overflow flagged if plan exceeds declared appetite
- Explicit ownership note: does not write to STATE.md (pm-orchestrator owns it)

**pm/SKILL.md**
- Added PM CHECKPOINT REPORT artifact (machine-checkable, greppable by hooks)
  - Fields: Project, Phase, Viability (PASS/HOLD/KILL), Blockers, Next
- Removed false trust assumption ("do not re-check for pentest — it already ran")

**hooks/process-step-check.py**
- Removed `pm_seen` dead code (variable was never True; function worked correctly via reset mechanism)
- Simplified `check_pm_after_increment()`: removed redundant variable and unreachable final return
- Added `check_pm_checkpoint_report()`: second enforcement layer that verifies PM CHECKPOINT REPORT artifact exists after /pm invocation
- Reports are tracked per-invocation (text after latest /pm, not cumulative)

### Enforcement Architecture (after fix)

| Layer | Mechanism | What it checks |
|-------|-----------|----------------|
| Classifier | Mandatory compounds table | 2+ compounds OR reactive trigger → pm in MUST DISPATCH |
| dispatch-compliance-check.py | MUST DISPATCH contract | Was /pm actually invoked when declared? |
| process-step-check.py (safety net) | TaskCreate count | 2+ TaskCreate + pentest done → PM required |
| process-step-check.py (artifact) | PM CHECKPOINT REPORT | After /pm: was structured report produced with Viability verdict? |

### Verification

- Per-increment QA: 10/10 claims passed across 3 increments
- Tier 2 pentest: SHIP (0 HIGH, 2 MED — one fixed inline, one structural limitation)
- Sensitive data scan: CLEAN (no employer/NDA references)

### Discovery

The `pm_seen` variable in `check_pm_after_increment()` was initially diagnosed as a critical bug ("never set to True, causes unconditional blocking"). Adversarial review + manual trace revealed this was incorrect: the function works correctly via the reset mechanism (when /pm fires, `task_creates` resets to 0, triggering the early return before `pm_seen` is ever consulted). The variable was dead code, not a behavioral bug.
