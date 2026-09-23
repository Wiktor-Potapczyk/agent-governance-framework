---
name: process-build
description: Build process template. Follow this procedure for all Build-type tasks after task-classifier routes here. Covers implementation planning, coding, and review.
---

# Build Process Template

## ⚡ Workflow-enforced (ADOPTED 2026-06-11)

This skill's procedure is enforced by construction: on invocation for a non-Quick task, execute it by calling the **Workflow tool** with `{scriptPath: "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\workflows\\process-build.js"}`, passing the task brief as `args: {project, spec, constraints?, llm_prompts?, n8n_domain?}`. The script drives the dispatch sequence (scope → implementation-plan → blueprint-mode → mandatory parallel review: architect-reviewer + adversarial-reviewer [+ prompt-engineer if llm_prompts] → capped revise → quality gate); agents reason freely inside each step.

The prose below remains (a) the procedure spec of record and (b) the FALLBACK path — use it only when the Workflow tool is unavailable (sub-agent context, degraded session) and say so explicitly. `DISPATCHES.json` is untouched and remains the read-only H11 verification source.

You have been routed here by the task-classifier. The task type is Build.

## Use-when

- Task-classifier returned `TASK TYPE: Build`
- Implementing code, scripts, hooks, or n8n workflow JSON
- Modifying executable artifacts (settings.json, registry, agent definitions) where edits change runtime behavior

## Do-NOT-use-when

- Design or spec authoring without implementation — use `process-planning`
- Markdown documentation or audience-facing prose — use `content-marketer` (terminal writer)
- Investigating a bug before knowing what to fix — use `process-analysis` Investigation mode first
- Per-task verification of completed work — use `process-qa`

## Gotchas

- **`implementation-plan` agent fabricates Read tool output** — invents file inventories with ghost files and invented contents (per `reference_implementation_plan_fabricates_read_output.md`). Verify any inventory the agent produces against main-session Glob before downstream dispatch.
- **`architect-reviewer` is mandatory post-build** — skipping the review step is a process violation caught by the Stop hook.
- **Never apply n8n workflow changes without explicit user instruction** — for n8n domain, route to `n8n-workflow-architect` (design) → human gate → `n8n-workflow-builder` (implementation).
- **Live verification overrides plan claims** — if the build describes a deployed system, fetch the live state and reconcile; the plan is not authoritative for what actually exists.

## Step 1 — Define Scope

Before any work, write this block:

```
BUILD SCOPE
Goal: [what is being built — one sentence]
Inputs: [specs, designs, or requirements this builds from]
Tech: [language, platform, framework — e.g., n8n workflow JSON, JavaScript, Python]
Output path: Projects/[Name]/work/YYYY-MM-DD-[artifact-name].[ext]
```

If scope is unclear or no spec/requirements exist, stop and route to Planning first.

## Step 2 — Plan

Delegate to the **implementation-plan** agent.

Include in the prompt:
- The scope block from Step 1
- All relevant specs, requirements, or designs (paste content or provide file paths)
- Instruction: produce a sequenced implementation plan with clear steps, dependencies, and acceptance criteria

Review the plan before proceeding. If the plan reveals missing requirements, route back to Research or Planning.

## Step 3 — Build

Delegate to the **blueprint-mode** agent.

Include in the prompt:
- The implementation plan from Step 2
- All source files, specs, and context needed to build
- Instruction: implement according to the plan, produce working code/config, save to the output path

For n8n workflows:
- Always fetch the current workflow first (`n8n_get_workflow`)
- Never apply changes directly — produce the spec/JSON for the user to apply
- Include node IDs and connection maps in the output

For code:
- Follow existing patterns in the codebase
- Include error handling at system boundaries only

For MCP servers/clients (MCP domain, GAP-5 binding 2026-07-10):
- **You MUST dispatch `mcp-server-architect`** for design review of the server/client architecture (protocol surface, tool/resource contracts) before or alongside the build.
- **You MUST dispatch `mcp-developer`** for the implementation itself (instead of blueprint-mode as the primary builder).
- These were advisory routing until 2026-07-10; they are now a mandatory-dispatch row per architecture-v2 Delta-1 close-out.

## Step 4 — Review (MANDATORY)

**You MUST dispatch architect-reviewer.** Skipping review is a process violation caught by the Stop hook.

Delegate to the **architect-reviewer** agent.

Include in the prompt:
- The implementation plan (what was intended)
- The built artifact (what was produced)
- Instruction: review for correctness, adherence to plan, SOLID principles, and any obvious defects

If the artifact includes LLM prompts, **you MUST also dispatch prompt-engineer** in parallel for prompt-specific review.

## Step 5 — Quality Check

Before marking build complete:

- [ ] Implementation matches the plan's acceptance criteria
- [ ] Review passed or issues resolved
- [ ] Output saved to the correct path in Projects/[Name]/work/
- [ ] No unsolicited changes beyond what was scoped
- [ ] **Live verification:** If the build produced artifacts that describe or depend on a live system (n8n workflow, deployed service, API), fetch the current live state and confirm the artifact matches reality. If the user deployed some components but not others, update the work file to reflect what actually exists — not what was planned.

If any check fails: for runtime errors or unexpected behavior, delegate to **debugger** to diagnose first. For implementation issues, fix via the build agent (Step 3), then re-run review (Step 4).

## Notes

- Never build without a plan. If Step 2 reveals the task is underspecified, stop and say so.
- Never apply n8n workflow changes without explicit user instruction.
- The value of this process is separation: planning, building, and reviewing are done by different agents with different objectives.
