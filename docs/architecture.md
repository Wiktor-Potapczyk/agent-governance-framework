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

## Component Counts

| Component | Count | Location |
|-----------|-------|----------|
| Active hooks (default config) | 12 | `hooks/` |
| Optional/disabled hooks | 4 | `hooks/disabled/` |
| Governance agents | 29 | `agents/governance/` |
| Core skills | 12 | `skills/core/` |
| Domain example skills | 19 | `skills/domain-examples/` (Apify, n8n) |
