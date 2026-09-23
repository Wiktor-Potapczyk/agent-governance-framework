---
component: "impeccable"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: impeccable

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/impeccable`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - outbound mentions_in_prose index [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use when the user wants to design, redesign, shape, critique, audit, polish, clarify, distill, harden, optimize, adapt, animate, colorize, extract, or otherwise improve a frontend interface. Covers websites, landing pages, dashboards, product UI, app shells, components, forms, settings, onboarding, and empty states. Handles UX review, visual hierarchy, information architecture, cognitive load, acc

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool on frontend design work; it is user-invocable, and the argument-hint lists its sub-commands (craft, shape, audit, polish, animate, and the rest) (.claude/skills/impeccable/SKILL.md:5). Routing rules map the first argument word, or a clear intent match, to a reference file that owns that command's flow (.claude/skills/impeccable/SKILL.md:158).

Frontmatter allows `Bash(npx impeccable *)` (.claude/skills/impeccable/SKILL.md:9), and the setup contract requires its bundled node scripts: context.mjs once per session, with a hard stop into reference/init.md on NO_PRODUCT_MD (.claude/skills/impeccable/SKILL.md:18), palette.mjs for brand-new projects only (.claude/skills/impeccable/SKILL.md:22), context-signals.mjs plus detect.mjs for the no-argument recommendation menu (.claude/skills/impeccable/SKILL.md:145), and pin.mjs for the pin/unpin management commands (.claude/skills/impeccable/SKILL.md:173).

It is contractually required to produce ready-to-ship, production-grade frontend code, not prototypes (.claude/skills/impeccable/SKILL.md:26), under match-and-refuse absolute bans (.claude/skills/impeccable/SKILL.md:93) and the two-altitude AI slop test (.claude/skills/impeccable/SKILL.md:108). Enforcement is in-skill: the setup steps are stated as MUST and the register reference read is non-optional (.claude/skills/impeccable/SKILL.md:16).
<!-- PROSE:END -->
