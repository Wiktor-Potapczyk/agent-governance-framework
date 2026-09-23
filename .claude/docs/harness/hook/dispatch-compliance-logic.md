---
component: "_dispatch_compliance_logic"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: _dispatch_compliance_logic

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/_dispatch_compliance_logic.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Pure logic for dispatch-compliance-check.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Pure decision logic for the dispatch-compliance-check Stop hook: the functions here do no stdin, stdout, or transcript I/O; the hook wrapper owns that (.claude/hooks/_dispatch_compliance_logic.py:1). The one import-time exception is loading KNOWN_DISPATCH_NAMES from the generated data file via _known_dispatch_names_loader, with a frozen 93-name snapshot as fallback so a missing file degrades to the old behavior instead of blocking every non-Quick turn (.claude/hooks/_dispatch_compliance_logic.py:106, .claude/hooks/_dispatch_compliance_logic.py:69).

scan_assistant_text_block scans assistant text: a block carrying a valid TASK TYPE resets state and re-extracts the MUST DISPATCH declaration (.claude/hooks/_dispatch_compliance_logic.py:276). extract_dispatch_names splits raw text on commas, semicolons, "and", and "&", then greedily matches up-to-3-word candidates against the known-name set, also recognizing plugin-namespaced tokens by their post-colon suffix (.claude/hooks/_dispatch_compliance_logic.py:148).

compute_missing returns declared names satisfied neither directly nor through a skill-agent alias (.claude/hooks/_dispatch_compliance_logic.py:222), and format_missing_reason / format_empty_dispatch_reason build the block-reason strings the wrapper emits as its Stop decision (.claude/hooks/_dispatch_compliance_logic.py:258).
<!-- PROSE:END -->
