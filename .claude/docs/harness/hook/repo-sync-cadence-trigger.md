---
component: "repo-sync-cadence-trigger"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: repo-sync-cadence-trigger

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/repo-sync-cadence-trigger.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Empirical trigger (2026-07-29): the framework repo went 39 days and the research
repo 48 days without an update, and nothing surfaced it. Every other periodic
sweep in this vault (lint, governance-mine, work-triage, setup-audit, ingest)
emits an overdue reminder at SessionStart; repo maintenance emitted none, so the
lapse produced no signal until the owner happened to notice. This closes that
asymmetry (.claude/hooks/repo-sync-cadence-trigger.py:8-13).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Runs at SessionStart on the startup and resume matchers. It reads stdin only to recover the session id (.claude/hooks/repo-sync-cadence-trigger.py:174-180), then checks a throttle state file: a reminder already emitted within the last 20 hours logs "throttled" and exits (.claude/hooks/repo-sync-cadence-trigger.py:39, .claude/hooks/repo-sync-cadence-trigger.py:99-108).

Staleness is measured from git itself, never from a recorded claim: `git log -1 --format=%cI` gives the last-commit age and `git rev-list --count origin/<branch>..HEAD` the unpushed count, for each of the two public-repo clones, AGF and AGR (.claude/hooks/repo-sync-cadence-trigger.py:41-46, .claude/hooks/repo-sync-cadence-trigger.py:66-96). A clone quiet 14 days or more counts as stale (.claude/hooks/repo-sync-cadence-trigger.py:38); unpushed commits and unreadable clones each get their own message section (.claude/hooks/repo-sync-cadence-trigger.py:120-156).

When there is something to say it records the throttle timestamp, logs "remind", and prints the message as SessionStart hookSpecificOutput.additionalContext JSON on stdout; the quiet path logs "in-sync" and prints nothing. It never blocks (.claude/hooks/repo-sync-cadence-trigger.py:182-199).
<!-- PROSE:END -->
