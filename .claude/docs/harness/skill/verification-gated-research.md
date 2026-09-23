---
component: "verification-gated-research"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: verification-gated-research

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/verification-gated-research`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose architect-loop [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - outbound mentions_in_prose process-research [unresolved: prose mention only]
  - outbound mentions_in_prose verifier-gate-check [unresolved: prose mention only]
  - outbound mentions_in_prose verify [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Run a depth/research/multi-source investigation as a verification-gated backlog — decompose into a ledger file, dispatch fresh-context worker agents, gate completion with a SEPARATE verifier agent. Use when a research or depth task must be exhaustively investigated and a self-graded loop would satisfice. NOT for Quick lookups or single-source tasks.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool for a research or depth task with multiple distinct sub-questions or sources, where a self-graded loop would satisfice and declare done on shallow work (`.claude/skills/verification-gated-research/SKILL.md:3`, lines 12-14). The invoking session becomes the orchestrator: it owns every ledger update and never investigates inline (lines 37, 43).

Its tool surface: a Write that puts the backlog ledger file on disk before any dispatch (`.claude/skills/verification-gated-research/SKILL.md:30`), parallel fresh-context worker Agent dispatches, one per cluster of ledger units (lines 41-46), and one separate verifier Agent whose dispatch description must contain the word "verifier" (line 50). Completion is read off the ledger file, not asserted: every row must be VERIFIED or UNREACHABLE-VALID with zero OPEN, IN-WORK, RETURNED, or FAIL rows (line 63).

Enforcement is mechanical: the `.claude/hooks/verifier-gate-check.py` Stop hook blocks completion when this skill was invoked but no separate-verifier Agent dispatch appears in the transcript (`.claude/skills/verification-gated-research/SKILL.md:26`). FAIL units return to OPEN and are re-worked and re-verified, never waved through (lines 59, 73).
<!-- PROSE:END -->
