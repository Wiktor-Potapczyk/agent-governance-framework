---
name: task-classifier
description: Classify the current task before any work begins. Determines task type and recommended approach. Invoke at the start of every substantive task.
---

# Task Classifier

Classify the current task. Announce classification before doing anything else.

## Step 0 — Read for Depth (before the type matrix)

**Before anything else, answer this question in one sentence:**
> **What does this prompt imply?**

Write your answer as `IMPLIES:` in the classification block. This is not optional. Engage with what the user actually needs beneath the literal words — not what the words say, but what they mean in context.

Conversational phrasing often disguises investigation as casual questions. These patterns signal depth:
- "Why did X happen?" → investigation (not a factual lookup — requires tracing causes)
- "Thought experiment — what if X?" → architectural reasoning
- "I've noticed X" / "I feel like X" → inviting analysis of a pattern
- "Analyze this" / "Think about this" → explicit depth request
- "Is it that X?" / "Was it always like this?" → hypothesis testing requiring evidence
- "Before deciding..." / "Before we..." → asking for deliberation, not a quick answer
- "Are you sure?" / "Think deeper" / "No deeper analysis?" → directive to reconsider — inherits or escalates current task, NEVER Quick

**If the message signals depth, you MUST find a matching type in Step 1.** If you scan the matrix and find 0 matches for a message that clearly asks for reasoning, investigation, or deliberation — your definitions are too narrow, not the message too simple.

## Step 1 — Apply the Type Matrix

Scan each type and note which ones apply. For each match, note whether it is **primary** (the main thing being done) or **compound** (a supporting activity embedded within the primary).

- **Research** — open questions, needs source materials → `architect-loop` → research team
- **Analysis** — investigating causes, diagnosing behavior, evaluating artifacts, reasoning about architecture, tracing failures, comparing options — any task where understanding WHY or HOW matters → specialist agent or inline reasoning with evidence
- **Content** — producing written copy for an audience → research-orchestrator → content-marketer
- **Build** — implementing code, scripts, or n8n workflow JSON → implementation-plan → blueprint-mode
- **Planning** — designing architecture, sequencing work, creating a spec → implementation-plan

If no types match → candidate for Quick (proceed to Step 3).
If exactly one matches → that type. No compounds.
If two or more match → the **primary** type becomes TYPE. Secondary types are **compounds** — declare them in APPROACH with their agents. If no clear primary (all types roughly equal), TYPE = Compound. **Compound sub-tasks cannot be Quick.**

### Mandatory compounds (always yes for these types)

| TYPE | Always-yes compound | Agent/Skill | Why |
|------|-------------------|-------------|-----|
| Build | Analysis | architect-review | Every build needs post-build quality review |
| Planning | Analysis | adversarial-reviewer | Every plan needs challenge before committing |
| **ALL non-Quick** | **QA** | **process-qa** | **Every non-Quick task produces claims that must be verified before completing. QA is not optional — it is the mechanism that extends autonomous run length.** |
| **2+ compounds detected** | **PM** | **pm** | **Tasks with 2+ compounds are complex enough to need project management oversight. PM reviews project state, validates scope, and catches phase transitions.** |

These are floor rules — the classifier MUST mark these compounds as "yes" regardless of what the task looks like. Additional compounds are still detected normally.

**QA enforcement:** process-qa goes into MUST DISPATCH for every non-Quick task. The dispatch-compliance Stop hook verifies it was invoked. The QA process must produce a QA REPORT block with PASS/FAIL counts — this is the machine-checkable proof that verification happened. QA does NOT fix failures — it reports them. If all attempts to fix fail, escalate to the user.

**PM enforcement:** `pm` goes into MUST DISPATCH when the classifier detects 2+ compounds in APPROACH. The dispatch-compliance Stop hook verifies it was invoked. The process-step-check hook provides a safety net via TaskCreate count (2+ TaskCreate also triggers PM enforcement independently).

**PM reactive triggers:** Beyond the 2+ compound floor rule, the classifier MUST also add `pm` to MUST DISPATCH when ANY of these signals are present in the user's message. If a reactive trigger fires on what would otherwise be Quick, escalate to Analysis (reactive triggers indicate state change, which is never Quick):
- **Scope change** — user introduces new requirements, changes direction, or says "actually", "instead", "let's pivot"
- **Blocker reported** — user says something is stuck, blocked, or not working as expected
- **New workstream** — user starts work on something clearly outside the current task_plan.md scope
- **Phase transition** — user reports a milestone is complete, all tasks are done, or asks "what's next?"
These signals indicate project state has changed and PM needs to re-evaluate. When a reactive trigger fires, PM runs BEFORE the primary task — it orients the session before work begins.

## Step 1.5 — Domain Detection

If the task involves a specialist domain, note it. Domain detection overrides the generic agent table in process skills — the specialist agent handles it directly.

| Domain | Specialist Agent | Trigger |
|--------|-----------------|---------|
| n8n workflows | workflow-orchestrator (design) / blueprint-mode (build) | n8n nodes, workflow JSON, execution errors |
| MCP servers/clients | mcp-server-architect (design) / mcp-developer (build) | MCP protocol, transport, tool definitions |
| PostgreSQL | postgres-pro | queries, EXPLAIN, replication, pgBouncer, JSONB |
| Redis/MongoDB/NoSQL | nosql-specialist | Redis, MongoDB, Cassandra, document stores |
| PowerShell/Windows | powershell-7-expert | PS scripts, Azure, M365, Graph API |
| LLM architecture | llm-architect | model selection, RAG, multi-agent design, inference |
| LLM prompts | prompt-engineer | system prompts, few-shot, output format, prompt optimization |
| API design/behavior | api-designer | REST/GraphQL endpoints, auth flows, unfamiliar APIs |
| Competitive analysis | competitive-analyst | SWOT, feature matrices, pricing, positioning |
| Security | api-security-audit | OWASP, auth vulnerabilities, webhook security |

**If no domain matches → leave DOMAIN blank.** The process skill uses its core agent table.
**If domain matches → the process skill should route to the specialist** instead of (or alongside) the generic agent.

## Step 2 — Challenge your approach (MANDATORY — not skippable)

After classifying TYPE and deciding your APPROACH, answer this question:

> **"What would I miss by handling it this way?"**

Write your answer as a `MISSED:` line in the classification block. If the answer reveals something significant — a blind spot, a wrong assumption, or a better alternative — reconsider your TYPE or APPROACH before proceeding.

## Step 3 — Quick Check (burden of proof is on Quick)

**The default is NOT Quick.** If you are unsure, classify as Analysis. Quick must be actively proven — ambiguity always resolves to depth, never to simplicity.

Downgrade to **Quick** ONLY if ALL of these are true:
- The type matrix produced 0 Yes answers AND Step 0 detected no depth signals
- The message is NOT a follow-up, correction, or directive about ongoing work (e.g., "think deeper", "are you sure?", "no, try again"). These inherit or escalate the prior classification — they are never Quick.
- The entire response is a single factual lookup, a file move, or a one-field edit
- You are not investigating, diagnosing, reasoning about causes, or tracing a chain of events
- You are not designing, evaluating, comparing, recommending, or producing any artifact
- The answer requires no reasoning chain longer than one step
- No specialist agent would produce a better answer
- A wrong answer has no consequences beyond a single field

If ANY criterion fails, Quick is not available. **Default to Analysis** and re-examine your Step 1 answers — you likely answered "No" too narrowly on a row that should be "Yes."

**Quick still requires the announcement block:**

```
IMPLIES: [one sentence from Step 0]
TASK TYPE: Quick
JUSTIFICATION: [one sentence — why no specialist agent would improve this answer]
```

Then answer inline.

## Step 4 — Ralph Loop check

This step is about whether the investigation needs isolation from this conversation's context.

Ralph Loop is appropriate if ANY of these are true:
- The task requires evaluating something this conversation has already formed opinions about
- Prior messages contain hypotheses that could anchor the investigation
- The task needs comparing multiple options where fairness requires fresh context
- Multiple open questions require exhausting source materials independently
- The investigation requires reading/processing enough material to significantly consume context
- The problem has enough interacting parts that you can't hold the full picture in a single reasoning chain

If yes → recommend `architect-loop`. If no → direct delegation is sufficient.

## Step 5 — Announce

Before outputting the block, consider which quality mechanism might apply (this guides your reasoning but is NOT emitted in the output):

| Task characteristic | Consider |
|---------------------|----------|
| Math or logic with verifiable steps | /verify (CoVe) |
| Framing, design, architecture, option comparison | /ensemble |
| Subjective judgment or high-stakes evaluation | Both |

This is a reasoning step only — do NOT output a MECHANISM field.

Output exactly this block before proceeding. **ALL fields are MANDATORY. Do not skip any field. Missing fields (IMPLIES, MISSED, MUST DISPATCH) will be caught by the Stop hook and block your response.**

```
IMPLIES: [one sentence from Step 0 — what does this prompt imply?]
TASK TYPE: [Quick / Research / Analysis / Content / Build / Planning / Compound]
DOMAIN: [specialist domain from Step 1.5, or "general" if none]
APPROACH: [Declare the primary path, then check EACH of the 5 primitive operations as a potential compound:
  Research compound? [yes/no — if yes, name the agent]
  Analysis compound? [yes/no — if yes, name the agent]
  Planning compound? [yes/no — if yes, name the agent]
  Build compound? [yes/no — if yes, name the agent]
  QA compound? [yes/no — if yes, name the agent/method. QA = does this task produce claims that need empirical verification?]
  Example: "Build via blueprint-mode. Research: yes (technical-researcher for API docs). Analysis: yes (architect-review for post-build). Planning: no. QA: yes (test hook fires in fresh session)."
  Note: Content is a domain specialization of Build, not a primitive. These 5 are the irreducible operations of knowledge work.]
MISSED: [one sentence from Step 2 — what would I miss by handling it this way? Quick tasks: write "N/A"]
MUST DISPATCH: [see rules below. Quick tasks: omit this field.
  **PM SELF-CHECK before writing this line:** count the "yes" answers above. If 2 or more → pm MUST be in this list. The Stop hook will block you if it's missing.]
```

**APPROACH** declares the full compound mixture — not just the primary path but all secondary compounds the task contains. Each compound names its agents. The process skill for TYPE handles the primary path; the compound agents handle the secondary paths within it. If APPROACH only names one agent for a task that IMPLIES reveals has multiple dimensions, you've missed a compound.

**MUST DISPATCH** is the enforcement contract. The Stop hook reads this field and verifies every listed item was actually invoked (Skill or Agent tool). Missing dispatches block your response.

**MUST DISPATCH rules — IMPLIES + COMPOUNDS drive the dispatch level:**
- List the process skill for TYPE + all agents named in APPROACH compounds marked "yes"
- If APPROACH says "Research: yes (technical-researcher)" → technical-researcher goes in MUST DISPATCH
- If APPROACH says "Analysis: yes (architect-review)" → architect-review goes in MUST DISPATCH
- **QA is ALWAYS in MUST DISPATCH for non-Quick tasks** — add `process-qa` to every non-Quick MUST DISPATCH list. This is non-negotiable.
- **PM checkpoint (`pm`) is in MUST DISPATCH when 2+ compounds are detected OR a reactive PM trigger fires** — if APPROACH lists 2 or more compounds marked "yes", add `pm` to MUST DISPATCH. Also add `pm` if any reactive trigger signal is present (scope change, blocker, new workstream, phase transition — see PM reactive triggers above). Single-compound tasks without reactive triggers skip PM.
- All compound agents are enforced — the Stop hook verifies each was actually invoked
- If IMPLIES reveals the work can be done inline with no compounds → `none` — BUT QA still applies. MUST DISPATCH is at minimum `process-qa` for non-Quick.
- Format: only comma-separated names or `none`. No parenthetical explanations after `none`. `none` is ONLY valid for Quick tasks.

**HARD STOP.** If MUST DISPATCH lists a process skill, your ONLY allowed next action is invoking it via the Skill tool. If MUST DISPATCH is `none`, proceed inline — but you must still follow APPROACH.

| TYPE | Invoke this skill |
|------|------------------|
| Research | `process-research` |
| Analysis | `process-analysis` |
| Content | `process-build` (Content is Build with DOMAIN: content — uses content-marketer as builder agent) |
| Build | `process-build` |
| Planning | `process-planning` |
| Compound | `process-analysis` (Decomposition mode) |
| Quick | No skill — respond inline |

**Pass the full classification block (TYPE, DOMAIN, APPROACH) as the skill's args parameter** so the process skill knows the routing decision. If DOMAIN is set, tell the process skill to route to the specialist agent.

### Classification traps (common mistakes)

| User request | WRONG classification | RIGHT classification | Why |
|---|---|---|---|
| "Design a scoring system for award entries" | Planning | Research → Planning | You don't know the scoring criteria yet — research first |
| "What's the best way to handle X?" | Quick | Research | "Best way" requires comparing options, not a single fact |
| "Review this workflow and fix the error" | Build | Analysis → Build | Evaluate before fixing — the error may not be what it looks like |
| "Update the prompt to handle edge case Y" | Quick | Analysis → Build | Need to understand current behavior before changing |
| "Move the old spec to archives" | Analysis | Quick | Single file move, no judgment needed |
| "Research best practices and redesign auth" | Research → Planning → Build | Compound: Research + Planning | User said "research and redesign" not "implement" — don't add Build |
| "Why did X fail?" | Quick | Analysis | Requires tracing causes, not a single fact — investigation |
| "Thought experiment — what if X leaks into Y?" | Quick | Analysis | Architectural reasoning about system behavior |
| "Was it always like this?" | Quick | Analysis (→ Research if needed) | Requires evidence gathering and timeline reconstruction |
| "I've noticed X behaves differently" | Quick | Analysis | Pattern observation invites investigation, not acknowledgment |
| "Analyze this thoroughly before deciding" | Quick | Analysis | The word "analyze" is literally there — never Quick |
| "Think about this more carefully" | Quick | Analysis | Explicit request for deeper reasoning |

## Step 6 — Execution Rules (non-Quick only)

**Every non-Quick task is a mini-project.** Apply lifecycle treatment:

1. **If the task has 2+ steps or compounds:** MUST create a task list (TaskCreate) before executing. The task list defines the increment. Each task gets its own classification, process skill, and QA.

2. **Execute tasks sequentially** (WIP limit: 1). Mark each TaskUpdate: completed as you finish it.

3. **When all tasks are completed:** invoke `process-pentest` before reporting back to the user. Pentesting tries to break what was built across the whole increment — not individual tasks (that's QA). You have Bash, Read, MCP — use them to actually test.

4. **If pentesting finds HIGH severity issues:** fix them, re-test, then report. After 2 failed fix attempts on the same finding, escalate to the user.

5. **After pentest completes:** invoke `/pm` to run a PM checkpoint. This reviews project state, recommends next action, and catches phase transitions. PM is in MUST DISPATCH whenever the classifier detected 2+ compounds (see mandatory compounds table).

6. **Single-compound non-Quick tasks** (one compound, no decomposition needed): skip TaskCreate. QA still fires per task. Pentesting and PM are not required for single-compound tasks — QA covers it.

## Notes

- This classification routes to the **delegation rules in CLAUDE.md** — use those to pick the specific agent within each type.
- When in doubt between two types, **pick the one that requires MORE investigation, not less.** The cost of over-investigating is low (extra time). The cost of under-investigating is high (wrong output, rework, missed complexity). Default to depth.
- **Compound tasks**: invoke `process-analysis` in Decomposition mode. It will break the request into sub-tasks, classify each (TYPE + DOMAIN), identify dependencies, and invoke each sub-task's process skill in order. Do NOT decompose inline — delegate to the process.
