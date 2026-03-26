---
name: process-planning
description: Planning process template. Follow this procedure for all Planning-type tasks after task-classifier routes here. Covers architecture design, spec writing, and work sequencing.
---

# Planning Process Template

You have been routed here by the task-classifier. The task type is Planning.

## Step 1 — Define Scope

**Before writing the scope block, check for project context.** If `Projects/[Name]/STATE.md` or `Projects/[Name]/PROJECT.md` exist, read them using the Read tool:
- Import **appetite** (Small/Medium/Large) from PROJECT.md into Constraints — the plan must fit within it
- Import **current phase** and **active tasks** from STATE.md into Inputs — the plan must build on current state, not contradict it
- If neither file exists, proceed without them — project context is optional, not blocking

Then write this block:

```
PLANNING SCOPE
Goal: [what is being designed or planned — one sentence]
Constraints: [tech stack, timeline, dependencies, team size, budget, appetite from PROJECT.md if available]
Inputs: [existing specs, prior research, requirements docs, STATE.md current phase if available]
Deliverable: [architecture doc, implementation plan, sequence diagram, spec]
Output path: Projects/[Name]/work/YYYY-MM-DD-[plan-name].md
```

If the goal is unclear or requirements are missing, route to Research first.
If the plan scope exceeds the declared appetite, flag this explicitly before proceeding — do not silently produce an oversized plan.

## Step 2 — Research (if needed)

Planning often requires understanding before designing. If ANY of these are true, run research first:
- The domain is unfamiliar (unfamiliar API, new framework, unknown constraints)
- Multiple approaches exist and the right one isn't obvious
- Dependencies or integrations need investigation

Delegate per the research process:
- **technical-researcher** for implementation options, API capabilities, framework comparisons
- **research-analyst** for market context, competitor approaches, best practices
- **api-designer** for understanding unfamiliar API behavior before designing around it

If research is not needed (requirements are clear, domain is familiar), skip to Step 3.

## Step 3 — Design

Delegate to the **implementation-plan** agent.

Include in the prompt:
- The scope block from Step 1
- All research findings from Step 2 (if any)
- All existing specs, requirements, or prior plans
- Instruction: produce a detailed plan with sequenced steps, dependencies, acceptance criteria, and risk flags

For architecture-level planning, also consider delegating to **llm-architect** (for LLM system design) or **data-engineer** (for data pipeline architecture) in parallel with implementation-plan.

## Step 4 — Review (MANDATORY)

**You MUST dispatch architect-review.** Skipping review is a process violation caught by the Stop hook.

Delegate to the **architect-review** agent.

Include in the prompt:
- The plan from Step 3
- The original goal and constraints from the scope block
- Instruction: review for feasibility, completeness, SOLID principles, over-engineering, and missing edge cases

If the plan involves LLM prompts or agent design, also delegate to **prompt-engineer** in parallel.

For high-stakes plans (multi-phase, cross-system, or irreversible decisions), **you MUST also dispatch adversarial-reviewer** to challenge assumptions before committing.

## Step 5 — Revise (if needed)

If review identified issues, send the plan + review feedback back to **implementation-plan** for revision.

Repeat Steps 4–5 until the review passes or the user decides to proceed.

## Step 6 — Quality Check

Before marking planning complete:

- [ ] Plan addresses the stated goal completely
- [ ] All constraints respected
- [ ] Steps are sequenced with clear dependencies
- [ ] Acceptance criteria defined for each step
- [ ] Risks and unknowns explicitly noted
- [ ] Output saved to the correct path in Projects/[Name]/work/

If any check fails: identify the gap, revise (Step 5), and re-check.

## Notes

- Planning is designing, not building. If you find yourself writing implementation code, stop — that's a Build task.
- A plan without acceptance criteria is not a plan. Every step must have a way to verify it's done.
- Prefer smaller increments over monolithic plans. If the plan has more than 7 steps, consider breaking it into phases.
- The plan is a living document — it will be revised as implementation reveals new information. Don't over-specify.
- **STATE.md is owned by pm-orchestrator.** Do not write to STATE.md from this skill. Save output to `work/` only. The `/pm` checkpoint (which fires for 2+ compound tasks) handles STATE.md updates.
