---
component: "_wiki_citation_logic"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: _wiki_citation_logic

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/_wiki_citation_logic.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Pure logic for wiki-citation-check.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Pure logic for the wiki-citation-check hook; only validate_source_entries touches the filesystem, to check cited files and hash their bytes (.claude/hooks/_wiki_citation_logic.py:1). The scope helpers decide what counts as wiki-layer: everything under Resources/KB/ unconditionally, and Notes/ or Projects/*/archive/ pages only when the frontmatter tags contain the exact token wiki (.claude/hooks/_wiki_citation_logic.py:41, .claude/hooks/_wiki_citation_logic.py:73).

parse_source_field extracts the frontmatter source: array in both block-list and inline-flow YAML forms (.claude/hooks/_wiki_citation_logic.py:151). validate_source_entries then grades each entry: no entries at all and empty paths are blocking errors, a path missing on disk is ORPHAN_CITATION, type: generated skips the SHA gate, type: schema-doctrine instead requires the cited anchor heading to exist in the source, and a sha256 mismatch reports SOURCE_DRIFT as a warning (.claude/hooks/_wiki_citation_logic.py:246).

format_findings_message renders the findings into the additionalContext text the wrapper emits, appending a note that blocking-level findings are currently advisory in v1 (.claude/hooks/_wiki_citation_logic.py:362).
<!-- PROSE:END -->
