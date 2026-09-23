---
component: "plain_language_check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: plain_language_check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/plain_language_check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Plain-Language Checker (T1 rules PL-1 to PL-10) - importable module + CLI lint mode.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This is not an event-fired hook: no settings file registers it, and the Usage line above records zero fires. It is the importable checker module that `plain-language-guard.py` wraps, plus a CLI lint mode for corpus baselines (`.claude/hooks/plain_language_check.py:11`).

`scan(text)` is a pure function. `strip_noise` masks frontmatter, fenced and inline code, MM1 spans, and table rows while preserving line numbers (`.claude/hooks/plain_language_check.py:163`); seven checks (PL-1 to PL-5, PL-7, PL-8) then run over the clean text (`.claude/hooks/plain_language_check.py:290`). The result carries `per_rule_finding_counts` with all ten PL keys (structural zeros for PL-6, PL-9, PL-10), `total_findings`, per-finding samples, and marker advisories (`.claude/hooks/plain_language_check.py:303`).

The MM1 carve-out strips everything between `<!-- MM1 -->` and `<!-- /MM1 -->` before any rule runs; an unclosed open marker exempts to end of document and yields one hygiene advisory, counted separately from findings (`.claude/hooks/plain_language_check.py:121`). The CLI takes paths or globs, prints a per-rule per-file count table, and always exits 0 so one unreadable file cannot abort a corpus run (`.claude/hooks/plain_language_check.py:326`).
<!-- PROSE:END -->
