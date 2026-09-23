# Plan: Agent Refactor — All 13 Agents

## Goal
Refactor all 13 Claude agents so each has a razor-sharp scope, clean routing logic, correct model assignment, and lean prompt bodies — eliminating overlap and bloat.

## Scope
Large — 13 files, 5-stage pipeline with review/reject loops, plus CLAUDE.md rewrite.

## Pipeline Steps

- [x] Step 1 — planner creates AGENT_REFACTOR_PLAN.md
- [x] Step 2 — workflow-orchestrator designs routing topology (builder/api-expert/data-engineer + researcher/competitive-analyst + llm-architect/prompt-engineer boundaries)
- [x] Step 3 — llm-architect assigns model per agent with rationale
- [x] Step 4 — prompt-engineer rewrites all 13 files (trigger-based description, NOT-for exclusion, numbered steps ≤8, least-privilege tools, body ≤60 lines)
  - [x] 4.01 vault-keeper
  - [x] 4.02 researcher
  - [x] 4.03 builder
  - [x] 4.04 api-expert
  - [x] 4.05 data-engineer
  - [x] 4.06 planner
  - [x] 4.07 debugger
  - [x] 4.08 content-marketer
  - [x] 4.09 competitive-analyst
  - [x] 4.10 workflow-orchestrator
  - [x] 4.11 prompt-engineer
  - [x] 4.12 llm-architect
  - [x] 4.13 reviewer
- [x] Step 5 — reviewer validates all 13 files
  - [x] 5.01 vault-keeper — PASS
  - [x] 5.02 researcher — PASS
  - [x] 5.03 builder — PASS
  - [x] 5.04 api-expert — PASS
  - [x] 5.05 data-engineer — PASS
  - [x] 5.06 planner — PASS
  - [x] 5.07 debugger — REJECT → fixed → PASS
  - [x] 5.08 content-marketer — PASS
  - [x] 5.09 competitive-analyst — PASS
  - [x] 5.10 workflow-orchestrator — PASS
  - [x] 5.11 prompt-engineer — PASS
  - [x] 5.12 llm-architect — PASS
  - [x] 5.13 reviewer — REJECT → fixed → PASS
- [x] Step 6 — vault-keeper writes all 13 approved files to .claude/agents/ and rewrites CLAUDE.md to under 200 lines

## Model Assignments Applied

| Agent | Model |
|-------|-------|
| vault-keeper | haiku |
| researcher | sonnet |
| builder | inherit |
| api-expert | sonnet |
| data-engineer | sonnet |
| planner | inherit |
| debugger | sonnet |
| content-marketer | sonnet |
| competitive-analyst | sonnet |
| workflow-orchestrator | sonnet |
| prompt-engineer | opus |
| llm-architect | opus |
| reviewer | sonnet (downgraded from opus) |

## Results

- All 13 agent files written to .claude/agents/
- Every description starts with "Use proactively when..."
- Every agent has explicit "NOT for" exclusion
- CLAUDE.md rewritten to 102 lines (under 200)
- AGENT_REFACTOR_PLAN.md all items checked
