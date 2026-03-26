# Changelog

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
