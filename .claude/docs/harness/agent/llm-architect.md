---
component: "llm-architect"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: llm-architect

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/llm-architect.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-build/DISPATCHES.json), `EVD-002` (.claude/skills/process-planning/DISPATCHES.json), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches process-build
  - inbound dispatches process-planning
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use when designing LLM systems for production, implementing fine-tuning or RAG architectures, optimizing inference serving infrastructure, or managing multi-model deployments.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Agent-tool dispatch when designing production LLM systems, implementing fine-tuning or RAG architectures, optimizing inference serving, or managing multi-model deployments (`.claude/agents/llm-architect.md:3`); MUST DISPATCH rows bind it into the process-build and process-planning skills (this page's Reachability line).

Tool surface: Read, Write, Edit, Bash, Glob, Grep (`.claude/agents/llm-architect.md:4`). On invocation it gathers LLM requirements and use cases, reviews existing models and infrastructure, analyzes scalability and safety, then implements (`.claude/agents/llm-architect.md:10-14`).

The contract is measured delivery against named performance targets (latency under 200ms P95, throughput over 100 tokens/sec, minimized cost per token) with everything measured: accuracy, latency, throughput, safety evaluation, and business impact (`.claude/agents/llm-architect.md:32`). No fixed report format or output-checking hook is named in the definition.
<!-- PROSE:END -->
