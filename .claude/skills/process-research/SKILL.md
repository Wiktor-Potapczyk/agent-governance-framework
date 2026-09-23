---
name: process-research
description: Research process template. Follow this procedure for all Research-type tasks after task-classifier routes here. Covers direct delegation and Ralph Loop paths.
---

# Research Process Template

## ⚡ Workflow-enforced (ADOPTED 2026-06-11)

This skill's procedure is enforced by construction: on invocation for a non-Quick task, execute it by calling the **Workflow tool** with `{scriptPath: "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\workflows\\process-research.js"}`, passing the task brief as `args: {project, question, sources?, constraints?}`. The script drives the dispatch sequence (scope → path classification → research agents [research-analyst / technical-researcher / research-orchestrator per coverage flag] → synthesis [research-synthesizer, mandatory if 2+ gatherers, enforced in code] → report-generator [mandatory] → quality gate); agents reason freely inside each step.

**Ralph Loop path (3A):** when the scope agent sets `ralph_loop_indicated: true`, the workflow HALTs with `status: 'ralph-loop-hand-back'` and returns the scope block. The main session must then invoke the `architect-loop` skill via the prose path (Step 3A below), then re-invoke this workflow with the loop findings as `args.question`. A workflow cannot invoke a skill; the HALT is the designed hand-back mechanism.

The prose below remains (a) the procedure spec of record and (b) the FALLBACK path — use it only when the Workflow tool is unavailable (sub-agent context, degraded session) and say so explicitly. `DISPATCHES.json` is untouched and remains the read-only H11 verification source.

You have been routed here by the task-classifier. The task type is Research.

## Use-when

- Task-classifier returned `TASK TYPE: Research` or named a Research compound
- Open question requiring source materials (web, repo, docs) to answer
- Multi-source synthesis across reports, papers, or repos
- Investigation that needs context-isolation from current conversation (Ralph Loop path)

## Do-NOT-use-when

- Single factual lookup answerable in one tool call — handle as Quick inline (trivial-research-compound exception)
- Investigating a known cause already in scope — use `process-analysis` Investigation mode
- Producing audience-facing copy — use `content-marketer` (it writes; this skill researches)
- Designing architecture without source-material gathering — use `process-planning`

## Gotchas

- **Never dispatch downstream researchers directly** — `technical-researcher`, `research-analyst`, `research-orchestrator` are routed BY this skill, not from the main session. Direct dispatch from main session bypasses the entry-point check and is a process violation.
- **Trivial-research-compound exception** — for a Build/Analysis primary with a Research compound that is ONE tool call, no comparison, single fact: main session may handle inline without dispatching here. Any synthesis or multi-source comparison fails the exception and routes through this skill.
- **Ralph Loop needs context-isolation** — don't pass conversation history or anchored hypotheses into a loop prompt; the loop's value is fresh investigation. Hypotheses leak in and the loop validates instead of investigating.

## Step 1 — Define Scope

Before any work, write this block:

```
RESEARCH SCOPE
Questions: [numbered list — be specific, one question per line]
Sources available: [known files, URLs, or "web search"]
Deliverable: [format the output should take]
Output path: Projects/[Name]/work/YYYY-MM-DD-[topic]-research.md
```

If scope is unclear, ask the user to clarify before proceeding.

## Step 2 — Choose Path

**Ralph Loop path** — use if ALL of these are true:
- 3 or more distinct open questions
- Requires reading 3+ source files OR searching multiple web sources
- Benefits from fresh, unanchored investigation (no bias from conversation context)

→ Go to Step 3A

**Direct delegation path** — use if ANY of these is true:
- 1–2 clear questions with known sources
- Quick synthesis of readily available material
- Single-pass coverage is sufficient

→ Go to Step 3B

## Step 3A — Ralph Loop Path

1. Invoke the `architect-loop` skill. Pass the scope block from Step 1 as context.
2. The architect-loop skill structures the loop prompt and produces a command to run.
3. Present the loop prompt file and command to the user for review before running.
4. After the loop completes, read the findings file it produced.
5. Continue to Step 4.

## Step 3B — Direct Delegation Path

Assign agents based on what the research covers:

| Coverage | Agent |
|---|---|
| Web sources, trends, market data, multi-source synthesis | research-analyst |
| Code repos, technical docs, API behavior, implementation | technical-researcher |
| Both of the above | Both — run in parallel |
| Complex multi-phase research with 4+ sub-questions | research-orchestrator (coordinates the above) |

Delegation rules:
- State observable facts only in each agent prompt — never a hypothesis or proposed answer
- Each agent prompt must be fully self-contained — include all context, assume no conversation history
- Run parallel agents simultaneously

Collect all findings before continuing to Step 4.

## Step 4 — Synthesis (MANDATORY if 2+ agents dispatched)

**You MUST dispatch research-synthesizer if Step 3 dispatched 2 or more agents.** Skipping synthesis when multiple agents contributed is a process violation caught by the Stop hook.

Pass all findings to the **research-synthesizer** agent.

Include in the prompt:
- The scope block (questions + deliverable format)
- All raw findings from each agent or the loop output file
- Instruction: merge findings into a coherent synthesis, resolve contradictions, note anything unconfirmed

## Step 5 — Report

Pass the synthesis to the **report-generator** agent.

Include in the prompt:
- The synthesized findings
- Deliverable format from the scope block
- Output path from the scope block

The report-generator writes the final output to disk.

## Step 6 — Quality Check

Before marking research complete:

- [ ] All scope questions answered or explicitly noted as unanswerable
- [ ] No major contradictions left unresolved
- [ ] Sources cited for key claims
- [ ] Output saved to the correct path in Projects/[Name]/work/

If any check fails: identify which questions are missing, run targeted follow-up agents (Step 3B), then re-run Steps 4–5.

## Notes

- Ralph Loop (3A) is slower but better for complex tasks where conversation context would anchor the result. Default to it when bias risk is real.
- Direct path (3B) is sufficient for most research. Default to it unless 3A criteria are clearly met.
- Never produce research inline. The value is agent isolation — each agent gets a clean context with no anchoring from the current session.
