---
component: "config-protection"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: config-protection

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/retired/config-protection.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Override mechanism:
  - Set env var CONFIG_PROTECTION_ALLOW=1 in the parent shell to permit subsequent
    Write/Edit/MultiEdit to protected files.
  - The override is SESSION-SCOPED, not single-use. Once set, every subsequent write
    in that shell session is allowed until the user explicitly `unset`s the variable
    (or restarts the shell). The hook does not auto-clear it.
  - Rationale: an env override is more deliberate than a CLI flag (visible in
    shell history). It is not designed to be airtight against an adversarial
    agent; it keeps a confused agent from quietly clobbering a load-bearing
    file (.claude/hooks/retired/config-protection.py:18).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Retired. main() returns 0 before any logic runs, per Wiktor's 2026-08-07 ruling quoted in the code; the guard was neutered first because it blocked the very settings edit that deregisters it, then moved to retired/ (.claude/hooks/retired/config-protection.py:150). The generated block above records no registration, so no event fires it today.

The dead code below the early return shows what it did when live: a PreToolUse Write/Edit/MultiEdit guard matching protected basenames case-insensitively, with settings.local.json and registry.json constrained to a .claude parent directory and MEMORY.md protected anywhere (.claude/hooks/retired/config-protection.py:77). A truthy CONFIG_PROTECTION_ALLOW env var was the session-scoped override (.claude/hooks/retired/config-protection.py:105); without it, a protected write got a permissionDecision "deny" with remediation text and a deny event in governance-log.jsonl (.claude/hooks/retired/config-protection.py:132).
<!-- PROSE:END -->
