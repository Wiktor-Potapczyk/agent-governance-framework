---
component: "api-security-audit"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: api-security-audit

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/api-security-audit.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-analysis/DISPATCHES.json), `EVD-003` (.claude/workflows/process-analysis.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches process-analysis
  - inbound invokes process-analysis
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

API security audit specialist.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Agent-tool dispatch; the description asks for PROACTIVE use on REST API security audits, authentication vulnerabilities, authorization flaws, injection attacks, and compliance validation (`.claude/agents/api-security-audit.md:3`). A MUST DISPATCH row binds it into the process-analysis skill (this page's Reachability line).

Tool surface: Read, Write, Edit, Bash (`.claude/agents/api-security-audit.md:4`). Its brief covers authentication security, authorization flaws, injection prevention, data protection, OWASP API Top 10, and GDPR/HIPAA/PCI DSS compliance (`.claude/agents/api-security-audit.md:10-16`).

The output contract is a single body sentence: always provide specific, actionable security recommendations with code examples and remediation steps (`.claude/agents/api-security-audit.md:93`). No output-checking hook is named in the definition.
<!-- PROSE:END -->
