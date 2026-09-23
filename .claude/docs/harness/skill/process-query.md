---
component: "process-query"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: process-query

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/process-query`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound cataloged_in registry.json
  - outbound mentions_in_prose index [unresolved: prose mention only]
  - outbound mentions_in_prose process-ingest [unresolved: prose mention only]
  - outbound mentions_in_prose process-lint [unresolved: prose mention only]
  - outbound mentions_in_prose verify [unresolved: prose mention only]
  - outbound mentions_in_prose wiki-citation-check [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use when answering a question from the LLM-Wiki layer, synthesizing a cited answer from accumulated wiki knowledge, or user says "/process-query". Produces a cited answer from Resources/KB/ wiki pages; optionally files the answer back as a new bootstrap wiki page. Implements Karpathy LLM-Wiki Query operation with anti-fabrication gate.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool when a question should be answered from the wiki layer or the user says `/process-query` (`.claude/skills/process-query/SKILL.md:3`, lines 10-15). Step 0 pre-classifies: a question needing live-system state is routed out with `NON_WIKI_QUESTION` before any retrieval (lines 36-38).

Retrieval calls `mcp__qmd__query` on the `agr-kb` collection with lex-only sub-queries (vec and hyde are banned on this machine), then `multi_get` for page bodies; the fallback is Read and Grep over `Resources/KB/` (`.claude/skills/process-query/SKILL.md:26`, 52-58). A file-back uses Bash to compute a fresh SHA-256 for every `source:` path before the Write, as a pre-write hard gate (lines 124-130).

The contract is a QUERY SCOPE block, a hard coverage gate that emits `INSUFFICIENT_WIKI_COVERAGE` instead of synthesizing from general knowledge, an answer where every claim carries a `[[wikilink]]` citation with a pre-delivery per-claim audit, and a closing QUERY REPORT block as plain unfenced text (`.claude/skills/process-query/SKILL.md:44-47`, 66-72, 79-84, 167-175). Enforcement: the `wiki-citation-check.py` PostToolUse hook gates every Write to a `#wiki`-tagged file by checking each source path exists and recomputing its SHA-256 (line 28), and the Stop hook strips fenced blocks, so the report must stay unfenced (line 185).
<!-- PROSE:END -->
