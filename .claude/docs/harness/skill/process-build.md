---
component: "process-build"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: process-build

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/process-build`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-003` (.claude/workflows/process-build.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose ensemble [unresolved: prose mention only]
  - inbound mentioned_in_prose process-analysis [unresolved: prose mention only]
  - inbound invokes process-build
  - inbound mentioned_in_prose process-planning [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - outbound dispatches adversarial-reviewer
  - outbound dispatches api-designer
  - outbound dispatches architect-reviewer
  - outbound mentions_in_prose blueprint [unresolved: prose mention only]
  - outbound dispatches blueprint-mode
  - outbound mentions_in_prose content-marketer [unresolved: prose mention only]
  - outbound dispatches data-engineer
  - outbound mentions_in_prose debugger [unresolved: prose mention only]
  - outbound dispatches implementation-plan
  - outbound dispatches llm-architect
  - outbound dispatches mcp-developer
  - outbound dispatches mcp-server-architect
  - outbound mentions_in_prose n8n-workflow-architect [unresolved: prose mention only]
  - outbound dispatches n8n-workflow-builder
  - outbound dispatches nosql-specialist
  - outbound dispatches postgres-pro
  - outbound dispatches powershell-7-expert
  - outbound mentions_in_prose process-analysis [unresolved: prose mention only]
  - outbound mentions_in_prose process-planning [unresolved: prose mention only]
  - outbound mentions_in_prose process-qa [unresolved: prose mention only]
  - outbound dispatches prompt-engineer
  - outbound mentions_in_prose save [unresolved: prose mention only]
  - outbound mentions_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Build process template. Follow this procedure for all Build-type tasks after task-classifier routes here. Covers implementation planning, coding, and review. Use-when: Task-classifier returned `TASK TYPE: Build`

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Entered when task-classifier returns TASK TYPE: Build (.claude/skills/process-build/SKILL.md:18). Non-Quick execution is workflow-enforced: call the Workflow tool with scriptPath .claude/workflows/process-build.js; the prose is the spec of record and the fallback path, used only when the Workflow tool is unavailable, and saying so explicitly (.claude/skills/process-build/SKILL.md:10, :12).

The dispatch chain runs through the Agent tool: implementation-plan for the sequenced plan (.claude/skills/process-build/SKILL.md:52), blueprint-mode to build (.claude/skills/process-build/SKILL.md:63), and for the MCP domain, mandatory mcp-server-architect design review plus mcp-developer as the primary builder (.claude/skills/process-build/SKILL.md:80). One gotcha is load-bearing: implementation-plan fabricates Read output, so its file inventories are verified against main-session Glob before downstream dispatch (.claude/skills/process-build/SKILL.md:31).

Required output: the BUILD SCOPE block first (.claude/skills/process-build/SKILL.md:41), the built artifact at the scoped path, then mandatory review: architect-reviewer always, prompt-engineer in parallel when the artifact includes LLM prompts (.claude/skills/process-build/SKILL.md:86, :95). Skipping review is a process violation caught by the Stop hook (.claude/skills/process-build/SKILL.md:86); the Step 5 gate adds live verification against the deployed system before the build is marked complete (.claude/skills/process-build/SKILL.md:105).
<!-- PROSE:END -->
