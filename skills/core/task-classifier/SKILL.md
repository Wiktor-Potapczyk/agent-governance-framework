---
name: task-classifier
description: Classify the current task before any work begins. Determines task type and recommended approach. Invoke at the start of every substantive task.
---

# Task Classifier

Classify the current task. Announce classification before doing anything else.

## Use-when

- Start of every substantive task: runs before any other skill or agent dispatch
- Re-classification after scope change, blocker report, or pivot signals from the user
- When uncertain whether a task is Quick or merits a full process skill: the classifier is the resolver

## Do-NOT-use-when

- Already inside a process skill executing classified work: re-classifying is a process violation that creates infinite loops
- The user message is a pure conversational follow-up (clarification reply, "ok", "continue"): inherits the prior classification, not a new one

## Gotchas

- **Step 0 is non-skippable**: answer "what does this prompt imply?" before the type matrix. Skipping Step 0 produces shallow classifications that miss compound depth.
- **Burden of proof is on Quick**: when uncertain, default to Analysis. Step 3a Explicit Imperative Fast Path is the ONLY path that flips this default; all other ambiguity resolves to depth.
- **`MUST DISPATCH: none` on non-Quick is a hook-blocker**: `none` is valid only for Quick; non-Quick must list at minimum `process-qa, pm`. The Stop hook verifies and blocks the response if either is missing from MUST DISPATCH or unrun.
- **Compound sub-tasks cannot be Quick**: if the primary task has 2+ type matches, Compound classification is mandatory and routes through `process-analysis` Decomposition.

## Step 0: Read for Depth (before the type matrix)

**Before anything else, answer this question in one sentence:**
> **What does this prompt imply?**

Write your answer as `IMPLIES:` in the classification block. This is not optional. Engage with what the user actually needs beneath the literal words: not what the words say, but what they mean in context.

Conversational phrasing often disguises investigation as casual questions. These patterns signal depth:
- "Why did X happen?" → investigation (not a factual lookup: requires tracing causes)
- "Thought experiment: what if X?" → architectural reasoning
- "I've noticed X" / "I feel like X" → inviting analysis of a pattern
- "Analyze this" / "Think about this" → explicit depth request
- "Is it that X?" / "Was it always like this?" → hypothesis testing requiring evidence
- "Before deciding..." / "Before we..." → asking for deliberation, not a quick answer
- "Are you sure?" / "Think deeper" / "No deeper analysis?" → directive to reconsider: inherits or escalates current task, NEVER Quick

**If the message signals depth, you MUST find a matching type in Step 1.** If you scan the matrix and find 0 matches for a message that clearly asks for reasoning, investigation, or deliberation: your definitions are too narrow, not the message too simple.

## Step 1: Apply the Type Matrix

Scan each type and note which ones apply. For each match, note whether it is **primary** (the main thing being done) or **compound** (a supporting activity embedded within the primary).

- **Research**: open questions, needs source materials → `process-research` (which routes internally: research-orchestrator for complex multi-phase work, technical-researcher for code/repo lookups, research-analyst for structured source synthesis; never dispatch a downstream researcher directly from the main session)
- **Analysis**: investigating causes, diagnosing behavior, evaluating artifacts, reasoning about architecture, tracing failures, comparing options: any task where understanding WHY or HOW matters → specialist agent or inline reasoning with evidence
- **Content**: producing written copy for an audience → `process-research` (if research needed) then content-marketer; never dispatch research-orchestrator directly from the main session
- **Build**: implementing code, scripts, or n8n workflow JSON → implementation-plan → blueprint-mode
- **Planning**: designing architecture, sequencing work, creating a spec → implementation-plan

If no types match → candidate for Quick (proceed to Step 3).
If exactly one matches → that type. No compounds.
If two or more match → the **primary** type becomes TYPE. Secondary types are **compounds**: declare them in APPROACH with their agents. If no clear primary (all types roughly equal), TYPE = Compound. **Compound sub-tasks cannot be Quick.**

### Mandatory compounds (always yes for these types)

| TYPE | Always-yes compound | Agent/Skill | Why |
|------|-------------------|-------------|-----|
| Build | Analysis | architect-reviewer | Every build needs post-build quality review |
| Planning | Analysis | adversarial-reviewer | Every plan needs challenge before committing |
| **ALL non-Quick** | **QA** | **process-qa** | **Every non-Quick task produces claims that must be verified before completing. QA is not optional: it is the mechanism that extends autonomous run length.** |
| **ALL non-Quick** | **PM** | **pm** | **Every non-Quick task gets PM oversight. PM reviews project state, validates scope, and catches phase transitions. This is not compound-dependent: PM runs on every substantive task.** |

These are floor rules: the classifier MUST mark these compounds as "yes" regardless of what the task looks like. Additional compounds are still detected normally.

**QA enforcement:** process-qa goes into MUST DISPATCH for every non-Quick task. The dispatch-compliance Stop hook verifies it was invoked. The QA process must produce a QA REPORT block with PASS/FAIL counts: this is the machine-checkable proof that verification happened. QA does NOT fix failures: it reports them. If all attempts to fix fail, escalate to the user.

**PM enforcement:** `pm` goes into MUST DISPATCH for every non-Quick task. No compound counting: PM always runs. The dispatch-compliance Stop hook verifies it was invoked. PM considers broad project context regardless of task size.

**PM reactive triggers:** The classifier MUST also add `pm` to MUST DISPATCH when ANY of these signals are present: even on what would otherwise be Quick. Reactive triggers escalate Quick to Analysis (state change is never Quick):
- **Scope change**: user introduces new requirements, changes direction, or says "actually", "instead", "let's pivot"
- **Blocker reported**: user says something is stuck, blocked, or not working as expected
- **New workstream**: user starts work on something clearly outside the current task_plan.md scope
- **Phase transition**: user reports a milestone is complete, all tasks are done, or asks "what's next?"
These signals indicate project state has changed and PM needs to re-evaluate. When a reactive trigger fires, PM runs BEFORE the primary task: it orients the session before work begins.

## Step 1.5: Domain Detection

If the task involves a specialist domain, note it. Domain detection overrides the generic agent table in process skills: the specialist agent handles it directly.

| Domain | Specialist Agent | Trigger |
|--------|-----------------|---------|
| n8n workflows | n8n-workflow-architect (design) / n8n-workflow-builder (build) | n8n nodes, workflow JSON, execution errors |
| MCP servers/clients | mcp-server-architect (design) / mcp-developer (build) | MCP protocol, transport, tool definitions |
| PostgreSQL | postgres-pro | queries, EXPLAIN, replication, pgBouncer, JSONB |
| Redis/MongoDB/NoSQL | nosql-specialist | Redis, MongoDB, Cassandra, document stores |
| PowerShell/Windows | powershell-7-expert | PS scripts, Azure, M365, Graph API |
| LLM architecture | llm-architect | model selection, RAG, multi-agent design, inference |
| LLM prompts | prompt-engineer | system prompts, few-shot, output format, prompt optimization |
| API design/behavior | api-designer | REST/GraphQL endpoints, auth flows, unfamiliar APIs |
| Competitive analysis | competitive-analyst | SWOT, feature matrices, pricing, positioning |
| Security | api-security-audit | OWASP, auth vulnerabilities, webhook security |
| Frontend code quality | impeccable (advisory) | React/Vue/CSS quality, a11y, component/layout review, design-system polish |
| Product strategy / PM artifacts | pm-skills plugin skills (create-prd, ansoff-matrix, cohort-analysis, gtm-motions, competitive-battlecard, ...) | PRD, go-to-market, growth experiments, OKRs, product metrics, market segmentation. Ruled available by the owner 2026-08-07 ("make them available to be used by you"); the plugin stays installed and this row is its routing moment. Academic output stays with the existing ARS trigger-phrase block in CLAUDE.md. |

**If no domain matches → leave DOMAIN blank.** The process skill uses its core agent table.
**If domain matches → the process skill should route to the specialist** instead of (or alongside) the generic agent.

**Whole-surface availability (owner ruling 2026-08-07, verbatim: "i want all installed plugins skills agents and whatever else we have to be available to use"):** this table and the process-skill tables are DEFAULTS, not boundaries. Every installed plugin skill and agent in `registry.json` is a legitimate routing target when it fits the task better than the table entry; name the substitution in the classification block. All floors (process-qa, pm, Gate-1, blind analysis) apply to plugin components exactly as to local ones.

**Wiki-first trigger at classification (2026-07-15, F-7 Step 1).** If DOMAIN resolves to n8n workflows, vault hooks or doctrine, agent dispatch or governance, or a CMDB-class structural inventory (the four wiki-first scope categories in CLAUDE.md), append one line to the classification block: "WIKI-FIRST REQUIRED before answering: call mcp__qmd__query against agr-kb." Embedding the trigger at the point of classification is more reliable than depending on session-start recall. This is the Step 1 prompt reinforcement only; no hook is added for this in this build.

## Step 1.6: Reversibility Surface Check (Gate-1 pre-warning: two-gate autonomy model)

Map the planned action against the canonical **irreversible surface**: file/record delete, DB `DROP`/`TRUNCATE`/unbounded `DELETE`, `git push`, external `POST`/`PUT`/`PATCH`/`DELETE`, n8n `active:true` flip, prod deploy, outbound email/Slack send.

- **If the action hits the surface** → the announce block carries `REVERSIBILITY: irreversible-surface`, and you MUST pre-surface a **Gate-1 decision brief** (what, why, options + tradeoffs + recommendation) to the owner BEFORE issuing the destructive tool call: **regardless of TYPE, including Quick.** This is the advisory pre-warning; the HARD stop is the Gate-1 PreToolUse `deny` (`bash-safety-guard.py` / `mcp-irreversible-guard.py`) at execution time, and the human gate is re-running via the `!`-prefix manual bypass. See [[2026-06-15-two-gate-enforcement-spec]].
- **If the action is NOT on the surface** → `REVERSIBILITY: reversible`, and set `DETECTABILITY` by the rule below.

**Anti-collision clause:** The reversibility floor is intentionally NOT a classifier gate. It lives in the PreToolUse hook (Gate 1) precisely so the Step-3a Quick fast-path cannot bypass it. The `REVERSIBILITY` field is an advisory pre-warning, not a block.

### DETECTABILITY decision rule (Gate-2: applies only to reversible actions)

Set `DETECTABILITY` by applying ONE decision rule:
> **"Can I, the agent, write a tool call RIGHT NOW that would FAIL if this action were wrong: without dispatching another agent and without a human looking?"** YES → `self-detectable`. NO → `needs-detector`.

- **self-detectable**: correctness is observable through the agent's OWN subsequent tool calls before the result propagates beyond its control. The agent can falsify its own work.
- **needs-detector**: correctness depends on properties the agent cannot observe with its own tools (external side effects after a POST/PUT, "did the right thing happen downstream", or the semantic/judgment correctness of generated prose, a prompt, or a design). No self-issued tool call falsifies it; an INDEPENDENT detector that RE-DERIVES (not re-reads) is required to license the reversible surface autonomously.

Two independent classifier runs on the same task MUST yield the same `DETECTABILITY` value. Worked examples (label in bold):
1. Edit `helper.js`, re-run the test suite → **self-detectable** (the suite falsifies a wrong edit).
2. `git push` to remote → **needs-detector** AND irreversible → Gate-1 `deny` stops it before Gate-2 is reached.
3. Generate marketing copy or a system prompt → **needs-detector** (semantic correctness; no self-issued call falsifies it).
4. Patch an n8n node field, then `n8n_validate_workflow` → **self-detectable** (validation re-derives).
5. Write a wiki `source:` SHA; the wiki-citation hook re-hashes it on Write → **self-detectable** (the hook re-computes).
6. Research synthesis asserting live-web facts with no fetch-back → **needs-detector** (the independent quality gate catches it).

## Step 2: Challenge your approach (MANDATORY: not skippable)

After classifying TYPE and deciding your APPROACH, answer this question:

> **"What would I miss by handling it this way?"**

Write your answer as a `MISSED:` line in the classification block. If the answer reveals something significant: a blind spot, a wrong assumption, or a better alternative: reconsider your TYPE or APPROACH before proceeding.

## Step 3a: Explicit Imperative Fast Path (added 2026-05-05 per ECC-LEARN-FAST)

**Before applying the burden-of-proof Quick check in Step 3**, scan the prompt for an Explicit Imperative pattern. If matched, the burden of proof flips: classify Quick by default and only escalate if a depth signal is also present.

**Explicit Imperative patterns:**
- "rename X to Y" (file or symbol rename, no logic change)
- "move X to Y" (file move, no content edit)
- "fix typo in X" (single-character or single-word correction)
- "delete the unused X" (removal of named, scoped artifact)
- "add line/comment X to file Y" (single line append, no logic)
- "rerun X" / "re-execute X" (re-invoke a known prior operation)

When matched, the default flips to Quick. Auto-escalate ONLY if one of these is also true:
- The named target requires understanding before action (e.g., "rename X" where X is ambiguous and needs a search to identify): Quick lookup first, then act
- The imperative is composed with a depth signal ("rename X and analyze why we needed it"): Analysis
- The imperative is preceded by a hypothesis ("I think we should rename X because Y"): invites discussion, Analysis
- Step 0 detected an explicit depth signal ("are you sure?", "think deeper", "no, try again")

If none of those escalation conditions hit → classify Quick, skip Step 3's burden-of-proof gate (you've already cleared it via the fast path), and proceed to Step 5 announcement.

**Gate-1 caveat (two-gate model):** An explicit imperative that targets the irreversible surface (e.g. file delete, push, activate) stays Quick for ceremony but MUST pre-surface a Gate-1 decision brief before the destructive tool call: the PreToolUse hook will deny it otherwise.

**Rationale:** vault classifier empirically over-classified small fixes as Analysis. Governance log shows ~2% classifier-block rate over 14 days but the ceremony cost on small tasks is high (process-skill + QA + PM dispatch chain on a one-line edit). User migrated routine small-fix work to web Opus 4.7 because of this. Recalibration explicitly recognizes the Explicit Imperative class without weakening Step 3's burden of proof for everything else. See `feedback_framework_overhead_on_small_tasks.md`.

## Step 3: Quick Check (burden of proof is on Quick): FALL-THROUGH from Step 3a

**If Step 3a already matched an Explicit Imperative and did not escalate, you are Quick: skip this section.**

**Otherwise: the default is NOT Quick.** If you are unsure, classify as Analysis. Quick must be actively proven: ambiguity always resolves to depth, never to simplicity.

Downgrade to **Quick** ONLY if ALL of these are true:
- The type matrix produced 0 Yes answers AND Step 0 detected no depth signals
- The message is NOT a follow-up, correction, or directive about ongoing work (e.g., "think deeper", "are you sure?", "no, try again"). These inherit or escalate the prior classification: they are never Quick.
- The entire response is a single factual lookup, a file move, or a one-field edit
- You are not investigating, diagnosing, reasoning about causes, or tracing a chain of events
- You are not designing, evaluating, comparing, recommending, or producing any artifact
- The answer requires no reasoning chain longer than one step
- No specialist agent would produce a better answer
- A wrong answer has no consequences beyond a single field

If ANY criterion fails, Quick is not available. **Default to Analysis** and re-examine your Step 1 answers: you likely answered "No" too narrowly on a row that should be "Yes."

**Quick still requires the announcement block:**

```
IMPLIES: [one sentence from Step 0]
TASK TYPE: Quick
REVERSIBILITY: [reversible | irreversible-surface: from Step 1.6. MANDATORY even for Quick: a Quick file-delete/push/activate MUST surface irreversible-surface and pre-surface a Gate-1 decision brief before the destructive tool call.]
DETECTABILITY: [self-detectable | needs-detector: emit only when REVERSIBILITY: reversible; omit when irreversible-surface.]
JUSTIFICATION: [one sentence: why no specialist agent would improve this answer]
```

Then answer inline.

## Step 4: Ralph Loop check

This step is about whether the investigation needs isolation from this conversation's context.

Ralph Loop is appropriate if ANY of these are true:
- The task requires evaluating something this conversation has already formed opinions about
- Prior messages contain hypotheses that could anchor the investigation
- The task needs comparing multiple options where fairness requires fresh context
- Multiple open questions require exhausting source materials independently
- The investigation requires reading/processing enough material to significantly consume context
- The problem has enough interacting parts that you can't hold the full picture in a single reasoning chain

If yes → recommend `architect-loop`. If no → direct delegation is sufficient.

## Step 5: Announce

Before outputting the block, consider which quality mechanism might apply (this guides your reasoning but is NOT emitted in the output):

| Task characteristic | Consider |
|---------------------|----------|
| Math or logic with verifiable steps | /verify (CoVe) |
| Framing, design, architecture, option comparison | /ensemble |
| Subjective judgment or high-stakes evaluation | Both |

This is a reasoning step only: do NOT output a MECHANISM field.

Output exactly this block before proceeding. **ALL fields are MANDATORY. Do not skip any field. Missing fields (IMPLIES, MISSED, MUST DISPATCH) will be caught by the Stop hook and block your response.** `REVERSIBILITY` (and `DETECTABILITY` when reversible) are also mandatory to emit per Step 1.6: they are advisory pre-warnings captured for observability by `classifier-field-check.py`, NOT a hard Stop-hook block (the HARD stop is the Gate-1 PreToolUse `deny`).

```
IMPLIES: [one sentence from Step 0: what does this prompt imply?]
TASK TYPE: [Quick / Research / Analysis / Content / Build / Planning / Compound]
DOMAIN: [specialist domain from Step 1.5, or "general" if none]
REVERSIBILITY: [reversible | irreversible-surface: from Step 1.6. MANDATORY for ALL task types incl. Quick. If irreversible-surface, pre-surface a Gate-1 decision brief before the destructive tool call.]
DETECTABILITY: [self-detectable | needs-detector: from Step 1.6's decision rule. Emit ONLY when REVERSIBILITY: reversible; omit this line entirely when REVERSIBILITY: irreversible-surface.]
APPROACH: [Declare the primary path, then check EACH of the 5 primitive operations as a potential compound:
  Research compound? [yes/no: if yes, name the agent]
  Analysis compound? [yes/no: if yes, name the agent]
  Planning compound? [yes/no: if yes, name the agent]
  Build compound? [yes/no: if yes, name the agent]
  QA compound? [yes/no: if yes, name the agent/method. QA = does this task produce claims that need empirical verification?]
  Example: "Build via blueprint-mode. Research: yes (process-research routing to technical-researcher for API docs). Analysis: yes (architect-reviewer for post-build). Planning: no. QA: yes (test hook fires in fresh session)." Note: when a Research compound is yes, MUST DISPATCH lists `process-research`, not the downstream researcher named in parentheses: the parentheses are documentation of intent only, not a dispatch target.
  Note: Content is a domain specialization of Build, not a primitive. These 5 are the irreducible operations of knowledge work.]
MISSED: [one sentence from Step 2: what would I miss by handling it this way? Quick tasks: write "N/A"]
MUST DISPATCH: [see rules below. Quick tasks: omit this field.
  **PM SELF-CHECK:** this is non-Quick, so pm MUST be in this list. The Stop hook will block you if it's missing.]
```

**Every labeled slot is mandatory as a written line, even when its value is "none" or "N/A" (2026-07-15, F-1).** Do not drop a slot because the value feels obvious or empty. The slots are, in order: IMPLIES, TASK TYPE, DOMAIN, REVERSIBILITY, DETECTABILITY (reversible only), APPROACH, MISSED, MUST DISPATCH (non-Quick only). Writing the slot label proves you evaluated it; an omitted slot is caught by the classifier-field hook and blocks the response. When compressing output, compress the slot values, never the slot labels.

**APPROACH** declares the full compound mixture: not just the primary path but all secondary compounds the task contains. Each compound names its agents. The process skill for TYPE handles the primary path; the compound agents handle the secondary paths within it. If APPROACH only names one agent for a task that IMPLIES reveals has multiple dimensions, you've missed a compound.

**MUST DISPATCH** is the enforcement contract. The Stop hook reads this field and verifies every listed item was actually invoked (Skill or Agent tool). Missing dispatches block your response.

**MUST DISPATCH rules: IMPLIES + COMPOUNDS drive the dispatch level:**
- List the process skill for TYPE + all agents named in APPROACH compounds marked "yes"
- **Research entry-point rule (Fix 2, 2026-04-14):** If TYPE is Research OR APPROACH names a Research compound, MUST DISPATCH must list `process-research`: NEVER list a downstream researcher (technical-researcher, research-analyst, research-orchestrator) directly. The process-research skill owns routing to the right researcher based on coverage. Naming downstream researchers in MUST DISPATCH is a process violation: it bypasses the entry-point check and lets the main session dispatch researchers without process discipline. Downstream researcher names in APPROACH prose are documentation of routing intent only: they do NOT authorize direct dispatch from the main session. The actual researcher dispatch must happen INSIDE process-research, never from the main session reading the APPROACH text. Same rule applies to Content type: if a Content task needs research, MUST DISPATCH lists `process-research`, not `research-orchestrator` directly.
- **Trivial Research compound exception:** for a Research compound on a Build/Analysis primary that consists of a SINGLE one-shot factual lookup (one grep, one file read, one URL fetch with no synthesis), the main session may handle it inline without dispatching `process-research`: but ONLY when (a) the lookup is one tool call, (b) no comparison or synthesis across sources is needed, and (c) the result is a single fact that does not require interpretation. If any of these fail, route through process-research.
- If APPROACH says "Analysis: yes (architect-reviewer)" → architect-reviewer goes in MUST DISPATCH
- **QA is ALWAYS in MUST DISPATCH for non-Quick tasks**: add `process-qa` to every non-Quick MUST DISPATCH list. This is non-negotiable.
- **PM checkpoint (`pm`) is in MUST DISPATCH for every non-Quick task**: no compound counting. PM always runs. Also fires on reactive triggers (scope change, blocker, new workstream, phase transition) which escalate Quick to Analysis.
- All compound agents are enforced: the Stop hook verifies each was actually invoked
- If IMPLIES reveals the work can be done inline with no compounds → `none`: BUT QA still applies. MUST DISPATCH is at minimum `process-qa` for non-Quick.
- Format: only comma-separated names or `none`. No parenthetical explanations after `none`. `none` is ONLY valid for Quick tasks.

**HARD STOP.** If MUST DISPATCH lists a process skill, your ONLY allowed next action is invoking it via the Skill tool. If MUST DISPATCH is `none`, proceed inline: but you must still follow APPROACH.

**Dispatch-now acknowledgment, non-Quick (2026-07-15, F-2).** After emitting the classifier block for any non-Quick task, immediately output one line: "Dispatching: [agent1], [agent2], ..." naming every agent and skill from MUST DISPATCH, and then make those tool calls. Do not write any other prose between the dispatch declaration and the tool calls. This collapses the gap between declaring an agent and invoking it: the declaration becomes the first move of the dispatch sequence, not a separate compliance checkbox.

| TYPE | Invoke this skill |
|------|------------------|
| Research | `process-research` |
| Analysis | `process-analysis` |
| Content | `process-research` (if research needed) → then dispatch `content-marketer` directly as terminal writer. Do NOT route through process-build: content-marketer is a terminal writer, not a "builder" in the blueprint-mode sense. Source material comes from research, then content-marketer writes. |
| Build | `process-build` |
| Planning | `process-planning` |
| Compound | `process-analysis` (Decomposition mode) |
| Quick | No skill: respond inline |

**Pass the full classification block (TYPE, DOMAIN, APPROACH) as the skill's args parameter** so the process skill knows the routing decision. If DOMAIN is set, tell the process skill to route to the specialist agent.

### Classification traps (common mistakes)

| User request | WRONG classification | RIGHT classification | Why |
|---|---|---|---|
| "Design a scoring system for award entries" | Planning | Research → Planning | You don't know the scoring criteria yet: research first |
| "What's the best way to handle X?" | Quick | Research | "Best way" requires comparing options, not a single fact |
| "Review this workflow and fix the error" | Build | Analysis → Build | Evaluate before fixing: the error may not be what it looks like |
| "Update the prompt to handle edge case Y" | Quick | Analysis → Build | Need to understand current behavior before changing |
| "Move the old spec to archives" | Analysis | Quick | Single file move, no judgment needed |
| "Rename auth-handler.js to AuthHandler.js" | Analysis | Quick (Step 3a) | Single explicit rename: no logic change, no scope analysis needed |
| "Fix typo in line 14 of CLAUDE.md" | Analysis | Quick (Step 3a) | Single-word correction at a known location |
| "Delete the unused helper.js file" | Analysis | Quick (Step 3a) | Removal of named, scoped artifact, no investigation |
| "Research best practices and redesign auth" | Research → Planning → Build | Compound: Research + Planning | User said "research and redesign" not "implement": don't add Build |
| "Why did X fail?" | Quick | Analysis | Requires tracing causes, not a single fact: investigation |
| "Thought experiment: what if X leaks into Y?" | Quick | Analysis | Architectural reasoning about system behavior |
| "Was it always like this?" | Quick | Analysis (→ Research if needed) | Requires evidence gathering and timeline reconstruction |
| "I've noticed X behaves differently" | Quick | Analysis | Pattern observation invites investigation, not acknowledgment |
| "Analyze this thoroughly before deciding" | Quick | Analysis | The word "analyze" is literally there: never Quick |
| "Think about this more carefully" | Quick | Analysis | Explicit request for deeper reasoning |

## Step 6: Execution Rules (non-Quick only)

**Every non-Quick task is a mini-project.** Apply lifecycle treatment:

1. **If the task has 2+ steps or compounds:** MUST create a task list (TaskCreate) before executing. The task list defines the increment. Each task gets its own classification, process skill, and QA.

1a. **Every TaskCreate description carries a one-line `CHECK:` clause** (ratified 2026-08-01, [[2026-08-01-iteration-decomposition-proposal]]): the executable check that decides the step is done, <=120 chars measured on the clause text after the `CHECK: ` prefix. Declare it at line start or after sentence punctuation (`RECHECK:` and mid-sentence "double CHECK:" are not declarations), on one line; multiple clauses in one step are allowed and the strongest one counts. Match check type to step type: Build step -> the failing test/assertion written first; stateful-system step -> the live tool call that validates it (e.g. `n8n_validate_workflow`); authored-artifact step -> the independent re-derivation that would catch an error. Where no real check exists, write `CHECK: none-exists (<why>)` honestly - a clause that restates the step goal without naming an executable action is check theater (WEAK_CHECK). A step whose check ran and FAILED is not complete, exactly as if no check had run.

2. **Execute tasks sequentially** (WIP limit: 1). Mark each TaskUpdate: completed as you finish it.

3. **When all tasks are completed:** invoke `process-pentest` before reporting back to the user. Pentesting tries to break what was built across the whole increment: not individual tasks (that's QA). You have Bash, Read, MCP: use them to actually test.

4. **If pentesting finds HIGH severity issues:** fix them, re-test, then report. After 2 failed fix attempts on the same finding, escalate to the user.

5. **After pentest completes:** invoke `/pm` to run a PM checkpoint. This reviews project state, recommends next action, and catches phase transitions. PM is in MUST DISPATCH for every non-Quick task.

6. **Single-step non-Quick tasks** (one compound, no decomposition needed): skip TaskCreate. QA and PM still fire. Pentesting is not required for single tasks: QA covers it.

## Notes

- This classification routes to the **delegation rules in CLAUDE.md**: use those to pick the specific agent within each type.
- When in doubt between two types, **pick the one that requires MORE investigation, not less.** The cost of over-investigating is low (extra time). The cost of under-investigating is high (wrong output, rework, missed complexity). Default to depth.
- **Compound tasks**: invoke `process-analysis` in Decomposition mode. It will break the request into sub-tasks, classify each (TYPE + DOMAIN), identify dependencies, and invoke each sub-task's process skill in order. Do NOT decompose inline: delegate to the process.
