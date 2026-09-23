---
component: "git-credential-scope-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: git-credential-scope-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/git-credential-scope-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

git-credential-scope-check.py: SessionStart safeguard for Git Credential Manager scoping.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This SessionStart hook (registered for both startup and resume) verifies that the global git config value credential.usehttppath is exactly "true": the one setting that makes Git Credential Manager pick the repo-scoped personal credential instead of the host-level work credential for github.com pushes (.claude/hooks/git-credential-scope-check.py:4). It deliberately reads with --global so the check matches the scope its own remediation command sets (.claude/hooks/git-credential-scope-check.py:15).

A fresh "ok" result is cached for 24 hours in _state/git-credential-scope.json; only a fresh ok skips the live check, while a prior warn, a missing file, or a future-dated timestamp all re-run it (.claude/hooks/git-credential-scope-check.py:97). The live check shells out to git config with a 5 second timeout and fails open if git is unavailable (.claude/hooks/git-credential-scope-check.py:160).

A missing key or any value other than "true" emits a loud additionalContext warning naming the NDA risk and the fix command, and caches "warn" (.claude/hooks/git-credential-scope-check.py:119); a correct value stays silent. Every path logs its decision (cached-ok, ok, warn, or skip) to hook-activity.jsonl, and the exit code is always 0 (.claude/hooks/git-credential-scope-check.py:48).
<!-- PROSE:END -->
