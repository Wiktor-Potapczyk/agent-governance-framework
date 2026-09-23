---
component: "architect-loop"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: architect-loop

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/architect-loop`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-research [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - outbound mentions_in_prose save [unresolved: prose mention only]
  - outbound mentions_in_prose verification-gated-research [unresolved: prose mention only]
  - outbound mentions_in_prose verify [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Design and structure Ralph Loop research prompts for complex tasks. Use when the user wants to prepare a deep research loop, says 'architect a loop', 'prepare a ralph loop', 'design a loop for', or when you identify a complex task that needs independent deep research before building. Also trigger proactively when the conversation reveals multiple open questions that need exhaustive investigation from source materials (`.claude/skills/architect-loop/SKILL.md:3`).

(machine-filled from rationale-index.json; extraction locus: frontmatter; truncated tail restored from SKILL.md:3)

## How

Invoked through the Skill tool on the trigger phrases in its description ("architect a loop", "prepare a ralph loop", "design a loop for") or proactively when a conversation reveals multiple open questions needing exhaustive investigation from source materials (`.claude/skills/architect-loop/SKILL.md:3`); its own do-NOT-use list excludes single-fact lookups, context-dependent investigations, and opinion questions (SKILL.md:12-17). The generated edge list above also records prose mentions from CLAUDE.md, process-research, and task-classifier naming it as the context-isolated route for Ralph Loop work.

It produces artifacts, not research: locate the project by its STATE.md (`.claude/skills/architect-loop/SKILL.md:27-29`), gather open questions (SKILL.md:31-42), Glob the project's source materials (SKILL.md:48-54), group questions into 3 to 6 PROBLEM sections (SKILL.md:56-64), write the loop prompt to `Projects/[Name]/work/YYYY-MM-DD-[topic]-research-loop.md` (SKILL.md:66-68), and emit a ready-to-paste `/ralph-loop:ralph-loop` command with a completion promise (SKILL.md:131-136). Tool surface is vault reads, Glob, and one file write; the loop itself runs later, only after the user reviews the prompt (SKILL.md:146-152).

Enforcement lives in its own rules: hypotheses are stripped so the loop investigates rather than validates (`.claude/skills/architect-loop/SKILL.md:21`), every research task must name a specific file or data source (SKILL.md:157), and `--max-iterations` has a hard ceiling of 30, described in the text as two-gate Gate-1-adjacent; oversized corpora are decomposed into separate loops instead of raising the cap (SKILL.md:144 and SKILL.md:162). The O16 appendix carries the loop-tool selection doctrine that scopes when this skill, rather than `/goal`, `/loop`, or `/workflows`, is the right form (SKILL.md:164-173).
<!-- PROSE:END -->
