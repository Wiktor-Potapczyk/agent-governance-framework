---
name: process-analysis
description: Analysis process template. Follow this procedure for all Analysis-type tasks after task-classifier routes here. Covers evaluation, investigation, diagnosis, and reasoning about causes or behavior.
---

# Analysis Process Template

You have been routed here by the task-classifier. The task type is Analysis.

Analysis covers three modes:

**Evaluation mode** — assessing an artifact against a rubric or quality standard
**Investigation mode** — diagnosing causes, tracing behavior, reasoning about why something works (or doesn't)
**Decomposition mode** — breaking a Compound task into sub-tasks with classifications and dependencies

## Step 1 — Define Scope

Before any work, write this block:

```
ANALYSIS SCOPE
Mode: [Evaluation | Investigation | Decomposition]
Subject: [what is being evaluated, investigated, or decomposed]
Question: [Evaluation: the rubric. Investigation: the core question. Decomposition: the compound request to break apart]
Deliverable: [Evaluation/Investigation: assessment or reasoning chain. Decomposition: numbered sub-task list with TYPE + DOMAIN + dependencies]
Output path: Projects/[Name]/work/YYYY-MM-DD-[subject]-analysis.md (only if output is substantial enough to save)
```

For **Evaluation mode**: if no rubric exists, define one before proceeding.
For **Investigation mode**: state the question clearly. If the answer is a single fact, this should have been Quick — investigation means multi-step reasoning.
For **Decomposition mode**: break the compound request into numbered sub-tasks. For each: state TYPE + DOMAIN, identify dependencies (parallel vs sequential), then invoke each sub-task's process skill in order, passing output from one as input to the next. Cap at 1 level — if a sub-task looks Compound, flatten it.

## Step 2 — Assign Specialist

Delegate to the appropriate specialist based on what is being evaluated:

| Subject | Agent |
|---|---|
| LLM prompts, system messages, output quality | prompt-engineer |
| Code architecture, SOLID, coupling, layering | architect-review |
| Runtime errors, failures, unexpected behavior | debugger |
| API design, endpoint quality, auth patterns | api-designer |
| Data schema, field mapping, pipeline quality | data-engineer |
<!-- Domain-specific: customize for your stack -->
| Workflow logic, branching, error recovery | workflow-orchestrator |
| Security (API, webhooks, auth) | api-security-audit |
| Multiple of the above | Run applicable agents in parallel |

Delegation rules:
- Include the full rubric in each agent prompt — do not assume the agent knows the standard
- Include the artifact to evaluate (paste content or provide file paths)
- State observable facts only — never pre-judge the result
- Each agent prompt must be fully self-contained

## Step 3 — Synthesize (MANDATORY if multiple agents)

If only one agent was used, skip to Step 4.

**You MUST dispatch research-synthesizer if Step 2 dispatched 2 or more agents.** Skipping synthesis when multiple agents contributed is a process violation caught by the Stop hook.

Pass all findings to the **research-synthesizer** agent:
- Include all evaluation results
- Instruction: merge findings, resolve any contradictions between specialist assessments, produce a unified evaluation

## Step 4 — Report

Write or delegate the final assessment:
- For simple single-agent evaluations: the agent's output may be sufficient as-is
- For complex multi-agent evaluations: pass to **report-generator** with the synthesis and deliverable format

Save output to the path from the scope block.

## Step 5 — Quality Check

Before marking analysis complete:

For Evaluation mode:
- [ ] Every rubric criterion addressed with a clear assessment
- [ ] No criteria skipped or glossed over

For Investigation mode:
- [ ] Core question answered with a clear conclusion (or explicitly noted as unresolvable)
- [ ] Alternative explanations considered and ruled out with evidence
- [ ] Reasoning chain is traceable from observations to conclusion

For both modes:
- [ ] Evidence cited for each finding (line numbers, specific examples)
- [ ] Output saved to the correct path in Projects/[Name]/work/

If any check fails: identify which criteria are missing, run targeted follow-up with the relevant specialist (Step 2), then re-run synthesis if needed.

## Notes

- Analysis is evaluation, not building. If the analysis reveals something that needs fixing, report it — do not fix it inline.
- The rubric is non-negotiable. If the user provides a rubric, evaluate against it exactly. Do not substitute your own criteria.
- When evaluating LLM outputs: compare against the system prompt's stated behavior, not against what you think the output "should" say.
