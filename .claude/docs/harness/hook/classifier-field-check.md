---
component: "classifier-field-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: classifier-field-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/classifier-field-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-qa [unresolved: prose mention only]
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Classifier Field Check - Stop Hook
Verifies that all mandatory classifier fields are present in the response.
Block: JSON { "decision": "block" } on stdout if fields are missing.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This Stop hook reads the last 200KB of the transcript (.claude/hooks/classifier-field-check.py:18), walks the assistant text blocks with fenced code stripped, and keeps the last block that carries a TASK TYPE or CLASSIFICATION header with a valid type name (.claude/hooks/classifier-field-check.py:88). It returns immediately on stop_hook_active so a hook-induced continuation cannot loop (.claude/hooks/classifier-field-check.py:43).

It then verifies the labeled slots: IMPLIES and TASK TYPE always, plus APPROACH, MISSED, and MUST DISPATCH on non-Quick classifications (.claude/hooks/classifier-field-check.py:98), and additionally requires "pm" inside MUST DISPATCH for every non-Quick task (.claude/hooks/classifier-field-check.py:119). Every classification, complete or not, also emits a classification_emitted event capturing the field values; the advisory REVERSIBILITY and DETECTABILITY fields are recorded but never required, since the hard stop for those is the Gate-1 PreToolUse deny (.claude/hooks/classifier-field-check.py:136).

If any required field is missing it prints {"decision": "block"} with the missing-field list, forcing a re-classification, and emits a classifier_field_missing event to the governance log (.claude/hooks/classifier-field-check.py:161).
<!-- PROSE:END -->
