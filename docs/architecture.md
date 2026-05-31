# Architecture

This document describes the technical architecture of the Agent Governance Framework -- how the components fit together, how data flows through the system, and how enforcement is achieved at each layer.

## Design Principles

The framework is built on four empirically derived principles:

1. **Exploration before extraction** -- classify what a prompt *implies* before acting on it. Open-ended investigation and directed retrieval require different processes.
2. **Process enforced, not suggested** -- soft instructions achieve ~25% compliance; hooks achieve ~90%. Every critical rule has a corresponding enforcement hook.
3. **Falsification over proof** -- QA proves absence of *found* bugs, not absence of bugs. Every QA artifact must state what was NOT tested.
4. **Recursion as the pattern** -- Classify, Decompose, Delegate, Work, QA, Report. This loop recurs at every depth with decreasing formality.

## Four-Layer Architecture

The framework operates across four enforcement layers. Each layer has hooks that fire at specific Claude Code lifecycle events.

```
User Message
    │
    ▼
┌─────────────────────────────────────────────┐
│  L0: CLASSIFIER                             │
│  UserPromptSubmit → context injection        │
│  Stop → classifier-field-check (hard block)  │
│  Stop → classifier-field-check PM check      │
└──────────────────┬──────────────────────────┘
                   │ TASK TYPE + MUST DISPATCH
                   ▼
┌─────────────────────────────────────────────┐
│  L1: PROCESS SKILLS                         │
│  PreToolUse → skill-routing-check            │
│  PostToolUse → skill-step-reminder           │
│  Stop → process-step-check (hard block)      │
└──────────────────┬──────────────────────────┘
                   │ Agent dispatches
                   ▼
┌─────────────────────────────────────────────┐
│  L2: AGENT DELEGATION                       │
│  SubagentStart → subagent-governance         │
│  SubagentStop → subagent-quality-check       │
│  Stop → dispatch-compliance-check            │
└──────────────────┬──────────────────────────┘
                   │ Tool calls
                   ▼
┌─────────────────────────────────────────────┐
│  L3: TOOL SAFETY + QUALITY                  │
│  PreToolUse → bash-safety-guard              │
│  Stop → dark-zone-check                      │
│  Stop → work-verification-check              │
│  Stop → governance-log                       │
└─────────────────────────────────────────────┘
```

### Layer 0: Classifier

Forces task classification before any work begins. Every user message triggers classification into one of 7 types: Quick, Research, Analysis, Content, Build, Planning, or Compound.

**Hook chain:**

| Hook | Event | Action | Type |
|------|-------|--------|------|
| `user-prompt-submit.py` | UserPromptSubmit | Injects context bar (token usage, session info) and classifier enforcement reminder | Context injection |
| `classifier-field-check.py` | Stop | Blocks response if IMPLIES, TASK TYPE, APPROACH, MISSED, or MUST DISPATCH fields are missing. Also enforces `pm` in MUST DISPATCH for every non-Quick task. | Hard block |

**Key artifact:** The classification block output by the task-classifier skill. Contains IMPLIES (depth analysis), TASK TYPE, DOMAIN, APPROACH (compound mixture), MISSED (blind spot check), and MUST DISPATCH (enforcement contract).

**Step 3a — Explicit Imperative Fast Path.** Before applying the burden-of-proof Quick check in Step 3, the classifier scans for explicit imperative patterns (`rename X to Y`, `move X to Y`, `fix typo in X`, `delete the unused X`, `add line/comment W to file V`, `rerun X`). When matched, the default flips to Quick. The classifier auto-escalates only if a depth signal is also present (composed depth ask, hypothesis preamble, directive to reconsider, or an ambiguous target requiring investigation). Step 3a does NOT weaken Step 3's burden of proof for general ambiguity — it explicitly recognizes a class where ambiguity does not exist (the imperative names target and action precisely). Empirical motivation: governance-log analysis showed disproportionate ceremony cost (full process skill + QA + PM dispatch chain) on one-line edits being classified as Analysis under the original burden-of-proof rule.

### Layer 1: Process Skills

Routes classified tasks to typed process flows. Each process skill defines a step sequence that the model must follow.

**Hook chain:**

| Hook | Event | Action | Type |
|------|-------|--------|------|
| `skill-routing-check.py` | PreToolUse:Skill | Validates that the invoked skill matches the classifier's TYPE routing | Hard block |
| `skill-step-reminder.py` | PostToolUse:Skill | Injects step reminders after a process skill loads | Context injection |
| `process-step-check.py` | Stop | Blocks if required artifacts are missing (SCOPE block, QA REPORT, PENTEST REPORT). Also enforces PM after multi-step increments. | Hard block |

**Process skills (12):**

| Skill | Purpose |
|-------|---------|
| `task-classifier` | Entry point -- classifies every task |
| `process-research` | Open questions needing source materials |
| `process-analysis` | Investigation, diagnosis, evaluation |
| `process-build` | Code, scripts, workflow implementation |
| `process-planning` | Architecture design, spec writing |
| `process-qa` | Empirical verification (3a/3b/3c: execute, show raw output, judge) |
| `process-pentest` | Per-increment adversarial testing (3a-3d pattern) |
| `pm` | Project management checkpoint |
| `verify` | CoVe step-level reasoning verification |
| `ensemble` | Parallel blind agents for design questions |
| `architect-loop` | Ralph Loop for context-isolated investigation |
| `index` | Research thread management |

### Layer 2: Agent Delegation

Controls how specialist agents are spawned, what context they receive, and what quality bar their output must meet.

**Hook chain:**

| Hook | Event | Action | Type |
|------|-------|--------|------|
| `subagent-governance.py` | SubagentStart | Injects behavioral rules (CLAUDE.md, MEMORY.md, skill context) into every subagent | Context injection |
| `subagent-quality-check.py` | SubagentStop | Blocks if agent output is empty, errored, or unstructured | Soft block |
| `dispatch-compliance-check.py` | Stop | Verifies every item in MUST DISPATCH was actually invoked via Skill or Agent tool | Hard block |

**Agent roster:** 29 governance agents across 5 categories: Core (blueprint-mode, debugger, architect-review, etc.), AI/Prompts (llm-architect, prompt-engineer), Research Team (orchestrator, analyst, technical-researcher, synthesizer, report-generator), Specialized (MCP, PostgreSQL, PowerShell, security), and Productivity (vault-keeper, content-marketer, competitive-analyst, workflow-orchestrator).

**Blind Analysis Rule:** When dispatching agents for evaluation, the delegation message contains ONLY what to examine and criteria -- no hypotheses, no expected outcomes, no prior conclusions. This prevents anchoring bias. Exceptions: blueprint-mode (needs specs), implementation-plan (needs requirements), content-marketer (needs briefs), adversarial-reviewer (needs what to challenge).

### Layer 3: Tool Safety and Quality Enforcement

The final layer before the response reaches the user. Covers both safety (blocking dangerous commands) and quality (ensuring actual work was done).

**Hook chain:**

| Hook | Event | Action | Type |
|------|-------|--------|------|
| `bash-safety-guard.py` | PreToolUse:Bash | Blocks rm -rf, force-push, credential exposure, and other dangerous patterns | Hard block |
| `dark-zone-check.py` | Stop | Monitors for unsupported citations and reasoning failures in areas without tool access | Soft log |
| `work-verification-check.py` | Stop | Three checks: (1) HARD -- blocks QA/pentest reports with zero execution tools; (2) HARD -- blocks premature user escalation with <3 tools used; (3) SOFT -- logs zero-work non-Quick tasks | Hard block + soft log |
| `governance-log.py` | Stop | Writes session governance events to JSONL audit log | Logging |

## Task Lifecycle

Every non-Quick task follows this lifecycle:

```
1. CLASSIFY    → task-classifier skill determines TYPE, APPROACH, MUST DISPATCH
2. PROCESS     → corresponding process skill (process-build, process-research, etc.)
3. DELEGATE    → specialist agents handle compound work
4. BUILD/WORK  → implementation via blueprint-mode or domain specialist
5. QA          → process-qa verifies claims (3a execute, 3b show raw output, 3c judge)
6. PENTEST     → process-pentest (per-increment, adversarial -- multi-step tasks only)
7. PM          → pm checkpoint (every non-Quick task)
```

**Multi-step tasks** create a task list (TaskCreate), execute sequentially (WIP limit: 1), then run pentest across the full increment before PM.

**Single-step tasks** skip TaskCreate and pentest but still run QA and PM.

## Three-Tier QA Model

Quality assurance is structured as Popperian falsification across three tiers:

| Tier | Scope | When | Tool |
|------|-------|------|------|
| **Tier 1** | Per-task verification | Every non-Quick task | `process-qa` |
| **Tier 2** | Per-increment adversarial pentest | All increment tasks complete | `process-pentest` |
| **Tier 3** | Per-milestone evaluation | Human-triggered | promptfoo or equivalent |

**Tier 1 (process-qa)** uses the 3a/3b/3c pattern:
- **3a** -- Run the test (tool call, not reasoning)
- **3b** -- Show the raw output (quote actual text before interpreting)
- **3c** -- Judge PASS or FAIL (based on specific output lines)

"Looks correct" is explicitly invalid evidence. The work-verification-check hook blocks QA reports filed with zero execution tools.

**Tier 2 (process-pentest)** uses the 3a-3d pattern: State the test, Execute it, Show raw output, Judge the result. Tests are adversarial -- boundary inputs, malformed data, regression checks, integration failures.

**Untested Surface** is mandatory in both tiers. Every report must name what was NOT tested and why.

## Two-Phase Agent Orchestration (Optional Pattern)

When agent work requires separating discovery/design from implementation with a human review gate between them, the framework supports a two-phase pattern. The motivating use case is workflow building (e.g., n8n), but the pattern generalizes to any domain where blueprint-then-build with human approval reduces wrong-direction cost.

**Phase 1 — Architect agent.** Owns all discovery, template selection, design decisions, and validation planning. Produces a `.md` blueprint at `Projects/<name>/work/YYYY-MM-DD-blueprint-<artifact>.md` containing:

- Frontmatter with `status: #pending-human-review`
- Milestones (3-5 sub-steps each)
- Per-milestone validation checkpoints
- Architectural rationale

The architect makes ZERO implementation moves — no files are created or modified beyond the blueprint itself.

**Human gate.** The user reads the blueprint (≤30 seconds for typical scope), then either:

- Approves verbally — main session flips frontmatter `status: #pending-human-review` → `#approved` via Edit
- Annotates corrections — main session re-dispatches architect with corrections
- Manually edits frontmatter to `#approved`

**Phase 2 — Builder agent.** Reads the blueprint, refuses to run if `status` is anything other than `#approved`, implements EXACTLY per blueprint, validates after every 3-5 sub-steps, and STOPS-and-reports on any blueprint gap or validation failure. The builder makes ZERO architectural decisions — on ambiguity it reports back rather than improvising.

**Trust mechanics.** The blueprint is the human-readable trust gate. If the architect misunderstood the requirement, the user catches it in the blueprint before any sub-step is built wrong. Per-milestone validation prevents error accumulation across long builds. The pattern is opt-in — for trivial single-step tasks, direct dispatch remains correct; for non-trivial multi-step builds, the two-phase structure pays back the small upfront cost.

**Reference agents:** see `agents/domain-examples/` for any shipped implementations of this pattern.

## Enforcement Summary

Every enforcement rule has at least two enforcement layers (prompt + hook). Critical rules have three or more:

| Rule | Prompt | Hook (hard) | Hook (soft) |
|------|--------|-------------|-------------|
| Classify every task | CLAUDE.md CRITICAL RULE | classifier-field-check.py | user-prompt-submit.py |
| PM for every non-Quick | task-classifier mandatory table | classifier-field-check.py, process-step-check.py | -- |
| QA for every non-Quick | task-classifier mandatory table | dispatch-compliance-check.py | work-verification-check.py |
| Execute before reporting QA | process-qa 3a/3b/3c steps | work-verification-check.py | -- |
| Exhaust tools before asking user | CLAUDE.md "Exhaust before asking" | work-verification-check.py | -- |
| Dispatch declared agents | MUST DISPATCH contract | dispatch-compliance-check.py | -- |
| Follow process skill steps | process-* SKILL.md | process-step-check.py | skill-step-reminder.py |
| Block dangerous commands | CLAUDE.md safety rules | bash-safety-guard.py | -- |

## Data Flow

```
governance-log.jsonl ← all enforcement events (blocks, denials, warnings, passes)
                       Written by: governance-log.py + 4 other hooks
                       Format: one JSON object per line, timestamped
                       Use: post-session analysis, compliance rates, hook effectiveness
```

All hooks are stateless -- they read from stdin (JSON payload from Claude Code), parse the session transcript (JSONL), and write to stdout. No database, no server, no persistent process. The governance log is the only shared state, append-only.

## Compaction Snapshot Framing

When Claude Code compacts a long session, the SessionStart hook can persist a snapshot of pre-compaction state for the post-compaction continuation. To prevent the snapshot from being read as authoritative current state (a real failure mode where post-compaction sessions made decisions citing stale frame-targets, project IDs, or file paths), every persisted snapshot is wrapped with an explicit `HISTORICAL REFERENCE ONLY (PRE-COMPACTION SNAPSHOT)` preamble and a closing reminder to verify against the live system before acting on the snapshot's facts. The framing reframes the snapshot as a pointer set (this is what was being worked on) rather than a fact set (this is what is true now). No hook-code change — content-only wrap at the snapshot generation site.

## Component Counts

| Component | Count | Location |
|-----------|-------|----------|
| Active enforcement hooks (default config) | 28 | `hooks/` |
| Shared hook libraries | 2 (`sidecar_loader.py`, `_governance_logger.py`) | `hooks/` |
| Archived stub | 1 (`context-fill-log.py`) | `_archived/hooks/` |
| Optional/disabled hook scripts | 4 (3 Python + 1 PowerShell) | `hooks/disabled/` |
| Governance agents | 29 | `agents/governance/` |
| Core skills | 12 | `skills/core/` |
| Vault management skills | 5 | `skills/vault/` |
| Domain example skills | 19 | `skills/domain-examples/` (12 Apify + 7 n8n) |
