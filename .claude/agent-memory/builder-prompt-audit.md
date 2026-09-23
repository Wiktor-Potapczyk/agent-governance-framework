---
date: 2026-03-16
type: audit
agent: prompt-engineer
target: .claude/agents/builder.md
---

# Builder Agent Prompt Audit — 2026-03-16

## Context

Two recent failures on n8n workflow tasks:
1. Designed a forked architecture (one node output to two downstream nodes) — impossible in n8n
2. Added a separate Code node to build an LLM prompt string instead of using Basic LLM Chain's built-in expression-capable User Message field

## Goal Verdicts (before revision)

| Goal | Verdict | Evidence |
|------|---------|----------|
| G1 — Execution model internalized | PARTIAL | Rule existed but lacked precision. "No forking" was stated but the concrete failure mode (connecting one output to two downstream nodes) was not spelled out. The agent could still interpret "paths" loosely. |
| G2 — Loop patterns correct | PARTIAL | SplitInBatches rules were present but: (a) loop-back wiring said "back to INPUT (not output)" which is ambiguous, (b) no guidance on accumulating results across iterations (staticData pattern), (c) no mention that `$input.all()` inside a loop body only contains the current batch. |
| G3 — LLM node knowledge accurate | PASS | Lines 38-40 directly addressed the failure. Clear "do NOT add a separate Code node" instruction. |
| G4 — Code node patterns correct | PARTIAL | Three rules were present but: (a) no explanation of WHY `$('NodeName')` fails after loops (only returns last execution), (b) missing warning about n8n expression syntax inside Code nodes, (c) no guidance on when a Code node before an LLM node IS valid (preparing complex prompt logic). |
| G5 — Instructions actionable | PARTIAL | Most rules were "do/don't" which is good. But execution model rules were too abstract — needed concrete examples of the anti-pattern (visual: "node with arrows to two downstream nodes"). Loop-back wiring instruction was ambiguous. |
| G6 — Scope well-defined | PASS | Frontmatter description has clear scope and NOT-FOR list. Operating instruction 1 directs to read plans first. |

## Changes Made

### Execution Model (G1 fix)
- Replaced 2 vague bullet points with 3 numbered rules
- Rule 1: explicitly says "you cannot connect one node's output to two different downstream nodes and have both execute"
- Rule 3: added a visual anti-pattern check: "If your design shows a node with arrows to two different downstream nodes (not via IF/Switch), the design is wrong"

### Loop Patterns (G2 fix)
- Expanded from 4 bullets to 5 numbered rules (4-8)
- Rule 5: added concrete code example for array expansion
- Rule 7: clarified loop-back goes "to the same input where the initial items enter"
- Rule 8: NEW — added staticData accumulation pattern with init/push/read lifecycle

### LLM Nodes (G3 enhancement)
- Expanded from 2 bullets to 3 numbered rules (9-11)
- Rule 10: NEW — defines the ONE valid exception (prompt requires logic beyond expressions), with correct pattern: Code node outputs `preparedPrompt` field, User Message uses `{{ $json.preparedPrompt }}`
- Rule 11: NEW — documents output field locations (`$json.text` for Basic LLM Chain, `$json.output` for AI Agent)

### Code Nodes (G4 fix)
- Expanded from 3 bullets to 4 numbered rules (12-15)
- Rule 14: explains WHY `$('NodeName')` fails after loops (returns data from LAST execution only)
- Rule 15: NEW — explicitly bans `{{ }}` syntax inside Code node JavaScript

### Node Naming (enhanced)
- Rule 17: NEW — requires unique node names within a workflow

### Design Verification Checklist (NEW)
- Added a 4-item checklist at the end that the agent must run through before finalizing any workflow design
- Each item maps to a specific past failure or high-risk pattern

### Operating Instructions
- Added instruction 8: "Before designing any n8n workflow, read the n8n Workflow Rules section below in full"

## Metrics

- Token count before: ~490 tokens (rules section only)
- Token count after: ~980 tokens (rules section only)
- Total prompt tokens: ~1,350 (full file)
- Rules went from 11 unstructured bullets to 17 numbered rules + 4-item checklist
- All rules are now numbered for unambiguous reference

## Known Limitation

The n8n-workflow-patterns skill file (SKILL.md) still shows a "Parallel Processing" pattern diagram with fork-like notation. This could confuse the builder if it reads that skill. Consider updating that skill to clarify that "parallel processing" in n8n requires a specific Merge node pattern, not a simple fork.
