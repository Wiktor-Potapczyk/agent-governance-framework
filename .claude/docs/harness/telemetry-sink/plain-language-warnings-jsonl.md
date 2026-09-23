---
component: "plain-language-warnings.jsonl"
kind: "telemetry-sink"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# telemetry-sink: plain-language-warnings.jsonl

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/aggregates/plain-language-warnings.jsonl`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded
- **Usage:** Recorded use count 923 (source: `self:total_lines (sink line count, this run's own stream)`). Writer fire count sum: 0 (source: `hook-activity.jsonl:hook_fire.hook summed over this sink's EVD-010 writer stems (telemetry-vocabulary.json)`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

The B1 per-write JSONL contract requires one record for every in-scope documentation write, findings or none (.claude/hooks/plain-language-guard.py:19). That makes the sink's line count the calibration denominator the plain-language rollout uses to judge each rule before any block flip (.claude/hooks/plain-language-guard.py:26).

## How

The sink is an append-only JSONL file written by `plain-language-guard.py`, a PostToolUse hook on Write and Edit. The hook builds the sink path from its own hooks directory (.claude/hooks/plain-language-guard.py:84) and appends records in text append mode (.claude/hooks/plain-language-guard.py:110). It fires only for in-scope files: `Projects/*/work/**.md` outside `work/backups/`, `Resources/KB/**.md`, and the framework-repo README plus docs, matched by a path regex (.claude/hooks/plain-language-guard.py:91); an out-of-scope write returns with no record (.claude/hooks/plain-language-guard.py:147).

Each in-scope write yields exactly one record, findings or none. The hook scans the written content with `plain_language_check.scan` (.claude/hooks/plain-language-guard.py:153), then appends `{ts, session, path, per_rule_finding_counts, total_findings}` (.claude/hooks/plain-language-guard.py:157). Every record carries all ten PL rule keys with zeros included; the first stored line shows the shape (.claude/hooks/aggregates/plain-language-warnings.jsonl:1).

The append never raises, so a locked or missing sink cannot break the write it observes (.claude/hooks/plain-language-guard.py:105). One line per invocation makes the sink's line count the calibration denominator for the plain-language rules (.claude/hooks/plain-language-guard.py:26).
<!-- PROSE:END -->
