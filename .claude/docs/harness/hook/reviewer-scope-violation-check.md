---
component: "reviewer-scope-violation-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: reviewer-scope-violation-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/reviewer-scope-violation-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose process-governance-mine [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Reviewer Scope Violation Check - PreToolUse Hook (matcher: Write|Edit|MultiEdit)

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires PreToolUse on Write, Edit, and MultiEdit. It first identifies the caller: the payload's `agent_type` field is primary (.claude/hooks/reviewer-scope-violation-check.py:213); when that is absent it reads the head of the subagent's own transcript and extracts the `name:` field from the dispatch prompt's frontmatter (.claude/hooks/reviewer-scope-violation-check.py:123-193). Anything not in the reviewer set (adversarial-reviewer, architect-reviewer, code-reviewer) exits immediately with no further I/O (.claude/hooks/reviewer-scope-violation-check.py:43, .claude/hooks/reviewer-scope-violation-check.py:229-230).

For a reviewer it applies two allow rules in order: Rule A allows paths matching the report naming convention `work/YYYY-MM-DD-*-review*.md` (.claude/hooks/reviewer-scope-violation-check.py:50-53, .claude/hooks/reviewer-scope-violation-check.py:259-262); Rule C allows any target that does not yet exist on disk, since a reviewer's report is always a new file (.claude/hooks/reviewer-scope-violation-check.py:264-267). Everything else is an existing non-report artifact and is denied.

The deny is the PreToolUse hookSpecificOutput form with permissionDecision "deny", printed to stdout with exit 0; the older {"decision":"block"} form is the SubagentStop protocol and is silently ignored on PreToolUse (.claude/hooks/reviewer-scope-violation-check.py:280-290). A block appends exactly one reviewer_scope_violation event to governance-log.jsonl (.claude/hooks/reviewer-scope-violation-check.py:88-120); the hook writes nothing to hook-activity.jsonl, which is why the Usage line above reads zero.
<!-- PROSE:END -->
